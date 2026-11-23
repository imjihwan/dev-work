"""Owned CPU translation process, bounded memory cache, no external text requests or prompt files."""
from collections import OrderedDict
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

from prompt_helper import PromptHelper, available_memory

QUALITY_INSTRUCTION = """You are a professional English (en) to Korean (ko) translator. Your goal is to accurately convey the meaning and nuances of the original English text while adhering to Korean grammar and vocabulary.
Produce only the Korean translation, without any additional explanations or commentary.
Preserve all instructions, negations, directions, time conditions and reference labels exactly.
Translate every sentence fully; never summarize or drop conditions such as 'until the final frame'.
Filming terminology: medium shot = 미디엄 샷; framing = 구도; zoom out = 줌아웃; zoom in = 줌인.
Directional terminology: closer = 더 가까이; backward = 뒤로; forward = 앞으로; diagonal tilt = 대각선 기울기; rotation in depth = 깊이 방향의 회전.
Keep labels such as <Picture 1>, placeholders such as {{face_side}}, and timecodes unchanged.

Please translate the following English text into Korean:
"""
REFERENCE_TOKEN = re.compile(r"<(?:Picture|Subject|Video|Audio)\s+\d+>|\{\{[A-Za-z0-9_]+\}\}|\d{2}:\d{2}\.\d{3}|\[Shot\s+\d+\]", re.I)


class TranslationBusy(ValueError):
    pass


class LocalTranslator:
    def __init__(self, home=None, worker=None, busy=None, engine="quality"):
        self.home = Path(home) if home else Path(__file__).resolve().parents[2] / "local-translator"
        self.python = self.home / ".venv/Scripts/python.exe"
        self.model = self.home / "models/quickmt-en-ko"
        self.helper = PromptHelper(self.home.parent / "local-prompt-helper")
        self.quality_model = self.home / "models/translategemma-4b-it/translategemma-4b-it-Q4_K_M.gguf"
        self.default_engine = engine
        self.engine = None
        self.base = None
        self.worker = Path(worker) if worker else Path(__file__).with_name("translation_worker.py")
        self.busy = busy or (lambda: False)
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.process = None
        self.touched = 0
        self.deadline = 0
        self.pause_until = 0
        self.monitor_started = False

    def ready(self, engine=None):
        if (engine or self.default_engine) == "quality":
            return self.helper.exe.is_file() and self.quality_model.is_file()
        return (self.python.is_file() and (self.model / "model.bin").is_file()
                and (self.model / "src.spm.model").is_file() and (self.model / "tgt.spm.model").is_file())

    def pause(self):
        self.pause_until = time.monotonic() + 2
        self._stop()

    def _stop(self, expected=None):
        process = self.process
        if process is None or (expected is not None and expected is not process):
            return
        self.process = None
        try:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=2)
        except OSError:
            pass
        finally:
            for pipe in (process.stdin, process.stdout):
                if pipe is not None:
                    try: pipe.close()
                    except OSError: pass

    def _monitor(self):
        while True:
            time.sleep(1)
            process = self.process
            if process is None:
                continue
            now = time.monotonic()
            minimum = 2.5 if self.engine == "quality" else 2
            if ((self.deadline and now > self.deadline) or available_memory() < minimum * 1024**3
                    or (not self.lock.locked() and now - self.touched > 45)):
                self._stop(process)

    def _ensure_worker(self, engine):
        if self.process is not None and self.process.poll() is None and self.engine == engine:
            return self.process
        self._stop()
        env = dict(os.environ, CUDA_VISIBLE_DEVICES="-1", HIP_VISIBLE_DEVICES="-1",
                   OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        flags = subprocess.CREATE_NO_WINDOW | subprocess.IDLE_PRIORITY_CLASS if os.name == "nt" else 0
        if engine == "quality":
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
            args = self.helper.command(port)
            args[args.index("-c") + 1] = "2048"
            args[args.index("-m") + 1] = str(self.quality_model)
            args[args.index("--alias") + 1] = "h3-local-translation"
            self.base = "http://127.0.0.1:" + str(port)
        else:
            args = [str(self.python), "-u", str(self.worker), str(self.model)]
            self.base = None
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL if engine == "quality" else subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=env, creationflags=flags)
        self.process = process
        self.engine = engine
        if self.busy() or time.monotonic() < self.pause_until:
            self._stop(process)
            raise TranslationBusy("프롬프트 도우미 작업이 끝난 뒤 번역을 재개합니다.")
        if engine == "quality":
            for _ in range(120):
                if process.poll() is not None: raise RuntimeError("Translation model stopped")
                try:
                    with urllib.request.urlopen(self.base + "/health", timeout=1) as response:
                        if response.status == 200: break
                except (OSError, http.client.HTTPException):
                    # 연결 거부(URLError)뿐 아니라 응답을 기다리다 난 시간 초과·끊김도 '아직 준비 안 됨'이다
                    pass
                time.sleep(.25)
            else: raise RuntimeError("Translation model startup timed out")
        elif json.loads(process.stdout.readline()).get("ready") is not True:
            raise RuntimeError("Worker did not start")
        return process

    def _quality_translate(self, text):
        prompt = "<start_of_turn>user\n" + QUALITY_INSTRUCTION + text + "<end_of_turn>\n<start_of_turn>model\n"
        payload = {"prompt":prompt, "temperature":0, "seed":42, "repeat_penalty":1.0,
                   "n_predict":1300, "stream":False, "cache_prompt":False,
                   "stop":["<end_of_turn>", "<eos>"]}
        request = urllib.request.Request(self.base + "/completion", json.dumps(payload).encode("utf-8"), {"Content-Type":"application/json"})
        with urllib.request.urlopen(request, timeout=90) as response: result = json.load(response)
        if result.get("stopped_limit") or result.get("stop_type") == "limit":
            raise ValueError("번역 길이를 초과했습니다. 문장을 더 짧게 선택해서 확인해 주세요.")
        answer = {"text":result.get("content")}
        value = answer["text"]
        if isinstance(value, str):
            from collections import Counter
            if Counter(REFERENCE_TOKEN.findall(text)) != Counter(REFERENCE_TOKEN.findall(value)):
                return {"text":text,"warning":"Reference tokens were not preserved"}
            answer["text"] = re.match(r"\s*", text).group() + value.strip() + re.search(r"\s*$", text).group()
        return answer

    def translate(self, text, engine=None):
        engine = engine or self.default_engine
        if engine not in ("quality", "fast"):
            raise ValueError("번역 방식이 올바르지 않습니다.")
        if not isinstance(text, str) or not text.strip() or len(text) > 1200:
            raise ValueError("번역할 문장을 1~1,200자로 나눠 주세요.")
        if not self.lock.acquire(blocking=False):
            raise TranslationBusy("다른 문장을 번역 중입니다. 잠시 후 다시 확인합니다.")
        process = None
        try:
            key = hashlib.sha256((engine + ":translation-v3:" + text).encode("utf-8")).hexdigest()
            if key in self.cache:
                self.cache.move_to_end(key)
                return {"text": self.cache[key], "cached": True}
            if self.busy() or time.monotonic() < self.pause_until:
                raise TranslationBusy("프롬프트 도우미 작업이 끝난 뒤 번역을 재개합니다.")
            if not self.ready(engine):
                raise ValueError("로컬 번역 모델이 준비되지 않았습니다. scripts/install_local_translator.py를 실행해 주세요.")
            if self.process is not None and self.engine != engine:
                self._stop()
            warm = self.process is not None and self.process.poll() is None and self.engine == engine
            minimum = (2.5 if engine == "quality" else 2) if warm else (4 if engine == "quality" else 3)
            if available_memory() < minimum * 1024**3:
                message = "정밀 번역은 RAM 여유 4GB가 필요하며 ‘빠르게’를 선택할 수도 있습니다." if engine == "quality" else "빠른 번역은 RAM 여유 3GB가 필요합니다."
                raise TranslationBusy("영상 작업에 메모리를 남기기 위해 번역을 기다립니다. " + message)
            self.touched = time.monotonic()
            self.deadline = self.touched + (90 if engine == "quality" else 30)
            if not self.monitor_started:
                threading.Thread(target=self._monitor, daemon=True).start(); self.monitor_started = True
            process = self._ensure_worker(engine)
            if engine == "quality":
                answer = self._quality_translate(text)
            else:
                process.stdin.write(json.dumps({"text": text}, ensure_ascii=False) + "\n"); process.stdin.flush()
                answer = json.loads(process.stdout.readline())
            value = answer.get("text")
            if not isinstance(value, str) or not value.strip() or len(value) > 12000:
                raise ValueError("이 문장의 번역 결과를 확인하지 못했습니다. 다시 시도해 주세요.")
            if answer.get("warning"):
                return {"text": value, "cached": False, "warning": "번역 표기를 확인하지 못한 구간은 원문으로 표시합니다."}
            self.cache[key] = value
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
            return {"text": value, "cached": False}
        except (BrokenPipeError, OSError, json.JSONDecodeError, RuntimeError, KeyError, IndexError, TypeError):
            self._stop(process)
            raise ValueError("로컬 번역을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.") from None
        finally:
            self.deadline = 0
            self.touched = time.monotonic()
            self.lock.release()
