"""Synthetic worker/API checks; no real prompts, media or model inference."""
import ast
import importlib.util
import io
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("TRANSLATION_TEST_SOURCE", ROOT / "simple_ui"))
sys.path.insert(0, str(ROOT / "simple_ui"))
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SOURCE / file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
LOCAL = load("local_translate_test", "local_translate.py")
WORKER = load("translation_worker_test", "translation_worker.py")


class LocalTranslateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        for name in (".venv/Scripts/python.exe", "models/quickmt-en-ko/model.bin", "models/quickmt-en-ko/src.spm.model", "models/quickmt-en-ko/tgt.spm.model"):
            p = self.home / name; p.parent.mkdir(parents=True, exist_ok=True); p.touch()
        self.translator = LOCAL.LocalTranslator(self.home, engine="fast")
        self.process = MagicMock(); self.process.poll.return_value = None
        self.process.stdout.readline.side_effect = [json.dumps({"ready": True}), json.dumps({"text": "합성 번역"})]
        for target, value in (("available_memory", 8 * 1024**3),):
            p = patch.object(LOCAL, target, return_value=value); p.start(); self.addCleanup(p.stop)
        p = patch.object(LOCAL.subprocess, "Popen", return_value=self.process); self.spawn = p.start(); self.addCleanup(p.stop)
        p = patch.object(LOCAL.threading, "Thread"); p.start(); self.addCleanup(p.stop)

    def test_cpu_only_process_and_private_json_pipe_cache(self):
        source = "Synthetic input with no personal content."
        first = self.translator.translate(source)
        self.assertEqual(first, {"text": "합성 번역", "cached": False})
        self.assertTrue(self.translator.translate(source)["cached"])
        self.assertEqual(self.spawn.call_count, 1)
        kwargs = self.spawn.call_args.kwargs
        self.assertEqual(kwargs["env"]["CUDA_VISIBLE_DEVICES"], "-1")
        self.assertEqual(kwargs["env"]["OMP_NUM_THREADS"], "2")
        self.assertEqual(kwargs["stderr"], LOCAL.subprocess.DEVNULL)
        self.assertEqual(json.loads(self.process.stdin.write.call_args.args[0]), {"text": source})
        self.assertTrue(all(len(key) == 64 and source not in key for key in self.translator.cache))

    def test_bad_input_never_spawns_worker(self):
        for value in (None, "", "  ", 7, "a" * 1201):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError): self.translator.translate(value)
        self.spawn.assert_not_called()

    def test_prompt_helper_priority_and_low_ram_prevent_spawn(self):
        self.translator.busy = lambda: True
        with self.assertRaises(LOCAL.TranslationBusy): self.translator.translate("Synthetic sentence.")
        self.translator.busy = lambda: False
        with patch.object(LOCAL, "available_memory", return_value=2 * 1024**3), self.assertRaises(LOCAL.TranslationBusy):
            self.translator.translate("Synthetic sentence.")
        self.spawn.assert_not_called()

    def test_concurrent_requests_wait_without_spawning_a_second_worker(self):
        self.translator.lock.acquire()
        try:
            with self.assertRaises(LOCAL.TranslationBusy): self.translator.translate("Synthetic sentence.")
        finally: self.translator.lock.release()
        self.spawn.assert_not_called()

    def test_missing_and_corrupted_worker_return_controlled_errors(self):
        self.process.stdout.readline.side_effect = [json.dumps({"ready": True}), "not-json"]
        with self.assertRaisesRegex(ValueError, "로컬 번역을 완료하지 못했습니다"):
            self.translator.translate("Synthetic input.")
        self.process.terminate.assert_called_once()
        self.assertFalse(self.translator.lock.locked())

    def test_fallback_is_explicit_and_not_cached(self):
        self.process.stdout.readline.side_effect = [json.dumps({"ready": True}), json.dumps({"text": "Synthetic source.", "warning": "Fallback"})]
        result = self.translator.translate("Synthetic source.")
        self.assertIn("warning", result)
        self.assertEqual(self.translator.cache, {})

    def test_memory_cache_is_bounded(self):
        self.process.stdout.readline.side_effect = [json.dumps({"ready": True})] + [json.dumps({"text": "합성 번역"})] * 140
        for i in range(140): self.translator.translate("Synthetic sentence " + str(i))
        self.assertEqual(len(self.translator.cache), 128)
        self.assertEqual(self.spawn.call_count, 1)

    def test_pause_stops_only_owned_worker(self):
        self.translator.translate("Synthetic sentence.")
        self.translator.pause()
        self.process.terminate.assert_called_once()
        self.assertIsNone(self.translator.process)

    def test_quality_is_default_and_uses_dedicated_translation_model(self):
        translator = LOCAL.LocalTranslator(self.home)
        self.assertEqual(translator.default_engine, "quality")
        self.assertEqual(translator.quality_model.parent, self.home / "models/translategemma-4b-it")
        translator.helper = SimpleNamespace(exe=self.python_fixture()); translator.quality_model = self.python_fixture()
        self.assertTrue(translator.ready())

    def python_fixture(self):
        return self.home / ".venv/Scripts/python.exe"

    def test_quality_request_preserves_terms_labels_and_outer_whitespace(self):
        self.translator.base = "http://127.0.0.1:12345"
        response = MagicMock()
        response.read.return_value = json.dumps({"content":"<Picture 1> 미디엄 샷을 사용하세요.", "stop_type":"word"}).encode()
        response.__enter__.return_value = response
        with patch.object(LOCAL.urllib.request, "urlopen", return_value=response) as request:
            answer = self.translator._quality_translate("  Use a medium shot of <Picture 1>.\n")
        self.assertEqual(answer["text"], "  <Picture 1> 미디엄 샷을 사용하세요.\n")
        payload = json.loads(request.call_args.args[0].data)
        self.assertIn("medium shot = 미디엄 샷", payload["prompt"])
        self.assertIn("English (en) to Korean (ko)", payload["prompt"])
        self.assertFalse(payload["cache_prompt"])
        self.assertFalse(payload["stream"])

    def test_quality_rejects_truncation_or_missing_reference(self):
        self.translator.base = "http://127.0.0.1:12345"
        response = MagicMock(); response.__enter__.return_value = response
        for reason in ("limit", "word"):
            response.read.return_value = json.dumps({"content":"합성 번역", "stop_type":reason}).encode()
            with patch.object(LOCAL.urllib.request, "urlopen", return_value=response):
                if reason == "limit":
                    with self.assertRaises(ValueError): self.translator._quality_translate("<Picture 1>")
                else:
                    answer = self.translator._quality_translate("<Picture 1>")
                    self.assertIn("warning", answer); self.assertEqual(answer["text"], "<Picture 1>")

    def test_quality_cpu_command_and_engine_switch_terminate_only_owned_process(self):
        self.translator.translate("Synthetic sentence.")
        original = self.translator.process
        self.translator.helper = MagicMock()
        self.translator.helper.command.return_value = ["llama-server.exe", "-m", "synthetic.gguf", "-ngl", "0", "-t", "2", "-c", "8192", "--alias", "h3-prompt-helper"]
        response = MagicMock(); response.__enter__.return_value.status = 200
        with patch.object(LOCAL.urllib.request, "urlopen", return_value=response): self.translator._ensure_worker("quality")
        original.terminate.assert_called_once()
        command = self.spawn.call_args.args[0]
        self.assertEqual(command[command.index("-c") + 1], "2048")
        self.assertEqual(command[command.index("-m") + 1], str(self.translator.quality_model))
        self.assertEqual(command[command.index("-ngl") + 1], "0")
        self.assertEqual(command[command.index("-t") + 1], "2")
        self.assertEqual(self.spawn.call_args.kwargs["stdout"], LOCAL.subprocess.DEVNULL)

    def test_engine_caches_are_separate_and_memory_thresholds_differ(self):
        self.translator.translate("Synthetic sentence.")
        with patch.object(self.translator, "ready", return_value=True), patch.object(self.translator, "_ensure_worker", return_value=self.process), patch.object(self.translator, "_quality_translate", return_value={"text":"정밀 합성 번역"}) as quality:
            self.assertEqual(self.translator.translate("Synthetic sentence.", "quality")["text"], "정밀 합성 번역")
            quality.assert_called_once()
            with patch.object(LOCAL, "available_memory", return_value=int(3.5 * 1024**3)):
                with self.assertRaises(LOCAL.TranslationBusy): self.translator.translate("Another synthetic sentence.", "quality")
        self.assertEqual(len(self.translator.cache), 2)
        with self.assertRaises(ValueError): self.translator.translate("Synthetic sentence.", "invalid")

    def test_warm_model_uses_running_memory_limit_without_blocking_itself(self):
        self.translator.process = self.process; self.translator.engine = "quality"
        with patch.object(self.translator, "ready", return_value=True), patch.object(self.translator, "_quality_translate", return_value={"text":"정밀 합성 번역"}):
            with patch.object(LOCAL, "available_memory", return_value=int(3.5 * 1024**3)):
                self.assertEqual(self.translator.translate("Synthetic warm-model sentence.", "quality")["text"], "정밀 합성 번역")
            with patch.object(LOCAL, "available_memory", return_value=int(2.4 * 1024**3)):
                with self.assertRaises(LOCAL.TranslationBusy): self.translator.translate("Another synthetic warm-model sentence.", "quality")

    def test_engine_change_releases_old_model_before_memory_check(self):
        self.translator.process = self.process; self.translator.engine = "fast"
        def memory():
            return int((3.5 if self.translator.process is self.process else 6) * 1024**3)
        with patch.object(LOCAL, "available_memory", side_effect=memory), patch.object(self.translator, "ready", return_value=True), patch.object(self.translator, "_ensure_worker", return_value=self.process), patch.object(self.translator, "_quality_translate", return_value={"text":"합성 번역"}):
            self.assertEqual(self.translator.translate("Synthetic engine switch.", "quality")["text"], "합성 번역")
        self.process.terminate.assert_called_once()


class WorkerTests(unittest.TestCase):
    def fake(self, output):
        tokenizer = SimpleNamespace(encode=lambda text, **_: [text], decode=lambda values: " ".join(values))
        model = MagicMock(); model.translate_batch.return_value = [SimpleNamespace(hypotheses=[[output]])]
        return model, tokenizer

    def test_reference_tokens_glossary_and_whitespace_preserved(self):
        model, tokenizer = self.fake("XREF0 XREF1 XREF2 XREF3")
        result = WORKER.translate_text("  medium shot <Picture 1> 00:01.000 {{face_side}}\n\n", model, tokenizer)
        self.assertEqual(result, "  미디엄 샷 <Picture 1> 00:01.000 {{face_side}}\n\n")
        self.assertEqual(model.translate_batch.call_args.kwargs["max_input_length"], 0)

    def test_whole_chunk_context_and_separate_target_tokenizer(self):
        model, tokenizer = self.fake("synthetic-target-tokens")
        target = SimpleNamespace(decode=lambda tokens: "합성 번역")
        source = "One continuous shot. Do not move forward. Move backward."
        self.assertEqual(WORKER.translate_text(source, model, tokenizer, target), "합성 번역")
        self.assertEqual(model.translate_batch.call_args.args[0], [[source]])
        self.assertEqual(model.translate_batch.call_args.kwargs["beam_size"], 5)

    def test_missing_or_duplicated_protected_marker_is_rejected(self):
        for output in ("합성 번역", "XREF0 XREF0"):
            model, tokenizer = self.fake(output)
            with self.assertRaises(ValueError): WORKER.translate_text("<Picture 1>", model, tokenizer)

    def test_word_boundaries_and_marker_collision(self):
        model, tokenizer = self.fake("shotgun XREF0 XREF1")
        result = WORKER.translate_text("shotgun XREF0 <Picture 1>", model, tokenizer)
        self.assertEqual(result, "shotgun XREF0 <Picture 1>")

    def test_truncated_output_is_rejected(self):
        model, tokenizer = self.fake("unused")
        model.translate_batch.return_value = [SimpleNamespace(hypotheses=[["x"] * 1024])]
        with self.assertRaises(ValueError): WORKER.translate_text("Synthetic sentence.", model, tokenizer)


class TranslationRouteTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((SOURCE / "server.py").read_text(encoding="utf-8"))
        handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and any(isinstance(n, ast.FunctionDef) and n.name == "do_POST" for n in node.body))
        function = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == "do_POST")
        self.translator = MagicMock(); self.helper = MagicMock()
        env = {"json": json, "TRANSLATOR": self.translator, "PROMPT_HELPER": self.helper, "TranslationBusy": LOCAL.TranslationBusy}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "synthetic-translation-route", "exec"), env)
        self.handler = env["do_POST"]

    def call(self, path, body):
        raw = json.dumps(body).encode(); answers = []
        request = SimpleNamespace(path=path, headers={"Content-Length": str(len(raw))}, rfile=io.BytesIO(raw), _json=lambda *args: answers.append(args))
        self.handler(request); return answers

    def test_only_submitted_text_reaches_translator(self):
        self.translator.translate.return_value = {"text": "합성 번역"}
        self.assertEqual(self.call("/api/translate", {"text": "Synthetic sentence."}), [({"text": "합성 번역"},)])
        self.translator.translate.assert_called_once_with("Synthetic sentence.", "quality")
        self.helper.start.assert_not_called()

    def test_engine_choice_passes_without_reading_other_state(self):
        self.translator.translate.return_value = {"text":"빠른 합성 번역"}
        self.call("/api/translate", {"text":"Synthetic sentence.", "engine":"fast"})
        self.translator.translate.assert_called_once_with("Synthetic sentence.", "fast")

    def test_busy_returns_retryable_status(self):
        self.translator.translate.side_effect = LOCAL.TranslationBusy("Synthetic busy")
        response = self.call("/api/translate", {"text": "Synthetic sentence."})[0]
        self.assertEqual(response[1], 409); self.assertTrue(response[0]["busy"])

    def test_prompt_helper_preempts_only_translator(self):
        calls = []
        self.translator.pause.side_effect = lambda: calls.append("pause")
        self.helper.start.side_effect = lambda body: calls.append("helper") or {"id": "synthetic"}
        self.call("/api/prompt-helper/start", {"idea": "Synthetic idea."})
        self.assertEqual(calls, ["pause", "helper"])


if __name__ == "__main__": unittest.main()
