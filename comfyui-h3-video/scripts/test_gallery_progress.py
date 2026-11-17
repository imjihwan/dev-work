"""Status-only gallery monitoring with a fake queue; no live tasks or media."""
import ast
import copy
import io
import json
import os
from pathlib import Path
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("GALLERY_TEST_SOURCE", ROOT / "simple_ui"))


class Clock:
    now = 100
    def monotonic(self): return self.now
    def time(self): return self.now


class GalleryProgressTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((SOURCE / "server.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "gallery_progress")
        self.clock = Clock()
        self.queue = {"queue_running": [[1, "running", {"prompt": "PRIVATE"}, {}, []]], "queue_pending": [[2, "waiting", {}, {}, []]]}
        self.entries = [{"id": "running", "t": 1, "state": "queued", "prompt": "PRIVATE", "ui": {"regeneration": {"source_id": "PRIVATE"}}},
                        {"id": "waiting", "t": 2, "state": "queued", "ui": {"regeneration": {"source_id": "PRIVATE"}}},
                        {"id": "unrelated", "t": 1, "state": "done", "video":{"filename":"synthetic.mp4"}, "prompt": "PRIVATE"}]
        self.calls, self.status_calls = [], []
        self.results = {}
        self.env = {"json": json, "time": self.clock, "HIST_DB": self.entries, "HLOCK": threading.Lock(), "PLOCK": threading.Lock(),
                    "GALLERY_PROGRESS_LOCK": threading.Lock(), "GALLERY_PROGRESS_CACHE": {"at": 0, "value": None},
                    "PROGRESS": {"running": {"pct": 42.4, "label": "PRIVATE", "classes": {"PRIVATE": "PRIVATE"}}},
                    "comfy": self.comfy, "_status": self.status, "hist_result": self.record}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "synthetic-gallery-progress", "exec"), self.env)

    def comfy(self, path, timeout):
        self.assertEqual(path, "/queue")
        self.assertEqual(timeout, 8)
        self.calls.append(path)
        return io.BytesIO(json.dumps(self.queue).encode())

    def record(self, pid, result):
        entry = next(entry for entry in self.entries if entry["id"] == pid)
        entry.update(result, t_end=self.clock.now)

    def status(self, pid, snapshot):
        self.assertEqual(snapshot,self.queue,'Reuse the one existing queue snapshot')
        self.status_calls.append(pid)
        result = self.results.get(pid, {"state": "unknown"})
        return result

    def run_progress(self): return self.env["gallery_progress"]()

    def test_only_status_fields_and_shared_cache(self):
        before = copy.deepcopy(self.queue)
        response = self.run_progress()
        self.assertEqual(set(response), {"running", "pct", "pending", "jobs"})
        self.assertEqual(response["pct"], 42)
        self.assertEqual(response["pending"], 1)
        self.assertNotIn("PRIVATE", json.dumps(response))
        self.assertTrue(all(set(job) == {"id", "state", "completed_at"} for job in response["jobs"]))
        self.assertEqual(self.status_calls, [])
        self.assertEqual(self.run_progress(), response)
        self.assertEqual(len(self.calls), 1)
        self.clock.now += 3
        self.run_progress()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.queue, before)

    def test_completion_updates_history_link_without_returning_result_paths(self):
        self.queue["queue_running"] = []
        self.results["running"] = {"state": "done", "video": {"filename": "PRIVATE-result.mp4"}}
        response = self.run_progress()
        self.assertFalse(response["running"])
        self.assertEqual(self.status_calls, ["running"])
        self.assertEqual(response["jobs"][0], {"id": "running", "state": "done", "completed_at": 100})
        self.assertNotIn("PRIVATE", json.dumps(response))
        self.assertEqual(self.entries[2]["state"], "done", "Already completed history must not be rewritten")

    def test_ordinary_completion_gets_recorded_in_gallery_only_session(self):
        self.entries[2]["state"] = "queued"
        self.results["unrelated"] = {"state":"done", "video":{"filename":"SYNTHETIC-result.mp4"}}
        response = self.run_progress()
        self.assertEqual(self.status_calls, ["unrelated"])
        self.assertEqual(self.entries[2]["state"], "done")
        self.assertEqual(len(response["jobs"]), 2, "Only regeneration status belongs in the public jobs array")
        self.assertNotIn("SYNTHETIC-result", json.dumps(response))

    def test_unknown_ordinary_jobs_do_not_starve_later_completions(self):
        self.entries[:] = [{"id":f"ordinary-{i}","t":1,"state":"queued"} for i in range(20)]
        self.run_progress();self.assertEqual(len(self.status_calls),8)
        self.clock.now+=3;self.run_progress();self.assertEqual(len(self.status_calls),16)
        self.assertEqual(len(set(self.status_calls)),16)
        self.assertTrue(all(entry["state"]=="queued" for entry in self.entries), "An unknown ordinary result is not evidence of loss")

    def test_done_without_video_is_rechecked_for_late_association(self):
        self.entries[2].pop('video')
        self.results['unrelated']={'state':'done','video':{'filename':'synthetic-late.mp4'}}
        self.run_progress();self.assertEqual(self.status_calls,['unrelated'])
        self.assertEqual(self.entries[2]['video']['filename'],'synthetic-late.mp4')

    def test_external_running_job_has_unknown_percentage(self):
        self.queue["queue_running"][0][1] = "external"
        self.queue["queue_pending"].append([3, "running", {}, {}, []])
        response = self.run_progress()
        self.assertTrue(response["running"])
        self.assertIsNone(response["pct"])
        self.assertNotIn("external", json.dumps(response))

    def test_lost_job_settles_and_recent_submission_is_not_marked_lost(self):
        self.queue["queue_running"] = []
        self.entries[0]["t"] = 99
        first = self.run_progress()
        self.assertEqual(self.status_calls, [])
        self.assertEqual(first["jobs"][0]["state"], "queued")
        self.clock.now = 140
        second = self.run_progress()
        self.assertEqual(second["jobs"][0]["state"], "lost")
        self.clock.now += 3
        self.run_progress()
        self.assertEqual(self.status_calls, ["running"])


class GalleryCompletionTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import MagicMock
        tree=ast.parse((SOURCE/'server.py').read_text(encoding='utf-8'))
        function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='hist_result')
        self.entries=[{'id':'synthetic','state':'done','images':['simpleui_0123456789.jpg'],'prompt':'PRIVATE'}]
        self.gallery=MagicMock();self.saved=[]
        self.env={'HIST_DB':self.entries,'HLOCK':threading.Lock(),'time':Clock(),'HIST':'unused','GALLERY':self.gallery,
                  '_save_json':lambda *args:self.saved.append(True)}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'synthetic-hist-result','exec'),self.env)

    def test_late_video_association_is_saved_even_when_state_is_already_done(self):
        video={'filename':'synthetic.mp4','subfolder':'video','type':'output'}
        self.env['hist_result']('synthetic',{'state':'done','video':video})
        self.assertEqual(self.entries[0]['video'],video);self.assertEqual(len(self.saved),1)
        link=self.gallery.remember.call_args.args[0][0]
        self.assertNotIn('PRIVATE',json.dumps(link));self.assertEqual(link['images'],self.entries[0]['images'])

    def test_unchanged_completion_retries_association_without_history_rewrite(self):
        video={'filename':'synthetic.mp4'};self.entries[0]['video']=video
        self.env['hist_result']('synthetic',{'state':'done','video':video})
        self.assertFalse(self.saved);self.gallery.remember.assert_called_once()


if __name__ == "__main__":
    unittest.main()
