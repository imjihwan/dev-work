"""실제 GPU 생성으로 속도·화질을 재는 개발용 도구.

사용자의 ComfyUI(8188)·화면(8190)·사진·결과물과 분리된 '측정 전용' ComfyUI 를 다른 포트에 띄운다.
모델 파일과 커스텀 노드만 같이 쓰고, 입력·출력·임시·사용자 폴더는 측정 폴더(기본 logs/bench) 아래에 따로 둔다.
입력은 합성 사진과 합성 문구뿐이다. 사용자의 ComfyUI 가 켜지면 하던 작업을 멈추고 측정 인스턴스를 내린다
(GPU 와 RAM 을 나눠 쓰면 양쪽 다 느려지고 측정도 틀어진다).

실행은 ComfyUI 의 파이썬으로 한다(PyAV·OpenCV·aiohttp·psutil 을 그대로 쓴다).

  <ComfyUI>/.venv/Scripts/python.exe scripts/bench_generation.py start
  <ComfyUI>/.venv/Scripts/python.exe scripts/bench_generation.py run plan.json
  <ComfyUI>/.venv/Scripts/python.exe scripts/bench_generation.py report
  <ComfyUI>/.venv/Scripts/python.exe scripts/bench_generation.py stop

plan.json: {"defaults": {...}, "variants": [{"name": "...", ...}, ...]}
변형 항목의 값: mode, image(측정 input 폴더 안 파일 이름), scene 또는 prompt, aspect, resolution, width, height, duration,
seed, model(파일 이름 일부), steps, sampler, scheduler, shift_video, shift_audio, loras[{name,strength}],
overrides{노드: {입력: 값}}(값만 바꾸기), nodes{노드: {...}}(노드 추가 — 구조 실험), preview_method, flags[실행 옵션], env{환경 변수}.
"""
import argparse
import ast
import ctypes
import json
import math
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MAIN_URL = "http://127.0.0.1:8188"          # 사용자의 ComfyUI. 읽기 확인(켜져 있는지)만 한다.
DIRECTOR, SEED, SAVE = "2730", "2739", "2568"
LOADERS = ("1512:2586", "1512:2588")
SCHED, SAMPLER, SHIFT, LORA = "1512:2590", "1512:2598", "1512:2692", "2678"
LORA_SLOTS = 10

# 합성 문구(실존 인물·실제 작업과 무관). 화면이 만드는 최종 프롬프트와 같은 틀을 쓴다.
SCENES = {
    "portrait-talk": {
        "summary": "A woman in her thirties with shoulder-length dark hair and a grey knit sweater sits by a window in a quiet cafe and talks to the camera.",
        "detail": "Soft daylight from the left, shallow depth of field, natural skin texture, realistic handheld documentary look. She smiles slightly, tilts her head, says a short sentence, then looks out of the window and back to the camera.",
        "keep": "Keep the same face, hairstyle, sweater and cafe background for the whole video.",
        "sound": "Quiet cafe ambience, a clear female voice speaking one calm sentence in English.",
    },
    "walk-street": {
        "summary": "The same person walks along a rainy city street at dusk holding a transparent umbrella.",
        "detail": "Wet asphalt reflects neon signs, cars pass in the background, the camera tracks backwards in front of the subject at walking speed. Hair and coat move naturally with each step.",
        "keep": "Keep the same face, hairstyle and outfit. Hands have five fingers, steady natural gait.",
        "sound": "Rain on the umbrella, distant traffic, footsteps on wet pavement.",
    },
    "detail-still": {
        "summary": "A close-up of a hand pouring coffee from a steel kettle into a white ceramic cup on a wooden table.",
        "detail": "Steam rises, fine wood grain and small water droplets are visible, slow push-in, macro lens look, crisp focus on the rim of the cup.",
        "keep": "The cup, kettle and table stay the same shape and colour.",
        "sound": "Coffee pouring, a soft kitchen room tone.",
    },
}


def scene_prompt(name, mode):
    s = SCENES[name]
    sound = f"overall_soundscape: {s['sound']}"
    music = "non_diegetic_music: N/A"
    if mode == "REF2VA":
        subject = "<Picture 1> shows the main subject. Copy the face, hairstyle, outfit and background from <Picture 1>."
        return "\n\n".join([f"subject_definitions: {subject}", f"summary: {s['summary']}", f"retention_analysis: {s['keep']}",
                            f"detailed_description: {s['detail']}", sound, music])
    head = {"I2VA": "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.",
            "FL2VA": "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 2) aligns with the end mark of the target video."}.get(mode)
    body = f"integrated_multimodal_description: {s['summary']} {s['detail']} {s['keep']}"
    return "\n\n".join(x for x in (head, body, sound, music) if x)


def default_comfy():
    local = PROJECT / "ComfyUI"
    return local if local.is_dir() else Path.home() / "ComfyUI"


def server_helpers():
    """화면 서버의 해상도 계산(canvas)을 그대로 가져온다 — 측정이 실제 화면과 같은 크기를 쓰게."""
    tree = ast.parse((PROJECT / "simple_ui" / "server.py").read_text(encoding="utf-8"))
    wanted = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in ("snap", "canvas"))
              or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in ("MULT", "RES_MP"))]
    scope = {}
    exec(compile(ast.Module(wanted, []), "server.py", "exec"), scope)
    return scope


def http_json(url, body=None, timeout=30):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


def reachable(url, timeout=1.5):
    try:
        http_json(url + "/system_stats", timeout=timeout)
        return True
    except (OSError, ValueError):
        return False


class Yield(Exception):
    """사용자의 ComfyUI 가 켜져서 물러난다."""


class Instance:
    def __init__(self, comfy, root, port):
        self.comfy, self.root, self.port = Path(comfy), Path(root), port
        self.url = f"http://127.0.0.1:{port}"
        self.state = self.root / "instance.json"

    def folders(self):
        return {k: self.root / k for k in ("input", "output", "temp", "user")}

    def info(self):
        try:
            return json.loads(self.state.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def alive(self):
        return reachable(self.url)

    def start(self, flags=(), env=None, wait=300):
        if not (self.comfy / "main.py").is_file():
            sys.exit(f"ComfyUI 를 찾지 못했습니다: {self.comfy}")
        if reachable(MAIN_URL):
            raise Yield("사용자의 ComfyUI(8188)가 켜져 있어 측정 인스턴스를 띄우지 않습니다.")
        for folder in self.folders().values():
            folder.mkdir(parents=True, exist_ok=True)
        dirs = self.folders()
        python = self.comfy / ".venv" / "Scripts" / "python.exe"
        args = [str(python if python.is_file() else sys.executable), "main.py", "--listen", "127.0.0.1", "--port", str(self.port),
                "--disable-auto-launch", "--input-directory", str(dirs["input"]), "--output-directory", str(dirs["output"]),
                "--temp-directory", str(dirs["temp"]), "--user-directory", str(dirs["user"]), *flags]
        environment = dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {}))
        log = open(self.root / "comfyui.log", "ab")
        creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        process = subprocess.Popen(args, cwd=self.comfy, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, creationflags=creation)
        self.state.write_text(json.dumps({"pid": process.pid, "flags": list(flags), "env": env or {}, "started": time.time()}), encoding="utf-8")
        deadline = time.time() + wait
        while time.time() < deadline:
            if process.poll() is not None:
                sys.exit(f"측정 인스턴스가 시작 중에 끝났습니다(코드 {process.returncode}). {self.root / 'comfyui.log'} 를 보세요.")
            if self.alive():
                return process.pid
            time.sleep(1)
        sys.exit("측정 인스턴스가 시간 안에 응답하지 않았습니다.")

    def stop(self):
        """이 도구가 띄운 프로세스만 끝낸다(명령줄에 측정 포트와 측정 폴더가 있는지 확인)."""
        pid = self.info().get("pid")
        if not pid:
            return False
        import psutil
        try:
            process = psutil.Process(pid)
            line = " ".join(process.cmdline())
        except (psutil.Error, OSError):
            self.state.unlink(missing_ok=True)
            return False
        if f"--port {self.port}" not in line or str(self.folders()["output"]) not in line:
            return False
        for child in process.children(recursive=True) + [process]:
            try:
                child.kill()
            except psutil.Error:
                pass
        self.state.unlink(missing_ok=True)
        return True

    def ensure(self, flags, env):
        info = self.info()
        if self.alive() and info.get("flags") == list(flags) and info.get("env") == (env or {}):
            return
        if self.alive() or info:
            self.stop()
            time.sleep(3)
        self.start(flags, env)


class EventTap(threading.Thread):
    """측정 인스턴스의 웹소켓 이벤트를 받은 시각과 함께 모은다."""
    def __init__(self, url, client_id):
        super().__init__(daemon=True)
        self.address = url.replace("http", "ws", 1) + f"/ws?clientId={client_id}"
        self.events, self.previews, self.ready, self.closing = [], [], threading.Event(), False

    def run(self):
        import asyncio
        import aiohttp

        async def listen():
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(self.address, heartbeat=30, max_msg_size=0) as socket:
                    self.ready.set()
                    async for message in socket:
                        now = time.time()
                        if message.type == aiohttp.WSMsgType.TEXT:
                            try:
                                self.events.append((now, json.loads(message.data)))
                            except ValueError:
                                pass
                        elif message.type == aiohttp.WSMsgType.BINARY:
                            self.previews.append((now, len(message.data)))
                        if self.closing:
                            break
        try:
            asyncio.run(listen())
        except Exception as exc:  # noqa: BLE001 - 끊기면 기다리는 쪽이 시간 초과로 알아챈다
            self.events.append((time.time(), {"type": "tap_error", "data": {"error": repr(exc)}}))
            self.ready.set()


class Resources(threading.Thread):
    """1초마다 GPU 메모리·사용률과 남은 RAM 을 적는다."""
    def __init__(self):
        super().__init__(daemon=True)
        self.rows, self.stopping = [], False

    @staticmethod
    def ram_available_gb():
        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
                        ("page_total", ctypes.c_ulonglong), ("page_available", ctypes.c_ulonglong), ("virtual_total", ctypes.c_ulonglong),
                        ("virtual_available", ctypes.c_ulonglong), ("extended", ctypes.c_ulonglong)]
        status = Status()
        status.length = ctypes.sizeof(Status)
        try:
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        except AttributeError:
            return None
        return status.available / 2**30

    def run(self):
        while not self.stopping:
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu,power.draw", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=5).stdout.strip().splitlines()[0]
                used, util, power = [float(x) for x in out.split(",")]
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                used = util = power = None
            self.rows.append((time.time(), used, util, power, self.ram_available_gb()))
            time.sleep(1)

    def summary(self, start, end):
        rows = [r for r in self.rows if start <= r[0] <= end and r[1] is not None]
        if not rows:
            return {}
        return {"vram_peak_gb": round(max(r[1] for r in rows) / 1024, 2), "gpu_util_mean": round(sum(r[2] for r in rows) / len(rows), 1),
                "power_mean_w": round(sum(r[3] for r in rows) / len(rows), 1),
                "ram_available_min_gb": round(min(r[4] for r in rows if r[4] is not None), 1) if any(r[4] is not None for r in rows) else None}


def upload_image(url, path):
    boundary = uuid.uuid4().hex
    raw = Path(path).read_bytes()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{Path(path).name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + raw + (
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(url + "/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)["name"]


def pick_option(url, node, field, wanted):
    """목록 값(경로 구분자 포함)에서 이름 일부로 고른다 — 문자열을 직접 만들지 않는다."""
    info = http_json(f"{url}/object_info/{node}")[node]["input"]
    spec = {**info.get("required", {}), **info.get("optional", {})}[field]
    options = spec[0] if isinstance(spec[0], list) else spec[1].get("options", [])
    exact = [o for o in options if o == wanted or o.replace("\\", "/").split("/")[-1] == wanted]
    found = exact or [o for o in options if wanted.lower() in o.lower()]
    if len(found) != 1:
        raise ValueError(f"{node}.{field} 에서 '{wanted}' 를 하나로 고르지 못했습니다: {found[:5]}")
    return found[0]


def build_graph(instance, v, helpers):
    graph = json.loads((PROJECT / "simple_ui" / "template_api.json").read_text(encoding="utf-8-sig"))
    mode = v.get("mode", "REF2VA")
    if v.get("model"):
        name = pick_option(instance.url, "UNETLoader", "unet_name", v["model"])
        for loader in LOADERS:
            graph[loader]["inputs"]["unet_name"] = name
    for field, node, key in (("steps", SCHED, "steps"), ("scheduler", SCHED, "scheduler"), ("sampler", SAMPLER, "sampler_name"),
                             ("shift_video", SHIFT, "shift_video"), ("shift_audio", SHIFT, "shift_audio")):
        if v.get(field) not in (None, ""):
            graph[node]["inputs"][key] = v[field]
    graph[SCHED]["inputs"]["model"] = [SHIFT, 0]          # 화면 서버와 같은 연결(Shift Video 가 영상 스케줄에 반영)
    rows = [{"on": True, "lora": pick_option(instance.url, "LoraLoaderModelOnly", "lora_name", x["name"]), "str": float(x.get("strength", 1)), "vs": 1, "as": 1}
            for x in v.get("loras", [])]
    rows += [{"on": True, "lora": "None", "str": 1, "vs": 1, "as": 1}] * (LORA_SLOTS - len(rows))
    graph[LORA]["inputs"]["stack_data"] = json.dumps(rows)

    images = [v["image"]] if isinstance(v.get("image"), str) else list(v.get("image") or [])
    items, first_size = [], None
    for index, name in enumerate(images):
        from PIL import Image
        path = instance.folders()["input"] / name
        with Image.open(path) as picture:
            size = picture.size
        first_size = first_size or size
        items.append({"id": f"image-bench-{index}", "enabled": True, "order": index, "slot": index, "start": index, "duration": 1,
                      "type": "image", "value": upload_image(instance.url, path), "thumbnail": None,
                      "source_width": size[0], "source_height": size[1]})
    aspect, resolution = v.get("aspect", "4:5"), v.get("resolution", "auto")
    width, height = (v["width"], v["height"]) if v.get("width") else helpers["canvas"](aspect, resolution, first_size)
    duration = float(v.get("duration", 5))
    text = v.get("prompt") or scene_prompt(v.get("scene", "portrait-talk"), mode)
    director = graph[DIRECTOR]["inputs"]
    timeline = json.loads(director["timeline_data"])
    timeline["items"] = items
    timeline["builder_state"].update(duration=duration, mode=mode, simple_prompt=text)
    timeline["resolution"].update(aspect=aspect, resolution=resolution if resolution in helpers["RES_MP"] else "auto",
                                  input_scaling="Auto" if mode == "REF2VA" else "Fill and crop")
    timeline["resolved_prompt"] = text
    timeline["continuity"]["continuation_prompt"] = text
    builder = json.loads(director["builder_state"])
    builder.update(duration=duration, mode=mode, simple_prompt=text)
    director.update(mode=mode, width=width, height=height, duration=duration, prompt=text,
                    timeline_data=json.dumps(timeline, ensure_ascii=False), builder_state=json.dumps(builder, ensure_ascii=False))
    graph[SEED]["inputs"]["seed_value"] = int(v.get("seed", 20261123))
    graph[SAVE]["inputs"]["filename_prefix"] = f"bench/{v['name']}"
    for node, body in (v.get("nodes") or {}).items():
        graph[node] = body
    for node, inputs in (v.get("overrides") or {}).items():
        graph[node]["inputs"].update(inputs)
    return graph, {"width": width, "height": height, "duration": duration, "mode": mode}


def timings(events, graph, prompt_id, submitted):
    mine = [(t, m) for t, m in events if (m.get("data") or {}).get("prompt_id") == prompt_id]
    stamp = lambda kind: next((t for t, m in mine if m["type"] == kind), None)
    start, end = stamp("execution_start"), stamp("execution_success") or stamp("execution_error") or stamp("execution_interrupted")
    cached = next((m["data"].get("nodes", []) for t, m in mine if m["type"] == "execution_cached"), [])
    nodes, order = {}, [(t, m["data"].get("node")) for t, m in mine if m["type"] == "executing"]
    for (t, node), (after, _) in zip(order, order[1:] + [(end or time.time(), None)]):
        if node:
            nodes[node] = nodes.get(node, 0) + after - t
    by_class = {}
    for node, seconds in nodes.items():
        cls = graph.get(node, {}).get("class_type", node)
        by_class[cls] = round(by_class.get(cls, 0) + seconds, 2)
    sampler_node = next((k for k, n in graph.items() if n["class_type"] == "SamplerCustomAdvanced"), None)
    steps = [(t, m["data"]["value"], m["data"]["max"]) for t, m in mine if m["type"] == "progress" and m["data"].get("node") == sampler_node]
    entered = next((t for t, node in order if node == sampler_node), None)
    step_seconds = [round(b[0] - a[0], 2) for a, b in zip(steps, steps[1:]) if b[1] > a[1]]
    result = {"queued_to_start": round(start - submitted, 2) if start else None, "total": round(end - start, 2) if start and end else None,
              "by_class": dict(sorted(by_class.items(), key=lambda kv: -kv[1])), "cached_nodes": len(cached),
              "sampler_total": round(nodes.get(sampler_node, 0), 2) if sampler_node else None,
              "before_first_step": round(steps[0][0] - entered, 2) if steps and entered else None,
              "step_seconds": step_seconds, "step_median": round(sorted(step_seconds)[len(step_seconds) // 2], 2) if step_seconds else None}
    return result, end, mine


def find_outputs(instance, history):
    found = []
    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("filename"), str):
                base = instance.folders().get(value.get("type") or "output", instance.folders()["output"])
                found.append(base / (value.get("subfolder") or "") / value["filename"])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(history.get("outputs") or {})
    videos = [p for p in found if p.suffix.lower() in (".mp4", ".webm", ".mkv", ".mov") and p.is_file()]
    return videos or [p for p in found if p.is_file()]


# ---------------- 영상 지표 ----------------
def read_frames(path, limit=None, colour=False):
    import av
    frames = []
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        info = {"codec": stream.codec_context.name, "pix_fmt": stream.codec_context.pix_fmt, "width": stream.codec_context.width,
                "height": stream.codec_context.height, "fps": float(stream.average_rate) if stream.average_rate else None,
                "bit_rate": container.bit_rate, "audio": bool(container.streams.audio)}
        for frame in container.decode(stream):
            frames.append(frame.to_ndarray(format="rgb24" if colour else "gray"))
            if limit and len(frames) >= limit:
                break
    info["frames"] = len(frames)
    return frames, info


def audio_levels(path):
    import av
    import numpy as np
    chunks = []
    try:
        with av.open(str(path)) as container:
            if not container.streams.audio:
                return {}
            # 채널을 합치지 않는다(모노로 섞으면 좌우가 더해져 최대치가 실제보다 크게 나온다). 채널 순서대로 이어 붙인 표본.
            resampler = av.AudioResampler(format="flt", layout="stereo", rate=48000)
            for frame in container.decode(container.streams.audio[0]):
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray().reshape(-1, 2))
    except Exception:  # noqa: BLE001 - 소리 지표는 참고용
        return {}
    if not chunks:
        return {}
    wave = np.concatenate(chunks).astype("float64")              # (표본, 2)
    rms = math.sqrt(float((wave ** 2).mean())) or 1e-9
    window = 4800
    quiet = [math.sqrt(float((wave[i:i + window] ** 2).mean())) < 0.003 for i in range(0, max(len(wave) - window, 1), window)]
    return {"audio_seconds": round(len(wave) / 48000, 2), "audio_rms_db": round(20 * math.log10(rms), 1),
            "audio_peak_db": round(20 * math.log10(max(float(abs(wave).max()), 1e-9)), 1), "audio_quiet_share": round(sum(quiet) / len(quiet), 2),
            "audio_clipped_share": round(float((abs(wave) >= 0.98).mean()), 5)}


def video_metrics(path):
    import cv2
    import numpy as np
    frames, info = read_frames(path)
    if not frames:
        return info
    sharp = [float(cv2.Laplacian(f, cv2.CV_64F).var()) for f in frames]
    means = [float(f.mean()) for f in frames]
    motion = [float(np.abs(a.astype("int16") - b.astype("int16")).mean()) for a, b in zip(frames, frames[1:])]
    info.update(size_mb=round(Path(path).stat().st_size / 2**20, 2), sharpness=round(sum(sharp) / len(sharp), 1),
                sharpness_min=round(min(sharp), 1), motion=round(sum(motion) / len(motion), 2) if motion else 0,
                luma_mean=round(sum(means) / len(means), 1),
                flicker=round(float(np.std(np.diff(means))), 3) if len(means) > 2 else 0, **audio_levels(path))
    return info


def compare_videos(reference, other):
    """같은 시드·같은 설정에서 저장 방식만 바꾼 두 영상처럼, 프레임이 1:1 로 대응할 때만 뜻이 있다."""
    import cv2
    import numpy as np
    a, _ = read_frames(reference)
    b, _ = read_frames(other)
    count = min(len(a), len(b))
    if not count or a[0].shape != b[0].shape:
        return {"comparable": False, "frames": (len(a), len(b))}
    psnr, ssim = [], []
    for x, y in zip(a[:count], b[:count]):
        x64, y64 = x.astype("float64"), y.astype("float64")
        mse = float(((x64 - y64) ** 2).mean())
        psnr.append(99.0 if mse == 0 else 10 * math.log10(255 ** 2 / mse))
        blur = lambda image: cv2.GaussianBlur(image, (11, 11), 1.5)
        mx, my = blur(x64), blur(y64)
        vx, vy, cov = blur(x64 * x64) - mx * mx, blur(y64 * y64) - my * my, blur(x64 * y64) - mx * my
        c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
        ssim.append(float((((2 * mx * my + c1) * (2 * cov + c2)) / ((mx * mx + my * my + c1) * (vx + vy + c2))).mean()))
    return {"comparable": True, "frames": count, "psnr_mean": round(sum(psnr) / count, 2), "psnr_min": round(min(psnr), 2),
            "ssim_mean": round(sum(ssim) / count, 4), "ssim_min": round(min(ssim), 4)}


def contact_sheet(path, target, count=6, width=1800, at=None):
    """눈으로 볼 프레임 묶음(가로로 나열). at 을 주면 그 프레임 번호들만."""
    import cv2
    import numpy as np
    frames, _ = read_frames(path, colour=True)
    if not frames:
        return None
    picks = at or [round(i * (len(frames) - 1) / max(count - 1, 1)) for i in range(count)]
    chosen = [frames[min(max(i, 0), len(frames) - 1)] for i in picks]
    each = width // len(chosen)
    scale = each / chosen[0].shape[1]
    tiles = [cv2.resize(f, (each, round(f.shape[0] * scale)), interpolation=cv2.INTER_AREA) for f in chosen]
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), cv2.cvtColor(np.hstack(tiles), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
    return str(target)


def save_frame(path, target, index=0):
    import cv2
    frames, _ = read_frames(path, limit=index + 1, colour=True)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), cv2.cvtColor(frames[min(index, len(frames) - 1)], cv2.COLOR_RGB2BGR))
    return str(target)


def detail_compare(comfy, videos, target, index=60, size=560, region="face"):
    """여러 영상의 같은 프레임에서 같은 부분(첫 영상의 얼굴 또는 가운데)을 원본 화소 그대로 잘라 같은 크기로 나란히 놓는다.
    해상도·저장 품질·샘플러 변형의 세부 묘사를 눈으로 비교하는 용도."""
    import cv2
    import numpy as np
    frames = []
    for video in videos:
        got, _ = read_frames(video, limit=index + 1, colour=True)
        frames.append(got[min(index, len(got) - 1)])
    height, width = frames[0].shape[:2]
    cx, cy, side = 0.5, 0.5, 0.5                               # 화면 대비 비율(가운데 절반)
    model = Path(comfy) / "models" / "face_detection" / "face_detection_yunet_2026may.onnx"
    if region == "face" and model.is_file():
        detector = cv2.FaceDetectorYN_create(str(model), "", (width, height), 0.6, 0.3, 5000)
        _, faces = detector.detect(cv2.cvtColor(frames[0], cv2.COLOR_RGB2BGR))
        if faces is not None and len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])[:4]
            cx, cy, side = (x + w / 2) / width, (y + h / 2) / height, max(w / width, h / height * height / width) * 1.3
    tiles = []
    for frame in frames:
        h, w = frame.shape[:2]
        half = side * w / 2
        left, top = int(max(cx * w - half, 0)), int(max(cy * h - half, 0))
        right, bottom = int(min(cx * w + half, w)), int(min(cy * h + half, h))
        crop = frame[top:bottom, left:right]
        tiles.append(cv2.resize(crop, (size, size), interpolation=cv2.INTER_LANCZOS4))
        tiles.append(np.full((size, 6, 3), 255, "uint8"))
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), cv2.cvtColor(np.hstack(tiles[:-1]), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])
    return str(target)


SFACE = "face_recognition_sface_2021dec.onnx"      # OpenCV Zoo 의 공개 얼굴 인식 모델(선택). 측정 폴더의 models/sface/ 에 있을 때만 쓴다


def identity_score(comfy, root, video, reference, count=16):
    """참조 사진의 얼굴과 영상 속 얼굴이 같은 사람으로 보이는 정도(SFace 코사인 유사도, 높을수록 같음. 같은 사람 기준 약 0.36 이상).
    눈대중 대신 변형끼리 비교하기 위한 수치다. 모델 파일이 없으면 빈 값을 돌려준다."""
    import cv2
    detector_file = Path(comfy) / "models" / "face_detection" / "face_detection_yunet_2026may.onnx"
    recogniser_file = Path(root) / "models" / "sface" / SFACE
    if not (detector_file.is_file() and recogniser_file.is_file() and reference and Path(reference).is_file()):
        return {}
    detector = cv2.FaceDetectorYN_create(str(detector_file), "", (640, 640), 0.6, 0.3, 5000)
    recogniser = cv2.FaceRecognizerSF_create(str(recogniser_file), "")

    def feature(image):                    # image: BGR
        detector.setInputSize((image.shape[1], image.shape[0]))
        _, faces = detector.detect(image)
        if faces is None or not len(faces):
            return None
        face = max(faces, key=lambda f: f[2] * f[3])
        return recogniser.feature(recogniser.alignCrop(image, face)).copy()

    base = feature(cv2.imread(str(reference)))
    frames, _ = read_frames(video, colour=True)
    if base is None or not frames:
        return {}
    scores = []
    for index in range(count):
        frame = frames[round(index * (len(frames) - 1) / max(count - 1, 1))]
        found = feature(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        if found is not None:
            scores.append(float(recogniser.match(base, found, cv2.FaceRecognizerSF_FR_COSINE)))
    if not scores:
        return {"identity_faces": 0}
    return {"identity_mean": round(sum(scores) / len(scores), 3), "identity_min": round(min(scores), 3), "identity_faces": len(scores)}


def face_sheet(comfy, video, target, reference=None, count=7, size=288):
    """참조 사진의 얼굴과 영상 프레임들의 얼굴을 같은 크기로 잘라 나란히 놓는다(동일 인물 유지·얼굴 품질을 눈으로 확인).
    반환: 얼굴이 잡힌 프레임 비율, 얼굴이 화면에서 차지하는 비율, 얼굴 영역 선명도."""
    import cv2
    import numpy as np
    model = Path(comfy) / "models" / "face_detection" / "face_detection_yunet_2026may.onnx"
    if not model.is_file():
        return {}
    detector = cv2.FaceDetectorYN_create(str(model), "", (640, 640), 0.6, 0.3, 5000)

    def crop(image):                       # image: RGB
        height, width = image.shape[:2]
        detector.setInputSize((width, height))
        _, faces = detector.detect(cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        if faces is None or not len(faces):
            return None, 0.0, 0.0
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])[:4]
        side = max(w, h) * 1.5
        cx, cy = x + w / 2, y + h / 2
        left, top = int(max(cx - side / 2, 0)), int(max(cy - side / 2, 0))
        right, bottom = int(min(cx + side / 2, width)), int(min(cy + side / 2, height))
        face = image[top:bottom, left:right]
        if not face.size:
            return None, 0.0, 0.0
        sharp = float(cv2.Laplacian(cv2.cvtColor(face, cv2.COLOR_RGB2GRAY), cv2.CV_64F).var())
        return cv2.resize(face, (size, size), interpolation=cv2.INTER_CUBIC), float(w * h) / (width * height), sharp

    frames, _ = read_frames(video, colour=True)
    if not frames:
        return {}
    picks = [frames[round(i * (len(frames) - 1) / max(count - 1, 1))] for i in range(count)]
    blank = np.full((size, size, 3), 40, "uint8")
    tiles, shares, sharps = [], [], []
    if reference and Path(reference).is_file():
        picture = cv2.cvtColor(cv2.imread(str(reference)), cv2.COLOR_BGR2RGB)
        tile, _, _ = crop(picture)
        tiles.append(tile if tile is not None else blank)
        tiles.append(np.full((size, 8, 3), 255, "uint8"))
    for frame in picks:
        tile, share, sharp = crop(frame)
        tiles.append(tile if tile is not None else blank)
        if tile is not None:
            shares.append(share)
            sharps.append(sharp)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), cv2.cvtColor(np.hstack(tiles), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 93])
    return {"face_sheet": str(target), "face_found": round(len(shares) / len(picks), 2),
            "face_share": round(sum(shares) / len(shares), 4) if shares else 0,
            "face_sharpness": round(sum(sharps) / len(sharps), 1) if sharps else 0}


# ---------------- 실행 ----------------
def run_variant(instance, v, helpers, resources, timeout):
    if reachable(MAIN_URL):
        instance.stop()
        raise Yield("사용자의 ComfyUI 가 켜져 측정을 멈췄습니다.")
    instance.ensure(v.get("flags") or [], v.get("env") or {})
    graph, shape = build_graph(instance, v, helpers)
    client = uuid.uuid4().hex
    tap = EventTap(instance.url, client)
    tap.start()
    tap.ready.wait(20)
    extra = {"preview_method": v["preview_method"]} if v.get("preview_method") else {}
    submitted = time.time()
    try:
        answer = http_json(instance.url + "/prompt", {"prompt": graph, "client_id": client, "extra_data": extra})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1500]
        return {"name": v["name"], "error": f"거절(HTTP {exc.code}): {detail}", **shape}
    prompt_id = answer["prompt_id"]
    final, checked = None, time.time()
    while time.time() - submitted < timeout:
        kinds = [m for t, m in tap.events if (m.get("data") or {}).get("prompt_id") == prompt_id]
        final = next((m for m in kinds if m["type"] in ("execution_success", "execution_error", "execution_interrupted")), None)
        if final or any(m["type"] == "tap_error" for t, m in tap.events):
            break
        if time.time() - checked > 5:
            checked = time.time()
            if reachable(MAIN_URL):
                try:
                    http_json(instance.url + "/interrupt", {"prompt_id": prompt_id})
                except (OSError, ValueError):
                    pass
                instance.stop()
                raise Yield("사용자의 ComfyUI 가 켜져 측정을 멈췄습니다.")
        time.sleep(0.2)
    if not final:                               # 시간 초과: 다음 변형이 이 작업 뒤에 줄 서지 않게 멈추고, 그래도 안 풀리면 인스턴스를 다시 띄운다
        try:
            http_json(instance.url + "/interrupt", {"prompt_id": prompt_id})
            http_json(instance.url + "/queue", {"delete": [prompt_id]})
        except (OSError, ValueError):
            pass
        time.sleep(20)
        try:
            busy = http_json(instance.url + "/prompt", timeout=10).get("exec_info", {}).get("queue_remaining", 0)
        except (OSError, ValueError):
            busy = 1
        if busy:
            instance.stop()
    time.sleep(0.5)
    tap.closing = True
    timing, end, mine = timings(tap.events, graph, prompt_id, submitted)
    result = {"name": v["name"], "at": time.strftime("%Y-%m-%d %H:%M:%S"), **shape,
              "settings": {k: v.get(k) for k in ("model", "steps", "sampler", "scheduler", "shift_video", "shift_audio", "loras", "seed", "scene",
                                                  "image", "aspect", "resolution", "overrides", "preview_method", "flags", "env", "note") if v.get(k) is not None},
              "extra_nodes": sorted((v.get("nodes") or {}).keys()), "timing": timing, "previews": len(tap.previews),
              "preview_bytes": sum(size for _, size in tap.previews),
              "resources": resources.summary(submitted, end or time.time())}
    if not final or final["type"] != "execution_success":
        error = next((m["data"] for m in mine if m["type"] == "execution_error"), None)
        result["error"] = (f"{error.get('node_type')}: {error.get('exception_message')}"[:1500] if error else
                           "시간 초과 또는 중단" if not final else final["type"])
        return result
    history = http_json(f"{instance.url}/history/{prompt_id}").get(prompt_id, {})
    outputs = find_outputs(instance, history)
    if outputs:
        result["file"] = str(outputs[0])
        try:
            result["video"] = video_metrics(outputs[0])
            result["sheet"] = contact_sheet(outputs[0], instance.root / "sheets" / f"{v['name']}.jpg")
            first = v["image"] if isinstance(v.get("image"), str) else (v.get("image") or [None])[0]
            result["face"] = face_sheet(instance.comfy, outputs[0], instance.root / "sheets" / f"{v['name']}.faces.jpg",
                                        instance.folders()["input"] / first if first else None)
            if first:
                result["face"].update(identity_score(instance.comfy, instance.root, outputs[0], instance.folders()["input"] / first))
        except Exception as exc:  # noqa: BLE001 - 지표 실패가 측정 기록을 버리게 두지 않는다
            result["metrics_error"] = repr(exc)
    return result


def command_run(instance, args):
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    helpers, resources = server_helpers(), Resources()
    resources.start()
    results = instance.root / "results.jsonl"
    done = 0
    finished = set()
    if args.resume and results.is_file():      # 중간에 끊긴 계획을 이어서: 오류 없이 끝난 (이름, 회차)는 건너뛴다
        for line in results.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not row.get("error"):
                finished.add((row.get("name"), row.get("repeat", 0)))
    try:
        for variant in plan["variants"]:
            v = {**plan.get("defaults", {}), **variant}
            if args.only and v["name"] not in args.only:
                continue
            for repeat in range(int(v.get("repeat", 1))):
                if (v["name"], repeat) in finished:
                    continue
                result = run_variant(instance, v, helpers, resources, args.timeout)
                result["repeat"] = repeat
                with results.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                timing = result.get("timing") or {}
                print(f"{result['name']}#{repeat}: " + (f"오류 {result['error']}" if result.get("error") else
                      f"{timing.get('total')}초, 스텝 중앙값 {timing.get('step_median')}초, 첫 스텝 전 {timing.get('before_first_step')}초, "
                      f"VRAM {result['resources'].get('vram_peak_gb')}GB"), flush=True)
                done += 1
    except Yield as reason:
        print(str(reason), flush=True)
        return 3
    finally:
        resources.stopping = True
    print(f"{done}건 측정, 기록: {results}", flush=True)
    return 0


def command_report(instance, args):
    rows = [json.loads(line) for line in (instance.root / "results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.names:
        rows = [r for r in rows if any(n in r["name"] for n in args.names)]
    print("| 이름 | 크기 | 스텝 | 전체(초) | 첫 스텝 전 | 스텝 중앙값 | 디코드 | 저장 | VRAM 최대 | 남은 RAM 최소 | 선명도 | 움직임 | 파일(MB) |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        t, video, res = r.get("timing") or {}, r.get("video") or {}, r.get("resources") or {}
        by = t.get("by_class") or {}
        decode = sum(s for c, s in by.items() if "Decode" in c)
        save = sum(s for c, s in by.items() if "VideoCombine" in c)
        steps = len(t.get("step_seconds") or []) + 1 if t.get("step_seconds") else (r.get("settings") or {}).get("steps", "")
        print(f"| {r['name']}{'' if not r.get('repeat') else '#' + str(r['repeat'])} | {r.get('width')}x{r.get('height')} {r.get('duration')}s | {steps} | "
              f"{t.get('total') if not r.get('error') else '오류'} | {t.get('before_first_step')} | {t.get('step_median')} | {round(decode, 1)} | {round(save, 1)} | "
              f"{res.get('vram_peak_gb')} | {res.get('ram_available_min_gb')} | {video.get('sharpness')} | {video.get('motion')} | {video.get('size_mb')} |")
    return 0


def main():
    parser = argparse.ArgumentParser(description="측정 전용 ComfyUI 로 실제 생성 속도·화질을 잰다(합성 입력만).")
    parser.add_argument("--comfy", default=str(default_comfy()))
    parser.add_argument("--root", default=str(PROJECT / "logs" / "bench"))
    parser.add_argument("--port", type=int, default=8198)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start")
    start.add_argument("flags", nargs="*")
    commands.add_parser("stop")
    commands.add_parser("status")
    run = commands.add_parser("run")
    run.add_argument("plan")
    run.add_argument("--only", nargs="*")
    run.add_argument("--timeout", type=int, default=2400)
    run.add_argument("--resume", action="store_true", help="results.jsonl 에 이미 성공으로 적힌 변형은 건너뛴다")
    report = commands.add_parser("report")
    report.add_argument("names", nargs="*")
    compare = commands.add_parser("compare")
    compare.add_argument("reference")
    compare.add_argument("other")
    sheet = commands.add_parser("sheet")
    sheet.add_argument("video")
    sheet.add_argument("target")
    sheet.add_argument("--count", type=int, default=6)
    sheet.add_argument("--at", type=int, nargs="*")
    identity = commands.add_parser("identity", help="기록된 결과들의 동일 인물 점수를 (다시) 계산해 표로 보여 준다")
    identity.add_argument("names", nargs="*")
    detail = commands.add_parser("detail")
    detail.add_argument("target")
    detail.add_argument("videos", nargs="+")
    detail.add_argument("--index", type=int, default=60)
    detail.add_argument("--size", type=int, default=560)
    detail.add_argument("--region", choices=("face", "centre"), default="face")
    frame = commands.add_parser("frame")
    frame.add_argument("video")
    frame.add_argument("target")
    frame.add_argument("--index", type=int, default=0)
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    instance = Instance(args.comfy, args.root, args.port)
    Path(args.root).mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "start":
            print(f"측정 인스턴스 시작: pid {instance.start(args.flags)}, {instance.url}")
        elif args.command == "stop":
            print("측정 인스턴스를 끝냈습니다." if instance.stop() else "끝낼 측정 인스턴스가 없습니다.")
        elif args.command == "status":
            print(json.dumps({"bench_alive": instance.alive(), "main_alive": reachable(MAIN_URL), **instance.info()}, ensure_ascii=False))
        elif args.command == "run":
            return command_run(instance, args)
        elif args.command == "report":
            return command_report(instance, args)
        elif args.command == "compare":
            print(json.dumps(compare_videos(args.reference, args.other), ensure_ascii=False))
        elif args.command == "sheet":
            print(contact_sheet(args.video, args.target, args.count, at=args.at))
        elif args.command == "identity":
            for line in (instance.root / "results.jsonl").read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                image = (row.get("settings") or {}).get("image")
                first = image if isinstance(image, str) else (image or [None])[0]
                if not row.get("file") or not first or (args.names and not any(n in row["name"] for n in args.names)):
                    continue
                score = identity_score(instance.comfy, instance.root, row["file"], instance.folders()["input"] / first)
                print(f"{row['name']:<34} mean {score.get('identity_mean')}  min {score.get('identity_min')}  faces {score.get('identity_faces')}/16", flush=True)
        elif args.command == "detail":
            print(detail_compare(args.comfy, args.videos, args.target, args.index, args.size, args.region))
        elif args.command == "frame":
            print(save_frame(args.video, args.target, args.index))
    except Yield as reason:
        print(str(reason))
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
