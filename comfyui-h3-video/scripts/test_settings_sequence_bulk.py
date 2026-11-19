"""Check settings, rotating references and bulk edits without live requests or user media."""
import ast
import base64
import io
import json
import os
import random
import re
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import uuid
import sys
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("REFERENCE_TEST_SOURCE", ROOT / "simple_ui"))
sys.path.insert(0,str(SOURCE))
from bulk_progress import BulkProgress
from queue_bulk import BuildCache, QueueBulkEditor
TREE = ast.parse((SOURCE / "server.py").read_text(encoding="utf-8"))
NAMES = {"_load_json", "_save_json", "save_settings", "rename_settings", "delete_settings", "hist_add", "snap", "canvas", "add_anchor", "build_and_queue", "person_canvas", "bulk_edit_queue", "bulk_queue_context", "commit_bulk_history", "bulk_queue_editor", "judge_face_side", "prepare_photo_reference", "pooled_photo_reference", "release_photo_references"}


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sent, self.uploaded, self.edited = [], [], []
        self.env = {"BULK_PROGRESS":BulkProgress(),"BuildCache":BuildCache,"QueueBulkEditor":QueueBulkEditor,"QUEUE_EDIT_LOCK":threading.Lock(),"json":json, "os":os, "random":random, "re":re, "time":time, "uuid":uuid, "base64":base64, "io":io,
                    "urllib":urllib, "Image":Image, "ImageOps":ImageOps, "ROOT":self.tmp.name, "HERE":self.tmp.name, "CLIENT_ID":"test-client",
                    "HLOCK":threading.Lock(), "PLOCK":threading.Lock(), "SETTINGS_LOCK":threading.Lock(), "PHOTO_REFERENCE_LOCK":threading.Lock(),
                    "HIST_DB":[], "HIST_MAX":1000, "PROGRESS":{},
                    "HIST":os.path.join(self.tmp.name,"history.json"), "SETTINGS":os.path.join(self.tmp.name,"settings.json"),
                    "TEMPLATE":str(ROOT / "simple_ui/template_api.json"),
                    "card_for":lambda *args:{"auto":{"h3":True,"fmt":"int8"}},
                    "object_options":lambda cls, field:["test-model.safetensors","other-model.safetensors"] if cls=="UNETLoader" else [],
                    "comfy":self.comfy, "upload":self.upload, "replace_queued_prompt":self.replace}
        self.crop_calls=[]
        def crop(raw, model):
            self.crop_calls.append(raw)
            return None
        # 얼굴 방향: 사진 바이트 → 판정 결과(시험마다 정함)
        self.directions={}; self.direction_calls=[]
        def direction(raw, model):
            self.direction_calls.append(raw)
            return self.directions.get(raw)
        self.crop_module=SimpleNamespace(ensure_available=lambda path:None,crop_reference=crop,face_direction=direction,MODEL_NAME='test.onnx')
        self.crop_patch=patch.dict(sys.modules,face_references=self.crop_module)
        self.crop_patch.start();self.addCleanup(self.crop_patch.stop)
        for node in TREE.body:
            if isinstance(node,ast.Assign):
                try: ast.literal_eval(node.value)
                except (ValueError,TypeError): continue
                exec(compile(ast.Module(body=[node],type_ignores=[]),"constant","exec"),self.env)
        functions=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in NAMES]
        exec(compile(ast.Module(body=functions,type_ignores=[]),"features","exec"),self.env)
        self.real_editor=self.env["bulk_queue_editor"]
        self.env["bulk_queue_editor"]=lambda:SimpleNamespace(apply=self.bulk_replace)
        self.photos=[]
        for i in range(5):
            output=io.BytesIO();Image.new("RGB",(16+i,8+i),(i*30,20,40)).save(output,format="PNG")
            self.photos.append("data:image/png;base64,"+base64.b64encode(output.getvalue()).decode())

    def upload(self, raw, ext):
        self.uploaded.append(raw)
        return f"reference-{len(self.uploaded)}.{ext}"

    def response(self, value): return io.BytesIO(json.dumps(value).encode())

    def comfy(self, path, data=None, headers=None):
        if path=="/prompt":
            payload=json.loads(data);pid=str(uuid.uuid4());self.sent.append((pid,payload))
            return self.response({"prompt_id":pid,"node_errors":{}})
        if path=="/queue":
            return self.response({"queue_pending":[[i,pid,p["prompt"],{},[]] for i,(pid,p) in enumerate(self.sent)],"queue_running":[]})
        raise AssertionError(path)

    def replace(self, pid, prompt, expected_graph=None):
        self.edited.append((pid,json.loads(json.dumps(prompt))))
        return {"prompt_id":pid,"node_errors":{},"prompt_verified":True}

    def bulk_replace(self, changes):
        verified,failed=[],[]
        for change in changes:
            try:
                r=self.env['replace_queued_prompt'](change['id'],change['prompt'])
                if not r.get('prompt_verified'):raise ValueError('Synthetic unverified edit')
                verified.append(change)
            except (OSError,ValueError) as exc:failed.append({'id':change['id'],'error':str(exc)})
        if verified:self.env['commit_bulk_history'](verified)
        return verified,failed

    def request(self, **changes):
        req={"images":self.photos,"prompt":"safe test prompt","mode":"REF2VA","model":"test-model.safetensors",
             "steps":4,"seed":"100","duration":5,"aspect":"auto","resolution":"draft","loras":[],
             "ui":{"f":{"summary":"safe test prompt"},"shots":[[0,"test"]]}}
        req.update(changes);return req

    def sequence(self, anchor=True, face_boost=True, **changes): return self.env["build_and_queue"](self.request(photo_sequence=True,count=20,anchor=anchor,face_boost=face_boost,**changes))

    def test_person_guard_keeps_phone_crop_only_when_all_visible_people_fit(self):
        def detect(raw,path):return [0.4,0.1,0.6,0.9]
        from person_framing import crop_contains
        module=SimpleNamespace(detect_bounds=detect,crop_contains=crop_contains,MODEL_NAME='synthetic.onnx')
        with patch.dict(sys.modules,person_framing=module):
            a=self.env['build_and_queue'](self.request(images=self.photos[:1],count=1,mode='I2VA',aspect='9:16',resolution='720p',protect_person=True),prepare_only=True)
            self.assertEqual((a['width'],a['height']),(736,1280))
            module.detect_bounds=lambda raw,path:[0,0,1,1]
            b=self.env['build_and_queue'](self.request(images=self.photos[:1],count=1,mode='I2VA',aspect='9:16',resolution='720p',protect_person=True),prepare_only=True)
            self.assertEqual(b['width']/b['height'],2.0)
            self.assertLessEqual(b['width']*b['height'],self.env['canvas']('auto','720p',(16,8))[0]*self.env['canvas']('auto','720p',(16,8))[1])
            state=json.loads(b['prompt'][self.env['DIRECTOR']]['inputs']['timeline_data'])
            self.assertEqual(state['resolution']['aspect'],'auto')
            self.assertEqual(state['items'][0]['source_width'],16)
            self.assertEqual(self.sent,[])

    def test_person_guard_checks_both_endpoint_frames_and_uses_original_on_detector_failure(self):
        calls=[]
        def detect(raw,path):
            calls.append(1)
            return [.4,.1,.6,.9] if len(calls)==1 else None
        module=SimpleNamespace(detect_bounds=detect,crop_contains=lambda size,target,bounds:bounds is not None,MODEL_NAME='synthetic.onnx')
        with patch.dict(sys.modules,person_framing=module):
            result=self.env['build_and_queue'](self.request(images=[self.photos[0],self.photos[0]],count=1,mode='FL2VA',aspect='9:16',resolution='720p',protect_person=True),prepare_only=True)
            self.assertEqual(len(calls),2)
            self.assertEqual((result['width'],result['height']),self.env['canvas']('auto','720p',(16,8)))
            module.detect_bounds=lambda *args:(_ for _ in ()).throw(RuntimeError('Synthetic detector unavailable'))
            result=self.env['build_and_queue'](self.request(images=self.photos[:1],count=1,aspect='9:16',protect_person=True),prepare_only=True)
            self.assertEqual(result['width']/result['height'],2.0)

    def test_repeats_reuse_person_bounds_without_reading_more_images_or_changing_source_files(self):
        calls=[]
        module=SimpleNamespace(detect_bounds=lambda *args:(calls.append(1) or [.4,.1,.6,.9]),
            crop_contains=lambda *args:True,MODEL_NAME='synthetic.onnx')
        with patch.dict(sys.modules,person_framing=module):
            result=self.env['build_and_queue'](self.request(images=self.photos[:1],count=20,aspect='9:16',protect_person=True))
        self.assertEqual(len(calls),1);self.assertEqual(len(self.uploaded),1)
        self.assertEqual(len(result['jobs']),20)
        self.assertTrue(all(entry['images']==['reference-1.png'] for entry in self.env['HIST_DB']))

    def test_sequence_person_guard_keeps_order_seed_photos_and_per_photo_fallback(self):
        decisions=[False,True,False,True,True]
        def layout(aspect,resolution,sizes,items,raws,index,reference,cache,mode):
            actual='auto' if decisions[index] else aspect
            return self.env['canvas'](actual,resolution,sizes[index]),actual,decisions[index]
        self.env['person_canvas']=layout
        result=self.sequence(protect_person=True,aspect='9:16')
        self.assertEqual([job['framing_fallback'] for job in result['jobs']],decisions)
        for index,entry in enumerate(self.env['HIST_DB']):
            self.assertEqual(entry['aspect'],'auto' if decisions[index] else '9:16')
            self.assertEqual(entry['seed'],100+index)
            self.assertEqual(entry['sequence_index'],index+1)
            self.assertEqual(entry['images'][0],f'reference-{index+1}.png')

    def test_phone_canvas_and_keyframes_use_cover_crop_but_auxiliary_references_keep_aspect(self):
        self.assertEqual(self.env['canvas']('9:16','720p',(1200,800)),(736,1280))
        for mode,count in [('I2VA',1),('FL2VA',2),('REF2VA',5)]:
            prepared=self.env['build_and_queue'](self.request(images=self.photos[:count],mode=mode,aspect='9:16',resolution='720p',count=1),prepare_only=True)
            graph=prepared['prompt'];director=graph[self.env['DIRECTOR']]['inputs'];state=json.loads(director['timeline_data'])
            self.assertEqual((director['width'],director['height']),(736,1280))
            self.assertEqual(state['resolution']['input_scaling'],'Auto' if mode=='REF2VA' else 'Fill and crop')
            self.assertEqual(len(state['items']),count)
            self.assertEqual((state['items'][0]['source_width'],state['items'][0]['source_height']),(16,8))
        self.assertEqual(self.sent,[])

    def test_auto_canvas_obeys_exif_orientation_in_regular_generation(self):
        image=Image.new('RGB',(32,16),(120,140,160));exif=Image.Exif();exif[274]=6
        stream=io.BytesIO();image.save(stream,format='JPEG',exif=exif)
        photo='data:image/jpeg;base64,'+base64.b64encode(stream.getvalue()).decode()
        prepared=self.env['build_and_queue'](self.request(images=[photo],mode='I2VA',count=1,aspect='auto',resolution='auto'),prepare_only=True)
        self.assertEqual((prepared['width'],prepared['height']),(768,1536))
        state=json.loads(prepared['prompt'][self.env['DIRECTOR']]['inputs']['timeline_data'])
        self.assertEqual((state['items'][0]['source_width'],state['items'][0]['source_height']),(16,32))

    def test_native_cover_crop_keeps_a_round_subject_round_and_has_no_black_padding(self):
        import importlib.util
        path=ROOT/'ComfyUI/custom_nodes/ComfyUI-DaSiWa-Nodes/nodes/nodes_scaling.py'
        if not path.exists():self.skipTest('Optional installed DaSiWa resize source unavailable')
        try:import torch
        except ImportError:self.skipTest('Optional PyTorch unavailable')
        torch.set_num_threads(1)
        spec=importlib.util.spec_from_file_location('synthetic_cpu_resize',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        # A centered disk on a light background exposes stretching and black padding.
        yy,xx=torch.meshgrid(torch.arange(120),torch.arange(160),indexing='ij')
        image=torch.full((1,120,160,3),0.35,device='cpu');image[0][(xx-80)**2+(yy-60)**2<=20**2]=1.0
        result=module.DaSiWa_TorchResize().resize(image,'Target resolution','Fill and crop',64,112,1.0,'Lanczos',True,16,'0, 0, 0','center',1,16.0,64)[0]
        self.assertEqual(tuple(result.shape),(1,112,64,3));self.assertEqual(result.device.type,'cpu')
        border=torch.cat([result[0,0,:,0],result[0,-1,:,0],result[0,:,0,0],result[0,:,-1,0]])
        self.assertGreater(float(border.min()),0.3)  # No padded strip; ignore interior Lanczos edge ringing.
        y,x=torch.where(result[0,:,:,0]>0.8)
        self.assertLessEqual(abs(int(x.max()-x.min())-int(y.max()-y.min())),2)
        self.assertLessEqual(abs(float(x.float().mean())-32),2)
        self.assertLessEqual(abs(float(y.float().mean())-56),2)

    def test_nine_references_keep_picture_order_and_first_frame_anchor(self):
        photos=(self.photos*2)[:9]
        self.env["build_and_queue"](self.request(images=photos,count=1,anchor=True))
        self.assertEqual(len(self.sent),1)
        self.assertEqual(len(self.uploaded),9)
        prompt=self.sent[0][1]["prompt"]
        items=json.loads(prompt[self.env["DIRECTOR"]]["inputs"]["timeline_data"])["items"]
        self.assertEqual([item["slot"] for item in items],list(range(9)))
        self.assertEqual([item["order"] for item in items],list(range(9)))
        self.assertEqual([item["value"] for item in items],[f"reference-{i}.png" for i in range(1,10)])
        self.assertEqual(prompt[self.env["ANCHOR_IMG"]]["inputs"]["image"],"reference-1.png")
        self.assertEqual(self.uploaded,[base64.b64decode(photo.split(",",1)[1]) for photo in photos])

    def test_fifty_uploaded_references_make_fifty_rotating_jobs_without_reuploads(self):
        ids=[self.env['prepare_photo_reference']({'image':self.photos[n%5],'group':'synthetic-folder'})['id'] for n in range(50)]
        originals=[self.env['PHOTO_REFERENCES'][key]['original']['value'] for key in ids]
        self.assertEqual(len(self.uploaded),50)
        for index in range(50):
            selected=[ids[(index+n)%50] for n in range(9)]
            self.env['build_and_queue'](self.request(images=[],reference_ids=selected,count=1,anchor=True,seed=str(42+index),reference_sequence_index=index+1))
            graph=self.sent[-1][1]['prompt'];items=json.loads(graph[self.env['DIRECTOR']]['inputs']['timeline_data'])['items']
            self.assertEqual([item['value'] for item in items],[originals[(index+n)%50] for n in range(9)])
            self.assertEqual(graph[self.env['ANCHOR_IMG']]['inputs']['image'],originals[index])
            self.assertEqual(graph[self.env['SEED']]['inputs']['seed_value'],42+index)
        self.assertEqual(len(self.uploaded),50);self.assertEqual(len(self.sent),50)
        self.env['release_photo_references']({'ids':ids})
        self.assertFalse(self.env['PHOTO_REFERENCES']);self.assertEqual(len(self.env['HIST_DB']),50)

    def test_pool_crops_only_auxiliary_references_and_never_the_first_picture(self):
        self.crop_module.crop_reference=lambda raw,model:(b'synthetic-crop',(4,4))
        ids=[self.env['prepare_photo_reference']({'image':image,'group':'synthetic-folder','face_boost':True})['id'] for image in self.photos]
        for index in range(5):
            refs=ids[index:]+ids[:index];reference=self.env['pooled_photo_reference']({'reference_ids':refs})
            records=[self.env['PHOTO_REFERENCES'][key] for key in refs]
            self.assertEqual(reference['entry']['images'],[records[0]['original']['value']]+[item['auxiliary']['value'] for item in records[1:]])
        self.assertEqual(len(self.uploaded),10)

    def test_pool_rejects_cross_folder_expired_duplicate_and_over_limit_references(self):
        a=self.env['prepare_photo_reference']({'image':self.photos[0],'group':'a'})['id']
        b=self.env['prepare_photo_reference']({'image':self.photos[1],'group':'b'})['id']
        for refs in ([a,b],[a,a],[a]*10,[]):
            with self.assertRaises(ValueError):self.env['pooled_photo_reference']({'reference_ids':refs})
        self.env['PHOTO_REFERENCES'][a]['created']=0
        with self.assertRaises(ValueError):self.env['pooled_photo_reference']({'reference_ids':[a]})

    def test_sequence_respects_disabled_anchor_and_keeps_all_rotated_references(self):
        result=self.sequence(anchor=False)
        self.assertEqual(len(result["jobs"]),5)
        names=[f"reference-{i+1}.png" for i in range(5)]
        for i,(_,payload) in enumerate(self.sent):
            p=payload["prompt"]
            self.assertNotIn(self.env["ANCHOR"],p)
            self.assertNotIn(self.env["ANCHOR_IMG"],p)
            self.assertFalse(result["jobs"][i]["anchor"])
            timeline=json.loads(p[self.env["DIRECTOR"]]["inputs"]["timeline_data"])
            self.assertEqual([item["value"] for item in timeline["items"]],names[i:]+names[:i])

    def test_anchor_bulk_change_is_explicit_boolean_and_preserves_other_fields(self):
        result=self.sequence()
        before=json.loads(json.dumps(self.env["HIST_DB"]))
        ids=[job["id"] for job in result["jobs"]]
        with self.assertRaises(ValueError):
            self.env["bulk_edit_queue"]({"edit_ids":ids,"bulk_fields":["anchor"],"anchor":"false"})
        changed=self.env["bulk_edit_queue"]({"edit_ids":ids,"bulk_fields":["anchor"],"anchor":False})
        self.assertEqual(len(changed["jobs"]),5)
        for old,new,(_,graph) in zip(before,self.env["HIST_DB"],self.edited):
            self.assertFalse(new["anchor"])
            self.assertNotIn(self.env["ANCHOR"],graph)
            for key in ("id","seed","images","mode","model","steps","prompt","ui","duration","sequence_index"):
                self.assertEqual(old.get(key),new.get(key))

    def test_five_photos_make_five_rotated_anchored_jobs(self):
        result=self.sequence();self.assertEqual(len(result["jobs"]),5);self.assertEqual(len(self.uploaded),5)
        names=[f"reference-{i+1}.png" for i in range(5)]
        for i,(_,payload) in enumerate(self.sent):
            p=payload["prompt"];tl=json.loads(p[self.env["DIRECTOR"]]["inputs"]["timeline_data"])
            expected=names[i:]+names[:i]
            self.assertEqual([x["value"] for x in tl["items"]],expected)
            self.assertEqual([x["slot"] for x in tl["items"]],list(range(5)))
            self.assertEqual(p[self.env["ANCHOR_IMG"]]["inputs"]["image"],expected[0])
            self.assertEqual(p[self.env["SEED"]]["inputs"]["seed_value"],100+i)
            self.assertEqual(result["jobs"][i]["images"],expected)

    def test_regular_repeat_does_not_rotate_or_add_anchor(self):
        result=self.env["build_and_queue"](self.request(count=2))
        self.assertEqual(len(result["jobs"]),2)
        self.assertEqual(result["jobs"][0]["images"],result["jobs"][1]["images"])
        self.assertNotIn(self.env["ANCHOR_IMG"],self.sent[0][1]["prompt"])
        self.assertEqual(self.crop_calls,[])

    def test_sequence_crops_are_cached_and_only_secondary_references_use_them(self):
        def crop(raw, model):
            self.crop_calls.append(raw)
            output=io.BytesIO();Image.new('RGB',(10,12),'blue').save(output,format='PNG')
            return output.getvalue(),(10,12)
        self.crop_module.crop_reference=crop
        photos=(self.photos*2)[:9]
        outcome=self.env['build_and_queue'](self.request(images=photos,photo_sequence=True,anchor=True,face_boost=True))
        self.assertEqual(len(self.crop_calls),9)
        self.assertEqual(len(self.uploaded),18)
        originals=[f'reference-{i*2+1}.png' for i in range(9)]
        crops=[f'reference-{i*2+2}.png' for i in range(9)]
        for primary,((pid,payload),entry) in enumerate(zip(self.sent,self.env['HIST_DB'])):
            graph=payload['prompt']
            order=list(range(primary,9))+list(range(primary))
            expected=[originals[primary]]+[crops[i] for i in order[1:]]
            timeline=json.loads(graph[self.env['DIRECTOR']]['inputs']['timeline_data'])
            self.assertEqual([item['value'] for item in timeline['items']],expected)
            self.assertEqual(entry['images'],expected)
            self.assertEqual(graph[self.env['ANCHOR_IMG']]['inputs']['image'],originals[primary])
            self.assertEqual(timeline['items'][0]['source_width'],16+primary%5)
            self.assertEqual([item['source_width'] for item in timeline['items'][1:]],[10]*8)
            self.assertEqual(graph[self.env['SEED']]['inputs']['seed_value'],100+primary)
        self.assertEqual(outcome['face_crops'],{'cropped':9,'original':0})

    def test_sequence_detector_failure_uses_originals_and_single_photo_needs_no_detector(self):
        self.sequence()
        self.assertEqual(len(self.crop_calls),5)
        self.crop_module.ensure_available=lambda path:(_ for _ in ()).throw(AssertionError('Not needed'))
        self.env['build_and_queue'](self.request(images=self.photos[:1],photo_sequence=True))

    def test_face_boost_is_off_by_default(self):
        self.crop_module.ensure_available=lambda path:(_ for _ in ()).throw(AssertionError('Not needed when off'))
        outcome=self.sequence(face_boost=False)
        self.assertEqual(self.crop_calls,[]);self.assertEqual(len(self.uploaded),len(self.photos))
        self.assertIsNone(outcome['face_crops'])

    def test_face_boost_in_regular_multi_photo_keeps_picture_one_original(self):
        def crop(raw, model):
            self.crop_calls.append(raw);return (b'face-crop',(10,10))
        self.crop_module.crop_reference=crop
        outcome=self.env['build_and_queue'](self.request(count=1,face_boost=True))
        self.assertEqual(len(self.crop_calls),len(self.photos)-1)  # 사진 1은 자르지 않는다
        graph=self.sent[0][1]['prompt']
        timeline=json.loads(graph[self.env['DIRECTOR']]['inputs']['timeline_data'])
        values=[item['value'] for item in timeline['items']]
        self.assertEqual(values[0],'reference-1.png')
        self.assertTrue(all(item['source_width']==10 for item in timeline['items'][1:]))
        self.assertEqual(self.env['HIST_DB'][0]['images'],values)
        self.assertEqual(outcome['face_crops'],{'cropped':len(self.photos)-1,'original':0})

    def test_face_boost_never_crops_first_last_frames(self):
        self.crop_module.ensure_available=lambda path:(_ for _ in ()).throw(AssertionError('FL2VA frames are not cropped'))
        self.env['build_and_queue'](self.request(images=self.photos[:2],mode='FL2VA',count=1,face_boost=True))
        self.assertEqual(self.crop_calls,[])

    def test_missing_detector_queues_originals_and_reports_reason(self):
        self.crop_module.ensure_available=lambda path:(_ for _ in ()).throw(ValueError('Unavailable'))
        outcome=self.sequence()
        self.assertEqual(self.crop_calls,[])
        self.assertEqual(len(self.sent),len(self.photos))
        self.assertEqual(len(self.uploaded),len(self.photos))
        self.assertEqual(outcome['face_crops']['unavailable'],'Unavailable')
        self.assertEqual(outcome['face_crops']['cropped'],0)

    def test_bulk_preserves_photos_order_seed_mode_and_anchor(self):
        result=self.sequence();before=json.loads(json.dumps(self.env["HIST_DB"]));uploads=len(self.uploaded)
        ids=[j["id"] for j in result["jobs"][:2]]
        req=self.request(edit_ids=ids,bulk_fields=["content","model","video"],prompt="updated",model="other-model.safetensors",steps=8,duration=3,
                         images=["forbidden replacement"],seed="999",mode="FL2VA",anchor=False)
        outcome=self.env["bulk_edit_queue"](req)
        self.assertEqual(len(outcome["jobs"]),2);self.assertEqual(outcome["failed"],[]);self.assertEqual(len(self.uploaded),uploads)
        for i,(_,p) in enumerate(self.edited):
            updated=next(e for e in self.env["HIST_DB"] if e["id"]==ids[i])
            for key in ("images","seed","mode","anchor"):
                self.assertEqual(updated[key],before[i][key])
            self.assertEqual(updated["prompt"],"updated");self.assertEqual(updated["duration"],3)
            self.assertEqual(p[self.env["ANCHOR_IMG"]]["inputs"]["image"],before[i]["images"][0])
        self.assertEqual(self.env["HIST_DB"][2]["prompt"],before[2]["prompt"])

    def test_single_action_mode_follows_content_in_bulk_without_touching_other_settings(self):
        result=self.sequence();ids=[job["id"] for job in result["jobs"]]
        before=json.loads(json.dumps(self.env["HIST_DB"]))
        changed=self.env["bulk_edit_queue"](self.request(edit_ids=ids,bulk_fields=["content"],prompt="Synthetic prose.",ui={"f":{"summary":"Synthetic"},"shots":[[0,"Continuous synthetic movement."]],"actionMode":"single"}))
        self.assertEqual(len(changed["jobs"]),5)
        for old,new in zip(before,self.env["HIST_DB"]):
            self.assertEqual(new["ui"]["actionMode"],"single")
            self.assertEqual(new["ui"]["shots"],[[0,"Continuous synthetic movement."]])
            for key in ("id","images","seed","mode","anchor","model","steps","duration"):
                self.assertEqual(old.get(key),new.get(key))

    def test_bulk_skips_started_or_missing_item(self):
        result=self.sequence()
        req=self.request(edit_ids=[result["jobs"][0]["id"],"missing"],bulk_fields=["model"],steps=8)
        outcome=self.env["bulk_edit_queue"](req)
        self.assertEqual(len(outcome["jobs"]),1);self.assertEqual(len(outcome["failed"]),1)
        self.assertEqual(self.env["HIST_DB"][0]["prompt"],"safe test prompt")

    def test_apply_current_updates_all_settings_including_anchor_but_keeps_each_photo_seed_mode(self):
        self.sequence(anchor=True);before=json.loads(json.dumps(self.env['HIST_DB']));uploads=len(self.uploaded)
        request=self.request(all_pending=True,apply_current=True,bulk_fields=['model'],prompt='Current synthetic prompt.',
            model='other-model.safetensors',steps=8,duration=3,aspect='16:9',anchor=False,seed='999',images=[],
            ui={'f':{'summary':'Current summary.','style':'Current camera.','keep':'Current appearance.'},'shots':[[0,'Current action.']],'oneTake':False,'trig':False,'actionMode':'single'})
        result=self.env['bulk_edit_queue'](request)
        self.assertTrue(result['apply_current']);self.assertEqual(result['failed'],[]);self.assertEqual(len(result['jobs']),5)
        self.assertEqual(len(self.uploaded),uploads)
        for old,new in zip(before,self.env['HIST_DB']):
            for key in ('id','images','seed','mode','sequence_index'):self.assertEqual(new.get(key),old.get(key),key)
            self.assertEqual(new['prompt'],'Current synthetic prompt.');self.assertEqual(new['model'],'other-model.safetensors')
            self.assertEqual(new['steps'],8);self.assertEqual(new['duration'],3);self.assertFalse(new['anchor'])
            self.assertEqual(new['ui']['f']['style'],'Current camera.');self.assertFalse(new['ui']['oneTake']);self.assertFalse(new['ui']['trig'])
        for (_,graph),old in zip(self.edited,before):
            self.assertEqual(graph[self.env['DIRECTOR']]['inputs']['prompt'],'Current synthetic prompt.')
            self.assertEqual(graph[self.env['SEED']]['inputs']['seed_value'],old['seed'])
            self.assertNotIn(self.env['ANCHOR'],graph)
        self.assertEqual(self.env['BULK_PROGRESS'].snapshot()['succeeded'],5)

    def test_apply_current_rejects_invalid_flag_and_missing_anchor_before_any_edit(self):
        for request in ({'apply_current':'yes','all_pending':True},{'apply_current':True,'all_pending':True}):
            with self.assertRaises(ValueError):self.env['bulk_edit_queue'](request)
        self.assertEqual(self.edited,[])

    def test_full_six_hundred_pipeline_caches_common_options_and_preserves_all_identities(self):
        import copy
        from test_queue_bulk import Backend
        self.sequence(anchor=True)
        originals=copy.deepcopy(self.env['HIST_DB'])
        graphs=[copy.deepcopy(body['prompt']) for _,body in self.sent]
        backend=Backend(0)
        records=[]
        for index in range(600):
            entry=copy.deepcopy(originals[index%5]);entry.update(id=f'synthetic-{index}',seed=1000+index)
            graph=copy.deepcopy(graphs[index%5]);graph[self.env['SEED']]['inputs']['seed_value']=entry['seed']
            records.append(entry)
            backend.pending.append([index,entry['id'],graph,{'synthetic_metadata':index},[]])
        # One running job and one foreign job must remain completely unchanged.
        backend.running=[[-1,'running',copy.deepcopy(graphs[0]),{},[]]]
        backend.pending.append([601,'foreign',copy.deepcopy(graphs[0]),{},[]])
        self.env['HIST_DB'][:]=copy.deepcopy(records)+[dict(copy.deepcopy(originals[0]),id='running')]
        before=copy.deepcopy(backend.pending);running=copy.deepcopy(backend.running)
        self.env.update(comfy=backend.request,bulk_queue_editor=self.real_editor)
        saves=[];options=[];cards=[]
        original_save=self.env['_save_json']
        def save(path,value):
            if path==self.env['HIST']:saves.append(1)
            original_save(path,value)
        def options_for(cls,field):
            options.append((cls,field))
            return ['other-model.safetensors'] if cls=='UNETLoader' else ['synthetic-a','synthetic-b','synthetic-c']
        def card(kind,name):
            cards.append((kind,name));return {'auto':{'h3':True,'fmt':'int8'}}
        self.env.update(_save_json=save,object_options=options_for,card_for=card)
        loras=[{'name':name,'strength':0.5} for name in ['synthetic-a','synthetic-b','synthetic-c']]
        request=self.request(all_pending=True,apply_current=True,images=[],prompt='Current synthetic action.',
            anchor=False,model='other-model.safetensors',steps=8,loras=loras,duration=3,seed='999999',
            ui={'f':{'summary':'Current synthetic action.','style':'Current synthetic camera.','keep':'Current synthetic retention.'},
                'shots':[[0,'Current synthetic action.']],'final':None,'actionMode':'single','oneTake':True,'trig':True})
        outcome=self.env['bulk_edit_queue'](request)
        self.assertEqual(outcome['verified_count'],600);self.assertEqual(outcome['failed'],[])
        self.assertEqual(outcome['target_count'],600)
        self.assertEqual(len(saves),24);self.assertEqual(len(options),2);self.assertEqual(len(cards),4)
        self.assertEqual(sum(path=='/queue' and body is None for path,body in backend.calls),49)
        rows={row[1]:row for row in backend.pending};saved={e['id']:e for e in self.env['HIST_DB']}
        for old,prior in zip(records,before):
            row=rows[old['id']];entry=saved[old['id']]
            self.assertEqual(row[:2],prior[:2]);self.assertEqual(row[3:],prior[3:])
            for key in ('images','seed','mode','sequence_index','t'):self.assertEqual(entry[key],old[key])
            self.assertEqual(entry['prompt'],request['prompt']);self.assertEqual(entry['steps'],8)
            self.assertEqual(entry['loras'],loras);self.assertFalse(entry['anchor'])
            director=row[2][self.env['DIRECTOR']]['inputs']
            self.assertEqual(director['prompt'],request['prompt'])
            self.assertEqual(json.loads(director['timeline_data'])['resolved_prompt'],request['prompt'])
            self.assertEqual(row[2][self.env['SEED']]['inputs']['seed_value'],old['seed'])
            self.assertNotIn(self.env['ANCHOR'],row[2])
        self.assertEqual(backend.running,running);self.assertEqual(rows['foreign'],before[-1])
        progress=self.env['BULK_PROGRESS'].snapshot()
        self.assertEqual(progress['state'],'done');self.assertEqual(progress['verified'],600)
        self.assertEqual(list(Path(self.tmp.name).glob('queue-edit-recovery/*.json')),[])

    def test_corrupt_saved_ui_fails_only_that_item_and_does_not_abort_other_changes(self):
        self.sequence();self.env['HIST_DB'][2]['ui']=['invalid']
        result=self.env['bulk_edit_queue'](self.request(all_pending=True,bulk_fields=['model'],steps=8))
        self.assertEqual(len(result['jobs']),4);self.assertEqual(len(result['failed']),1)
        self.assertEqual(self.env['BULK_PROGRESS'].snapshot()['processed'],5)

    def test_bulk_reuses_recorded_direction_without_reading_any_reference_image(self):
        self.sequence()
        for entry in self.env['HIST_DB']:entry['face_side']={'side':'left','used':'left','offset':-0.2}
        def forbidden(name):raise AssertionError('Existing direction must not read an image')
        self.env['input_bytes']=forbidden
        result=self.env['bulk_edit_queue'](self.request(all_pending=True,bulk_fields=['content'],prompt='Synthetic {{face_side}} direction.'))
        self.assertEqual(len(result['jobs']),5)
        for _,graph in self.edited:self.assertEqual(graph[self.env['DIRECTOR']]['inputs']['prompt'],'Synthetic left direction.')

    def test_model_only_bulk_keeps_recorded_direction_even_without_a_placeholder(self):
        self.sequence()
        saved={'side':'left','used':'left','offset':-0.2}
        for entry in self.env['HIST_DB']:entry['face_side']=dict(saved)
        result=self.env['bulk_edit_queue'](self.request(all_pending=True,bulk_fields=['model'],steps=8))
        self.assertEqual(len(result['jobs']),5)
        for entry in self.env['HIST_DB']:self.assertEqual(entry['face_side'],saved)

    def test_bulk_metadata_checkpoint_keeps_fast_finish_status_and_timing(self):
        self.sequence();entry=self.env['HIST_DB'][0]
        entry.update(state='done',video={'synthetic':True},generation_started_at=10,generation_finished_at=15,generation_seconds=5,t_end=15)
        proposed={**entry,'state':'queued','video':None,'prompt':'New synthetic prompt.'}
        self.env['commit_bulk_history']([{'id':entry['id'],'entry':proposed}])
        self.assertEqual(entry['state'],'done');self.assertEqual(entry['video'],{'synthetic':True});self.assertEqual(entry['generation_seconds'],5)

    def test_sequence_cannot_replace_one_existing_job(self):
        with self.assertRaises(ValueError): self.env["build_and_queue"](self.request(photo_sequence=True,edit_id="existing"))
        self.assertEqual(self.sent,[])

    def test_all_pending_context_excludes_running_and_foreign_and_copies_only_first_entry(self):
        self.sequence()
        items=[[i,pid,payload["prompt"],{},[]] for i,(pid,payload) in enumerate(self.sent)]
        queue={"queue_running":[items[0]],"queue_pending":[items[3],[-1,"foreign",{}, {},[]],items[2],items[1],items[4]]}
        self.env["comfy"]=lambda path:self.response(queue)
        context=self.env["bulk_queue_context"]()
        self.assertEqual(context["ids"],[item[1] for item in items[1:]])
        self.assertEqual(context["total"],4)
        self.assertEqual(context["first"]["id"],items[1][1])
        self.assertEqual(context["first"]["position"],2)
        context["first"]["ui"]["f"]["summary"]="edited copy"
        self.assertEqual(self.env["HIST_DB"][1]["ui"]["f"]["summary"],"safe test prompt")

    def test_all_pending_resolves_new_jobs_at_save_time_and_preserves_unselected_values(self):
        self.sequence()
        context=self.env["bulk_queue_context"]()
        added=self.env["build_and_queue"](self.request(count=1,seed="333",anchor=True))
        before=json.loads(json.dumps(self.env["HIST_DB"]))
        items=[[i,pid,payload["prompt"],{},[]] for i,(pid,payload) in enumerate(self.sent)]
        self.env["comfy"]=lambda path:self.response({"queue_running":[items[0]],"queue_pending":items[1:]+[[20,"foreign",{}, {},[]]]})
        outcome=self.env["bulk_edit_queue"](self.request(all_pending=True,edit_ids=context["ids"],bulk_fields=["model"],model="other-model.safetensors",steps=8))
        self.assertTrue(outcome["all_pending"])
        self.assertEqual(outcome["target_count"],5)
        self.assertEqual(outcome["failed"],[])
        self.assertIn(added["id"],[job["id"] for job in outcome["jobs"]])
        self.assertNotIn(items[0][1],[job["id"] for job in outcome["jobs"]])
        self.assertEqual(self.env["HIST_DB"][0],before[0])
        for old,new in zip(before[1:],self.env["HIST_DB"][1:]):
            for key in ("images","seed","prompt","duration","aspect","resolution","anchor","mode","sequence_index"):
                self.assertEqual(new[key],old[key],key)
            self.assertEqual(new["model"],"other-model.safetensors")
            self.assertEqual(new["steps"],8)

    def test_all_pending_skips_a_job_that_starts_during_the_bulk_request(self):
        result=self.sequence()
        running_id=result["jobs"][0]["id"]
        original=json.loads(json.dumps(self.env["HIST_DB"][0]))
        def replace(pid,prompt):
            if pid==running_id: raise ValueError("already started")
            return self.replace(pid,prompt)
        self.env["replace_queued_prompt"]=replace
        response=self.env["bulk_edit_queue"](self.request(all_pending=True,bulk_fields=["model"],steps=8))
        self.assertEqual(len(response["jobs"]),4)
        self.assertEqual(len(response["failed"]),1)
        self.assertEqual(self.env["HIST_DB"][0],original)

    def test_all_pending_empty_and_invalid_scope(self):
        self.assertEqual(self.env["bulk_queue_context"](),{"ids":[],"total":0,"first":None})
        response=self.env["bulk_edit_queue"]({"all_pending":True,"bulk_fields":["model"],"steps":8})
        self.assertEqual(response["jobs"],[])
        self.assertEqual(response["target_count"],0)
        with self.assertRaises(ValueError): self.env["bulk_edit_queue"]({"all_pending":"true","bulk_fields":["model"]})
        self.assertFalse(self.sent)

    def test_full_bulk_pipeline_reads_back_native_graph_and_retains_partial_failure(self):
        self.sequence();before=json.loads(json.dumps(self.env['HIST_DB']))
        rows=[[i,pid,json.loads(json.dumps(body['prompt'])),{},[]] for i,(pid,body) in enumerate(self.sent)]
        running=[rows[0]];pending=rows[1:];originals={row[1]:row for row in rows};bad=rows[-1][1]
        def native(path,data=None,headers=None):
            nonlocal pending
            body=json.loads(data) if data else None
            if path=='/queue' and body is None:return self.response({'queue_running':running,'queue_pending':pending})
            if path=='/queue':
                pending=[row for row in pending if row[1] not in body['delete']]
                return io.BytesIO(b'')
            if path.startswith('/api/jobs/'):
                pid=path.rsplit('/',1)[1]
                if any(row[1]==pid for row in running):return self.response({'id':pid,'status':'in_progress'})
                if any(row[1]==pid for row in pending):return self.response({'id':pid,'status':'pending'})
                raise urllib.error.HTTPError(path,404,'Absent',{},self.response({'error':'Job not found'}))
            if path.startswith('/history/'):return self.response({})
            if path=='/prompt':
                graph=originals[bad][2] if body['prompt_id']==bad else body['prompt']
                pending.append([body['number'],body['prompt_id'],json.loads(json.dumps(graph)),body.get('extra_data',{}),[]])
                return self.response({'prompt_id':body['prompt_id'],'node_errors':{}})
            raise AssertionError(path)
        function=next(node for node in TREE.body if isinstance(node,ast.FunctionDef) and node.name=='replace_queued_prompt')
        self.env.update(comfy=native,QUEUE_EDIT_LOCK=threading.Lock(),bulk_queue_editor=self.real_editor)
        exec(compile(ast.Module(body=[function],type_ignores=[]),'native-queue-replace','exec'),self.env)
        request=self.request(all_pending=True,bulk_fields=['content'],prompt='New synthetic final action.',
                             ui={'f':{'summary':'New synthetic action.'},'shots':[[0,'New synthetic action.']],'final':None})
        result=self.env['bulk_edit_queue'](request)
        self.assertEqual(result['verified_count'],3);self.assertEqual(len(result['jobs']),3);self.assertEqual(len(result['failed']),1)
        self.assertEqual(running[0],rows[0]);self.assertEqual(self.env['HIST_DB'][0],before[0])
        self.assertEqual([row[1] for row in sorted(pending,key=lambda row:row[0])],[row[1] for row in rows[1:]])
        for row in pending:
            saved=next(entry for entry in self.env['HIST_DB'] if entry['id']==row[1])
            if row[1]==bad:
                self.assertEqual(saved,before[-1]);continue
            director=row[2][self.env['DIRECTOR']]['inputs'];timeline=json.loads(director['timeline_data'])
            self.assertEqual(director['prompt'],'New synthetic final action.')
            self.assertEqual(timeline['resolved_prompt'],director['prompt'])
            self.assertEqual(timeline['builder_state']['simple_prompt'],director['prompt'])
            self.assertEqual(timeline['continuity']['continuation_prompt'],director['prompt'])
            self.assertEqual(json.loads(director['builder_state'])['simple_prompt'],director['prompt'])
            self.assertEqual(saved['prompt'],director['prompt']);self.assertEqual(saved['ui']['shots'],request['ui']['shots'])

    def test_settings_roundtrip_and_invalid_photo_rejected(self):
        data={"version":1,"f":{"summary":"safe","duration":"5"},"model":{"mode":"REF2VA","loras":{}},"images":self.photos,"seed":"123","shots":[[0,"safe"]]}
        self.env["save_settings"](" saved ",data)
        stored=self.env["_load_json"](self.env["SETTINGS"],{})
        self.assertEqual(stored["saved"]["data"],data)
        with self.assertRaises(ValueError): self.env["save_settings"]("bad",dict(data,images=['data:image/png;base64,\" onerror=bad']))

    def test_settings_rename_preserves_data_timestamp_and_other_entries(self):
        data={'f':{'summary':'synthetic'},'model':{'loras':{}},'images':self.photos}
        self.env['save_settings']('original',data);self.env['save_settings']('other',data)
        before=self.env['_load_json'](self.env['SETTINGS'],{})
        self.env['rename_settings']('original',' renamed ')
        after=self.env['_load_json'](self.env['SETTINGS'],{})
        self.assertNotIn('original',after)
        self.assertEqual(after['renamed'],before['original'])
        self.assertEqual(after['other'],before['other'])
        self.assertEqual(self.sent,[]);self.assertEqual(self.uploaded,[])

    def test_settings_rename_rejects_duplicates_missing_and_invalid_names_without_writes(self):
        data={'f':{},'model':{},'images':[]}
        self.env['save_settings']('first',data);self.env['save_settings']('second',data)
        before=Path(self.env['SETTINGS']).read_bytes()
        for old,new in [('first','second'),('missing','new'),('first','  '),('first','x'*61)]:
            with self.subTest(old=old,new=new),self.assertRaises(ValueError):self.env['rename_settings'](old,new)
            self.assertEqual(Path(self.env['SETTINGS']).read_bytes(),before)
        self.env['rename_settings']('first','first')
        self.assertEqual(Path(self.env['SETTINGS']).read_bytes(),before)

    def test_settings_delete_removes_only_named_entry_and_handles_last_entry(self):
        data={'f':{},'model':{},'images':self.photos}
        self.env['save_settings']('first',data);self.env['save_settings']('second',data)
        self.env['delete_settings']('first')
        self.assertEqual(list(self.env['_load_json'](self.env['SETTINGS'],{})),['second'])
        with self.assertRaises(ValueError):self.env['delete_settings']('missing')
        self.env['delete_settings']('second')
        self.assertEqual(self.env['_load_json'](self.env['SETTINGS'],{}),{})
        self.assertEqual(self.sent,[]);self.assertEqual(self.uploaded,[])


    def raw_of(self, index): return base64.b64decode(self.photos[index].split(",",1)[1])

    def sent_prompt(self, i): return self.sent[i][1]["prompt"][self.env["DIRECTOR"]]["inputs"]["prompt"]

    def test_face_side_token_is_filled_from_picture_one_and_recorded(self):
        self.directions[self.raw_of(0)]={"side":"left","offset":-0.21}
        self.env["build_and_queue"](self.request(count=1,prompt="Turn toward the {{face_side}} side of the frame."))
        self.assertEqual(self.sent_prompt(0),"Turn toward the left side of the frame.")
        entry=self.env["HIST_DB"][0]
        self.assertEqual(entry["prompt"],"Turn toward the {{face_side}} side of the frame.")  # 이력엔 자리표시 그대로(다시 쓰면 다시 잰다)
        self.assertEqual(entry["face_side"],{"side":"left","offset":-0.21,"used":"left"})

    def test_front_or_undetected_face_uses_the_right_side(self):
        self.directions[self.raw_of(0)]={"side":"front","offset":0.01}
        self.env["build_and_queue"](self.request(count=1,prompt="toward the {{face_side}}"))
        self.assertEqual(self.sent_prompt(0),"toward the right");self.assertEqual(self.env["HIST_DB"][0]["face_side"]["side"],"front")
        self.sent.clear();self.env["HIST_DB"].clear()
        self.env["build_and_queue"](self.request(count=1,images=self.photos[1:2],prompt="toward the {{face_side}}"))
        self.assertEqual(self.sent_prompt(0),"toward the right");self.assertEqual(self.env["HIST_DB"][0]["face_side"]["side"],"none")

    def test_sequence_judges_each_job_by_its_own_picture_one(self):
        self.directions[self.raw_of(0)]={"side":"left","offset":-0.3}
        self.directions[self.raw_of(1)]={"side":"right","offset":0.3}
        self.env["build_and_queue"](self.request(images=self.photos[:2],photo_sequence=True,prompt="go {{face_side}}"))
        self.assertEqual([self.sent_prompt(i) for i in range(2)],["go left","go right"])
        self.assertEqual([e["face_side"]["used"] for e in self.env["HIST_DB"]],["left","right"])

    def test_prompt_without_token_never_measures_faces(self):
        self.env["build_and_queue"](self.request(count=1))
        self.assertEqual(self.direction_calls,[]);self.assertIsNone(self.env["HIST_DB"][0]["face_side"])


if __name__=="__main__": unittest.main()
