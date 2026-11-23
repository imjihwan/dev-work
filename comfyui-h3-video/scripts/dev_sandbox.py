"""개발용 샌드박스: 가짜 ComfyUI + 화면 서버를 임시 폴더·임시 포트에 띄운다.

실제 ComfyUI(8188)·화면 서버(8190)·설치본·사용자 사진/이력/결과에는 접근하지 않는다. 모든 데이터는 합성이며
임시 폴더에만 쓴다(끝나면 지운다). 영상 모델을 돌리지 않으므로 '생성'은 정해진 시간 뒤 합성 영상이 나오는 흉내다.

    <python> scripts/dev_sandbox.py                      # 띄워 두고 브라우저로 확인 (Ctrl+C 로 종료)
    <python> scripts/dev_sandbox.py --pending 300        # 대기 300건이 있는 상태로 시작
    <python> scripts/dev_sandbox.py --measure 20 --pending 300 --tabs 2 --tracked 20
                                                         # 20초 동안 화면 2개의 폴링을 흉내 내고 부하를 잰 뒤 종료

--measure 는 화면(index.html poll)의 조회 방식을 흉내 낸다: 탭마다 추적 중인 작업을 2초 간격으로 차례로 조회하고
10초마다 이력 첫 쪽을 다시 읽는다. 출력은 화면 서버가 받은 요청 수, 가짜 ComfyUI 가 받은 요청 수·보낸 바이트,
두 프로세스의 CPU 시간이다. 폴링 구조를 고칠 때 전후 비교에 쓴다.
"""
import argparse
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "simple_ui"
SAVE_NODE = "2568"


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def safetensors_header(path, keys, metadata):
    """헤더만 있는 가짜 가중치 파일. 화면 서버의 판정(analyze)은 헤더만 읽는다."""
    header = {"__metadata__": metadata}
    header.update({key: {"dtype": "I8", "shape": [1], "data_offsets": [0, 1]} for key in keys})
    raw = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + b"\0")


def synthetic_video(path):
    """재생되는 아주 작은 합성 영상. FFmpeg 가 없으면 재생되지 않는 자리표시 파일을 둔다."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        done = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                               "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=2",
                               "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if done.returncode == 0 and path.is_file():
            return
    path.write_bytes(b"\0\0\0\x18ftypmp42\0\0\0\0mp42isom" + b"\0" * 64)


def synthetic_image(path, index):
    try:
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (480, 640), ((index * 53) % 200 + 30, (index * 97) % 200 + 30, (index * 31) % 200 + 30))
        ImageDraw.Draw(image).text((20, 20), f"synthetic {index}", fill="white")
        image.save(path, format="PNG")
    except ImportError:   # Pillow 없이도 목록·부하 측정은 된다
        path.write_bytes(b"\x89PNG\r\n\x1a\n")


class FakeComfy:
    """ComfyUI 의 HTTP API 중 화면 서버가 쓰는 부분만 흉내 낸다. 요청 수·응답 바이트를 센다."""

    def __init__(self, home, models, loras, seconds_per_job, old_api=False):
        self.home, self.models, self.loras, self.seconds = home, models, loras, seconds_per_job
        self.old_api = old_api   # True 면 /api/jobs 가 없는 예전 ComfyUI 를 흉내 낸다
        self.lock = threading.Lock()
        self.pending, self.running, self.history = [], None, {}
        self.number = 0
        self.stats = {}
        self.video = home / "output" / "sandbox-source.mp4"
        (home / "input").mkdir(parents=True, exist_ok=True)
        (home / "output" / "video").mkdir(parents=True, exist_ok=True)
        synthetic_video(self.video)
        self.stop = threading.Event()
        threading.Thread(target=self.work, daemon=True).start()

    # ---- 상태 ----
    def count(self, label, size, started):
        with self.lock:
            row = self.stats.setdefault(label, {"requests": 0, "bytes": 0, "seconds": 0.0})
            row["requests"] += 1
            row["bytes"] += size
            row["seconds"] += time.perf_counter() - started

    def enqueue(self, graph, identity=None, number=None, extra=None):
        with self.lock:
            if number is None:
                number, self.number = self.number, self.number + 1
            identity = identity or str(uuid.uuid4())
            self.pending.append([number, identity, graph, extra or {}, [SAVE_NODE]])
            self.pending.sort(key=lambda item: item[0])
            return identity, number

    def finish(self, item, status, video=None):
        now = int(time.time() * 1000)
        final = {"success": "execution_success", "error": "execution_error"}.get(status, "execution_interrupted")
        entry = {"prompt": item, "outputs": {SAVE_NODE: {"gifs": [video]}} if video else {},
                 "status": {"status_str": "success" if status == "success" else "error", "completed": status == "success",
                            "messages": [["execution_start", {"prompt_id": item[1], "timestamp": now - int(self.seconds * 1000)}],
                                         [final, {"prompt_id": item[1], "timestamp": now}]]}}
        with self.lock:
            self.history[item[1]] = entry

    def work(self):
        serial = 0
        while not self.stop.is_set():
            with self.lock:
                if self.running is None and self.pending:
                    self.running = self.pending.pop(0)
                    self.running_until = time.monotonic() + self.seconds
                    self.interrupted = False
                item = self.running
            if item is None:
                self.stop.wait(0.1)
                continue
            if self.interrupted:
                self.finish(item, "interrupted")
            elif time.monotonic() < self.running_until:
                self.stop.wait(0.1)
                continue
            else:
                serial += 1
                folder = self.home / "output" / "video" / datetime.date.today().isoformat()
                folder.mkdir(parents=True, exist_ok=True)
                name = f"sandbox_{serial:05d}.mp4"
                shutil.copyfile(self.video, folder / name)
                self.finish(item, "success", {"filename": name, "subfolder": f"video/{folder.name}", "type": "output"})
            with self.lock:
                self.running = None

    # ---- HTTP ----
    def handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def send(self, label, started, body=b"", code=200, content_type="application/json", headers=None):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)
                fake.count(label, len(body), started)

            def json(self, label, started, value, code=200):
                self.send(label, started, json.dumps(value).encode(), code)

            def do_GET(self):
                started = time.perf_counter()
                url = urllib.parse.urlparse(self.path)
                query = dict(urllib.parse.parse_qsl(url.query))
                if url.path == "/queue":
                    with fake.lock:
                        value = {"queue_running": [fake.running] if fake.running else [], "queue_pending": list(fake.pending)}
                        body = json.dumps(value).encode()   # 실제 ComfyUI 처럼 그래프 전체를 싣는다
                    return self.send("GET /queue", started, body)
                if url.path == "/api/jobs" and not fake.old_api:
                    # 실제 ComfyUI 처럼 그래프 없이 순번·ID·상태만 싣는다
                    with fake.lock:
                        rows = ([{"id": fake.running[1], "status": "in_progress", "priority": fake.running[0], "create_time": 0, "outputs_count": 0, "previewable_outputs_count": 0}] if fake.running else []) + [
                            {"id": item[1], "status": "pending", "priority": item[0], "create_time": 0, "outputs_count": 0, "previewable_outputs_count": 0} for item in fake.pending]
                    return self.json("GET /api/jobs", started, {"jobs": rows, "pagination": {"offset": 0, "limit": None, "total": len(rows), "has_more": False}})
                if url.path == "/prompt":
                    with fake.lock:
                        remaining = len(fake.pending) + (1 if fake.running else 0)
                    return self.json("GET /prompt", started, {"exec_info": {"queue_remaining": remaining}})
                if url.path.startswith("/history/"):
                    identity = urllib.parse.unquote(url.path[len("/history/"):])
                    with fake.lock:
                        entry = fake.history.get(identity)
                    return self.json("GET /history/{id}", started, {identity: entry} if entry else {})
                if url.path == "/history":
                    with fake.lock:
                        items = dict(list(fake.history.items())[-int(query.get("max_items", 64)):])
                    return self.json("GET /history", started, items)
                if url.path.startswith("/object_info/"):
                    name = url.path.rsplit("/", 1)[-1]
                    options = {"UNETLoader": ("unet_name", fake.models), "LoraLoaderModelOnly": ("lora_name", fake.loras),
                               "KSamplerSelect": ("sampler_name", ["euler", "res_multistep", "dpmpp_2m"]),
                               "BasicScheduler": ("scheduler", ["simple", "normal", "beta"])}.get(name)
                    if not options:
                        return self.json("GET /object_info", started, {}, 404)
                    return self.json("GET /object_info", started, {name: {"input": {"required": {options[0]: [options[1]]}}}})
                if url.path == "/system_stats":
                    return self.json("GET /system_stats", started, {"system": {"comfyui_version": "sandbox"}})
                if url.path == "/view":
                    base = fake.home / ("input" if query.get("type") == "input" else "output")
                    path = (base / query.get("subfolder", "") / query.get("filename", "")).resolve()
                    if not path.is_relative_to(base.resolve()) or not path.is_file():
                        return self.json("GET /view", started, {"error": "not found"}, 404)
                    data = path.read_bytes()
                    kind = {".mp4": "video/mp4", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower(), "application/octet-stream")
                    span = self.headers.get("Range", "")
                    if span.startswith("bytes="):
                        first, _, last = span[6:].partition("-")
                        start = int(first or 0)
                        end = min(int(last), len(data) - 1) if last else len(data) - 1
                        return self.send("GET /view", started, data[start:end + 1], 206, kind,
                                         {"Content-Range": f"bytes {start}-{end}/{len(data)}", "Accept-Ranges": "bytes"})
                    return self.send("GET /view", started, data, 200, kind, {"Accept-Ranges": "bytes"})
                if url.path == "/__stats":
                    with fake.lock:
                        return self.json("GET /__stats", started, {"stats": fake.stats, "pending": len(fake.pending), "history": len(fake.history)})
                self.json("GET other", started, {"error": "not found"}, 404)

            def do_POST(self):
                started = time.perf_counter()
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.path == "/upload/image":
                    boundary = self.headers.get("Content-Type", "").split("boundary=")[-1].encode()
                    part = raw.split(b"--" + boundary)[1]
                    head, _, data = part.partition(b"\r\n\r\n")
                    name = head.split(b'filename="')[1].split(b'"')[0].decode()
                    (fake.home / "input" / Path(name).name).write_bytes(data[:-2])
                    return self.json("POST /upload/image", started, {"name": Path(name).name, "subfolder": "", "type": "input"})
                body = json.loads(raw or b"{}")
                if self.path == "/prompt":
                    graph = body.get("prompt")
                    wanted = [node["inputs"].get("unet_name") for node in (graph or {}).values()
                              if isinstance(node, dict) and node.get("class_type") == "UNETLoader"]
                    missing = [name for name in wanted if name not in fake.models]
                    if not isinstance(graph, dict) or missing:
                        # 실제 ComfyUI 의 검증 실패 응답 모양(HTTP 400)
                        return self.json("POST /prompt", started, {"error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation", "details": "", "extra_info": {}},
                                                                    "node_errors": {"1512:2588": {"class_type": "UNETLoader", "dependent_outputs": [SAVE_NODE], "errors": [
                                                                        {"type": "value_not_in_list", "message": "Value not in list", "details": f"unet_name: {missing[:1]} not in list", "extra_info": {}}]}}}, 400)
                    identity, number = fake.enqueue(graph, body.get("prompt_id"), body.get("number"),
                                                    dict(body.get("extra_data") or {}, client_id=body.get("client_id")))
                    return self.json("POST /prompt", started, {"prompt_id": identity, "number": number, "node_errors": {}})
                if self.path == "/queue":
                    with fake.lock:
                        if body.get("clear"):
                            fake.pending.clear()
                        doomed = set(body.get("delete") or [])
                        fake.pending[:] = [item for item in fake.pending if item[1] not in doomed]
                    return self.send("POST /queue", started)
                if self.path == "/interrupt":
                    with fake.lock:
                        if fake.running and body.get("prompt_id") in (None, fake.running[1]):
                            fake.interrupted = True
                    return self.send("POST /interrupt", started)
                if self.path == "/__stats/reset":
                    with fake.lock:
                        fake.stats.clear()
                    return self.send("POST /__stats/reset", started)
                self.json("POST other", started, {"error": "not found"}, 404)

        return Handler


def prepare(args):
    """임시 ComfyUI 폴더(화면 서버 사본·가짜 모델·합성 이력)를 만들고 (폴더, 가짜 서버, 화면 서버 프로세스)를 돌려준다."""
    home = Path(tempfile.mkdtemp(prefix="h3-sandbox-")) / "ComfyUI"
    ui = home / "simple_ui"
    ui.mkdir(parents=True)
    for path in Path(args.source or SOURCE).iterdir():
        if path.is_file() and (path.suffix in (".py", ".html", ".js", ".bat") or path.name.endswith(".seed.json") or path.name == "template_api.json"):
            shutil.copyfile(path, ui / path.name)
    template = json.loads((ui / "template_api.json").read_text(encoding="utf-8-sig"))
    model = template["1512:2588"]["inputs"]["unet_name"]
    regular = model.rsplit("\\", 1)[0] + "\\synthetic-regular-int8.safetensors" if "\\" in model else "synthetic-regular-int8.safetensors"
    loras = [row["lora"] for row in json.loads(template["2678"]["inputs"]["stack_data"]) if row.get("lora") not in (None, "", "None")] or ["synthetic-style.safetensors"]
    loras = list(dict.fromkeys(loras + ["synthetic-style.safetensors"]))
    block = ["blocks.0.attn.to_q.weight", "blocks.0.attn.to_k.weight", "blocks.0.ff.weight"]
    for name in (model, regular):
        safetensors_header(home / "models" / "diffusion_models" / name.replace("\\", "/"), ["audio_patch_proj.weight", *block], {"modelspec.architecture": "minimax_h3"})
    cards = {"model": {}, "lora": {}}
    for name in loras:
        path = home / "models" / "loras" / name.replace("\\", "/")
        safetensors_header(path, [f"diffusion_model.{key[:-7]}.lora_A.weight" for key in block], {"ss_base_model_version": "minimax_h3"})
        stamp = [path.stat().st_size, int(path.stat().st_mtime)]
        # 합성 파일의 해시를 외부(Civitai)에 조회하지 않도록 '없음'으로 채워 둔다
        cards["lora"][name] = {"civitai": {"found": False, "sha256": "SANDBOX"}, "civitai_stamp": stamp}
    (ui / "cards.json").write_text(json.dumps(cards), encoding="utf-8")

    comfy_port, ui_port = args.comfy_port or free_port(), args.port or free_port()
    fake = FakeComfy(home, [model, regular], loras, args.seconds, args.old_comfy)
    backend = ThreadingHTTPServer(("127.0.0.1", comfy_port), fake.handler())
    backend.daemon_threads = True
    threading.Thread(target=backend.serve_forever, daemon=True).start()

    # 화면 서버 사본이 가짜 ComfyUI 를 보게 한다(저장소의 server.py 는 바꾸지 않는다)
    server = (ui / "server.py").read_text(encoding="utf-8")
    assert '"http://127.0.0.1:8188"' in server and "ws://127.0.0.1:8188/ws" in server, "server.py 의 ComfyUI 주소 표기가 바뀌었습니다"
    server = server.replace('"http://127.0.0.1:8188"', f'"http://127.0.0.1:{comfy_port}"').replace("ws://127.0.0.1:8188/ws", f"ws://127.0.0.1:{comfy_port}/ws")
    (ui / "server.py").write_text(server, encoding="utf-8")

    # 합성 이력·대기열: 사진 한 장을 올린 것으로 하고, 완료 N건 + 대기 M건
    photo = "simpleui_0123456789.png"
    synthetic_image(home / "input" / photo, 1)
    now, history = time.time(), []
    base = {"seed": 1, "error": None, "mode": "REF2VA", "model": model, "steps": 4, "sampler": "euler", "scheduler": "simple",
            "shift_video": 7.0, "shift_audio": 4.0, "shift_applied": True, "loras": [], "aspect": "auto", "requested_aspect": "auto",
            "protect_person": False, "framing_fallback": False, "resolution": "draft", "duration": 5.0, "width": 480, "height": 640,
            "count": 1, "anchor": False, "images": [photo], "face_side": None, "sequence_index": None}
    text = "Synthetic sandbox prompt. " * 40
    folder = home / "output" / "video" / datetime.date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(args.history):
        name = f"history_{index:05d}.mp4"
        shutil.copyfile(fake.video, folder / name)
        history.append(dict(base, id=str(uuid.uuid4()), t=now - 3600 + index, state="done", t_end=now - 3500 + index, generation_seconds=95.0,
                            video={"filename": name, "subfolder": f"video/{folder.name}", "type": "output"}, prompt=text,
                            ui={"f": {"summary": f"synthetic {index}"}, "shots": [[0, "synthetic motion"]], "final": text}))
    for index in range(args.pending):
        identity, _ = fake.enqueue(json.loads(json.dumps(template)), extra={"client_id": "sandbox"})
        history.append(dict(base, id=identity, t=now + index / 1000, state="queued", video=None, prompt=text,
                            ui={"f": {"summary": f"pending {index}"}, "shots": [[0, "synthetic motion"]], "final": text}))
    (ui / "history.json").write_text(json.dumps(history), encoding="utf-8")

    environment = dict(os.environ, SIMPLEUI_PORT=str(ui_port), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    environment.pop("SIMPLEUI_RESTART_STATE", None)
    process = subprocess.Popen([sys.executable, "-X", "utf8", "server.py"], cwd=ui, env=environment,
                               stdout=subprocess.DEVNULL if args.measure else None, stderr=subprocess.DEVNULL if args.measure else None)
    address = f"http://127.0.0.1:{ui_port}"
    for _ in range(100):
        try:
            with urllib.request.urlopen(address + "/api/health", timeout=1) as response:
                if json.load(response).get("ok"):
                    break
        except OSError:
            if process.poll() is not None:
                raise SystemExit("화면 서버 사본이 시작하지 못했습니다(파이썬 환경에 Pillow·psutil·av·opencv 가 있는지 확인).")
            time.sleep(0.2)
    else:
        process.kill()
        raise SystemExit("화면 서버 사본이 응답하지 않습니다.")
    return home, fake, backend, process, address, f"http://127.0.0.1:{comfy_port}", [entry["id"] for entry in history if entry["state"] == "queued"]


def measure(args, process, address, comfy, pending):
    """화면의 폴링을 흉내 내고 부하를 잰다."""
    import psutil
    get = lambda url: urllib.request.urlopen(url, timeout=60).read()
    ui = psutil.Process(process.pid)

    def cpu_seconds():
        # 가상환경의 python.exe 는 실제 인터프리터를 자식으로 띄우므로 자식까지 더한다
        total = 0.0
        for item in [ui, *ui.children(recursive=True)]:
            try:
                times = item.cpu_times()
                total += times.user + times.system
            except psutil.Error:
                pass
        return total
    sent = {"status": 0, "history": 0, "gallery": 0}
    errors, stop = [], threading.Event()
    tracked = pending[:args.tracked]

    def tab():
        last_history = 0.0
        while not stop.is_set():
            started = time.monotonic()
            try:
                if args.batch:
                    wanted = tracked[:3] if len(tracked) > 20 else tracked
                    json.loads(get(f"{address}/api/status?ids={','.join(wanted)}"))["jobs"]
                    sent["status"] += 1
                for index, identity in enumerate([] if args.batch else tracked):
                    json.loads(get(f"{address}/api/status?id={identity}"))
                    sent["status"] += 1
                    if len(tracked) > 20 and index == 0:
                        break   # 화면은 20건을 넘는 묶음에서 맨 앞 미완료 작업만 본다
                if started - last_history >= 10:
                    get(f"{address}/api/history?offset=0&limit=20")
                    sent["history"] += 1
                    last_history = started
                if args.gallery:
                    get(f"{address}/api/gallery/progress")
                    sent["gallery"] += 1
            except Exception as error:  # noqa: BLE001 — 측정 중 실패는 모아 보고한다
                errors.append(type(error).__name__)
            stop.wait(max(0.0, 2 - (time.monotonic() - started)))

    urllib.request.urlopen(urllib.request.Request(comfy + "/__stats/reset", b"{}", method="POST"), timeout=5).read()
    before, wall = cpu_seconds(), time.monotonic()
    threads = [threading.Thread(target=tab) for _ in range(args.tabs)]
    for thread in threads:
        thread.start()
    time.sleep(args.measure)
    stop.set()
    for thread in threads:
        thread.join()
    elapsed, after = time.monotonic() - wall, cpu_seconds()
    upstream = json.loads(get(comfy + "/__stats"))["stats"]
    upstream.pop("GET /__stats", None)
    upstream.pop("POST /__stats/reset", None)
    result = {"seconds": round(elapsed, 1), "pending_jobs": args.pending, "tabs": args.tabs, "tracked_per_tab": len(tracked),
              "ui_requests": sent, "ui_requests_per_s": round(sum(sent.values()) / elapsed, 1),
              "ui_server_cpu_s": round(after - before, 2),
              "upstream_requests": sum(row["requests"] for row in upstream.values()),
              "upstream_megabytes": round(sum(row["bytes"] for row in upstream.values()) / 1e6, 1),
              "upstream_megabytes_per_s": round(sum(row["bytes"] for row in upstream.values()) / 1e6 / elapsed, 2),
              "fake_comfy_handler_s": round(sum(row["seconds"] for row in upstream.values()), 2),
              "upstream_by_path": {label: {"requests": row["requests"], "megabytes": round(row["bytes"] / 1e6, 2)} for label, row in sorted(upstream.items())},
              "errors": sorted(set(errors))}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return result


def main():
    parser = argparse.ArgumentParser(description="가짜 ComfyUI 와 화면 서버 사본을 임시 폴더·포트에 띄운다(합성 데이터만).")
    parser.add_argument("--port", type=int, default=0, help="화면 서버 포트(기본: 빈 포트)")
    parser.add_argument("--comfy-port", type=int, default=0, help="가짜 ComfyUI 포트(기본: 빈 포트)")
    parser.add_argument("--pending", type=int, default=3, help="미리 넣어 둘 대기 작업 수")
    parser.add_argument("--history", type=int, default=6, help="미리 넣어 둘 완료 이력 수")
    parser.add_argument("--seconds", type=float, default=20, help="가짜 생성 한 건에 걸리는 시간(초)")
    parser.add_argument("--measure", type=float, default=0, help="이 시간(초) 동안 폴링을 흉내 내 부하를 재고 끝낸다")
    parser.add_argument("--tabs", type=int, default=1, help="측정: 열려 있는 화면 수")
    parser.add_argument("--tracked", type=int, default=20, help="측정: 화면마다 추적 중인 작업 수")
    parser.add_argument("--gallery", action="store_true", help="측정: 갤러리 진행률 조회도 포함")
    parser.add_argument("--batch", action="store_true", help="측정: 작업마다 묻는 대신 한 번에 묻는 조회(/api/status?ids=)를 쓴다")
    parser.add_argument("--source", default="", help="화면 서버 소스 폴더(기본: 이 저장소의 simple_ui). 이전 판과 비교할 때 쓴다")
    parser.add_argument("--old-comfy", action="store_true", help="작업 목록 API(/api/jobs)가 없는 예전 ComfyUI 를 흉내 낸다")
    args = parser.parse_args()
    if args.measure and args.seconds < 3600:
        args.seconds = 3600   # 측정 중에는 대기열이 줄지 않게
    home, fake, backend, process, address, comfy, pending = prepare(args)
    try:
        if args.measure:
            measure(args, process, address, comfy, pending)
        else:
            print(f"샌드박스 화면: {address}   (가짜 ComfyUI: {comfy})\n임시 폴더: {home}\nCtrl+C 로 끝내면 임시 폴더를 지웁니다.", flush=True)
            while process.poll() is None:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        fake.stop.set()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        backend.shutdown()
        shutil.rmtree(home.parent, ignore_errors=True)


if __name__ == "__main__":
    main()
