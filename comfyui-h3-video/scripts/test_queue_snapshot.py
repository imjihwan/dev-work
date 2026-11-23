"""표시용 대기열 스냅샷과 묶음 상태 조회를 가짜 ComfyUI 응답으로 시험한다. 실제 서버·작업에는 연결하지 않는다.

지키려는 것: 화면이 작업마다·창마다 상태를 물어도 ComfyUI 의 대기열은 초당 한 번만, 그래프 없이 받는다.
대기 중인 작업에는 history 를 묻지 않고, 이 서버가 대기열을 바꾸면 바로 다음 조회가 새 내용을 본다.
"""
import ast
import io
import json
import math
import pathlib
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "simple_ui" / "server.py"
NAMES = {"comfy", "_fetch_queue_ids", "queue_snapshot", "_status", "_queue_state", "status_many", "execution_timing"}


class Backend:
    """가짜 ComfyUI: 요청을 기록하고 대기열·이력을 돌려준다."""
    def __init__(self):
        self.calls, self.running, self.pending, self.history = [], [], [], {}
        self.jobs_api, self.on_fetch = True, None

    def graph(self):
        return {"node": {"class_type": "Synthetic", "inputs": {"text": "x" * 2000}}}

    def urlopen(self, request, timeout=None):
        url = urllib.parse.urlparse(request.full_url)
        path = url.path + ("?" + url.query if url.query else "")
        self.calls.append(("POST " if request.data is not None else "GET ") + url.path)
        if request.data is not None:
            return io.BytesIO(b"{}")
        if self.on_fetch:
            self.on_fetch(url.path)
        if url.path == "/api/jobs":
            if not self.jobs_api:
                raise urllib.error.HTTPError(path, 404, "Not Found", {}, io.BytesIO(b"404: Not Found"))
            if self.jobs_api == "odd":
                return io.BytesIO(json.dumps({"unexpected": []}).encode())
            if self.jobs_api == "dict":      # 목록 자리에 객체: 빈 대기열로 읽으면 안 된다
                return io.BytesIO(json.dumps({"jobs": {}}).encode())
            if self.jobs_api == "partial":   # 일부만 온 응답
                return io.BytesIO(json.dumps({"jobs": [], "pagination": {"has_more": True}}).encode())
            if self.jobs_api == "metadata":  # 쪽 정보가 객체가 아니다
                return io.BytesIO(json.dumps({"jobs": [], "pagination": "unsupported"}).encode())
            if self.jobs_api == "entry":     # 모르는 상태 값
                return io.BytesIO(json.dumps({"jobs": [{"id": "x", "status": "completed"}]}).encode())
            rows = [{"id": pid, "status": "in_progress", "priority": number} for number, pid in self.running]
            rows += [{"id": pid, "status": "pending", "priority": number} for number, pid in self.pending]
            return io.BytesIO(json.dumps({"jobs": rows, "pagination": {"total": len(rows)}}).encode())
        if url.path == "/queue":
            full = lambda rows: [[number, pid, self.graph(), {}, []] for number, pid in rows]
            return io.BytesIO(json.dumps({"queue_running": full(self.running), "queue_pending": full(self.pending)}).encode())
        if url.path.startswith("/history/"):
            pid = urllib.parse.unquote(url.path[len("/history/"):])
            return io.BytesIO(json.dumps({pid: self.history[pid]} if pid in self.history else {}).encode())
        raise AssertionError(path)

    def count(self, label):
        return sum(1 for call in self.calls if call == label)


class QueueSnapshotTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in NAMES]
        self.backend = Backend()
        self.recorded = []
        self.hold = None
        self.clock = [1000.0]
        fake_time = mock.Mock(wraps=time)
        fake_time.monotonic = lambda: self.clock[0]
        self.env = {"json": json, "math": math, "time": fake_time, "urllib": urllib, "threading": threading, "COMFY": "http://127.0.0.1:1",
                    "QUEUE_CACHE": {"at": 0.0, "value": None, "epoch": 0, "jobs_api_retry_at": 0.0, "failed_at": -1.0, "failure": None},
                    "QUEUE_CACHE_LOCK": threading.Lock(), "QUEUE_EPOCH_LOCK": threading.Lock(),
                    "PLOCK": threading.Lock(), "PROGRESS": {}, "backend_restart_hold": lambda pid=None: self.hold,
                    "video_of": lambda entry: {"filename": "synthetic.mp4", "subfolder": "", "type": "output"},
                    "hist_result": lambda pid, state: self.recorded.append((pid, state["state"]))}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "queue_snapshot", "exec"), self.env)
        patcher = mock.patch.object(urllib.request, "urlopen", self.backend.urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.backend.running = [[-3, "running"]]
        self.backend.pending = [[7, "second"], [2, "first"], [9, "third"]]   # ComfyUI 는 정렬하지 않은 채 돌려준다

    def snapshot(self, **kwargs):
        return self.env["queue_snapshot"](**kwargs)

    def test_snapshot_comes_from_the_light_job_list_without_graphs(self):
        value = self.snapshot()
        self.assertEqual(value, {"queue_running": [[-3, "running"]], "queue_pending": [[7, "second"], [2, "first"], [9, "third"]]})
        self.assertEqual(self.backend.calls, ["GET /api/jobs"])
        self.assertEqual(self.env["_queue_state"]("first", value), {"state": "queued", "position": 1})
        self.assertEqual(self.env["_queue_state"]("third", value), {"state": "queued", "position": 3})
        self.assertEqual(self.env["_queue_state"]("running", value)["state"], "running")

    def test_many_status_checks_share_one_snapshot_until_it_ages_out(self):
        for _ in range(50):
            for pid in ("first", "second", "third", "running"):
                self.assertNotEqual(self.env["_status"](pid)["state"], "unknown")
        self.assertEqual(self.backend.calls, ["GET /api/jobs"])   # 대기 중인 작업은 history 도 묻지 않는다
        self.clock[0] += 1.01
        self.env["_status"]("first")
        self.assertEqual(self.backend.count("GET /api/jobs"), 2)

    def test_queue_changes_made_by_this_server_are_visible_immediately(self):
        self.snapshot()
        self.backend.pending.append([11, "added"])
        self.assertEqual(self.env["_status"]("added"), {"state": "unknown"})          # 방금 받은 스냅샷에는 없다
        # 다른 곳(ComfyUI 화면 등)에서 등록한 작업: '찾을 수 없음'으로 답하기 전에 새 스냅샷으로 한 번 더 확인한다
        self.clock[0] += 0.5
        self.assertEqual(self.env["_status"]("added"), {"state": "queued", "position": 4})
        self.assertEqual(self.backend.count("GET /api/jobs"), 2)
        self.backend.pending.pop()
        self.env["comfy"]("/queue", b"{}").close()
        self.assertEqual(self.env["_status"]("added"), {"state": "unknown"})
        self.backend.pending.append([11, "added"])
        for path in ("/prompt", "/queue", "/interrupt"):
            with self.subTest(path=path):
                before = self.backend.count("GET /api/jobs")
                self.env["comfy"](path, b"{}", {"Content-Type": "application/json"}).close()
                self.assertEqual(self.env["_status"]("added"), {"state": "queued", "position": 4})
                self.assertEqual(self.backend.count("GET /api/jobs"), before + 1)
        before = self.backend.count("GET /api/jobs")
        self.env["comfy"]("/history/x").close()            # 읽기는 스냅샷을 버리지 않는다
        self.env["_status"]("added")
        self.assertEqual(self.backend.count("GET /api/jobs"), before)

    def test_snapshot_fetched_while_this_server_changed_the_queue_is_not_kept(self):
        original, raced = self.backend.urlopen, []

        def racing(request, timeout=None):
            response = original(request, timeout)          # 등록 전의 내용으로 응답이 만들어진 뒤
            if "/api/jobs" in request.full_url and not raced:
                raced.append(True)
                self.env["comfy"]("/prompt", b"{}").close()   # 응답을 받기 전에 이 서버의 등록이 끼어든다
                self.backend.pending.append([11, "added"])
            return response
        with mock.patch.object(urllib.request, "urlopen", racing):
            first = self.snapshot()
            self.assertNotIn([11, "added"], first["queue_pending"])
            self.assertIn([11, "added"], self.snapshot()["queue_pending"])   # 낡은 스냅샷은 저장되지 않았으므로 다시 받는다

    def test_older_backend_falls_back_to_the_full_queue_and_stops_probing(self):
        for mode in (False, "odd", "dict", "partial", "entry", "metadata"):
            with self.subTest(jobs_api=mode):
                self.backend.jobs_api, self.backend.calls = mode, []
                self.env["QUEUE_CACHE"].update(value=None, jobs_api_retry_at=0.0)
                value = self.snapshot()
                self.assertEqual(value["queue_pending"], [[7, "second"], [2, "first"], [9, "third"]])   # 그래프는 버리고 순번·ID 만
                self.assertEqual(self.backend.calls, ["GET /api/jobs", "GET /queue"])
                self.clock[0] += 5
                self.snapshot()
                self.assertEqual(self.backend.calls, ["GET /api/jobs", "GET /queue", "GET /queue"])       # 한동안 다시 묻지 않는다
                self.clock[0] += 301
                self.backend.jobs_api = True
                self.snapshot()
                self.assertEqual(self.backend.calls[-1], "GET /api/jobs")

    def test_failing_job_list_falls_back_briefly_and_a_failing_backend_is_reported(self):
        original = self.backend.urlopen

        def jobs_broken(request, timeout=None):
            if "/api/jobs" in request.full_url:
                self.backend.calls.append("GET /api/jobs")
                raise urllib.error.HTTPError(request.full_url, 500, "Server Error", {}, io.BytesIO(b"{}"))
            return original(request, timeout)
        with mock.patch.object(urllib.request, "urlopen", jobs_broken):
            self.assertEqual(self.snapshot()["queue_running"], [[-3, "running"]])     # 목록 API 만 고장: /queue 로 받는다
        self.assertEqual(self.env["QUEUE_CACHE"]["jobs_api_retry_at"], self.clock[0] + 30)   # 없는 것이 아니므로 곧 다시 시도

        def broken(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 500, "Server Error", {}, io.BytesIO(b"{}"))
        self.env["QUEUE_CACHE"].update(value=None)
        with mock.patch.object(urllib.request, "urlopen", broken):
            with self.assertRaises(urllib.error.HTTPError):
                self.snapshot()

    def test_requests_waiting_on_a_fetch_that_fails_share_its_failure_instead_of_retrying_in_turn(self):
        # ComfyUI 가 연결만 받고 답하지 않을 때: 기다리던 조회가 차례로 다시 시간 초과를 기다리면 안 된다
        gate, attempts, outcomes = threading.Event(), [], []

        def hanging(request, timeout=None):
            attempts.append(request.full_url)
            gate.wait(2)
            raise TimeoutError("synthetic timeout")

        def caller():
            try:
                self.snapshot()
                outcomes.append("ok")
            except TimeoutError:
                outcomes.append("timeout")
        real_monotonic = time.monotonic
        self.env["time"].monotonic = real_monotonic          # 기다린 순서를 실제 시각으로 가린다
        with mock.patch.object(urllib.request, "urlopen", hanging):
            threads = [threading.Thread(target=caller) for _ in range(8)]
            for thread in threads:
                thread.start()
            time.sleep(0.15)
            gate.set()
            for thread in threads:
                thread.join()
            self.assertEqual(outcomes, ["timeout"] * 8)
            self.assertEqual(len(attempts), 1, "여덟 조회가 한 번의 받아 오기만 기다린다")
            time.sleep(0.01)
            with self.assertRaises(TimeoutError):            # 그 뒤에 온 조회는 새로 시도한다
                self.snapshot()
            self.assertEqual(len(attempts), 2)

    def test_finished_and_unknown_jobs_are_resolved_from_history_only_when_not_queued(self):
        self.backend.history["done"] = {"status": {"status_str": "success", "messages": [
            ["execution_start", {"timestamp": 1000000}], ["execution_success", {"timestamp": 1002500}]]}}
        self.backend.history["failed"] = {"status": {"status_str": "error", "messages": [["execution_error", {"exception_message": "synthetic failure"}]]}}
        self.assertEqual(self.env["_status"]("done")["state"], "done")
        self.assertEqual(self.env["_status"]("done")["generation_seconds"], 2.5)
        self.assertEqual(self.env["_status"]("failed"), {"state": "error", "error": "synthetic failure"})
        self.assertEqual(self.env["_status"]("never-seen"), {"state": "unknown"})
        self.assertEqual(self.backend.count("GET /api/jobs"), 1)
        self.assertEqual(self.backend.count("GET /history/done"), 2)
        self.assertEqual(self.backend.count("GET /queue"), 0)

    def test_batch_status_uses_one_snapshot_and_records_results(self):
        self.backend.history["done"] = {"status": {"status_str": "success", "messages": []}}
        result = self.env["status_many"](["first", "done", "first", "gone", "", 5, "running"])
        self.assertEqual({pid: state["state"] for pid, state in result["jobs"].items()},
                         {"first": "queued", "done": "done", "gone": "unknown", "running": "running"})
        self.assertEqual(self.backend.calls, ["GET /api/jobs", "GET /history/done", "GET /history/gone"])
        self.assertEqual(self.recorded, [("first", "queued"), ("done", "done"), ("gone", "unknown"), ("running", "running")])
        for bad in ([], [""], ["x" * 101], [str(n) for n in range(201)]):
            with self.subTest(bad=len(bad)), self.assertRaises(ValueError):
                self.env["status_many"](bad)

    def test_batch_status_during_a_backend_restart_does_not_touch_the_backend(self):
        self.hold = {"state": "queued", "position": 2, "pct": 0, "label": "서버 재시작 중 · 대기열 보존됨"}
        self.backend.calls = []
        result = self.env["status_many"](["first", "second"])
        self.assertEqual([state["label"] for state in result["jobs"].values()], [self.hold["label"]] * 2)
        self.assertEqual(self.backend.calls, [])

    def test_simultaneous_requests_fetch_once(self):
        gate, results = threading.Event(), []
        original = self.backend.urlopen

        def slow(request, timeout=None):
            gate.wait(2)
            return original(request, timeout)
        with mock.patch.object(urllib.request, "urlopen", slow):
            threads = [threading.Thread(target=lambda: results.append(self.snapshot())) for _ in range(8)]
            for thread in threads:
                thread.start()
            time.sleep(0.1)
            gate.set()
            for thread in threads:
                thread.join()
        self.assertEqual(len(results), 8)
        self.assertTrue(all(result is results[0] for result in results))
        self.assertEqual(self.backend.count("GET /api/jobs"), 1)


if __name__ == "__main__":
    unittest.main()
