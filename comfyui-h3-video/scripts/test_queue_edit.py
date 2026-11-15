"""Exercise queue replacement using a fake backend; no live jobs or media are opened."""
import ast
import copy
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "simple_ui/server.py").read_text(encoding="utf-8"))
FUNCTION = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "replace_queued_prompt")


class Backend:
    def __init__(self):
        self.original = [7, "owned", {"original": True}, {"client_id": "old-client"}, []]
        self.pending = [copy.deepcopy(self.original), [8, "other", {}, {}, []]]
        self.running = []
        self.posts = []
        self.deleted = []
        self.race = False
        self.reject = False
        self.history = {}

    def response(self, value):
        return io.BytesIO(json.dumps(value).encode())

    def call(self, path, data=None, headers=None):
        body = json.loads(data) if data else None
        if path == "/queue" and body is None:
            return self.response({"queue_pending": self.pending, "queue_running": self.running})
        if path == "/queue":
            self.deleted.extend(body["delete"])
            self.pending = [x for x in self.pending if x[1] not in body["delete"]]
            if self.race:
                self.running = [copy.deepcopy(self.original)]
            return self.response({})
        if path.startswith("/history/"):
            return self.response(self.history)
        if path == "/prompt":
            self.posts.append(body)
            if self.reject and body["prompt"] == {"updated": True}:
                raise urllib.error.URLError("invalid replacement")
            self.pending.append([body["number"], body["prompt_id"], body["prompt"], body.get("extra_data", {}), []])
            return self.response({"prompt_id": body["prompt_id"], "number": body["number"], "node_errors": {}})
        raise AssertionError(path)


class QueueEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backend = Backend()
        def save(path, value):
            Path(path).write_text(json.dumps(value), encoding="utf-8")
        self.env = {"json": json, "os": os, "urllib": urllib, "HERE": self.tmp.name,
                    "QUEUE_EDIT_LOCK": threading.Lock(), "HLOCK": threading.Lock(),
                    "HIST_DB": [{"id": "owned"}], "CLIENT_ID": "new-client",
                    "comfy": self.backend.call, "_save_json": save}
        exec(compile(ast.Module(body=[FUNCTION], type_ignores=[]), "queue-edit", "exec"), self.env)

    def edit(self, pid="owned"):
        return self.env["replace_queued_prompt"](pid, {"updated": True})

    def test_keeps_id_and_position_and_other_jobs(self):
        self.assertEqual(self.edit()["prompt_id"], "owned")
        updated = next(x for x in self.backend.pending if x[1] == "owned")
        self.assertEqual(updated[:3], [7, "owned", {"updated": True}])
        self.assertEqual(self.backend.deleted, ["owned"])
        self.assertTrue(any(x[1] == "other" for x in self.backend.pending))
        self.assertFalse((Path(self.tmp.name) / "queue-edit-recovery.json").exists())

    def test_running_job_is_untouched(self):
        self.backend.running = [self.backend.original]
        with self.assertRaises(ValueError): self.edit()
        self.assertEqual(self.backend.deleted, [])
        self.assertEqual(self.backend.posts, [])

    def test_start_during_save_does_not_queue_duplicate(self):
        self.backend.race = True
        with self.assertRaises(ValueError): self.edit()
        self.assertEqual(self.backend.posts, [])
        self.assertEqual(self.backend.running[0][2], {"original": True})

    def test_invalid_replacement_restores_original(self):
        self.backend.reject = True
        with self.assertRaisesRegex(ValueError, "복원"):
            self.edit()
        restored = next(x for x in self.backend.pending if x[1] == "owned")
        self.assertEqual(restored, self.backend.original)

    def test_foreign_job_is_untouched(self):
        with self.assertRaises(ValueError): self.edit("other")
        self.assertEqual(self.backend.deleted, [])


if __name__ == "__main__":
    unittest.main()
