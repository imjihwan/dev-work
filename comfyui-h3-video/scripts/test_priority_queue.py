"""Priority submissions against a fake queue; no live work or private media."""
import ast
import copy
import io
import json
import threading
import unittest
import urllib.error

from scripts import test_settings_sequence_bulk as fixtures


class PriorityQueueTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FeatureTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.env = self.fixture.env
        tree = ast.parse((fixtures.SOURCE / "server.py").read_text(encoding="utf-8"))
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("queue_prompt_first", "comfy_rejection")]
        exec(compile(ast.Module(body=functions, type_ignores=[]), "priority-test", "exec"), self.env)
        self.queue = {"queue_running": [[-8, "running", {}, {}, []]],
                      "queue_pending": [[-10, "previous-first", {}, {}, []], [4, "previous-second", {}, {}, []]]}
        self.original = copy.deepcopy(self.queue)
        self.calls, self.submitted = [], []
        self.fail_at = None
        self.rejection = None
        self.env.update(comfy=self.comfy, QUEUE_EDIT_LOCK=threading.Lock())

    def comfy(self, path, data=None, headers=None):
        self.calls.append(path)
        if path == "/queue":
            self.assertIsNone(data, "Existing work must never be deleted or reordered")
            return self.fixture.response(self.queue)
        if path == "/prompt":
            payload = json.loads(data)
            if self.fail_at == len(self.submitted) + 1:
                if self.rejection is not None:
                    raise urllib.error.HTTPError("http://synthetic/prompt", 400, "Bad Request", {}, io.BytesIO(json.dumps(self.rejection).encode()))
                raise ValueError("Synthetic submission failure")
            identity = "priority-" + str(len(self.submitted) + 1)
            self.submitted.append(payload)
            self.queue["queue_pending"].append([payload.get("number", 100), identity, payload["prompt"], {}, []])
            return self.fixture.response({"prompt_id": identity})
        raise AssertionError("Unexpected queue mutation or endpoint: " + path)

    def request(self, **changes):
        return self.fixture.request(images=self.fixture.photos[:1], **changes)

    def check_existing_work(self):
        self.assertEqual(self.queue["queue_running"], self.original["queue_running"])
        self.assertEqual(self.queue["queue_pending"][:2], self.original["queue_pending"])
        self.assertTrue(all(path in ("/queue", "/prompt") for path in self.calls))

    def test_single_priority_job_is_next_without_interrupting_running_work(self):
        result = self.env["build_and_queue"](self.request(count=1), queue_first=True)
        self.assertEqual(result["jobs"][0]["id"], "priority-1")
        self.assertEqual(self.submitted[0]["number"], -11)
        self.assertEqual(sorted(self.queue["queue_pending"])[0][1], "priority-1")
        self.assertEqual(self.env["HIST_DB"][-1]["seed"], 100)
        self.check_existing_work()

    def test_priority_repeats_preserve_seed_and_submission_order(self):
        result = self.env["build_and_queue"](self.request(count=3), queue_first=True)
        self.assertEqual([p["number"] for p in self.submitted], [-13, -12, -11])
        self.assertEqual([j["seed"] for j in result["jobs"]], [100, 101, 102])
        self.assertEqual([p["prompt"][self.env["SEED"]]["inputs"]["seed_value"] for p in self.submitted], [100, 101, 102])
        self.assertEqual([q[1] for q in sorted(self.queue["queue_pending"])][:3], [j["id"] for j in result["jobs"]])
        self.check_existing_work()

    def test_new_priority_submission_goes_before_previous_priority_batch(self):
        self.env["build_and_queue"](self.request(count=2), queue_first=True)
        self.env["build_and_queue"](self.request(count=1), queue_first=True)
        self.assertEqual([q[1] for q in sorted(self.queue["queue_pending"])][:3], ["priority-3", "priority-1", "priority-2"])
        self.check_existing_work()

    def test_normal_submission_retains_normal_queue_behavior(self):
        self.env["build_and_queue"](self.request(count=2))
        self.assertTrue(all("number" not in payload for payload in self.submitted))
        self.assertNotIn("/queue", self.calls)
        self.check_existing_work()

    def test_priority_rejects_edit_sequence_and_prepare_without_side_effects(self):
        for changes, options in [({"edit_id": "existing"}, {}), ({"photo_sequence": True}, {}), ({}, {"prepare_only": True})]:
            with self.subTest(changes=changes, options=options), self.assertRaises(ValueError):
                self.env["build_and_queue"](self.request(**changes), queue_first=True, **options)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.fixture.uploaded, [])
        self.assertEqual(self.env["HIST_DB"], [])

    def test_partial_failure_keeps_successful_priority_job_in_history(self):
        self.fail_at = 2
        with self.assertRaisesRegex(ValueError, "1개는 대기열에 등록"):
            self.env["build_and_queue"](self.request(count=3), queue_first=True)
        self.assertEqual(len(self.submitted), 1)
        self.assertEqual(self.env["HIST_DB"][-1]["id"], "priority-1")
        self.check_existing_work()

    def test_partial_failure_explains_why_the_backend_refused_the_next_job(self):
        self.fail_at = 2
        self.rejection = {"error": {"message": "Prompt outputs failed validation", "details": ""},
                          "node_errors": {"7": {"class_type": "LoadImage", "errors": [{"message": "Invalid image file", "details": "synthetic-missing.png"}]}}}
        with self.assertRaises(ValueError) as caught:
            self.env["build_and_queue"](self.request(count=3), queue_first=True)
        message = str(caught.exception)
        self.assertIn("1개는 대기열에 등록", message)
        self.assertIn("LoadImage", message)
        self.assertIn("synthetic-missing.png", message)
        self.assertNotIn("HTTP Error 400", message)
        self.assertEqual(self.env["HIST_DB"][-1]["id"], "priority-1")
        self.check_existing_work()

    def test_interleaved_priority_batches_get_disjoint_ordered_ranges(self):
        first = self.env["queue_prompt_first"]({"batch": "a", "i": 0}, slots=3)
        second = self.env["queue_prompt_first"]({"batch": "b", "i": 0}, slots=2)
        self.env["queue_prompt_first"]({"batch": "a", "i": 1}, number=first["number"] + 1)
        self.env["queue_prompt_first"]({"batch": "b", "i": 1}, number=second["number"] + 1)
        self.env["queue_prompt_first"]({"batch": "a", "i": 2}, number=first["number"] + 2)
        ordered = sorted(self.submitted, key=lambda p: p["number"])
        self.assertEqual([(p["prompt"]["batch"], p["prompt"]["i"]) for p in ordered], [("b", 0), ("b", 1), ("a", 0), ("a", 1), ("a", 2)])
        self.assertEqual(len({p["number"] for p in ordered}), 5)
        self.check_existing_work()


if __name__ == "__main__":
    unittest.main()
