"""Four-clip orchestration with synthetic projects and a fake backend only."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid
import urllib.error

from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
# 설치 위치 규칙: <저장소>/ComfyUI 폴더가 있으면 그것, 없으면 %USERPROFILE%\ComfyUI
COMFY=ROOT/'ComfyUI' if (ROOT/'ComfyUI').is_dir() else Path.home()/'ComfyUI'
sys.path.insert(0,str(ROOT/'simple_ui'))
from story import StoryProjects, media_path, merge_clips
from story_workflow import CLIP_COUNT, DIRECTOR, GUIDE, GUIDER, SAVE, compose_prompt, continuation_graph


def graph():
    return {DIRECTOR:{'class_type':'MiniMaxH3Director','inputs':{'timeline_data':json.dumps({'items':[{'value':'synthetic-original.png'}]})}},
        GUIDE:{'class_type':'MiniMaxH3DirectorGuide','inputs':{}},
        GUIDER:{'class_type':'BasicGuider','inputs':{'conditioning':[GUIDE,0]}},
        'sampler':{'class_type':'SamplerCustomAdvanced','inputs':{'latent_image':[GUIDE,1]}},
        'prepare':{'class_type':'DaSiWaH3ContinuitySegmentPrepare','inputs':{'sampled':['sampler',0],'context':[GUIDE,2]}},
        'decode':{'class_type':'DaSiWaH3ContinuitySegmentDecode','inputs':{'latent':['prepare',0],'context':['prepare',1],'vae':['video-vae',0],'audio_vae':['audio-vae',0]}},
        SAVE:{'class_type':'DaSiWa_EnhancedVideoCombine','inputs':{'images':['decode',0],'audio':['decode',1],'filename_prefix':'synthetic'}},
        'publish':{'class_type':'DaSiWaH3ContinuityPublish','inputs':{'filename':[SAVE,1],'ticket':['prepare',2]}}}


def definition():
    return {'title':'synthetic test','common':{'model':'test-model','steps':4,'loras':[{'name':'test-lora','strength':.5}],
        'aspect':'auto','resolution':'draft','subject':'The original subject.','keep':'Keep face and outfit.','style':'Fixed camera.'},
        'boundaries':['','','','',''],'clips':[{'scenario':f'Action {i+1}','seed':str(100+i),
            'draft':{'f':{'summary':f'Action {i+1}','sound':'Quiet room.','music':'N/A'},'shots':[['0',f'The subject performs action {i+1}.']]}} for i in range(4)]}


class StoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.output=self.base/'output';self.output.mkdir()
        self.calls=[];self.prepared=[];self.states={};self.checkpoints={};self.mode='done';self.merges=[]
        self.store=StoryProjects(self.base/'projects',self.output,self.prepare,self.comfy,lambda *_:'simpleui_1234567890.png',
            lambda pid:self.states.get(pid,{'state':'unknown'}),lambda *_:None,merge=self.merge,client_id='synthetic-client')
        data=io.BytesIO()
        with Image.new('RGB',(32,16),'blue') as image:image.save(data,format='PNG')
        import base64
        self.image='data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()
        self.project=self.store.save({'definition':definition(),'images':[self.image]})
        self.pid=self.project['id']
        self.addCleanup(self.stop_workers)

    def stop_workers(self):
        for event in list(self.store.cancels.values()):event.set()
        for worker in list(self.store.workers.values()):worker.join(timeout=3)

    def prepare(self,request,reference):
        self.prepared.append(copy.deepcopy(request))
        p=graph()
        p[DIRECTOR]['inputs']['timeline_data']=reference['prompt'][DIRECTOR]['inputs']['timeline_data']
        if request['anchor']:
            p['anchor']={'class_type':'MiniMaxH3AddGuide','inputs':{'positive':[GUIDE,0],'frame_idx':0}}
            p[GUIDER]['inputs']['conditioning']=['anchor',0]
        return {'prompt':p,'width':192,'height':96,'seed':int(request['seed'])}

    def comfy(self,path,data=None,headers=None):
        body=json.loads(data) if data else None;self.calls.append((path,copy.deepcopy(body)))
        if path=='/prompt':
            pid=body['prompt_id'];p=body['prompt'];settings=json.loads(p[DIRECTOR]['inputs']['timeline_data'])['continuity']
            clip_id=uuid.uuid4().hex;directory=self.output/'df_h3_continuity'/settings['session']/clip_id;directory.mkdir(parents=True)
            video=self.output/'story'/settings['session']/(pid+'.mp4');video.parent.mkdir(parents=True,exist_ok=True);video.write_bytes(b'synthetic-only')
            (directory/'clip.json').write_text(json.dumps({'session':settings['session'],'status':'ready','parent_id':settings['source_id'],'output_path':str(video)}))
            (directory.parent/'latest.json').write_text(json.dumps({'clip_id':clip_id}))
            self.checkpoints[pid]=clip_id
            self.states[pid]={'state':'done','video':{'type':'output','filename':video.name,'subfolder':str(video.parent.relative_to(self.output))}} if self.mode=='done' else {'state':self.mode,'pct':5}
            return io.BytesIO(json.dumps({'prompt_id':pid}).encode())
        if path in ('/queue','/interrupt'):return io.BytesIO(b'')
        raise AssertionError(path)

    def merge(self,paths,destination,cancel,bgm):
        self.merges.append(list(paths));destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(b'synthetic-merge');return destination

    def wait(self):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            with self.store.lock:
                if self.pid not in self.store.workers:return self.store.get(self.pid)
            time.sleep(.01)
        self.fail('Synthetic worker did not finish')

    def render(self,index,approve=True):
        self.store.start(self.pid,index);result=self.wait()
        self.assertEqual(result['renders'][index]['state'],'done')
        self.assertFalse(result['renders'][index]['approved'])
        if approve:result=self.store.approve(self.pid,index)
        return result

    def test_speed_choice_in_common_settings_reaches_every_clip_request(self):
        # 속도 우선(희소 어텐션)은 공통 설정으로 저장되고, 첫 편과 이어 붙는 편 모두 같은 값으로 그래프를 준비한다
        self.render(0)
        self.assertNotIn('speed',self.prepared[-1])
        chosen=definition();chosen['common']['speed']='sparse'
        saved=self.store.save({'id':self.pid,'revision':self.project['revision'],'definition':chosen})
        self.assertTrue(saved['renders'][0]['stale'],'공통 설정이 바뀌면 이미 만든 편은 재검토 대상이 된다')
        self.render(0);self.render(1)
        self.assertEqual([request.get('speed') for request in self.prepared[-2:]],['sparse','sparse'])

    def test_only_the_verified_speed_mode_can_be_saved_for_four_clip_projects(self):
        # 스텝 캐시를 함께 쓰는 방식은 이어 붙는 편에서 확인하지 않았다: 화면이 내놓지 않는 값은 저장 단계에서 거절한다
        for value in ('sparse_cache','warp',1):
            crafted=definition();crafted['common']['speed']=value
            with self.assertRaisesRegex(ValueError,'속도 우선'):
                self.store.save({'id':self.pid,'revision':self.project['revision'],'definition':crafted})
        for value in ('sparse',''):
            accepted=definition();accepted['common']['speed']=value
            self.project=self.store.save({'id':self.pid,'revision':self.project['revision'],'definition':accepted})

    def test_upscale_quality_is_not_accepted_for_continuation_clips(self):
        # 업스케일 화질은 한 편씩 만드는 영상에서만 검증했다. 이어 만들기 그래프에 그 노드가 있으면 등록하지 않고 알린다
        prepare=self.prepare
        def with_upscale(request,reference):
            prepared=prepare(request,reference)
            prepared['prompt']['9006']={'class_type':'DaSiWaH3TiledUpscale','inputs':{}}
            return prepared
        self.store.prepare=with_upscale
        self.store.start(self.pid,0);result=self.wait()
        self.assertEqual(result['renders'][0]['state'],'error')
        self.assertIn('업스케일',result['renders'][0]['error'])
        self.assertFalse([call for call in self.calls if call[0]=='/prompt'])

    def test_four_steps_require_explicit_approval_and_reuse_original_refs(self):
        with self.assertRaises(ValueError):self.store.start(self.pid,1)
        for i in range(4):
            self.render(i,approve=False)
            self.assertEqual(len([p for p,_ in self.calls if p=='/prompt']),i+1)
            if i<3:
                with self.assertRaises(ValueError):self.store.start(self.pid,i+1)
            self.store.approve(self.pid,i)
        payloads=[b for p,b in self.calls if p=='/prompt']
        for i,payload in enumerate(payloads):
            settings=json.loads(payload['prompt'][DIRECTOR]['inputs']['timeline_data'])
            self.assertEqual(settings['items'][0]['value'],'simpleui_1234567890.png')
            self.assertEqual(settings['continuity']['use_references'],True)
            self.assertEqual(settings['continuity']['output_mode'],'segment')
            expected='' if i==0 else self.checkpoints[payloads[i-1]['prompt_id']]
            self.assertEqual(settings['continuity']['source_id'],expected)
            self.assertEqual(self.prepared[i]['model'],'test-model')
            self.assertEqual(self.prepared[i]['loras'],definition()['common']['loras'])
            self.assertEqual(self.prepared[i]['anchor'],i==0)
        self.store.start_merge(self.pid);result=self.wait()
        self.assertEqual(result['merged']['state'],'done');self.assertEqual(len(self.merges[0]),4)
        self.assertNotIn('video_path',result['merged']);self.assertNotIn('job_id',result['renders'][0]);self.assertTrue(result['renders'][0]['has_video'])

    def test_changing_third_prompt_only_invalidates_third_and_fourth(self):
        for i in range(4):self.render(i)
        project=self.store.get(self.pid);changed=copy.deepcopy(project['definition']);changed['clips'][2]['draft']['f']['summary']='Updated third action.'
        result=self.store.save({'id':self.pid,'revision':project['revision'],'definition':changed})
        self.assertEqual([r['approved'] for r in result['renders']],[True,True,False,False])
        self.assertEqual([r['stale'] for r in result['renders']],[False,False,True,True])
        with self.assertRaises(ValueError):self.store.start_merge(self.pid)

    def test_common_change_and_regeneration_invalidate_descendants(self):
        for i in range(4):self.render(i)
        self.render(1)
        result=self.store.get(self.pid);self.assertTrue(result['renders'][0]['approved']);self.assertFalse(result['renders'][2]['approved'])
        changed=copy.deepcopy(result['definition']);changed['common']['style']='New fixed camera.'
        result=self.store.save({'id':self.pid,'revision':result['revision'],'definition':changed})
        self.assertTrue(all(r['stale'] and not r['approved'] for r in result['renders']))

    def test_cancel_only_targets_this_projects_job(self):
        self.mode='running';self.store.start(self.pid,0)
        deadline=time.monotonic()+3
        while not self.checkpoints and time.monotonic()<deadline:time.sleep(.01)
        owned=next(iter(self.checkpoints));self.store.cancel(self.pid);result=self.wait()
        self.assertEqual(result['renders'][0]['state'],'error')
        self.assertEqual([body for path,body in self.calls if path=='/queue'],[{'delete':[owned]}])
        self.assertEqual([body for path,body in self.calls if path=='/interrupt'],[{'prompt_id':owned}])

    def test_stale_revision_and_path_escape_are_rejected(self):
        with self.assertRaises(ValueError):self.store.save({'id':self.pid,'revision':-1,'definition':definition()})
        with self.assertRaises(ValueError):self.store.get('../private')
        with self.assertRaises(ValueError):media_path(self.output,{'type':'output','filename':'outside.mp4','subfolder':'../private'})

    def test_resume_waits_for_saved_job_instead_of_duplicating(self):
        self.render(0)
        with self.store.lock:
            stored=self.store._read(self.pid);job=stored['renders'][0]['job_id'];stored['active']={'kind':'render','index':0,'job_id':job};stored['renders'][0]['state']='queued';self.store._write(stored)
        before=len(self.calls);self.store.get(self.pid);result=self.wait()
        self.assertEqual(result['renders'][0]['state'],'done');self.assertEqual(len(self.calls),before)

    def test_lost_submission_response_follows_owned_id_without_duplicate(self):
        original=self.store.comfy
        def lost_response(path,data=None,headers=None):
            result=original(path,data,headers)
            if path=='/prompt': raise urllib.error.URLError('Synthetic connection loss after acceptance')
            return result
        self.store.comfy=lost_response
        self.render(0)
        self.assertEqual(len([path for path,_ in self.calls if path=='/prompt']),1)

    @unittest.skipUnless((COMFY/'custom_nodes/ComfyUI-DaSiWa-Nodes/nodes/h3_continuity/validation.py').is_file(), 'Pinned DaSiWa nodes unavailable')
    def test_separate_graph_has_valid_capture_chain_and_does_not_change_base(self):
        source=graph();before=copy.deepcopy(source)
        p=continuation_graph(source,self.pid,1,'a'*32,'synthetic continuation')
        self.assertEqual(source,before)
        spec=importlib.util.spec_from_file_location('capture_validation',COMFY/'custom_nodes/ComfyUI-DaSiWa-Nodes/nodes/h3_continuity/validation.py')
        validation=importlib.util.module_from_spec(spec);spec.loader.exec_module(validation)
        validation.validate_capture_graph(p,GUIDE,'segment')
        common=definition()['common'];text=compose_prompt(common,definition()['clips'][1],1,['','','','',''])
        self.assertIn('<Picture 1>',text);self.assertIn('preceding',text);self.assertIn('Fixed camera.',text)
        self.assertIn('At 0.917 seconds',text)

    @unittest.skipUnless((COMFY/'custom_nodes/ComfyUI-DaSiWa-Nodes/nodes/h3_continuity/validation.py').is_file(), 'Pinned DaSiWa nodes unavailable')
    def test_preparation_hook_does_not_enqueue_or_write_single_video_history(self):
        import test_settings_sequence_bulk as fixtures
        fixture=fixtures.FeatureTests();fixture.setUp()
        try:
            prepared=fixture.env['build_and_queue'](fixture.request(count=1,anchor=True),prepare_only=True)
            self.assertEqual(fixture.sent,[])
            self.assertEqual(fixture.env['HIST_DB'],[])
            p=continuation_graph(prepared['prompt'],self.pid,0,None,'Synthetic story prompt.')
            spec=importlib.util.spec_from_file_location('capture_validation_real_template',COMFY/'custom_nodes/ComfyUI-DaSiWa-Nodes/nodes/h3_continuity/validation.py')
            validation=importlib.util.module_from_spec(spec);spec.loader.exec_module(validation)
            validation.validate_capture_graph(p,GUIDE,'segment')
            self.assertEqual(p[SAVE]['inputs']['frame_rate'],24)
            self.assertTrue(p[SAVE]['inputs']['save_output'])
        finally: fixture.doCleanups()

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg unavailable')
    def test_cpu_merge_of_synthetic_clips_and_optional_music(self):
        import av
        import wave
        paths=[]
        for i in range(4):
            path=self.base/f'synthetic-{i}.mp4'
            command=[shutil.which('ffmpeg'),'-hide_banner','-loglevel','error','-nostdin','-y',
                '-f','lavfi','-i','color=c=blue:s=192x96:r=24:d=5','-f','lavfi','-i','anullsrc=r=32000:cl=stereo',
                '-t','5','-c:v','libx264','-preset','ultrafast','-threads','1','-c:a','aac',str(path)]
            completed=subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.assertEqual(completed.returncode,0,'Synthetic fixture encode failed')
            paths.append(path)
        music=self.base/'synthetic-music.wav'
        with wave.open(str(music),'wb') as audio:
            audio.setnchannels(2);audio.setsampwidth(2);audio.setframerate(32000);audio.writeframes(b'\0'*(32000*4))
        for bgm in (None,music):
            destination=self.base/('joined-music.mp4' if bgm else 'joined.mp4')
            merge_clips(paths,destination,threading.Event(),bgm)
            with av.open(str(destination)) as video:
                self.assertAlmostEqual(float(video.duration)/av.time_base,20,delta=.15)
                self.assertEqual((video.streams.video[0].width,video.streams.video[0].height),(192,96))
                self.assertEqual(len(video.streams.audio),1)

    def synthetic_clips(self,codecs=('libx264',)*4):
        """움직이는 시험 무늬 5초짜리 네 편(편마다 무늬가 달라 어느 편의 프레임인지 구분된다)."""
        paths=[]
        for i,codec in enumerate(codecs):
            path=self.base/f'pattern-{i}.mp4'
            extra=['-preset','ultrafast','-threads','1'] if codec=='libx264' else ['-q:v','5']
            command=[shutil.which('ffmpeg'),'-hide_banner','-loglevel','error','-nostdin','-y',
                '-f','lavfi','-i',f'testsrc2=s=192x96:r=24:d=5,hue=h={i*80}','-f','lavfi','-i','anullsrc=r=32000:cl=stereo',
                '-t','5','-pix_fmt','yuv420p','-c:v',codec,*extra,'-c:a','aac',str(path)]
            self.assertEqual(subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode,0,'Synthetic fixture encode failed')
            paths.append(path)
        return paths

    @staticmethod
    def video_facts(path):
        import av
        with av.open(str(path)) as container:
            stream=container.streams.video[0]
            frames=[frame.to_ndarray(format='gray').copy() for frame in container.decode(stream)]
            return {'codec':stream.codec_context.codec.canonical_name,'profile':stream.codec_context.profile,
                'seconds':float(container.duration)/av.time_base,'frames':frames}

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg unavailable')
    def test_merge_copies_the_video_track_when_all_clips_share_one_format(self):
        # 다시 인코딩하면 화질이 한 번 더 깎인다(실측 -3.8dB). 같은 형식의 네 편은 프레임이 한 화소도 달라지지 않아야 한다.
        paths=self.synthetic_clips()
        sources=[self.video_facts(path) for path in paths]
        merged=self.video_facts(merge_clips(paths,self.base/'copied.mp4',threading.Event()))
        self.assertAlmostEqual(merged['seconds'],20,delta=.15)
        self.assertEqual((merged['codec'],merged['profile']),(sources[0]['codec'],sources[0]['profile']))
        self.assertEqual(len(merged['frames']),480)
        for index,source in enumerate(sources):
            for offset in (0,60,119):
                self.assertTrue((merged['frames'][index*120+offset]==source['frames'][offset]).all(),f'{index + 1}편 {offset}번째 프레임이 달라졌습니다')

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg unavailable')
    def test_merge_reencodes_when_formats_differ_when_asked_or_when_the_copy_does_not_verify(self):
        import story
        plain=self.synthetic_clips()
        copied=self.video_facts(merge_clips(plain,self.base/'plain.mp4',threading.Event()))
        with patch.dict(os.environ,{'SIMPLEUI_STORY_MERGE':'reencode'}):
            forced=self.video_facts(merge_clips(plain,self.base/'forced.mp4',threading.Event()))
        self.assertEqual(forced['codec'],'h264')
        self.assertNotEqual(forced['profile'],copied['profile'],'다시 인코딩을 요청했는데 영상 트랙을 그대로 복사했습니다')
        # 다시 인코딩한 쪽은 편마다 소리가 영상보다 조금 길어 끝의 한두 프레임이 20초 밖으로 밀릴 수 있다
        self.assertAlmostEqual(len(forced['frames']),480,delta=3)
        # 그대로 붙인 파일이 검증을 통과하지 못하면(여기서는 프레임 확인을 일부러 틀리게 한다) 다시 인코딩한 파일이 나온다
        with patch.object(story,'frame_checksums',return_value=[]):
            repaired=self.video_facts(merge_clips(plain,self.base/'repaired.mp4',threading.Event()))
        self.assertEqual((repaired['codec'],repaired['profile']),('h264',forced['profile']))
        self.assertAlmostEqual(len(repaired['frames']),480,delta=3)
        # 프레임 수는 맞는데 내용이 다른 파일(한 편이 깨진 화면으로 풀리는 경우)도 통과하지 못한다
        real=story.frame_checksums
        with patch.object(story,'frame_checksums',side_effect=lambda path:[1]*480 if str(path).endswith('.part') else real(path)):
            garbled=self.video_facts(merge_clips(plain,self.base/'garbled.mp4',threading.Event()))
        self.assertEqual((garbled['codec'],garbled['profile']),('h264',forced['profile']))
        # 소리 형식이 다른 편이 섞이면 그대로 붙이지 않는다(목록 입력은 소리 디코더도 하나라 그 편의 소리가 깨진다)
        other=self.base/'pattern-1-44k.mp4'
        self.assertEqual(subprocess.run([shutil.which('ffmpeg'),'-hide_banner','-loglevel','error','-nostdin','-y','-i',str(plain[1]),'-c:v','copy','-c:a','aac','-ar','44100',str(other)],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode,0)
        uneven_sound=self.video_facts(merge_clips([plain[0],other,plain[2],plain[3]],self.base/'sound.mp4',threading.Event()))
        self.assertEqual((uneven_sound['codec'],uneven_sound['profile']),('h264',forced['profile']))
        # 한 편이라도 코덱이 다르면 그대로 붙일 수 없다
        import wave
        music=self.base/'pattern-music.wav'
        with wave.open(str(music),'wb') as audio:
            audio.setnchannels(2);audio.setsampwidth(2);audio.setframerate(32000);audio.writeframes(b'\0'*(32000*4))
        uneven=self.synthetic_clips(('libx264','libx264','mpeg4','libx264'))
        originals=[self.video_facts(path) for path in uneven]
        for bgm in (None,music):
            mixed=self.video_facts(merge_clips(uneven,self.base/('mixed-music.mp4' if bgm else 'mixed.mp4'),threading.Event(),bgm))
            self.assertEqual(mixed['codec'],'h264')
            self.assertAlmostEqual(len(mixed['frames']),480,delta=3)
            self.assertAlmostEqual(mixed['seconds'],20,delta=.15)
            # 코덱이 다른 세 번째 편도 빠지지 않고 제자리에 들어간다(목록 입력으로 풀면 이 5초가 통째로 사라진다)
            for index,source in enumerate(originals):
                difference=abs(mixed['frames'][index*120+60].astype(int)-source['frames'][60].astype(int)).mean()
                self.assertLess(difference,12,f'{index + 1}편 자리에 다른 화면이 들어갔습니다')
        self.assertEqual(sorted(path.name for path in self.base.glob('*.part'))+sorted(path.name for path in self.base.glob('*.concat')),[])

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg unavailable')
    def test_copied_merge_with_one_clip_from_other_encoder_settings_is_not_accepted_as_it_is(self):
        # 같은 코덱·프로파일·화소 형식이라도 인코더 설정이 다르면 첫 편의 설정으로 풀려 그 편 전체가 깨진 화면이 된다(프레임 수는 그대로).
        encoders=subprocess.run([shutil.which('ffmpeg'),'-hide_banner','-encoders'],capture_output=True,text=True,encoding='utf-8',errors='replace').stdout
        if ' libx265 ' not in encoders: self.skipTest('libx265 unavailable')
        paths=[]
        for i in range(4):
            path=self.base/f'hevc-{i}.mp4'
            options='log-level=error'+(':signhide=0' if i==1 else '')
            command=[shutil.which('ffmpeg'),'-hide_banner','-loglevel','error','-nostdin','-y',
                '-f','lavfi','-i',f'testsrc2=s=192x96:r=24:d=5,hue=h={i*80}','-f','lavfi','-i','anullsrc=r=32000:cl=stereo',
                '-t','5','-pix_fmt','yuv420p','-c:v','libx265','-preset','fast','-x265-params',options,'-c:a','aac',str(path)]
            self.assertEqual(subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode,0,'Synthetic fixture encode failed')
            paths.append(path)
        sources=[self.video_facts(path) for path in paths]
        merged=self.video_facts(merge_clips(paths,self.base/'hevc.mp4',threading.Event()))
        self.assertEqual(merged['codec'],'h264','깨진 채로 풀리는 복사본이 그대로 통과했습니다(프레임 수만 맞는 경우)')
        self.assertAlmostEqual(len(merged['frames']),480,delta=3)
        for index,source in enumerate(sources):
            for offset in (0,60,115):
                difference=abs(merged['frames'][index*120+offset].astype(int)-source['frames'][offset].astype(int)).mean()
                self.assertLess(difference,12,f'{index + 1}편 {offset}번째 프레임이 깨졌습니다')

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg unavailable')
    def test_merge_details_music_alignment_and_stop_during_the_check(self):
        import story
        import wave
        plain=self.synthetic_clips()
        music=self.base/'align-music.wav'
        with wave.open(str(music),'wb') as audio:
            audio.setnchannels(2);audio.setsampwidth(2);audio.setframerate(32000);audio.writeframes(b'\0'*(32000*4))
        commands=[];run=story.run_ffmpeg
        with patch.object(story,'run_ffmpeg',side_effect=lambda command,cancel:(commands.append(command),run(command,cancel))[1]):
            merge_clips(plain,self.base/'aligned.mp4',threading.Event(),music)
        self.assertEqual(len(commands),1,'같은 형식의 네 편은 그대로 붙이는 한 번으로 끝난다')
        graph=commands[0][commands[0].index('-filter_complex')+1]
        # 편의 소리가 영상보다 짧을 때 빈 곳을 채워야 뒤 편의 소리가 앞당겨지지 않는다(배경음악이 없을 때와 같은 처리)
        self.assertIn('[0:a]aresample=async=1:first_pts=0[voice]',graph);self.assertIn('[voice][m]amix',graph)
        # 검증하는 동안 누른 중지: 결과 파일을 남기지 않고 취소로 끝난다
        cancel=threading.Event();real=story.frame_checksums
        with patch.object(story,'frame_checksums',side_effect=lambda path:(cancel.set(),real(path))[1]):
            with self.assertRaisesRegex(ValueError,'병합을 취소했습니다'):
                merge_clips(plain,self.base/'stopped.mp4',cancel)
        self.assertFalse((self.base/'stopped.mp4').exists())
        self.assertEqual(sorted(path.name for path in self.base.glob('*.part'))+sorted(path.name for path in self.base.glob('*.concat')),[])

    def test_stop_pressed_as_the_merge_finishes_is_not_overwritten_by_done(self):
        for index in range(CLIP_COUNT):self.render(index)
        made=[]
        def merge(paths,destination,cancel,bgm):
            destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(b'synthetic-merge');made.append(destination)
            self.store.cancel(self.pid)      # 병합이 끝나는 순간에 누른 중지
            return destination
        self.store.merge=merge
        self.store.start_merge(self.pid);result=self.wait()
        self.assertIsNone(result['merged']);self.assertEqual(result.get('merge_error'),'작업을 중지했습니다.')
        self.assertIsNone(result['active']);self.assertFalse(made[0].exists(),'중지한 병합의 결과 파일이 남았습니다')
        self.assertTrue(all(run['state']=='done' and run['has_video'] for run in result['renders']),'각 편의 영상은 그대로다')


    def test_brief_file_lock_neither_fails_a_stage_nor_loses_its_result(self):
        import story
        real=story.os.replace;calls={'n':0}
        def flaky(source,target):
            calls['n']+=1
            if calls['n']%3==0:raise PermissionError(13,'synthetic scanner')   # every third replace is refused once
            return real(source,target)
        with patch.object(story.os,'replace',flaky):
            for i in range(2):self.render(i)
        self.assertGreater(calls['n'],6)
        self.assertEqual([r['state'] for r in self.store.get(self.pid)['renders'][:2]],['done','done'])

    def test_progress_write_failure_while_running_does_not_end_the_stage(self):
        self.mode='running';self.store.start(self.pid,0)
        deadline=time.monotonic()+3
        while not self.checkpoints and time.monotonic()<deadline:time.sleep(.01)
        owned=next(iter(self.checkpoints));original=self.store._write;failed=[]
        def write(project):
            if project.get('active') and project['renders'][0].get('state')=='running' and not failed:
                failed.append(True);raise PermissionError(13,'synthetic scanner')
            return original(project)
        self.store._write=write
        deadline=time.monotonic()+5
        while not failed and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue(failed)
        self.assertIn(self.pid,self.store.workers)          # still following the job
        video=self.output/'story'/self.pid/(owned+'.mp4')
        self.states[owned]={'state':'done','video':{'type':'output','filename':video.name,'subfolder':str(video.parent.relative_to(self.output))}}
        deadline=time.monotonic()+6
        while self.pid in self.store.workers and time.monotonic()<deadline:time.sleep(.02)
        self.assertEqual(self.store.get(self.pid)['renders'][0]['state'],'done')

    def test_unknown_project_is_reported_without_a_server_path(self):
        with self.assertRaises(ValueError) as caught:self.store.get('f'*32)
        self.assertEqual(str(caught.exception),'프로젝트를 찾을 수 없습니다.')


if __name__=='__main__':unittest.main()
