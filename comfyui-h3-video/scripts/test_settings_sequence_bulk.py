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
TREE = ast.parse((SOURCE / "server.py").read_text(encoding="utf-8"))
NAMES = {"_load_json", "_save_json", "save_settings", "hist_add", "snap", "canvas", "add_anchor", "build_and_queue", "bulk_edit_queue", "bulk_queue_context", "judge_face_side"}


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sent, self.uploaded, self.edited = [], [], []
        self.env = {"json":json, "os":os, "random":random, "re":re, "time":time, "uuid":uuid, "base64":base64, "io":io,
                    "urllib":urllib, "Image":Image, "ImageOps":ImageOps, "ROOT":self.tmp.name, "HERE":self.tmp.name, "CLIENT_ID":"test-client",
                    "HLOCK":threading.Lock(), "PLOCK":threading.Lock(), "SETTINGS_LOCK":threading.Lock(),
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

    def replace(self, pid, prompt):
        self.edited.append((pid,json.loads(json.dumps(prompt))))
        return {"prompt_id":pid,"node_errors":{}}

    def request(self, **changes):
        req={"images":self.photos,"prompt":"safe test prompt","mode":"REF2VA","model":"test-model.safetensors",
             "steps":4,"seed":"100","duration":5,"aspect":"auto","resolution":"draft","loras":[],
             "ui":{"f":{"summary":"safe test prompt"},"shots":[[0,"test"]]}}
        req.update(changes);return req

    def sequence(self, anchor=True, face_boost=True): return self.env["build_and_queue"](self.request(photo_sequence=True,count=20,anchor=anchor,face_boost=face_boost))

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

    def test_bulk_skips_started_or_missing_item(self):
        result=self.sequence()
        req=self.request(edit_ids=[result["jobs"][0]["id"],"missing"],bulk_fields=["model"],steps=8)
        outcome=self.env["bulk_edit_queue"](req)
        self.assertEqual(len(outcome["jobs"]),1);self.assertEqual(len(outcome["failed"]),1)
        self.assertEqual(self.env["HIST_DB"][0]["prompt"],"safe test prompt")

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

    def test_settings_roundtrip_and_invalid_photo_rejected(self):
        data={"version":1,"f":{"summary":"safe","duration":"5"},"model":{"mode":"REF2VA","loras":{}},"images":self.photos,"seed":"123","shots":[[0,"safe"]]}
        self.env["save_settings"](" saved ",data)
        stored=self.env["_load_json"](self.env["SETTINGS"],{})
        self.assertEqual(stored["saved"]["data"],data)
        with self.assertRaises(ValueError): self.env["save_settings"]("bad",dict(data,images=['data:image/png;base64,\" onerror=bad']))


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
