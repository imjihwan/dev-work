"""Four-clip orchestration with synthetic projects and a fake backend only."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
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


if __name__=='__main__':unittest.main()
