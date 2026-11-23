"""Copy settings and queue priority using synthetic entries and in-memory images only."""
import ast
import copy
import io
import json
import os
from pathlib import Path
import re
import threading
import time
import unittest
import urllib.parse

from PIL import Image
from scripts import test_apply_queued_style as fixtures


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("GALLERY_TEST_SOURCE", ROOT / "simple_ui"))


class RegenerationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StyleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.env = self.fixture.env
        tree = ast.parse((SOURCE / "server.py").read_text(encoding="utf-8-sig"))
        names = {"gallery_regeneration_entry", "applied_shift", "regenerate_gallery", "queue_prompt_first", "build_and_queue"}
        code = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        exec(compile(ast.Module(body=code, type_ignores=[]), "synthetic-gallery-regeneration", "exec"), self.env)
        self.target = copy.deepcopy(self.fixture.entry)
        self.target.update(id="target", state="done", video={"filename": "synthetic-target.mp4"}, images=["simpleui_0000000001.png"])
        self.source = copy.deepcopy(self.target)
        self.source.update(id="source", seed=999, anchor=False, duration=9, resolution="1080p", aspect="16:9", model="source-model", steps=6,
                           shift_video=7, shift_audio=4, shift_applied=True, sampler="heun", scheduler="source-scheduler", loras=[{"name": "source-lora", "strength": 0.3}],
                           prompt="subject_definitions: A synthetic person from <Picture 1>.\n\ndetailed_description: A synthetic copied movement.")
        self.source["ui"].update(shots=[[0, "A synthetic copied movement."]], trig=False, oneTake=True)
        self.source["ui"]["f"].update(style="Source synthetic camera.", summary="Source synthetic summary.")
        self.history = [self.target, self.source]
        self.queue = {"queue_running": [[-50, "running", {"untouched": True}, {}, []]],
                      "queue_pending": [[-100, "priority-wait", {"untouched": True}, {}, []], [3, "normal-wait", {"untouched": True}, {}, []]]}
        self.calls, self.submitted = [], []
        photo = io.BytesIO()
        Image.new("RGB", (640, 384), "gray").save(photo, format="PNG")
        self.photo = photo.getvalue()
        self.env.update(HIST_DB=self.history, HLOCK=threading.Lock(), PLOCK=threading.Lock(), QUEUE_EDIT_LOCK=threading.Lock(),
                        GALLERY_REGENERATE_LOCK=threading.Lock(), CLIENT_ID="synthetic-client", PROGRESS={}, time=time, re=re,
                        urllib=urllib, Image=Image, comfy=self.comfy, hist_add=lambda entries: self.history.extend(copy.deepcopy(entries)),
                        object_options=lambda kind, field: ["synthetic-model", "source-model"] if kind=="UNETLoader" else ["source-lora"])
        self.request = {"target_id": "target", "source_id": "source", "request_id": "synthetic-request-0001"}

    def comfy(self, path, data=None, headers=None):
        self.calls.append(path)
        if path.startswith("/view?"):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(path).query))
            self.assertEqual(query, {"filename": "simpleui_0000000001.png", "type": "input"})
            return io.BytesIO(self.photo)
        if path == "/queue":
            self.assertIsNone(data, "No existing job may be deleted or reordered")
            return io.BytesIO(json.dumps(self.queue).encode())
        if path == "/prompt":
            body = json.loads(data)
            self.submitted.append(body)
            identity = "new-" + str(len(self.submitted))
            self.queue["queue_pending"].append([body["number"], identity, body["prompt"], {}, []])
            return io.BytesIO(json.dumps({"prompt_id": identity}).encode())
        raise AssertionError("Unexpected endpoint")

    def test_source_made_before_the_shift_fix_copies_the_shift_that_actually_ran(self):
        del self.source["shift_applied"]
        self.source.update(shift_video=10.0, shift_audio=3.0)
        self.env["regenerate_gallery"](self.request)
        added = self.history[-1]
        self.assertEqual((added["shift_video"], added["shift_audio"]), (12.0, 3.0))
        self.assertTrue(added["shift_applied"])

    def test_copies_source_prompt_and_model_settings_preserving_target_and_queue(self):
        old_history, old_queue = copy.deepcopy(self.history), copy.deepcopy(self.queue)
        result = self.env["regenerate_gallery"](self.request)
        self.assertEqual(result["id"], "new-1")
        added = self.history[-1]
        for key in ("prompt", "model", "steps", "sampler", "scheduler", "shift_video", "shift_audio", "loras"):
            self.assertEqual(added[key], self.source[key], key)
        for key in ("images", "seed", "duration", "aspect", "resolution", "width", "height", "anchor", "mode"):
            self.assertEqual(added[key], self.target[key], key)
        self.assertEqual(added["ui"]["shots"], self.source["ui"]["shots"])
        self.assertEqual(added["ui"]["final"], self.source["prompt"])
        self.assertEqual(added["ui"]["f"]["duration"], self.target["duration"])
        self.assertEqual(self.history[:2], old_history)
        self.assertEqual(self.queue["queue_running"], old_queue["queue_running"])
        self.assertEqual(self.queue["queue_pending"][:2], old_queue["queue_pending"])
        self.assertEqual(self.submitted[0]["number"], -101)
        graph = self.submitted[0]["prompt"]
        self.assertEqual(graph[self.env["SEED"]]["inputs"]["seed_value"], self.target["seed"])
        self.assertEqual(graph[self.env["ANCHOR_IMG"]]["inputs"]["image"], self.target["images"][0])
        self.assertTrue(all(not path.startswith(("/history", "/interrupt", "/upload")) for path in self.calls))

    def test_retry_returns_existing_job_even_if_original_history_was_removed(self):
        first = self.env["regenerate_gallery"](self.request)
        self.history[:2] = []
        count = len(self.calls)
        repeated = self.env["regenerate_gallery"](self.request)
        self.assertEqual(repeated, {"id": first["id"], "already_queued": True})
        self.assertEqual(len(self.submitted), 1)
        self.assertEqual(len(self.calls), count)
        with self.assertRaises(ValueError):
            self.env["regenerate_gallery"](dict(self.request, source_id="changed"))

    def test_concurrent_double_click_queues_once(self):
        results, errors = [], []
        def generate():
            try: results.append(self.env["regenerate_gallery"](self.request))
            except Exception as error: errors.append(type(error).__name__)
        threads = [threading.Thread(target=generate) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=3)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(errors)
        self.assertEqual(len(results), 2)
        self.assertEqual(len(self.submitted), 1)

    def test_missing_history_wrong_mode_or_reference_stops_before_submission(self):
        for changes in ({"source_id": "missing"}, {"request_id": "invalid"}):
            with self.assertRaises(ValueError): self.env["regenerate_gallery"](dict(self.request, **changes))
        self.source["mode"] = "I2VA"
        with self.assertRaises(ValueError): self.env["regenerate_gallery"](self.request)
        self.source["mode"] = "REF2VA"
        self.source["prompt"] = "A synthetic action using <Picture 2>."
        with self.assertRaises(ValueError): self.env["regenerate_gallery"](self.request)
        self.assertEqual(self.calls, [])

    def test_invalid_input_name_never_reads_another_path(self):
        self.target["images"] = ["../outside.png"]
        with self.assertRaises(ValueError): self.env["regenerate_gallery"](self.request)
        self.assertEqual(self.calls, [])

    def test_missing_model_does_not_enqueue_or_change_originals(self):
        original = copy.deepcopy(self.history)
        self.env["object_options"] = lambda kind, field: []
        with self.assertRaises(ValueError): self.env["regenerate_gallery"](self.request)
        self.assertFalse(self.submitted)
        self.assertEqual(self.history, original)


if __name__ == "__main__":
    unittest.main()
