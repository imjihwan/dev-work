"""Restart checks with a fake queue only; never inspects or changes live jobs."""
import ast
import copy
import io
import json
import threading
import time
import unittest
import urllib.error
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "simple_ui/server.py").read_text(encoding="utf-8"))
FUNCTION = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "restart_running_prompt")


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.graph = {"1": {"class_type": "SafeTest", "inputs": {"seed": 123, "image": "synthetic.png"}}}
        self.running = [[5, "owned", self.graph, {"test": True}, []]]
        self.pending = [[-8, "other-first", {}, {}, []], [6, "other-second", {}, {}, []]]
        self.original_pending = copy.deepcopy(self.pending)
        self.calls = []
        self.reject = False
        self.interrupt_failure = False
        self.env = {"json": json, "time": time, "uuid": uuid, "urllib": urllib,
            "QUEUE_EDIT_LOCK": threading.Lock(), "HLOCK": threading.Lock(), "PLOCK": threading.Lock(),
            "HIST_DB": [{"id": "owned", "seed": 123, "images": ["synthetic.png"], "state": "running"}],
            "HIST": "unused", "HIST_MAX": 1000, "PROGRESS": {}, "CLIENT_ID": "test-client",
            "_save_json": lambda *args: None, "comfy": self.call}
        exec(compile(ast.Module(body=[FUNCTION], type_ignores=[]), "restart", "exec"), self.env)

    def call(self, path, data=None, headers=None):
        body = json.loads(data) if data else None
        self.calls.append((path, body))
        if path == "/queue":
            return io.BytesIO(json.dumps({"queue_running": self.running, "queue_pending": self.pending}).encode())
        if path == "/prompt":
            if self.reject: raise urllib.error.URLError("rejected")
            self.pending.append([body["number"], body["prompt_id"], body["prompt"], body["extra_data"], []])
            return io.BytesIO(json.dumps({"prompt_id": body["prompt_id"], "node_errors": {}}).encode())
        if path == "/interrupt":
            if self.interrupt_failure: raise urllib.error.URLError("offline")
            self.assertEqual(body, {"prompt_id": "owned"})
            return io.BytesIO(b"")
        raise AssertionError(path)

    def restart(self, pid="owned"):
        return self.env["restart_running_prompt"](pid)

    def test_enqueues_exact_graph_before_targeted_stop_and_keeps_other_order(self):
        result = self.restart()
        self.assertEqual([path for path, _ in self.calls], ["/queue", "/prompt", "/interrupt"])
        self.assertEqual(self.pending[:2], self.original_pending)
        ordered = sorted(self.pending, key=lambda item: item[0])
        self.assertEqual(ordered[0][1], result["id"])
        self.assertEqual(ordered[0][2], self.graph)
        self.assertEqual([item[1] for item in ordered[1:]], ["other-first", "other-second"])
        self.assertEqual(self.env["HIST_DB"][-1]["seed"], 123)
        self.assertEqual(self.env["HIST_DB"][-1]["images"], ["synthetic.png"])

    def test_rejected_enqueue_never_stops_current_job(self):
        self.reject = True
        with self.assertRaises(urllib.error.URLError): self.restart()
        self.assertNotIn("/interrupt", [path for path, _ in self.calls])
        self.assertEqual(self.pending, self.original_pending)

    def test_stale_or_foreign_request_does_not_mutate_queue(self):
        with self.assertRaises(ValueError): self.restart("foreign")
        self.running = []
        with self.assertRaises(ValueError): self.restart()
        self.assertTrue(all(body is None for _, body in self.calls))

    def test_retry_does_not_duplicate_restart(self):
        first = self.restart()
        second = self.restart()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.pending), 3)

    def test_interrupt_failure_reports_queued_restart(self):
        self.interrupt_failure = True
        self.assertTrue(self.restart()["warning"])
        self.assertEqual(len(self.pending), 3)


if __name__ == "__main__": unittest.main()
