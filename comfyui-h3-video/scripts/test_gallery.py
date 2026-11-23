"""Gallery tests use synthetic metadata and generated colors only."""
import ast
from http.server import BaseHTTPRequestHandler
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("GALLERY_TEST_SOURCE", ROOT / "simple_ui"))
SPEC = importlib.util.spec_from_file_location("gallery_under_test", SOURCE / "gallery.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GalleryStateFileTests(unittest.TestCase):
    """즐겨찾기·휴지통 상태 파일: 읽지 못한 것을 빈 상태로 보고 덮어쓰지 않는다. 합성 파일만 쓴다."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.output, self.home = self.base / "output", self.base / "gallery_data"
        path = self.output / "video/2026-11-15/synthetic.mp4"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"synthetic-not-a-user-video")
        os.utime(path, (time.time() - 20, time.time() - 20))
        self.identity = MODULE.VideoGallery(self.output, self.home).list()["items"][0]["id"]

    def favorite(self, gallery=None):
        gallery = gallery or MODULE.VideoGallery(self.output, self.home)
        return gallery.update({"ids": [self.identity], "action": "favorite", "value": True})

    def test_locked_state_file_fails_the_request_instead_of_wiping_saved_flags(self):
        self.favorite()
        state, saved = self.home / "state.json", (self.home / "state.json").read_bytes()
        gallery, real = MODULE.VideoGallery(self.output, self.home), Path.read_text

        def locked(path, *args, **kwargs):
            if path == state:
                raise PermissionError(13, "synthetic lock")
            return real(path, *args, **kwargs)
        with patch.object(Path, "read_text", locked), patch.object(MODULE.time, "sleep"):
            with self.assertRaises(OSError):
                gallery.list()
            with self.assertRaises(OSError):
                gallery.update({"ids": [self.identity], "action": "trash"})
        self.assertEqual(state.read_bytes(), saved)
        self.assertTrue(gallery.list(mode="favorites")["items"][0]["favorite"])   # 잠금이 풀리면 그대로 읽는다

    def test_corrupt_state_file_is_kept_aside_once_and_the_gallery_keeps_working(self):
        self.favorite()
        state = self.home / "state.json"
        state.write_bytes(b'{"damaged": ')
        gallery = MODULE.VideoGallery(self.output, self.home)
        self.assertEqual(gallery.list()["counts"], {"all": 1, "favorites": 0, "trash": 0})
        kept = [path for path in self.home.iterdir() if ".corrupt-" in path.name]
        self.assertEqual([path.read_bytes() for path in kept], [b'{"damaged": '])
        self.favorite(gallery)
        self.assertEqual(len([path for path in self.home.iterdir() if ".corrupt-" in path.name]), 1)
        self.assertTrue(MODULE.VideoGallery(self.output, self.home).list()["items"][0]["favorite"])

    def test_briefly_refused_replace_is_retried_and_a_lost_save_is_not_shown_as_saved(self):
        real, denied = os.replace, [PermissionError(13, "synthetic scanner")] * 3

        def flaky(source, target):
            if denied:
                raise denied.pop()
            return real(source, target)
        with patch.object(MODULE.os, "replace", flaky), patch.object(MODULE.time, "sleep"):
            self.favorite()
        self.assertEqual(denied, [])
        gallery = MODULE.VideoGallery(self.output, self.home)
        with patch.object(MODULE.os, "replace", side_effect=PermissionError(13, "synthetic scanner")), patch.object(MODULE.time, "sleep"):
            with self.assertRaises(OSError):
                gallery.update({"ids": [self.identity], "action": "trash"})
        listed = gallery.list()["items"][0]
        self.assertEqual((listed["favorite"], listed["trashed"]), (True, False))   # 저장 못 한 휴지통 표시는 보이지 않는다


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.output = self.base / "output"
        self.home = self.base / "gallery_data"
        self.gallery = MODULE.VideoGallery(self.output, self.home)

    def video(self, relative="video/2026-11-15/synthetic.mp4", age=20):
        path = self.output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic-not-a-user-video")
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def test_lazy_start_and_only_owned_video_roots(self):
        self.assertFalse(self.home.exists())
        self.assertIsNone(self.gallery.thumbnailer)
        self.video()
        self.video("story/synthetic/merged.mp4")
        self.video("unrelated/private.mp4")
        self.video("input/not-an-output.mp4")
        result = self.gallery.list()
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["counts"], {"all": 2, "favorites": 0, "trash": 0})
        self.assertTrue(all(len(item["id"]) == 64 for item in result["items"]))
        self.assertTrue(all(item["thumbnail"] is None for item in result["items"]))
        self.assertFalse(self.home.exists(), "Listing does not create a state file or alter videos")

    def test_filters_sort_paging_search_and_metadata_whitelist(self):
        self.video("video/old.mp4", age=60)
        self.video("video/new.mp4", age=10)
        metadata = [{"video": {"filename": "new.mp4", "subfolder": "video", "type": "output"},
                     "id": "synthetic-source", "mode": "REF2VA",
                     "width": 640, "height": 384, "model": "synthetic-model", "loras": [],
                     "prompt": "MUST NOT BE RETURNED", "images": ["MUST NOT BE RETURNED"]}]
        result = self.gallery.list(limit=1, metadata=metadata)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["items"][0]["width"], 640)
        self.assertNotIn("prompt", result["items"][0])
        self.assertNotIn("images", result["items"][0])
        self.assertEqual(result["items"][0]["source_id"], "synthetic-source")
        other = self.gallery.list(offset=1, limit=1)
        self.assertNotEqual(result["items"][0]["id"], other["items"][0]["id"])
        self.assertEqual(self.gallery.list(order="oldest")["items"][0]["id"], other["items"][0]["id"])
        self.assertEqual(self.gallery.list(query="synthetic-model", metadata=metadata)["total"], 1)
        self.assertEqual(self.gallery.list(query=result['items'][0]['id'],metadata=metadata)['items'][0]['source_id'],'synthetic-source')
        self.assertEqual(self.gallery.list(query='synthetic-source',metadata=metadata)['total'],1)
        self.assertEqual(self.gallery.list(query='unknown-source',metadata=metadata)['total'],0)

    def test_generation_time_remains_after_history_is_removed(self):
        self.video('video/timed.mp4')
        metadata=[{'video':{'filename':'timed.mp4','subfolder':'video','type':'output'},'images':['synthetic-input.png'],'generation_seconds':85.123}]
        first=self.gallery.list(metadata=metadata)
        self.assertEqual(first['items'][0]['generation_seconds'],85.123)
        restored=MODULE.VideoGallery(self.output,self.home)
        self.assertEqual(restored.list()['items'][0]['generation_seconds'],85.123)

    def test_favorites_trash_and_restore_persist_without_touching_files(self):
        path = self.video()
        original = (path.read_bytes(), path.stat().st_mtime_ns)
        identity = self.gallery.list()["items"][0]["id"]
        self.gallery.update({"ids": [identity], "action": "favorite", "value": True})
        self.assertEqual(self.gallery.list(mode="favorites")["total"], 1)
        self.gallery.update({"ids": [identity], "action": "trash"})
        self.assertEqual(self.gallery.list()["total"], 0)
        self.assertEqual(self.gallery.list(mode="favorites")["total"], 0)
        self.assertEqual(self.gallery.list(mode="trash")["items"][0]["id"], identity)
        restarted = MODULE.VideoGallery(self.output, self.home)
        self.assertEqual(restarted.list(mode="trash")["total"], 1)
        restarted.update({"ids": [identity], "action": "restore"})
        self.assertEqual(restarted.list(mode="favorites")["total"], 1)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), original)

    def test_regeneration_marker_persists_and_completed_focus_moves_to_top(self):
        self.video("video/older-regenerated.mp4", age=60)
        self.video("video/newer-ordinary.mp4", age=10)
        metadata = [{"id": "regenerated-job", "mode": "REF2VA", "regenerated": True,
                     "video": {"filename": "older-regenerated.mp4", "subfolder": "video", "type": "output"},
                     "images": ["simpleui_0000000001.png"], "prompt": "PRIVATE"}]
        normal = self.gallery.list(metadata=metadata)
        self.assertFalse(normal["items"][0]["regenerated"])
        focused = self.gallery.list(metadata=metadata, focus="regenerated-job", limit=1)
        self.assertEqual(focused["items"][0]["source_id"], "regenerated-job")
        self.assertTrue(focused["items"][0]["regenerated"])
        following = self.gallery.list(metadata=metadata, focus="regenerated-job", offset=1, limit=1)
        self.assertNotEqual(focused["items"][0]["id"], following["items"][0]["id"])
        self.assertNotEqual(normal["revision"], focused["revision"])
        restarted = MODULE.VideoGallery(self.output, self.home)
        self.assertTrue(any(item["regenerated"] for item in restarted.list()["items"]))
        self.assertNotIn("PRIVATE", (self.home / "state.json").read_text())

    def test_new_results_and_changed_files_invalidate_revision_and_thumbnail(self):
        path = self.video()
        first = self.gallery.list()
        known = self.gallery.list(known=first["revision"])
        self.assertTrue(known["unchanged"])
        self.assertEqual(known["items"], [])
        self.video("video/new-result.mp4")
        self.gallery.refresh(force=True)
        second = self.gallery.list(known=first["revision"])
        self.assertFalse(second["unchanged"])
        self.assertEqual(second["total"], 2)
        identity = first["items"][0]["id"]
        old = self.gallery.items[identity]["version"]
        path.write_bytes(b"a different synthetic container")
        stamp = time.time() - 10
        os.utime(path, (stamp, stamp))
        self.gallery.refresh(force=True)
        self.assertNotEqual(old, self.gallery.items[identity]["version"])
        with self.assertRaises(FileNotFoundError):
            self.gallery.thumbnail(identity, old)

    def test_original_image_thumbnail_is_cached_shared_and_survives_history_removal(self):
        self.video()
        before=self.gallery.list()
        item=before["items"][0]
        name="simpleui_0123456789.png"
        metadata=[{"video":item["video"],"images":[name,"simpleui_9876543210.png"],"prompt":"PRIVATE"}]
        buffer=io.BytesIO()
        with Image.new("RGB",(320,180),"blue") as image:
            image.save(buffer,"WEBP")
        calls=[]
        self.gallery.thumbnailer=lambda name:(calls.append(name),buffer.getvalue())[1]
        ready=self.gallery.list(metadata=metadata)
        result=ready["items"][0]
        self.assertEqual(result["thumbnail_kind"],"source")
        self.assertEqual(result["thumbnail_state"],"ready")
        self.assertNotEqual(ready["revision"],before["revision"])
        self.assertEqual(calls,[],"Listing metadata must never decode photos or result videos")
        self.assertNotIn(name,json.dumps(ready))
        self.assertNotIn("PRIVATE",json.dumps(ready))
        version=self.gallery._source_version(name)
        self.assertEqual(self.gallery.thumbnail(item["id"],version),buffer.getvalue())
        self.assertEqual(self.gallery.thumbnail(item["id"],version),buffer.getvalue())
        self.assertEqual(calls,[name],"Only first source image decoded, only once")
        restarted = MODULE.VideoGallery(self.output, self.home)
        self.assertEqual(restarted.list()["items"][0]["thumbnail"], ready["items"][0]["thumbnail"])
        self.assertEqual(restarted.thumbnail(item["id"],version),buffer.getvalue())
        self.video("video/another.mp4")
        self.gallery.refresh(force=True)
        other=next(entry for entry in self.gallery.list()["items"] if entry["id"]!=item["id"])
        self.gallery.remember([{"video":other["video"],"images":[name]}])
        self.assertEqual(self.gallery.thumbnail(other["id"],version),buffer.getvalue())
        self.assertEqual(calls,[name],"Repeated source image reuses its persistent cache")

    def test_partial_files_are_not_listed_and_no_result_decoder_is_started(self):
        self.video(age=0)
        self.assertEqual(self.gallery.list()["total"], 0)
        self.video(age=30)
        self.gallery.refresh(force=True)
        self.assertEqual(self.gallery.list()["total"],1)
        for _ in range(4):
            self.gallery.refresh(force=True)
        self.assertFalse(hasattr(self.gallery,"jobs"))
        self.assertFalse(hasattr(self.gallery,"worker"))

    def test_path_validation_and_unknown_actions_never_mutate_state(self):
        self.video()
        identity = self.gallery.list()["items"][0]["id"]
        for path in ("../outside.mp4", "video/../../outside.mp4", "video/../input/private.mp4", str(self.base / "outside.mp4"), "input/photo.png"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.gallery._path(path)
        for request in ({"ids": ["missing"], "action": "trash"}, {"ids": [identity], "action": "purge"},
                        {"ids": [identity], "action": "favorite", "value": "yes"}, {"ids": [], "action": "restore"}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.gallery.update(request)
        self.assertFalse((self.home / "state.json").exists())

    def test_invalid_or_missing_source_never_falls_back_to_result_frames(self):
        self.video()
        item=self.gallery.list()["items"][0]
        for name in ("../private.png","simpleui_not-valid.png","C:/private.png",None):
            result=self.gallery.list(metadata=[{"video":item["video"],"images":[name]}])
            self.assertIsNone(result["items"][0]["thumbnail"])
            self.assertEqual(result["items"][0]["thumbnail_state"],"missing")
        with self.assertRaises(FileNotFoundError):
            self.gallery.thumbnail(item["id"],"invalid")
        name="simpleui_0123456789.png"
        self.gallery.remember([{"video":item["video"],"images":[name]}])
        with self.assertRaises(FileNotFoundError):
            self.gallery.thumbnail(item["id"],self.gallery._source_version(name))
        self.assertFalse((self.home/"source_thumbnails").exists())

    def test_source_association_can_be_saved_before_result_scan(self):
        entry={"video":{"filename":"synthetic.mp4","subfolder":"video/2026-11-15","type":"output"},
               "images":["simpleui_0123456789.png"],"prompt":"PRIVATE"}
        self.gallery.remember([entry])
        self.assertEqual(self.gallery.items,{})
        self.assertNotIn("PRIVATE",(self.home/"state.json").read_text())
        self.video()
        self.assertIsNotNone(self.gallery.list()["items"][0]["thumbnail"])

    def test_failed_association_write_is_retried_instead_of_kept_only_in_memory(self):
        metadata=[{'video':{'filename':'synthetic.mp4','subfolder':'video'},'images':['simpleui_0123456789.png']}]
        with patch.object(self.gallery,'_save_state',side_effect=OSError('Synthetic failure')):
            with self.assertRaises(OSError):self.gallery.remember(metadata)
        self.assertIsNone(self.gallery.state)
        self.gallery.remember(metadata)
        self.assertTrue((self.home/'state.json').is_file())
        restarted=MODULE.VideoGallery(self.output,self.home);restarted._load_state()
        self.assertEqual(restarted.state,self.gallery.state)

    def test_empty_or_truncated_thumbnail_cache_is_regenerated(self):
        self.video();item=self.gallery.list()['items'][0];name='simpleui_0123456789.png'
        self.gallery.remember([{'video':item['video'],'images':[name]}])
        output=io.BytesIO()
        with Image.new('RGB',(24,32),'blue') as image:image.save(output,'WEBP')
        data=output.getvalue();calls=[]
        self.gallery.thumbnailer=lambda source:(calls.append(source),data)[1]
        version=self.gallery._source_version(name);path=self.home/'source_thumbnails'/(version+'.webp');path.parent.mkdir(parents=True)
        for corrupt in (b'',data[:12]):
            path.write_bytes(corrupt)
            self.assertEqual(self.gallery.thumbnail(item['id'],version),data)
            self.assertEqual(path.read_bytes(),data)
        self.assertEqual(len(calls),2)


class GalleryRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.here = Path(self.temp.name)
        (self.here / "gallery.html").write_text("synthetic gallery", encoding="utf-8")
        self.calls = []
        owner = self
        class Controller:
            def list(self, *args):
                owner.calls.append(("list", args))
                return {"items": [], "total": 0}
            def update(self, body):
                owner.calls.append(("update", body))
                return {"ok": True}
            def thumbnail(self, identity, version):
                owner.calls.append(("thumbnail", identity, version))
                if identity == "missing":
                    raise FileNotFoundError()
                return b"synthetic-cached-webp"
        source = ast.parse((SOURCE / "server.py").read_text(encoding="utf-8-sig"))
        handler = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "H")
        self.entries = [{"video": {"filename": "synthetic.mp4"}, "width": 640,
                         "prompt": "MUST NOT LEAVE HISTORY", "images": ["PRIVATE"]}]
        env = {"BaseHTTPRequestHandler": BaseHTTPRequestHandler, "json": json, "os": os, "urllib": urllib,
               "HERE": str(self.here), "GALLERY": Controller(), "HLOCK": threading.Lock(), "HIST_DB": self.entries}
        def regenerate(body):
            self.calls.append(("regenerate", body))
            return {"id": "synthetic-new"}
        env["regenerate_gallery"] = regenerate
        env["gallery_progress"] = lambda: {"running": True, "pct": 42, "pending": 3, "jobs": []}
        exec(compile(ast.Module(body=[handler], type_ignores=[]), "synthetic-handler", "exec"), env)
        self.handler = env["H"]

    def request(self, path, body=None):
        handler = self.handler.__new__(self.handler)
        raw = json.dumps(body).encode() if body is not None else b""
        handler.path = path
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.response_headers = {}
        handler.send_response = lambda code: setattr(handler, "code", code)
        handler.send_header = lambda key, value: handler.response_headers.update({key: value})
        handler.end_headers = lambda: None
        handler.do_GET() if body is None else handler.do_POST()
        return handler

    def test_gallery_page_is_lazy_and_does_not_request_media_or_jobs(self):
        response = self.request("/gallery")
        self.assertEqual(response.code, 200)
        self.assertEqual(response.wfile.getvalue(), b"synthetic gallery")
        self.assertEqual(self.calls, [])

    def test_metadata_request_passes_source_link_but_never_prompts(self):
        response = self.request("/api/gallery?offset=48&limit=48&mode=favorites&order=oldest&q=synthetic&known=rev")
        self.assertEqual(response.code, 200)
        method, args = self.calls[0]
        self.assertEqual(method, "list")
        self.assertEqual(args[:7], ("48", "48", "favorites", "oldest", "synthetic", "rev", [{"video": {"filename": "synthetic.mp4"}, "width": 640,"images":["PRIVATE"],"regenerated":False}]))
        self.assertIsNone(args[7])

    def test_cached_images_are_immutable_and_missing_images_return_404(self):
        response = self.request("/api/gallery/thumbnail?id=synthetic&v=version")
        self.assertEqual(response.response_headers["Content-Type"], "image/webp")
        self.assertIn("immutable", response.response_headers["Cache-Control"])
        self.assertEqual(response.wfile.getvalue(), b"synthetic-cached-webp")
        self.assertEqual(self.request("/api/gallery/thumbnail?id=missing&v=version").code, 404)

    def test_gallery_update_does_not_call_comfy_queue_or_history_delete(self):
        body = {"ids": ["synthetic"], "action": "trash"}
        response = self.request("/api/gallery/update", body)
        self.assertEqual(response.code, 200)
        self.assertEqual(self.calls, [("update", body)])

    def test_regeneration_route_uses_only_explicit_selection(self):
        body = {"target_id": "synthetic-target", "source_id": "synthetic-source", "request_id": "synthetic-request-001"}
        response = self.request("/api/gallery/regenerate", body)
        self.assertEqual(response.code, 200)
        self.assertEqual(self.calls, [("regenerate", body)])
        self.assertEqual(json.loads(response.wfile.getvalue()), {"id": "synthetic-new"})

    def test_progress_route_returns_status_only(self):
        response = self.request("/api/gallery/progress")
        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.wfile.getvalue()), {"running": True, "pct": 42, "pending": 3, "jobs": []})
        self.assertFalse(self.calls)


class ProgressHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.stage = self.project / "scripts"
        self.stage.mkdir(parents=True)
        self.home = self.project / "ComfyUI/simple_ui"
        self.home.mkdir(parents=True)
        self.handoff = self.stage / "prepare_ui_restart.py"
        # The deployment helper is code, not a runtime data file.
        self.handoff.write_text((ROOT / "scripts/prepare_ui_restart.py").read_text(encoding="utf-8"), encoding="utf-8")
        (self.home / "history.json").write_text(json.dumps([{"id": "own", "prompt": "PRIVATE"}]), encoding="utf-8")
        self.requests = []
        self.queue = {"queue_running": [[1, "own", {"node": {"class_type": "KSampler", "inputs": {"prompt": "PRIVATE"}}}, {"client_id": "old-client"}]],
                      "queue_pending": [[2, "foreign", {"private": "PRIVATE"}, {"client_id": "foreign-client"}]]}

    def fetch(self, url, timeout):
        self.requests.append(url)
        result = {'state':'idle'} if url.endswith('/api/queue/bulk-progress') else self.queue if url.endswith("/queue") else {"state": "running", "pct": 43, "label": "영상 생성"}
        return io.BytesIO(json.dumps(result).encode())

    def test_handoff_only_keeps_owned_progress_and_client_ids(self):
        with patch("urllib.request.urlopen", self.fetch), patch("sys.stdout", io.StringIO()):
            runpy.run_path(str(self.handoff))
        text = (self.home / "ui-restart-state.tmp").read_text(encoding="utf-8")
        state = json.loads(text)
        self.assertEqual(state["client_ids"], ["old-client"])
        self.assertEqual(state["progress"]["own"]["pct"], 43)
        self.assertEqual(state["progress"]["own"]["classes"], {"node": "KSampler"})
        self.assertNotIn("PRIVATE", text)
        self.assertNotIn("foreign", text)
        self.assertEqual(self.requests, ["http://127.0.0.1:8190/api/queue/bulk-progress","http://127.0.0.1:8188/queue", "http://127.0.0.1:8190/api/status?id=own"])

    def test_active_bulk_edit_blocks_ui_restart_without_querying_jobs(self):
        def fetch(url,timeout):
            self.requests.append(url);return io.BytesIO(b'{"state":"running"}')
        with patch('urllib.request.urlopen',fetch),self.assertRaises(SystemExit):runpy.run_path(str(self.handoff))
        self.assertEqual(self.requests,['http://127.0.0.1:8190/api/queue/bulk-progress'])
        self.assertFalse((self.home/'ui-restart-state.tmp').exists())

    def test_active_story_blocks_restart_without_querying_jobs(self):
        state_file = self.home / "story_data/synthetic/project.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text('{"active":{"kind":"render"}}', encoding="utf-8")
        with patch("urllib.request.urlopen", self.fetch), self.assertRaises(SystemExit):
            runpy.run_path(str(self.handoff))
        self.assertEqual(self.requests, [])
        self.assertFalse((self.home / "ui-restart-state.tmp").exists())

    def test_server_consumes_handoff_without_resetting_progress(self):
        path = self.home / "ui-restart-state.tmp"
        state = {"client_id": "old-client", "client_ids": ["old-client"], "progress": {"own": {"pct": 43, "classes": {}}}}
        path.write_text(json.dumps(state), encoding="utf-8")
        tree = ast.parse((SOURCE / "server.py").read_text(encoding="utf-8-sig"))
        nodes = [node for node in tree.body if (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in ("RESTART_CLIENT_IDS", "restart_state_path") for target in node.targets))
                 or (isinstance(node, ast.If) and "restart_state_path" in ast.unparse(node.test))]
        env = {"os": os, "CLIENT_ID": "new-client", "PROGRESS": {}, "_load_json": lambda filename, default: json.loads(Path(filename).read_text(encoding="utf-8"))}
        with patch.dict(os.environ, {"SIMPLEUI_RESTART_STATE": str(path)}):
            exec(compile(ast.Module(body=nodes, type_ignores=[]), "synthetic-progress-restore", "exec"), env)
        self.assertEqual(env["CLIENT_ID"], "old-client")
        self.assertEqual(env["PROGRESS"]["own"]["pct"], 43)
        self.assertEqual(env["RESTART_CLIENT_IDS"], ["old-client"])
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
