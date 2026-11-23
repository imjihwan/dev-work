"""상태 파일 읽기·쓰기 보호를 임시 폴더에서만 시험한다. 앱·ComfyUI·사용자 파일에 접근하지 않는다.

지키려는 것: 파일이 '없을 때'만 빈 값으로 시작하고, 잠깐 잠겼거나 깨진 파일을 빈 값으로 덮어쓰지 않는다.
Windows 에서 바꿔치기(os.replace)가 잠깐 거절돼도 저장을 잃지 않는다.
"""
import ast
import json
import os
import pathlib
import re
import tempfile
import threading
import time
import unittest
from unittest import mock

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "simple_ui" / "server.py"
NAMES = {"_load_json", "_save_json", "save_settings", "rename_settings", "delete_settings", "save_preset", "delete_preset"}


def load(here):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in NAMES]
    logs = []
    env = {"json": json, "os": os, "re": re, "time": time, "print": lambda *args, **kwargs: logs.append(args),
           "SETTINGS": os.path.join(here, "saved-settings.json"), "PRESETS": os.path.join(here, "presets.json"),
           "SETTINGS_LOCK": threading.Lock(), "PRESET_LOCK": threading.Lock(), "logs": logs}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "state_files", "exec"), env)
    return env


def quick_sleep(case):
    """다시 시도 사이의 대기를 세되 아주 짧게만 실제로 기다린다(진짜 잠김이 풀릴 틈은 남긴다)."""
    real = time.sleep
    patcher = mock.patch("time.sleep", side_effect=lambda seconds: real(min(seconds, 0.01)))
    sleeper = patcher.start()
    case.addCleanup(patcher.stop)
    return sleeper


class StateFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.here = pathlib.Path(self.tmp.name)
        self.env = load(self.tmp.name)
        self.load, self.save = self.env["_load_json"], self.env["_save_json"]
        self.path = str(self.here / "state.json")
        self.sleep = quick_sleep(self)

    def backups(self):
        return sorted(item.name for item in self.here.iterdir() if ".corrupt-" in item.name)

    def test_missing_file_is_the_only_case_that_returns_the_default_silently(self):
        self.assertEqual(self.load(self.path, {"empty": True}), {"empty": True})
        self.assertEqual(self.load(self.path, [], strict=True), [])
        self.assertEqual(list(self.here.iterdir()), [])
        self.assertEqual(self.env["logs"], [])

    def test_round_trip_keeps_korean_text_and_leaves_no_temporary_file(self):
        value = {"이름": "합성 설정", "items": [1, 2, {"k": "값"}]}
        self.save(self.path, value)
        self.assertEqual(self.load(self.path, None), value)
        self.assertEqual([item.name for item in self.here.iterdir()], ["state.json"])
        self.assertIn("합성 설정", pathlib.Path(self.path).read_text(encoding="utf-8"))

    def test_file_saved_with_a_byte_order_mark_still_loads(self):
        pathlib.Path(self.path).write_bytes(b"\xef\xbb\xbf" + json.dumps({"edited": "by hand"}).encode())
        self.assertEqual(self.load(self.path, {}), {"edited": "by hand"})
        self.assertEqual(self.backups(), [])

    def test_owned_store_preserves_a_corrupt_file_before_starting_empty(self):
        damaged = b'{"synthetic": [1, 2'
        pathlib.Path(self.path).write_bytes(damaged)
        self.assertEqual(self.load(self.path, [], owned=True), [])
        kept = self.backups()
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0].startswith("state.json.corrupt-") and kept[0].endswith(".bak"))
        self.assertEqual((self.here / kept[0]).read_bytes(), damaged)
        self.assertFalse(os.path.exists(self.path))
        # 원본을 옮겼으므로 다시 읽어도 보관 사본이 늘지 않고, 이후 저장은 사본을 건드리지 않는다
        self.assertEqual(self.load(self.path, [], owned=True), [])
        self.save(self.path, ["new"])
        self.assertEqual(self.backups(), kept)
        self.assertEqual((self.here / kept[0]).read_bytes(), damaged)
        # 안내에는 파일 이름만 싣고 폴더 경로는 싣지 않는다
        printed = " ".join(str(part) for line in self.env["logs"] for part in line)
        self.assertIn(kept[0], printed)
        self.assertNotIn(str(self.here), printed)

    def test_two_corrupt_files_in_the_same_second_keep_separate_copies(self):
        for content in (b"first damaged", b"second damaged"):
            pathlib.Path(self.path).write_bytes(content)
            self.assertEqual(self.load(self.path, {}, owned=True), {})
        self.assertEqual(sorted((self.here / name).read_bytes() for name in self.backups()), [b"first damaged", b"second damaged"])

    def test_read_only_use_never_moves_or_rewrites_an_unreadable_file(self):
        # 읽기만 하는 곳(조합 목록·저장 설정 목록)은 파일을 건드리지 않는다. 그래야 뒤따르는 '읽고-고쳐-쓰기'가
        # 파일이 없다고 보고 한 항목짜리 새 파일로 덮어쓰는 일이 없다.
        damaged = b'{"synthetic": [1, 2'
        pathlib.Path(self.path).write_bytes(damaged)
        self.assertEqual(self.load(self.path, {"fallback": True}), {"fallback": True})
        self.assertEqual(pathlib.Path(self.path).read_bytes(), damaged)
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.env["logs"], [])
        with self.assertRaises(ValueError):
            self.load(self.path, {}, strict=True)

    def test_absurdly_nested_content_is_handled_like_any_other_damage(self):
        pathlib.Path(self.path).write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
        self.assertEqual(self.load(self.path, []), [])
        with self.assertRaises(ValueError):
            self.load(self.path, [], strict=True)
        self.assertEqual(self.load(self.path, [], owned=True), [])
        self.assertEqual(len(self.backups()), 1)

    def test_wrong_top_level_shape_counts_as_damaged(self):
        pathlib.Path(self.path).write_text('{"not": "a list"}', encoding="utf-8")
        self.assertEqual(self.load(self.path, []), [])                 # 읽기만: 기본값, 파일 그대로
        self.assertTrue(os.path.exists(self.path))
        with self.assertRaises(ValueError):
            self.load(self.path, [], strict=True)
        self.assertEqual(self.load(self.path, [], owned=True), [])     # 소유 저장소: 보관 후 빈 값
        self.assertEqual(len(self.backups()), 1)
        self.assertFalse(os.path.exists(self.path))

    def test_strict_read_refuses_corrupt_content_and_leaves_the_file_alone(self):
        damaged = b"not json at all"
        pathlib.Path(self.path).write_bytes(damaged)
        with self.assertRaises(ValueError):
            self.load(self.path, {}, strict=True)
        self.assertEqual(pathlib.Path(self.path).read_bytes(), damaged)
        self.assertEqual(self.backups(), [])

    def test_temporarily_locked_file_is_retried_then_read(self):
        self.save(self.path, {"kept": 1})
        real_open, failures = open, [PermissionError(13, "synthetic lock"), PermissionError(13, "synthetic lock")]

        def flaky(file, *args, **kwargs):
            if str(file) == self.path and failures:
                raise failures.pop()
            return real_open(file, *args, **kwargs)
        with mock.patch("builtins.open", flaky):
            self.assertEqual(self.load(self.path, {}), {"kept": 1})
        self.assertEqual(failures, [])
        self.assertEqual(self.sleep.call_count, 2)

    def test_file_that_stays_unreadable_is_never_treated_as_empty(self):
        self.save(self.path, {"kept": 1})
        original = pathlib.Path(self.path).read_bytes()
        real_open = open

        def locked(file, *args, **kwargs):
            if str(file) == self.path:
                raise PermissionError(13, "synthetic lock")
            return real_open(file, *args, **kwargs)
        for mode in ({"strict": True}, {"owned": True}):
            with self.subTest(mode=mode), mock.patch("builtins.open", locked):
                with self.assertRaises(ValueError) as caught:
                    self.load(self.path, {}, **mode)
                self.assertNotIn(str(self.here), str(caught.exception))
        with mock.patch("builtins.open", locked):
            self.assertEqual(self.load(self.path, {"fallback": True}), {"fallback": True})   # 읽기만: 기본값
        self.assertEqual(pathlib.Path(self.path).read_bytes(), original)
        self.assertEqual(self.backups(), [])

    def test_replace_denied_a_few_times_still_saves(self):
        self.save(self.path, {"version": 1})
        real_replace, denied = os.replace, [PermissionError(13, "synthetic scanner")] * 3

        def flaky(source, target):
            if denied:
                raise denied.pop()
            return real_replace(source, target)
        with mock.patch.object(os, "replace", flaky):
            self.save(self.path, {"version": 2})
        self.assertEqual(self.load(self.path, None), {"version": 2})
        self.assertEqual(self.sleep.call_count, 3)

    def test_replace_denied_forever_reports_failure_and_keeps_the_previous_file(self):
        self.save(self.path, {"version": 1})
        with mock.patch.object(os, "replace", side_effect=PermissionError(13, "synthetic scanner")) as replace:
            with self.assertRaises(PermissionError):
                self.save(self.path, {"version": 2})
        self.assertEqual(replace.call_count, 8)
        self.assertEqual(self.load(self.path, None), {"version": 1})
        self.assertEqual([item.name for item in self.here.iterdir()], ["state.json"])   # 임시 파일을 남기지 않는다

    def test_other_replace_errors_are_not_retried(self):
        with mock.patch.object(os, "replace", side_effect=FileNotFoundError(2, "synthetic")) as replace:
            with self.assertRaises(FileNotFoundError):
                self.save(self.path, {"version": 1})
        self.assertEqual(replace.call_count, 1)
        self.assertEqual(list(self.here.iterdir()), [])

    def test_overlapping_saves_use_separate_staging_files(self):
        # 한 스레드가 바꿔치기 직전에 멈춰 있는 동안 다른 스레드가 같은 파일을 저장해도,
        # 멈춰 있던 쪽이 준비해 둔 내용이 섞이거나 사라지지 않는다(임시 파일 이름이 스레드마다 다르다).
        real_replace = os.replace
        staged, may_finish, errors = threading.Event(), threading.Event(), []

        def gate(source, target):
            if threading.current_thread().name == "slow-writer":
                staged.set()
                may_finish.wait(5)
            return real_replace(source, target)

        def slow():
            try:
                self.save(self.path, {"owner": "slow", "rows": list(range(2000))})
            except Exception as error:  # noqa: BLE001 — 스레드 안의 실패를 모아 아래에서 확인
                errors.append(error)
        with mock.patch.object(os, "replace", gate):
            thread = threading.Thread(target=slow, name="slow-writer")
            thread.start()
            self.assertTrue(staged.wait(5))
            self.save(self.path, {"owner": "fast"})
            self.assertEqual(self.load(self.path, None), {"owner": "fast"})
            may_finish.set()
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.load(self.path, None), {"owner": "slow", "rows": list(range(2000))})
        self.assertEqual([item.name for item in self.here.iterdir()], ["state.json"])

    @unittest.skipUnless(os.name == "nt", "Windows 의 파일 공유 규칙을 실제로 확인하는 검사")
    def test_save_succeeds_while_another_thread_briefly_holds_the_file_open(self):
        self.sleep.side_effect = lambda seconds: threading.Event().wait(seconds)   # 실제로 기다린다
        self.save(self.path, {"version": 1})
        opened, release = threading.Event(), threading.Event()

        def reader():
            with open(self.path, encoding="utf-8"):
                opened.set()
                release.wait(0.15)   # 읽는 쪽이 파일을 잡고 있는 동안 바꿔치기는 거절된다
        thread = threading.Thread(target=reader)
        thread.start()
        self.assertTrue(opened.wait(2))
        try:
            self.save(self.path, {"version": 2})
        finally:
            release.set()
            thread.join()
        self.assertEqual(self.load(self.path, None), {"version": 2})
        self.assertGreaterEqual(self.sleep.call_count, 1)


class SavedSettingsAndPresetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = load(self.tmp.name)
        quick_sleep(self)
        self.data = {"f": {"summary": "synthetic"}, "model": {"anchor": False}, "images": []}

    def test_saving_a_setting_does_not_wipe_the_others_when_the_file_is_damaged(self):
        self.env["save_settings"]("first", self.data)
        self.env["save_settings"]("second", self.data)
        path = pathlib.Path(self.env["SETTINGS"])
        damaged = path.read_bytes()[:-20]
        path.write_bytes(damaged)
        for call in (lambda: self.env["save_settings"]("third", self.data),
                     lambda: self.env["rename_settings"]("first", "renamed"),
                     lambda: self.env["delete_settings"]("first")):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(path.read_bytes(), damaged)   # 고칠 수 있도록 그대로 둔다
        self.assertEqual([item.name for item in path.parent.iterdir()], [path.name])

    def test_presets_round_trip_and_keep_every_concurrent_save(self):
        save, delete = self.env["save_preset"], self.env["delete_preset"]
        self.assertEqual(save(" 빠른 조합 ", {"steps": 4}), {"빠른 조합": {"steps": 4}})
        with self.assertRaises(ValueError):
            save("   ", {"steps": 4})
        errors = []

        def worker(prefix):
            try:
                for index in range(15):
                    save(f"{prefix}-{index}", {"steps": index})
            except Exception as error:  # noqa: BLE001 — 스레드 안의 실패를 모아 아래에서 확인
                errors.append(error)
        threads = [threading.Thread(target=worker, args=(name,)) for name in ("a", "b", "c")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        stored = self.env["_load_json"](self.env["PRESETS"], {})
        self.assertEqual(len(stored), 46)
        self.assertEqual(sorted(delete("빠른 조합")), sorted(name for name in stored if name != "빠른 조합"))
        self.assertEqual(len(delete("없는 이름")), 45)

    def test_preset_changes_refuse_to_overwrite_a_damaged_file(self):
        self.env["save_preset"]("kept", {"steps": 4})
        path = pathlib.Path(self.env["PRESETS"])
        path.write_bytes(b"{ damaged")
        with self.assertRaises(ValueError):
            self.env["save_preset"]("new", {"steps": 8})
        with self.assertRaises(ValueError):
            self.env["delete_preset"]("kept")
        self.assertEqual(path.read_bytes(), b"{ damaged")


if __name__ == "__main__":
    unittest.main()
