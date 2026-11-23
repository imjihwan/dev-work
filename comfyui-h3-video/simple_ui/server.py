"""MiniMax H3 간단 입력 화면 (기본 http://127.0.0.1:8190).

template_api.json = 원본 DaSiWa 워크플로를 ComfyUI 에서 한 번 실행한 API 프롬프트(노드 구조의 틀).
이 화면은 틀의 노드 구조는 그대로 두고 값만 바꿔서 ComfyUI(8188)에 넘긴다:
  사진·프롬프트·화면비·해상도·길이·시드 + 모드(REF2VA/FL2VA/I2VA)·모델 파일·스텝·샘플러·shift·LoRA(최대 10).

모델·LoRA 목록은 ComfyUI 가 보는 models 폴더 목록을 그대로 쓰고, 파일마다 '카드'(cards.json)에
자동 판정(파일 헤더)·Civitai 정보(해시 조회)·사용자 기본값을 모아 둔다. 조합은 presets.json.
"""
import base64, datetime, hashlib, html, io, json, math, os, queue, random, re, struct, threading, time
import urllib.error, urllib.parse, urllib.request, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import lru_cache

from PIL import Image, ImageOps
from prompt_helper import PromptHelper
from bulk_progress import BulkProgress
from queue_bulk import BuildCache, QueueBulkEditor
from production_chat import ProductionChat
from production_assistant import ProductionAssistant, READS as PRODUCTION_READS, WRITES as PRODUCTION_WRITES
from local_translate import LocalTranslator, TranslationBusy
from story import StoryProjects
from gallery import VideoGallery

BULK_PROGRESS = BulkProgress()

COMFY = "http://127.0.0.1:8188"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEMPLATE = os.path.join(HERE, "template_api.json")
INDEX = os.path.join(HERE, os.environ.get("SIMPLEUI_INDEX", "index.html"))
PORT = int(os.environ.get("SIMPLEUI_PORT", "8190"))
BACKEND_RESTART_HOLD = os.path.join(HERE, "backend-restart.tmp")

def backend_restart_hold(pid=None):
    """Hold status polling during an explicitly prepared backend restart."""
    try:
        with open(BACKEND_RESTART_HOLD, encoding="utf-8") as handle:
            held = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        # Fail closed for writes if the operator's marker cannot be read.
        return True if pid is None else {"state":"queued","pct":0,"label":"서버 복구 확인 중"}
    if pid is None:
        return True
    position = held.get("jobs", {}).get(pid)
    if position is not None:
        return {"state":"queued","position":position,"pct":0,"label":"서버 재시작 중 · 대기열 보존됨"}
    return None

PROMPT_HELPER = PromptHelper()
def prompt_helper_busy():
    with PROMPT_HELPER.lock:
        return bool(PROMPT_HELPER.job and PROMPT_HELPER.job.get("state") in ("starting", "generating", "enriching", "reviewing"))
TRANSLATOR = LocalTranslator(busy=prompt_helper_busy)
CARDS = os.path.join(HERE, "cards.json")
PRESETS = os.path.join(HERE, "presets.json")
OUTPUT = os.path.join(ROOT, "output")
GALLERY = VideoGallery(OUTPUT, os.path.join(HERE, "gallery_data"), thumbnailer=lambda name: input_thumbnail(name, 480))
MODELS = os.path.join(ROOT, "models")
DIRECTOR, SEED, SAVE = "2730", "2739", "2568"
LOADERS = ("1512:2586", "1512:2588")      # Director 의 fl2va_model / ref2va_model 입력(선택된 모드 쪽만 실제로 불러옴)
SCHED, SAMPLER, SHIFT, LORA = "1512:2590", "1512:2598", "1512:2692", "2678"
# '사진 1 첫 장면 고정' 틀 = 기본 틀 + 노드 2개(LoadImage → 네이티브 MiniMaxH3AddGuide frame 0), 연결 1곳 변경
GUIDE, GUIDER, VIDEO_VAE = "1512:2701", "1512:2592", "1512:2584"
ANCHOR_IMG, ANCHOR = "9001", "9002"
# 속도 노드: shift 노드와 미리보기 노드 사이에 끼운다(add_speed_nodes). 9003 은 결과가 같은 노드(기본), 9004·9005 는 고른 작업에만
PREVIEW, CHUNK_FF, SPARSE, STEP_CACHE = "2737", "9003", "9004", "9005"
# '속도 우선' 선택(요청의 speed). 결과 영상이 기본과 달라지는 가속이라 고른 작업에만 넣는다.
SPEED_MODES = {"sparse": ("BlockSparseAttention",), "sparse_cache": ("BlockSparseAttention", "MiniMaxH3Cache")}
LORA_SLOTS = 10
MULT = 32
# draft = 초안(약 0.4MP, 공식 문서의 빠른 시험용 권장). H3 최소 짧은 변 384 는 어떤 화면비든 넘음
RES_MP = {"draft": 0.4, "720p": 0.879, "1080p": 1.978}
UA = {"User-Agent": "Mozilla/5.0 (simple-ui model card)"}


# ---------- 진행률: ComfyUI 웹소켓 이벤트를 받아 prompt_id 별로 기록 ----------
CLIENT_ID = uuid.uuid4().hex
PROGRESS = {}          # prompt_id -> {"classes": {node: class}, "pct": float, "label": str}
PLOCK = threading.Lock()
STAGES = [  # (class_type 판별, 시작%, 끝%, 이름)
    (lambda c: c == "SamplerCustomAdvanced" or c.startswith("KSampler") and c != "KSamplerSelect", 15, 82, "영상 생성"),
    (lambda c: "Decode" in c, 82, 95, "디코딩"),
    (lambda c: "VideoCombine" in c or c in ("SaveVideo", "CreateVideo"), 95, 99, "파일 저장"),
    (lambda c: "Loader" in c, 2, 10, "모델 불러오기"),
]


def stage_of(cls):
    for test, lo, hi, name in STAGES:
        if test(cls or ""):
            return lo, hi, name
    return 10, 15, "사진·프롬프트 처리"


def _bump(pid, pct, label):
    st = PROGRESS.setdefault(pid, {"classes": {}, "pct": 0.0, "label": "대기"})
    st["pct"] = max(st["pct"], min(pct, 100.0))
    st["label"] = label


def _on_message(msg):
    t, d = msg.get("type"), msg.get("data") or {}
    pid = d.get("prompt_id")
    if not pid:
        return
    started=None
    with PLOCK:
        st = PROGRESS.get(pid)
        if st is None:
            if t!="execution_start":return
            st=PROGRESS.setdefault(pid,{"classes":{},"pct":0.0,"label":"대기"})
        if t == "execution_start":
            st["pct"] = 0.0
            stamp=d.get("timestamp")
            started=stamp/1000 if type(stamp) in (int,float) and math.isfinite(stamp) and stamp>=0 else time.time()
            st.update(generation_started_at=started,elapsed_estimated=False)
            st.pop("elapsed_only",None)
            _bump(pid, 1, "시작")
        elif t == "executing" and d.get("node"):
            lo, _, name = stage_of(st["classes"].get(d["node"]))
            _bump(pid, lo, name)
        elif t == "progress" and d.get("max"):
            lo, hi, name = stage_of(st["classes"].get(d.get("node")))
            frac = d["value"] / d["max"]
            _bump(pid, lo + (hi - lo) * frac, f"{name} {d['value']}/{d['max']}")
        elif t in ("execution_success",) or (t == "executing" and d.get("node") is None):
            _bump(pid, 100, "완료")
    if started is not None:
        # Never hold the progress and history locks together. Persist only timing.
        with HLOCK:
            for entry in HIST_DB:
                if entry["id"]==pid:
                    entry["generation_started_at"]=started
                    entry.pop("generation_finished_at",None);entry.pop("generation_seconds",None)
                    try:_save_json(HIST,HIST_DB)
                    except OSError:pass
                    break


def ws_loop(client_id):
    import asyncio, aiohttp

    async def run():
        while True:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"ws://127.0.0.1:8188/ws?clientId={urllib.parse.quote(client_id)}", heartbeat=30) as ws:
                        async for m in ws:
                            if m.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    _on_message(json.loads(m.data))
                                except Exception:  # noqa: BLE001
                                    pass
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(3)

    asyncio.run(run())


def snap(v):
    return max(MULT, round(v / MULT) * MULT)


def canvas(aspect, resolution, first_size):
    if aspect == "auto":
        a = first_size[0] / first_size[1] if first_size else 4 / 3
    else:
        w, h = map(float, aspect.split(":"))
        a = w / h
    if resolution in RES_MP:
        px = RES_MP[resolution] * 1024 * 1024
        h = (px / a) ** 0.5
        return snap(h * a), snap(h)
    short = 768
    return (snap(short * a), short) if a >= 1 else (short, snap(short / a))


def comfy(path, data=None, headers=None, timeout=60):
    req = urllib.request.Request(COMFY + path, data, headers or {})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    finally:
        if data is not None and path in ("/prompt", "/queue", "/interrupt"):
            # 이 서버가 대기열을 바꿨다(등록·삭제·중지): 공유 스냅샷을 버려 바로 다음 조회가 새로 받게 한다.
            # 지금 받는 중인 스냅샷(바꾸기 전 내용일 수 있다)이 뒤늦게 저장되지 않도록 세대 번호도 올린다.
            with QUEUE_EPOCH_LOCK:
                QUEUE_CACHE["value"] = None
                QUEUE_CACHE["epoch"] += 1


# ComfyUI 의 /queue 는 대기 작업의 그래프 전체를 싣는다(작업 하나에 수십 KB, 수백 건이면 수 MB).
# 화면은 작업마다 2초 간격으로 상태를 묻고 창·기기마다 따로 묻기 때문에, 조회마다 새로 받으면 초당 수 MB 를
# ComfyUI 가 직렬화하고 이 서버가 해석하게 된다(영상을 만드는 프로세스의 CPU 를 쓴다).
# 표시용 조회(상태·이력·갤러리 진행률)는 순번과 ID 만 있으면 되므로 그래프를 싣지 않는 /api/jobs 로 받고,
# 1초 안에서는 같은 스냅샷을 나눠 쓴다. 대기열을 고치는 경로는 지금처럼 그때그때 /queue 를 새로 받는다.
QUEUE_CACHE = {"at": 0.0, "value": None, "epoch": 0, "jobs_api_retry_at": 0.0, "failed_at": -1.0, "failure": None}
QUEUE_CACHE_LOCK = threading.Lock()    # 받아 오는 동안 쥔다: 동시에 온 조회는 한 번만 받아 나눠 쓴다
QUEUE_EPOCH_LOCK = threading.Lock()    # 짧게만 쥔다: 무효화와 '세대가 그대로면 저장'을 한 덩어리로


def _fetch_queue_ids():
    """대기열의 순번·ID 만 담은 스냅샷: {"queue_running": [[순번, ID]], "queue_pending": [[순번, ID], …]}."""
    if time.monotonic() >= QUEUE_CACHE["jobs_api_retry_at"]:
        try:
            with comfy("/api/jobs?status=in_progress,pending", timeout=20) as response:
                payload = json.load(response)
            jobs = payload["jobs"]
            # 모양이 다르거나 일부만 온 응답을 '빈 대기열'로 읽으면 대기 중인 작업이 사라진 것처럼 보인다
            if not isinstance(jobs, list) or (payload.get("pagination") or {}).get("has_more"):
                raise ValueError("unexpected job list")
            state = {"queue_running": [], "queue_pending": []}
            for job in jobs:
                if not isinstance(job["id"], str) or job["status"] not in ("in_progress", "pending"):
                    raise ValueError("unexpected job entry")
                state["queue_running" if job["status"] == "in_progress" else "queue_pending"].append([job.get("priority") or 0, job["id"]])
            return state
        except urllib.error.HTTPError as exc:
            # 없는 판(404·405)이면 오래, 그 밖의 오류면 잠깐 /queue 로 받는다
            QUEUE_CACHE["jobs_api_retry_at"] = time.monotonic() + (300 if exc.code in (404, 405) else 30)
        except (KeyError, TypeError, ValueError, AttributeError):       # 응답 모양이 다르다
            QUEUE_CACHE["jobs_api_retry_at"] = time.monotonic() + 300
    with comfy("/queue", timeout=20) as response:
        full = json.load(response)
    return {key: [[item[0], item[1]] for item in full.get(key, [])] for key in ("queue_running", "queue_pending")}


def queue_snapshot(max_age=1.0):
    """표시용 대기열 스냅샷(순번·ID 만). max_age 초 안의 것이 있으면 그대로 쓰고, 동시에 온 요청은 한 번만 받아 나눠 쓴다.

    돌려준 값은 여러 요청이 함께 보므로 읽기만 한다. 그래프가 필요한 곳(수정·일괄 적용)은 쓰지 않는다.
    받아 오기에 실패하면, 그 요청이 끝나기를 기다리던 조회들도 같은 실패를 바로 돌려받는다
    (ComfyUI 가 응답하지 않을 때 기다리던 조회가 차례로 다시 시간 초과를 기다리지 않게).
    """
    asked = time.monotonic()
    with QUEUE_CACHE_LOCK:
        value = QUEUE_CACHE["value"]
        if value is not None and time.monotonic() - QUEUE_CACHE["at"] <= max_age:
            return value
        if QUEUE_CACHE["failed_at"] >= asked:
            raise QUEUE_CACHE["failure"]
        epoch = QUEUE_CACHE["epoch"]
        try:
            value = _fetch_queue_ids()
        except Exception as exc:
            QUEUE_CACHE.update(failed_at=time.monotonic(), failure=exc)
            raise
        with QUEUE_EPOCH_LOCK:
            if QUEUE_CACHE["epoch"] == epoch:   # 받는 동안 이 서버가 대기열을 바꿨다면 저장하지 않는다
                QUEUE_CACHE.update(at=time.monotonic(), value=value)
        return value


def comfy_rejection(exc):
    """ComfyUI 가 HTTP 오류로 답한 이유를 한 줄로 만든다.

    ComfyUI 는 켜져 있는데 요청을 받아 주지 않은 경우(검증 실패 400 등)다. 연결 실패(URLError)와 달리
    '연결할 수 없습니다'로 알리면 사용자가 엉뚱하게 ComfyUI 실행 여부를 살피게 되므로, 응답 본문의 사유를 보여 준다.
    """
    def clip(value, limit=220):
        text = " ".join(str(value or "").split())
        return text if len(text) <= limit else text[:limit - 1] + "…"
    parts = []
    try:
        data = json.loads(exc.read(200000) or b"{}")
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            parts.append(": ".join(text for text in (clip(error.get("message")), clip(error.get("details"))) if text))
        elif isinstance(error, str):
            parts.append(clip(error))
        node_errors = data.get("node_errors") if isinstance(data, dict) else None
        for node_id, info in list(node_errors.items())[:3] if isinstance(node_errors, dict) else []:
            errors = info.get("errors") if isinstance(info, dict) else None
            for item in [x for x in errors if isinstance(x, dict)][:2] if isinstance(errors, list) else []:
                reason = ": ".join(text for text in (clip(item.get("message")), clip(item.get("details"))) if text)
                if reason:
                    parts.append(f"{clip(info.get('class_type') or node_id, 60)} — {reason}")
    except Exception:  # noqa: BLE001 — 본문이 없거나 예상한 모양이 아니면 상태 코드만 알린다
        parts = []
    finally:
        try:
            exc.close()
        except Exception:  # noqa: BLE001
            pass
    detail = " / ".join(part for part in parts if part)
    code = getattr(exc, "code", "?")
    return clip(f"ComfyUI 가 요청을 받지 않았습니다(HTTP {code})" + (f": {detail}" if detail else ". ComfyUI 창의 기록을 확인해 주세요."), 1200)


def queue_pause(body=None):
    """Proxy only the queue gate's booleans/counts; never fetch queued graphs."""
    if body is not None and (not isinstance(body,dict) or set(body)!={'paused'} or type(body['paused']) is not bool):
        raise ValueError('일시정지 상태를 확인해 주세요.')
    try:
        with comfy('/h3-video/queue-pause',None if body is None else json.dumps(body).encode(),{'Content-Type':'application/json'},timeout=5) as response:
            value=json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code==404:return {'supported':False,'state':'unsupported'}
        raise ValueError('일시정지 제어 요청에 실패했습니다. 상태를 다시 확인해 주세요.') from None
    except OSError:
        return {'supported':False,'state':'unavailable'}
    if not isinstance(value,dict) or value.get('supported') is not True or type(value.get('paused')) is not bool or value.get('state') not in ('running','finishing','paused'):
        raise ValueError('일시정지 상태를 확인하지 못했습니다.')
    if any(type(value.get(key)) is not int or value[key]<0 for key in ('running','pending')) or type(value.get('storage_error',False)) is not bool:
        raise ValueError('일시정지 상태 형식을 확인하지 못했습니다.')
    return {key:value[key] for key in ('supported','paused','state','running','pending','storage_error') if key in value}


@lru_cache(maxsize=256)
def input_thumbnail(name, size=192):
    with comfy("/view?" + urllib.parse.urlencode({"filename": name, "type": "input"})) as response:
        with Image.open(response) as source, ImageOps.exif_transpose(source) as image:
            image.thumbnail((size, size))
            with io.BytesIO() as output:
                image.save(output, format="WEBP", quality=75, method=1)
                return output.getvalue()


def upload(raw, ext):
    """사진을 ComfyUI input 폴더에 올린다. 이름은 내용에서 만든다: 같은 사진을 다시 올리면 ComfyUI 가 이미 있는 파일을
    그대로 쓰므로 복사본이 늘지 않고, 같은 사진·같은 문구를 다시 등록할 때 사진·문구 인코딩 결과를 다시 쓴다
    (이름이 매번 다르면 그래프가 달라져 텍스트 모델과 참조 인코딩을 처음부터 다시 돈다).
    드물게 다른 사진과 이름이 겹치면 ComfyUI 가 다른 이름을 돌려주므로, 그때만 예전처럼 임의 이름으로 올린다."""
    import hashlib
    stored = None
    for name in (f"simpleui_{hashlib.sha256(raw).hexdigest()[:10]}.{ext}", f"simpleui_{uuid.uuid4().hex[:10]}.{ext}"):
        bnd = uuid.uuid4().hex
        body = (f'--{bnd}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + raw + f"\r\n--{bnd}--\r\n".encode()
        stored = json.load(comfy("/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={bnd}"}))["name"]
        if stored == name:
            break
    return stored


def upright_photo(raw):
    """EXIF 방향이 걸린 사진(휴대폰으로 세워 찍은 사진 등)의 화소를 실제로 돌려 다시 만든다.
    DaSiWa Director 는 사진을 읽을 때 EXIF 방향을 무시해서, 그대로 올리면 눕거나 뒤집힌 사진이 참조·첫 장면으로 들어간다
    (캔버스는 세운 크기로 잡히므로 서로 어긋난다). 방향 표시가 없거나 정상이면 받은 바이트를 그대로 둔다(재압축 없음).
    반환: (올릴 바이트, 확장자, (가로, 세로))"""
    with Image.open(io.BytesIO(raw)) as im:
        ext = {"PNG": "png", "WEBP": "webp"}.get(im.format, "jpg")
        orientation = im.getexif().get(274)
        # ImageOps.exif_transpose 와 같은 표. 그 함수는 돌린 뒤 EXIF 를 다시 쓰는데, 읽히기만 하고 다시 쓸 수 없는 EXIF 가 든 사진에서
        # 예외가 난다. 여기서는 EXIF 를 버리므로 화소만 돌린다.
        turn = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
                5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
                8: Image.Transpose.ROTATE_90}.get(orientation if isinstance(orientation, int) else None)
        if turn is None:
            return raw, ext, im.size
        turned = im.transpose(turn)
        extra = {"icc_profile": im.info["icc_profile"]} if im.info.get("icc_profile") else {}
        out = io.BytesIO()
        # 휴대폰 사진은 Pillow 가 JPEG 이 아니라 MPO(보조 영상이 붙은 JPEG)로 읽는 경우가 많다. 둘 다 JPEG 으로 다시 만든다.
        if im.format in ("JPEG", "MPO") and turned.mode in ("RGB", "L"):
            turned.save(out, format="JPEG", quality=95, subsampling=0, **extra)     # 원본이 JPEG 이면 크기를 지키며 화질 손실을 최소로
        else:
            if turned.mode not in ("RGB", "RGBA", "L", "LA"):
                turned = turned.convert("RGB")
            turned.save(out, format="PNG", compress_level=3, **extra)
            ext = "png"
        return out.getvalue(), ext, turned.size


# =====================================================================
# 모델·LoRA 카드
# =====================================================================
CLOCK = threading.RLock()
DIRS = {"model": ("diffusion_models", "unet"), "lora": ("loras",)}


def _load_json(path, default, strict=False, owned=False):
    """상태 파일을 읽는다. 파일이 없으면 default.

    파일이 '있는데 못 읽은' 경우(잠깐 잠김·내용 깨짐)를 없음으로 취급하면 다음 저장이 사용자의 이력·저장 설정을
    통째로 덮어쓴다. 쓰임에 따라 셋으로 나눈다. 잠깐 잠긴 파일(Windows 백신·동기화 도구)은 어느 쪽이든 몇 번 다시 읽는다.
    - 읽기만 하는 곳(기본): 못 읽으면 default. 파일은 건드리지 않는다.
    - strict: 읽고-고쳐-쓰는 곳. 못 읽으면 ValueError — 기존 파일을 덮어쓰지 않고 실패를 알린다.
    - owned: 한 번 읽어 메모리에 두고 계속 다시 쓰는 저장소(이력·카드·화면 상태). 잠긴 파일은 ValueError,
      깨진 파일은 '<이름>.corrupt-<시각>.bak' 으로 옮겨 보관한 뒤 default 로 시작한다.
      파일을 옮기므로 부르는 쪽이 겹치지 않게 해야 한다(서버를 켤 때, 또는 그 저장소의 잠금 안에서).
    최상위 형식이 default 와 다르면(목록 자리에 객체 등) 깨진 것으로 본다.
    """
    import time
    name, problem = os.path.basename(path), None
    for attempt in range(4):
        try:
            # 메모장 등으로 고쳐 BOM 이 붙은 파일도 읽는다
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
            if default is not None and not isinstance(data, type(default)):
                raise ValueError("unexpected top-level type")
            return data
        except FileNotFoundError:
            return default
        except (ValueError, RecursionError) as exc:      # JSON·인코딩이 깨짐(지나치게 깊은 중첩 포함): 다시 읽어도 같다
            problem = ValueError(str(exc))
            break
        except OSError as exc:
            problem = exc
            time.sleep(0.05 * (attempt + 1))
    if owned and isinstance(problem, ValueError):
        backup = f"{path}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 10**9:09d}.bak"
        try:
            os.rename(path, backup)
        except OSError:
            raise ValueError(f"{name} 내용이 깨져 있고 보관용 사본도 만들지 못했습니다. 파일을 확인해 주세요.") from problem
        print(f"{name} 내용이 깨져 있어 {os.path.basename(backup)} 으로 보관하고 빈 상태로 시작합니다.", flush=True)
        return default
    if strict or owned:
        raise ValueError(f"{name} 을(를) 읽지 못했습니다. 기존 내용을 지키려고 중단했으니 잠시 뒤 다시 시도해 주세요.") from problem
    return default


def _save_json(path, obj):
    """임시 파일에 디스크까지 다 쓴 뒤 바꿔치기한다(중간에 꺼져도 예전 파일이나 새 파일 중 하나는 온전하다).

    Windows 에서는 백신·동기화 도구나 읽는 중인 다른 스레드·점검 스크립트가 대상 파일을 잠깐 잡고 있으면
    바꿔치기가 PermissionError 로 실패한다. 이미 대기열에 넣은 작업의 이력을 잃지 않도록 잠깐 다시 시도한다.
    임시 파일 이름은 프로세스·스레드마다 달라, 겹친 저장이 서로의 내용을 내보내지 않는다.
    """
    import threading
    import time
    tmp = f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(8):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        try:
            os.remove(tmp)   # 바꿔치기에 성공했으면 이미 없다
        except OSError:
            pass


SETTINGS = os.path.join(HERE, "saved-settings.json")
SETTINGS_LOCK = threading.Lock()

# 화면 상태 동기화: 사용자 한 명이 여러 창을 오가며 쓰므로 화면 칸·설정(form)과 사진(images)을
# 서버 한 곳에 두고 모든 창이 따라간다(마지막으로 고친 창이 기준). 부분마다 번호(rev)를 올려 바뀐 것만 내려준다.
UI_STATE = os.path.join(HERE, "ui-state.json")
UI_STATE_LOCK = threading.Lock()
UI_STATE_PARTS = ("form", "images")
_ui_state = None


def _ui_state_data():
    global _ui_state
    if _ui_state is None:
        data = _load_json(UI_STATE, {}, owned=True)
        _ui_state = data if isinstance(data, dict) else {}
    return _ui_state


def ui_state_get(have):
    """have = {부분: 창이 가진 rev}. rev 가 다른 부분만 내용을 싣는다(같으면 번호만)."""
    with UI_STATE_LOCK:
        data = _ui_state_data()
        out = {}
        for part in UI_STATE_PARTS:
            rev = data.get(part + "_rev", 0)
            out[part + "_rev"] = rev
            if have.get(part) != rev:
                out[part] = data.get(part)
        return out


def ui_state_save(body):
    part, value = body.get("part"), body.get("value")
    if part not in UI_STATE_PARTS:
        raise ValueError("저장할 화면 상태가 올바르지 않습니다.")
    if part == "form" and not (isinstance(value, dict) and isinstance(value.get("f"), dict)):
        raise ValueError("화면 칸 상태가 올바르지 않습니다.")
    if part == "images" and not (isinstance(value, list) and len(value) <= 9
                                 and all(isinstance(x, str) and x.startswith("data:image/") for x in value)):
        raise ValueError("사진 상태가 올바르지 않습니다.")
    base = body.get("base")
    with UI_STATE_LOCK:
        data = _ui_state_data()
        current = data.get(part + "_rev", 0)
        # 창이 마지막으로 본 번호(base)와 다르면 그 사이 다른 창이 고친 것 → 덮어쓰지 않고 최신 상태를 돌려준다
        if isinstance(base, int) and not isinstance(base, bool) and base != current:
            return {"conflict": True, "rev": current, "value": data.get(part)}
        data[part] = value
        data[part + "_rev"] = data.get(part + "_rev", 0) + 1
        _save_json(UI_STATE, data)
        return {"rev": data[part + "_rev"]}


def save_settings(name, data):
    name = str(name or "").strip()[:60]
    if not name or not isinstance(data, dict) or not isinstance(data.get("f"), dict) or not isinstance(data.get("model"), dict):
        raise ValueError("설정 이름과 저장할 입력값이 필요합니다.")
    photos = data.get("images", [])
    if not isinstance(photos, list) or any(not isinstance(photo, str) or not re.fullmatch(r"data:image/[\w.+-]+;base64,[A-Za-z0-9+/=\r\n]*", photo) for photo in photos):
        raise ValueError("저장할 사진 형식이 올바르지 않습니다.")
    with SETTINGS_LOCK:
        settings = _load_json(SETTINGS, {}, strict=True)
        settings[name] = {"data": data, "saved_at": time.time()}
        _save_json(SETTINGS, settings)
    return {"ok": True, "name": name}


def rename_settings(name, new_name):
    name = str(name or '').strip()
    new_name = str(new_name or '').strip()
    if not new_name or len(new_name) > 60:
        raise ValueError('새 설정 이름은 1~60자로 입력해 주세요.')
    with SETTINGS_LOCK:
        settings = _load_json(SETTINGS, {}, strict=True)
        if name not in settings:
            raise ValueError('저장된 설정을 찾지 못했습니다.')
        if name != new_name:
            if new_name in settings:
                raise ValueError('같은 이름의 설정 묶음이 있습니다. 다른 이름을 입력해 주세요.')
            settings[new_name] = settings.pop(name)
            _save_json(SETTINGS, settings)
    return {'ok': True, 'name': new_name}


def delete_settings(name):
    name = str(name or '').strip()
    with SETTINGS_LOCK:
        settings = _load_json(SETTINGS, {}, strict=True)
        if name not in settings:
            raise ValueError('저장된 설정을 찾지 못했습니다.')
        del settings[name]
        _save_json(SETTINGS, settings)
    return {'ok': True, 'name': name}


PRESET_LOCK = threading.Lock()


def save_preset(name, data):
    name = str(name or "").strip()[:60]
    if not name:
        raise ValueError("조합 이름을 적어 주세요.")
    with PRESET_LOCK:
        presets = _load_json(PRESETS, {}, strict=True)
        presets[name] = data or {}
        _save_json(PRESETS, presets)
        return presets


def delete_preset(name):
    with PRESET_LOCK:
        presets = _load_json(PRESETS, {}, strict=True)
        presets.pop(name, None)
        _save_json(PRESETS, presets)
        return presets


def _seed(path):
    """처음 설치한 PC: cards.json / presets.json 이 없으면 함께 배포한 *.seed.json 으로 시작."""
    seed = path.replace(".json", ".seed.json")
    if not os.path.exists(path) and os.path.exists(seed):
        _save_json(path, _load_json(seed, {}))


_seed(CARDS)
_seed(PRESETS)

# 2026-11-23 전에는 스케줄러가 shift 노드 앞 모델에 연결돼 화면 shift 가 영상에 반영되지 않았다(실제 영상 shift 는 H3 기본값 12).
# 그때 저장된 10/3 은 예전 일괄 기본값일 뿐 효과가 없던 값이므로, 모델·조합에서 지워 모델별 권장값을 따르게 한다.
LEGACY_SHIFT = {"shift_video": 10.0, "shift_audio": 3.0}


def drop_legacy_shift(values):
    """예전 기본값 shift 10/3 이 저장돼 있으면 지운다. 바뀌었으면 True."""
    if not isinstance(values, dict) or any(values.get(k) != v for k, v in LEGACY_SHIFT.items()):
        return False
    for k in LEGACY_SHIFT:
        values.pop(k, None)
    return True


def applied_shift(entry):
    """이력 항목이 실제로 쓴 shift. 수정 전 항목은 영상 shift 가 H3 기본값 12 로 돌았으므로 그 값을 돌려준다."""
    if entry.get("shift_applied"):
        return {"shift_video": entry.get("shift_video"), "shift_audio": entry.get("shift_audio")}
    return {"shift_video": 12.0, "shift_audio": entry.get("shift_audio", 3.0)}


def _migrate_legacy_presets():
    try:
        presets = _load_json(PRESETS, {}, strict=True)
    except ValueError:
        return   # 못 읽는 파일은 그대로 둔다(조합 저장 때 사유를 알린다)
    if isinstance(presets, dict) and [name for name, preset in presets.items() if drop_legacy_shift(preset)]:
        _save_json(PRESETS, presets)


_migrate_legacy_presets()

# ---------- 작업 이력: 생성할 때의 설정·프롬프트·사진 ↔ 결과 영상 (history.json, 이 PC 에만) ----------
HIST = os.path.join(HERE, "history.json")
HLOCK = threading.Lock()
HIST_DB = _load_json(HIST, [], owned=True)         # 오래된 것 → 최근 순
try:
    GALLERY.remember(HIST_DB)  # Persist links without decoding photos or result videos.
except OSError:
    pass
HIST_MAX = 1000
QUEUE_EDIT_LOCK = threading.Lock()
GALLERY_REGENERATE_LOCK = threading.Lock()
GALLERY_PROGRESS_LOCK = threading.Lock()
GALLERY_PROGRESS_CACHE = {"at": 0, "value": None}
RESTART_CLIENT_IDS = []
restart_state_path = os.environ.get("SIMPLEUI_RESTART_STATE")
if restart_state_path and os.path.isfile(restart_state_path):
    restart_state = _load_json(restart_state_path, {})
    CLIENT_ID = restart_state.get("client_id") or CLIENT_ID
    PROGRESS.update(restart_state.get("progress") or {})
    RESTART_CLIENT_IDS = restart_state.get("client_ids") or []
    os.remove(restart_state_path)


def hist_add(entries):
    with HLOCK:
        HIST_DB.extend(entries)
        del HIST_DB[:-HIST_MAX]
        _save_json(HIST, HIST_DB)


def delete_history(req):
    requested = req.get("ids") or []
    if not isinstance(requested, list) or not all(isinstance(pid, str) for pid in requested):
        raise ValueError("삭제할 작업을 선택해 주세요.")
    with QUEUE_EDIT_LOCK:
        with HLOCK:
            ids = list(dict.fromkeys(e["id"] for e in HIST_DB if req.get("all") or e["id"] in requested))
            links = [{**{key: e[key] for key in ("video", "images", "generation_seconds") if key in e},
                      "regenerated": bool(e.get("regenerated") or (e.get("ui") or {}).get("regeneration"))}
                     for e in HIST_DB if e["id"] in ids and e.get("video")]
        # Preserve the first-input association before removing its last history record.
        # No image/video decoding, and no prompts or generation settings are copied.
        if links:
            GALLERY.remember(links)
        if ids:
            state = json.load(comfy("/queue"))
            active = {item[1] for item in state["queue_running"] + state["queue_pending"]}
            cancel = [pid for pid in ids if pid in active]
            if cancel:
                headers = {"Content-Type": "application/json"}
                comfy("/queue", json.dumps({"delete": cancel}).encode(), headers)
                # 조회 뒤 대기→실행으로 넘어간 항목도 해당 ID로만 중지한다.
                for pid in cancel:
                    comfy("/interrupt", json.dumps({"prompt_id": pid}).encode(), headers)
        with HLOCK:
            removed = set(ids)
            HIST_DB[:] = [entry for entry in HIST_DB if entry["id"] not in removed]
            _save_json(HIST, HIST_DB)
            total = len(HIST_DB)
    return {"ok": True, "total": total, "ids": ids}


def hist_result(pid, st):
    """작업이 끝나면(완료·오류) 이력에 결과를 적는다. 상태가 바뀔 때만 파일에 쓴다."""
    if st.get("state") not in ("done", "error", "lost"):
        return
    changed = None
    with HLOCK:
        for e in HIST_DB:
            if e["id"] == pid:
                timing={key:st[key] for key in ("generation_started_at","generation_finished_at","generation_seconds") if key in st}
                update = e.get("state") != st["state"] or (st.get("video") and e.get("video") != st["video"]) or any(e.get(key)!=value for key,value in timing.items())
                if update:
                    e.update(state=st["state"], video=st.get("video") or e.get("video"), error=st.get("error"), t_end=time.time())
                    e.update(timing)
                    _save_json(HIST, HIST_DB)
                if e.get("video"):
                    changed = {key: e[key] for key in ("video", "images", "regenerated", "generation_seconds") if key in e}
                    changed["regenerated"] = bool(e.get("regenerated") or (e.get("ui") or {}).get("regeneration"))
                break
    if changed is not None:
        # 갤러리 연결은 이력 잠금을 푼 뒤에: 갤러리 잠금을 기다리는 동안 이력·상태 조회가 막히지 않게
        try:
            GALLERY.remember([changed])
        except OSError:
            pass  # A later gallery refresh can retry saving the association.
CARD_DB = _load_json(CARDS, {"model": {}, "lora": {}}, owned=True)
CARD_DB.setdefault("model", {})
CARD_DB.setdefault("lora", {})
if [name for name, card in CARD_DB["model"].items() if drop_legacy_shift(card.get("user"))]:
    _save_json(CARDS, CARD_DB)
FETCH = {}             # (kind, name) -> {"state", "msg", "pct"}  (메모리; 끝난 결과는 CARD_DB 에)
FETCH_Q = queue.Queue()


def object_options(cls, field):
    info = json.load(comfy(f"/object_info/{cls}"))[cls]["input"]
    spec = (info.get("required") or {}).get(field) or (info.get("optional") or {}).get(field)
    opts = spec[0]
    if isinstance(opts, str) and opts == "COMBO":   # 새 형식: ["COMBO", {"options": [...]}]
        opts = spec[1].get("options", [])
    return [o for o in opts if isinstance(o, str)]


def resolve(kind, name):
    rel = name.replace("\\", os.sep).replace("/", os.sep)
    for d in DIRS[kind]:
        base = os.path.realpath(os.path.join(MODELS, d))
        p = os.path.realpath(os.path.join(base, rel))
        if p.startswith(base + os.sep) and os.path.isfile(p):
            return p
    return None


def st_header(path):
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        if n > 100 * 1024 * 1024:
            raise ValueError("header too large")
        return json.loads(f.read(n))


_H3_MODS = None


def _norm_mod(k):
    k = re.sub(r"^(model\.diffusion_model\.|diffusion_model\.|transformer\.|lora_unet_|lycoris_)", "", k)
    k = re.sub(r"\.(lora_[AB]|lora_up|lora_down|lora\.up|lora\.down)\.weight$|\.(alpha|diff|diff_b|dora_scale|weight|bias)$", "", k)
    k = re.sub(r"(blocks[._])\d+", r"\1N", k)
    return re.sub(r"[._]", "", k)


def h3_modules():
    """H3 본체 모델 하나에서 모듈 이름 집합(블록 번호 무시)을 뽑아 LoRA 판정 기준으로 쓴다."""
    global _H3_MODS
    if _H3_MODS is None:
        mods = set()
        for d in DIRS["model"]:
            for dirpath, _, files in os.walk(os.path.join(MODELS, d)):
                for fn in files:
                    if fn.endswith(".safetensors"):
                        try:
                            h = st_header(os.path.join(dirpath, fn))
                        except Exception:  # noqa: BLE001
                            continue
                        if "audio_patch_proj.weight" in h:
                            mods = {_norm_mod(k) for k in h if k != "__metadata__"}
                            break
                if mods:
                    break
            if mods:
                break
        _H3_MODS = mods
    return _H3_MODS


def _fmt_of(low, h):
    for tag in ("nvfp4", "mxfp8", "w4a8", "w6a8", "w4a4", "int4", "int8", "fp8", "bf16", "fp16", "fp32"):
        if tag in low:
            return tag
    if low.endswith(".gguf"):
        return "gguf"
    dts = {v.get("dtype") for k, v in h.items() if k != "__metadata__" and isinstance(v, dict)}
    for dt, tag in (("I8", "int8"), ("F8_E4M3", "fp8"), ("BF16", "bf16"), ("F16", "fp16")):
        if dt in dts:
            return tag
    return "?"


def _steps_hint(low):
    m = re.search(r"(\d{1,2})\s*-?\s*(?:step|steps|turbo)", low)
    return int(m.group(1)) if m and 1 <= int(m.group(1)) <= 50 else None


def analyze(kind, name):
    """파일 헤더·이름으로 자동 판정. 실패해도 예외 대신 note 로 남긴다."""
    path = resolve(kind, name)
    low = os.path.basename(name).lower()
    a = {"size_gb": None, "h3": None, "modes": ["REF2VA", "FL2VA"], "fmt": "?", "turbo": False,
         "steps_hint": _steps_hint(low), "note": ""}
    if not path:
        a["note"] = "파일 위치를 찾지 못함"
        return a
    a["size_gb"] = round(os.path.getsize(path) / 1e9, 1)
    if low.endswith(".gguf"):
        a.update(fmt="gguf", h3=None, note="GGUF 는 이 화면에서 지원 안 함(불러오는 노드가 다름)")
        return a
    try:
        h = st_header(path)
    except Exception as e:  # noqa: BLE001
        a["note"] = f"헤더를 읽지 못함: {e}"
        return a
    meta = h.get("__metadata__") or {}
    a["fmt"] = _fmt_of(low, h)
    if "fl2v" in low and "ref2v" not in low:
        a["modes"] = ["FL2VA"]
    elif "ref2v" in low and "dasiwa" not in low:        # DaSiWa = REF2VA + FL2VA 혼합 모델
        a["modes"] = ["REF2VA"]
    if kind == "model":
        a["h3"] = "audio_patch_proj.weight" in h or meta.get("modelspec.architecture") == "minimax_h3"
        a["turbo"] = any(t in low for t in ("turbo", "distill", "lightspeed", "lightning"))
        if not a["h3"]:
            a["note"] = "MiniMax H3 본체 모델이 아님"
    else:
        keys = [k for k in h if k != "__metadata__"]
        ref = h3_modules()
        mods = {_norm_mod(k) for k in keys}
        hit = len(mods & ref) / max(1, len(mods)) if ref else 0
        base = " ".join(str(v) for v in meta.values())[:2000].lower()
        a["h3"] = hit >= 0.6 or "minimax-h3" in base or "minimax_h3" in base
        a["match"] = round(hit, 2)
        a["turbo"] = "turbo" in low or "distill" in low
        if not a["h3"]:
            a["note"] = "H3 용 LoRA 가 아님(구조 불일치)"
    return a


def _strip_html(s):
    s = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", s or "", flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def _suggest(text, kind):
    """설명문에서 권장값 후보만 뽑는다(확인 필요 표시용)."""
    t = text.lower()
    s = {}
    if kind == "lora":
        for m in re.finditer(r"(?:strength|weight|권장\s*강도|强度|权重)\s*(?:of|=|:|：)?\s*(\d(?:\.\d{1,2})?)", t):
            v = float(m.group(1))
            if 0.1 <= v <= 2.0:
                s["strength"] = v
                break
    m = re.search(r"(\d{1,2})\s*-?\s*steps?\s*[:：\-–]?\s*(?:\(?\s*)?(?:quality|best|recommended|품질|권장)", t)
    if m and 1 <= int(m.group(1)) <= 50:
        s["steps"] = int(m.group(1))
    return s


def civitai_get(path):
    req = urllib.request.Request("https://civitai.com/api/v1" + path, None, UA)
    return json.load(urllib.request.urlopen(req, timeout=40))


def fetch_worker():
    while True:
        kind, name = FETCH_Q.get()
        key = (kind, name)
        try:
            path = resolve(kind, name)
            if not path:
                raise FileNotFoundError("파일 위치를 찾지 못함")
            size = os.path.getsize(path)
            h, done = hashlib.sha256(), 0
            with open(path, "rb") as f:
                while chunk := f.read(16 << 20):
                    h.update(chunk)
                    done += len(chunk)
                    FETCH[key] = {"state": "hashing", "pct": round(done * 100 / max(1, size)), "msg": "파일 확인 중"}
            sha = h.hexdigest().upper()
            FETCH[key] = {"state": "querying", "pct": 100, "msg": "Civitai 조회 중"}
            try:
                v = civitai_get(f"/model-versions/by-hash/{sha}")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    with CLOCK:
                        CARD_DB[kind].setdefault(name, {})["civitai"] = {"found": False, "sha256": sha}
                        _save_json(CARDS, CARD_DB)
                    FETCH[key] = {"state": "done", "msg": "Civitai 에 없음(직접 값 입력)"}
                    continue
                raise
            desc = _strip_html(v.get("description") or "")
            mid = v.get("modelId")
            try:
                mdesc = _strip_html(civitai_get(f"/models/{mid}").get("description") or "") if mid else ""
            except Exception:  # noqa: BLE001
                mdesc = ""
            text = (desc + "\n\n" + mdesc).strip()
            info = {"found": True, "sha256": sha, "model_name": (v.get("model") or {}).get("name"),
                    "version_name": v.get("name"), "type": (v.get("model") or {}).get("type"),
                    "base_model": v.get("baseModel"), "trained_words": v.get("trainedWords") or [],
                    "url": f"https://civitai.com/models/{mid}?modelVersionId={v.get('id')}" if mid else "",
                    "description": text[:6000], "suggest": _suggest(text, kind)}
            with CLOCK:
                CARD_DB[kind].setdefault(name, {})["civitai"] = info
                _save_json(CARDS, CARD_DB)
            FETCH[key] = {"state": "done", "msg": "Civitai 정보 받음"}
        except Exception as e:  # noqa: BLE001
            FETCH[key] = {"state": "error", "msg": f"실패: {e}"}


def queue_fetch(kind, name):
    key = (kind, name)
    if FETCH.get(key, {}).get("state") in ("queued", "hashing", "querying"):
        return
    FETCH[key] = {"state": "queued", "msg": "대기 중"}
    FETCH_Q.put(key)


def effective(kind, card):
    """자동 판정 → Civitai 권장값 → 사용자 저장값 순으로 덮어쓴 기본값."""
    a = card.get("auto") or {}
    c = (card.get("civitai") or {}).get("suggest") or {}
    u = card.get("user") or {}
    if kind == "model":
        turbo = a.get("turbo")
        # DaSiWa 작성자 권장(C-MMH3-33 표): 일반 25스텝·res_multistep·shift 10~12/3~5(예시 11/4),
        # 터보 4~8스텝·euler·shift 6~8/4~5. 범위 가운데 값을 쓴다.
        e = {"steps": a.get("steps_hint") or (4 if turbo else 25),
             "sampler": "euler" if turbo else "res_multistep", "scheduler": "simple",
             "shift_video": 7.0 if turbo else 11.0, "shift_audio": 4.0}
        if c.get("steps"):
            e["steps"] = c["steps"]
    else:
        e = {"strength": c.get("strength", 1.0), "steps": a.get("steps_hint") if a.get("turbo") else None}
    e.update({k: v for k, v in u.items() if v is not None})
    # 예전에 기본값으로 저장해 둔 샘플러가 H3 에서 결과가 깨지는 계열이면 권장 샘플러로 되돌린다(자동 값이 거절되는 값을 가리키지 않게)
    if kind == "model" and str(e.get("sampler") or "").endswith("_cfg_pp"):
        e["sampler"] = "euler" if a.get("turbo") else "res_multistep"
    return e


def card_for(kind, name):
    with CLOCK:
        card = CARD_DB[kind].setdefault(name, {})
        path = resolve(kind, name)
        stamp = [os.path.getsize(path), int(os.path.getmtime(path))] if path else None
        if card.get("stamp") != stamp or "auto" not in card:
            card["auto"] = analyze(kind, name)
            card["stamp"] = stamp
            if stamp != card.get("civitai_stamp") and card.get("civitai"):
                card.pop("civitai", None)       # 파일이 바뀌면 Civitai 정보도 다시
            card["civitai_stamp"] = stamp
            _save_json(CARDS, CARD_DB)
        out = {"name": name, **card, "effective": effective(kind, card),
               "fetch": FETCH.get((kind, name), {"state": "idle"})}
        out.pop("stamp", None)
        out.pop("civitai_stamp", None)
        return out


def template_defaults():
    with open(TEMPLATE, encoding="utf-8-sig") as handle:
        p = json.load(handle)
    rows = json.loads(p[LORA]["inputs"]["stack_data"])
    return {"model": p[LOADERS[1]]["inputs"]["unet_name"], "steps": p[SCHED]["inputs"]["steps"],
            "scheduler": p[SCHED]["inputs"]["scheduler"], "sampler": p[SAMPLER]["inputs"]["sampler_name"],
            "shift_video": p[SHIFT]["inputs"]["shift_video"], "shift_audio": p[SHIFT]["inputs"]["shift_audio"],
            "loras": [{"name": r["lora"], "strength": r.get("str", 1)} for r in rows
                      if r.get("on") and r.get("lora") not in (None, "", "None")],
            "mode": p[DIRECTOR]["inputs"].get("mode", "REF2VA")}


def model_defaults():
    """새 작업의 기본값: 틀의 기본 모델 + 그 모델의 권장 스텝·샘플러·스케줄러·shift(모델 카드의 effective).
    틀에 적힌 값(예: shift 10/3)을 그대로 쓰면 일반 화면(모델별 권장값)과 이어 만들기 화면의 기본값이 서로 달라진다."""
    values = template_defaults()
    try:
        recommended = card_for("model", values["model"])["effective"]
    except (OSError, ValueError, KeyError):
        return values                       # 모델 파일을 못 읽으면 틀 값 그대로
    values.update({key: recommended[key] for key in ("steps", "sampler", "scheduler", "shift_video", "shift_audio") if recommended.get(key) is not None})
    return values


# H3 는 CFG 없이(BasicGuider, 조건 하나) 돈다. ComfyUI 의 샘플러·스케줄러 목록은 모든 모델 공용이라 H3 에 맞지 않는 것이 섞여 있다
# (근거: comfy/samplers.py · comfy/k_diffusion/sampling.py, 2026-11-23 확인).
def h3_sampler_broken(name):
    """*_cfg_pp 샘플러는 무조건부(네거티브) 예측으로 진행 방향을 만든다. H3 에는 그 예측이 없어 0 이 들어가고 결과 영상이 깨진다."""
    return isinstance(name, str) and name.endswith("_cfg_pp")


H3_SAMPLING_NOTES = {
    "samplers": {**{name: "스텝마다 모델을 2~3번 불러 그만큼 오래 걸립니다." for name in
                    ("heun", "heunpp2", "dpm_2", "dpm_2_ancestral", "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_sde_gpu", "seeds_2", "seeds_3",
                     "exp_heun_2_x0", "exp_heun_2_x0_sde", "sa_solver_pece")},
                 "dpm_adaptive": "스텝 수와 스케줄러·shift 를 따르지 않습니다.", "dpm_fast": "스케줄러와 shift 를 따르지 않습니다."},
    "schedulers": {**{name: "영상·소리 shift 를 따르지 않고 고노이즈 구간을 거의 건너뜁니다(구도·움직임이 무너질 수 있음)."
                      for name in ("karras", "exponential", "kl_optimal")},
                   "linear_quadratic": "영상·소리 shift 를 따르지 않습니다.",
                   "ddim_uniform": "첫 스텝이 완전한 노이즈에서 시작하지 않습니다."},
}


def catalog():
    models = object_options("UNETLoader", "unet_name")
    loras = object_options("LoraLoaderModelOnly", "lora_name")
    out = {"models": [card_for("model", n) for n in models], "loras": [card_for("lora", n) for n in loras],
           "samplers": [name for name in object_options("KSamplerSelect", "sampler_name") if not h3_sampler_broken(name)],
           "schedulers": object_options("BasicScheduler", "scheduler"),
           "sampling_notes": H3_SAMPLING_NOTES,
           "presets": _load_json(PRESETS, {}), "default": model_defaults(),
           "capabilities": {"queue_edit": True, "bulk_edit": True, "bulk_edit_all": True, "photo_sequence": True, "photo_reference_pool": True, "saved_settings": True, "restart_running": True, "priority_queue": True,
                            "speed_modes": speed_modes_available()}}
    # 작은 LoRA 는 처음 보면 Civitai 정보를 자동으로 가져온다(큰 본체 모델은 버튼으로)
    for c in out["loras"]:
        if "civitai" not in c and c["fetch"]["state"] == "idle" and (c["auto"].get("size_gb") or 99) < 4:
            queue_fetch("lora", c["name"])
            c["fetch"] = FETCH[("lora", c["name"])]
    return out


# =====================================================================
# 생성
# =====================================================================
def replace_queued_prompt(pid, prompt, expected_graph=None):
    with QUEUE_EDIT_LOCK:
        with HLOCK:
            if not any(e["id"] == pid for e in HIST_DB):
                raise ValueError("이 화면에서 만든 대기 항목만 수정할 수 있습니다.")
        queue_state = json.load(comfy("/queue"))
        if any(item[1] == pid for item in queue_state["queue_running"]):
            raise ValueError("이미 생성이 시작된 항목입니다. 실행 중인 작업은 수정할 수 없습니다.")
        old = next((item for item in queue_state["queue_pending"] if item[1] == pid), None)
        if old is None:
            raise ValueError("이미 생성이 시작됐거나 대기열에서 빠진 항목입니다. 새 작업으로 추가해 주세요.")
        if expected_graph is not None and old[2] != expected_graph:
            raise ValueError("조회 후 대기 작업이 수정됐습니다. 다시 조회해 주세요.")
        original = {"number": old[0], "prompt_id": pid, "prompt": old[2], "extra_data": old[3]}
        recovery_dir = os.path.join(HERE, "queue-edit-recovery")
        os.makedirs(recovery_dir, exist_ok=True)
        backup = os.path.join(recovery_dir, urllib.parse.quote(pid, safe="") + ".json")
        _save_json(backup, original)
        headers = {"Content-Type": "application/json"}
        comfy("/queue", json.dumps({"delete": [pid]}).encode(), headers)
        try:
            live = json.load(comfy("/queue"))
            started = any(item[1] == pid for item in live["queue_running"] + live["queue_pending"]) or json.load(comfy("/history/" + urllib.parse.quote(pid)))
        except (urllib.error.URLError, ValueError) as exc:
            raise ValueError("대기열 상태 확인에 실패했습니다. queue-edit-recovery 폴더에 원래 작업을 보관했습니다.") from exc
        if started:
            os.remove(backup)
            raise ValueError("수정하는 동안 생성이 시작됐습니다. 실행 중인 작업은 변경하지 않았습니다.")
        try:
            result = json.load(comfy("/prompt", json.dumps({"number": old[0], "prompt_id": pid,
                                    "prompt": prompt, "extra_data":old[3], "client_id": CLIENT_ID}).encode(), headers))
        except (urllib.error.URLError, ValueError) as exc:
            try:
                json.load(comfy("/prompt", json.dumps(original).encode(), headers))
            except (urllib.error.URLError, ValueError) as restore_error:
                raise ValueError("수정과 원본 복원에 실패했습니다. queue-edit-recovery 폴더에 원래 작업을 보관했습니다.") from restore_error
            os.remove(backup)
            raise ValueError("수정에 실패해 원래 대기 항목을 복원했습니다.") from exc
        # An acknowledgement alone does not prove the queued graph changed.
        # Inspect only this identity, including the fast-start/fast-finish races.
        try:
            observed = json.load(comfy("/queue"))
            item = next((row for row in observed["queue_running"] + observed["queue_pending"] if row[1] == pid), None)
            if item is None:
                item = (json.load(comfy("/history/" + urllib.parse.quote(pid))).get(pid) or {}).get("prompt")
            if result.get("prompt_id") != pid or item is None or item[2] != prompt:
                raise ValueError("ComfyUI 대기열의 수정 결과 대조에 실패했습니다. 원본 사본을 queue-edit-recovery 폴더에 보관했습니다.")
        except (urllib.error.URLError, OSError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("ComfyUI 반영 확인을 완료하지 못했습니다. 원본 사본을 queue-edit-recovery 폴더에 보관했습니다.") from exc
        os.remove(backup)
        result["prompt_verified"] = True
        return result


def restart_running_prompt(pid):
    with QUEUE_EDIT_LOCK:
        with HLOCK:
            entry = next((e for e in HIST_DB if e["id"] == pid), None)
            if entry is None:
                raise ValueError("이 화면에서 만든 작업만 재시작할 수 있습니다.")
            if entry.get("restarted_as"):
                return {"id": entry["restarted_as"], "replaces": pid, "seed": entry["seed"]}
            saved = json.loads(json.dumps(entry))
        state = json.load(comfy("/queue"))
        running = next((item for item in state["queue_running"] if item[1] == pid), None)
        if running is None:
            raise ValueError("현재 실행 중인 작업이 아닙니다. 대기열은 변경하지 않았습니다.")
        new_id = str(uuid.uuid4())
        number = min(item[0] for item in state["queue_running"] + state["queue_pending"]) - 1
        headers = {"Content-Type": "application/json"}
        # 재시작할 작업을 먼저 맨 앞에 넣어야 중지 직후 다른 대기 항목이 시작되지 않는다.
        result = json.load(comfy("/prompt", json.dumps({"number": number, "prompt_id": new_id,
            "prompt": running[2], "extra_data": running[3], "client_id": CLIENT_ID}).encode(), headers))
        if result.get("error") or not result.get("prompt_id"):
            raise ValueError("재시작 준비에 실패했습니다. 현재 작업은 중지하지 않았습니다.")
        saved.update(id=new_id, t=time.time(), state="queued", video=None, error=None, restarted_from=pid)
        for key in ("t_end", "edited_at", "restarted_as"):
            saved.pop(key, None)
        with HLOCK:
            entry["restarted_as"] = new_id
            HIST_DB.append(saved)
            del HIST_DB[:-HIST_MAX]
            _save_json(HIST, HIST_DB)
        with PLOCK:
            PROGRESS[new_id] = {"classes": {k: v["class_type"] for k, v in running[2].items()}, "pct": 0.0, "label": "재시작 대기"}
        warning = None
        try:
            comfy("/interrupt", json.dumps({"prompt_id": pid}).encode(), headers)
        except urllib.error.URLError:
            warning = "재시작 작업은 맨 앞에 준비됐지만 현재 작업 중지 요청을 확인하지 못했습니다."
        return {"id": new_id, "replaces": pid, "seed": saved["seed"], "warning": warning}


def gallery_regeneration_entry(pid):
    with HLOCK:
        entry = next((entry for entry in HIST_DB if entry["id"] == pid), None)
        if entry is None:
            raise ValueError("원래 작업 이력이 없어 재생성할 수 없습니다.")
        if entry.get("state") != "done" or not entry.get("video") or entry.get("mode") not in ("REF2VA", "I2VA", "FL2VA"):
            raise ValueError("완료된 개별 영상을 선택해 주세요.")
        if not entry.get("images") or not (entry.get("ui") or {}).get("f") or not entry.get("prompt"):
            raise ValueError("원래 사진 또는 작성 정보가 없어 재생성할 수 없습니다.")
        copied = json.loads(json.dumps(entry))
        copied.update(applied_shift(copied))
        return copied


def regenerate_gallery(req):
    target_id, source_id, request_id = (req.get(key) for key in ("target_id", "source_id", "request_id"))
    if (not all(isinstance(value, str) and value for value in (target_id, source_id, request_id))
            or not re.fullmatch(r"[A-Za-z0-9-]{12,80}", request_id)):
        raise ValueError("재생성할 영상과 설정을 가져올 영상을 선택해 주세요.")
    identity = {"target_id": target_id, "source_id": source_id, "request_id": request_id}
    with GALLERY_REGENERATE_LOCK:
        with HLOCK:
            previous = next((entry for entry in HIST_DB if (entry.get("ui") or {}).get("regeneration", {}).get("request_id") == request_id), None)
            if previous:
                if previous["ui"]["regeneration"] != identity:
                    raise ValueError("선택이 바뀌었습니다. 재생성을 다시 준비해 주세요.")
                return {"id": previous["id"], "already_queued": True}
        target = gallery_regeneration_entry(target_id)
        source = gallery_regeneration_entry(source_id)
        if source["mode"] != target["mode"]:
            raise ValueError("사진 참조 방식이 같은 영상에서 설정을 가져와 주세요.")
        if str(source.get("sampler") or "").endswith("_cfg_pp"):       # 사진을 다시 올리기 전에 알린다(이 대화상자에서는 샘플러를 바꿀 수 없다)
            raise ValueError("설정을 가져올 영상이 H3 에서 결과가 깨지는 샘플러로 만들어졌습니다. 다른 영상을 골라 주세요.")
        referenced = [int(value) for value in re.findall(r"<Picture\s*(\d+)>", source["prompt"], re.I)]
        if referenced and max(referenced) > len(target["images"]):
            raise ValueError("복사할 프롬프트가 대상에 없는 참조 사진 번호를 사용합니다. 다른 영상을 골라 주세요.")
        values = dict(target, count=1, edit_id=None, photo_sequence=False, prompt=source["prompt"])
        for key in ("model", "steps", "sampler", "scheduler", "shift_video", "shift_audio", "loras"):
            values[key] = source[key]
        values["speed"] = source.get("speed") or ""          # 속도 우선 옵션도 모델 설정의 일부로 가져온다(예전 이력에는 없다)
        ui = json.loads(json.dumps(target["ui"]))
        source_ui = source["ui"]
        for key in ("subject", "summary", "style", "keep", "sound", "music"):
            ui["f"][key] = source_ui["f"].get(key, "")
        for key in ("shots", "actionMode", "trig", "oneTake"):
            if key in source_ui:
                ui[key] = source_ui[key]
            else:
                ui.pop(key, None)
        for key in ("aspect", "resolution", "duration"):
            ui["f"][key] = target[key]
        ui.update(final=source["prompt"], regeneration=identity)
        values["ui"] = ui
        items, names = [], []
        for index, name in enumerate(target["images"]):
            if not isinstance(name, str) or not re.fullmatch(r"simpleui_[0-9a-f]{10}\.(jpg|png|webp)", name):
                raise ValueError("원래 참조 사진 정보를 확인할 수 없습니다.")
            with comfy("/view?" + urllib.parse.urlencode({"filename": name, "type": "input"})) as response:
                stored = response.read()
            # 예전에 올린 사진에 EXIF 방향이 남아 있으면(눕거나 뒤집혀 들어가던 사진) 세운 사본을 올려 그것으로 다시 만든다
            raw, ext, (width, height) = upright_photo(stored)
            if raw is not stored:
                name = upload(raw, ext)
            names.append(name)
            items.append({"id": f"image-{name.rsplit('.', 1)[0].rsplit('_', 1)[-1]}-{index}", "enabled": True, "order": index, "slot": index,
                          "start": index, "duration": 1, "type": "image", "value": name, "thumbnail": None,
                          "source_width": width, "source_height": height})
        target = dict(target, images=names)
        reference = {"entry": target, "prompt": {DIRECTOR: {"inputs": {"timeline_data": json.dumps({"items": items})}}}}
        return build_and_queue(values, reference=reference, queue_first=True)


def queue_prompt_first(prompt, slots=1, number=None):
    """Add a new job before pending work without changing or interrupting any job."""
    with QUEUE_EDIT_LOCK:
        if number is None:
            state = json.load(comfy("/queue"))
            # Reserve consecutive priorities so repeats retain their seed/order.
            number = min([0] + [item[0] for item in state["queue_running"] + state["queue_pending"]]) - slots
        result = json.load(comfy("/prompt", json.dumps({"number": number, "prompt": prompt, "client_id": CLIENT_ID}).encode(),
                                {"Content-Type": "application/json"}))
        result["number"] = number
        return result


def judge_face_side(raw):
    """사진 1(바이트)의 얼굴이 화면 어느 쪽을 보는지 잰다. 프롬프트에 넣을 방향(used)은 left/right 뿐이고,
    정면·얼굴 못 찾음·검출기 없음은 화면 오른쪽으로 둔다(지금까지의 기본값)."""
    from face_references import ensure_available, face_direction, MODEL_NAME
    path = os.path.join(ROOT, 'models', 'face_detection', MODEL_NAME)
    try:
        ensure_available(path)
        found = face_direction(raw, path)
    except (ValueError, OSError):
        return {"side": "unavailable", "offset": None, "used": "right"}
    if found is None:
        return {"side": "none", "offset": None, "used": "right"}
    return {"side": found["side"], "offset": found["offset"], "used": found["side"] if found["side"] in ("left", "right") else "right"}


def input_bytes(name):
    with comfy("/view?" + urllib.parse.urlencode({"filename": name, "type": "input"})) as response:
        return response.read()


PHOTO_REFERENCES = {}
PHOTO_REFERENCE_LOCK = threading.Lock()


def prepare_photo_reference(req):
    image=req.get("image");group=req.get("group")
    if not isinstance(image,str) or not image.startswith("data:image/") or not isinstance(group,str) or not 1<=len(group)<=120:
        raise ValueError("준비할 사진과 폴더 정보를 확인해 주세요.")
    try:
        # EXIF 방향이 걸린 사진은 화소를 세워서 올린다(build_and_queue 와 같은 규칙)
        raw,ext,(width,height)=upright_photo(base64.b64decode(image.split(",",1)[1],validate=True))
    except (ValueError,IndexError,OSError):raise ValueError("사진을 읽지 못했습니다.") from None
    name=upload(raw,ext);original={"value":name,"source_width":width,"source_height":height}
    auxiliary=dict(original);unavailable=False
    if req.get("face_boost") is True:
        from face_references import ensure_available,crop_reference,MODEL_NAME
        try:
            detector=os.path.join(ROOT,'models','face_detection',MODEL_NAME);ensure_available(detector)
            cropped=crop_reference(raw,detector)
            if cropped:
                crop_raw,crop_size=cropped
                auxiliary={"value":upload(crop_raw,'png'),"source_width":crop_size[0],"source_height":crop_size[1]}
        except (ValueError,OSError):unavailable=True
    identity=uuid.uuid4().hex;now=time.time()
    with PHOTO_REFERENCE_LOCK:
        for key in list(PHOTO_REFERENCES):
            if now-PHOTO_REFERENCES[key]["created"]>3600:del PHOTO_REFERENCES[key]
        PHOTO_REFERENCES[identity]={"created":now,"group":group,"original":original,"auxiliary":auxiliary}
    return {"id":identity,"cropped":original["value"]!=auxiliary["value"],"face_unavailable":unavailable}


def pooled_photo_reference(req):
    ids=req.get("reference_ids")
    if not isinstance(ids,list) or not 1<=len(ids)<=9 or any(not isinstance(key,str) for key in ids) or len(set(ids))!=len(ids):
        raise ValueError("한 작업의 사진 참조는 서로 다른 1~9장이어야 합니다.")
    with PHOTO_REFERENCE_LOCK:
        records=[PHOTO_REFERENCES.get(key) for key in ids]
        if any(record is None or time.time()-record["created"]>3600 for record in records):
            raise ValueError("사진 준비 정보가 만료됐습니다. 남은 사진을 다시 등록해 주세요.")
        if len({record["group"] for record in records})!=1:raise ValueError("서로 다른 폴더의 사진은 한 작업에 섞을 수 없습니다.")
        selected=[dict(record["original"] if index==0 else record["auxiliary"]) for index,record in enumerate(records)]
    items=[dict(item,id=f'pool-image-{index}',enabled=True,order=index,slot=index,start=index,duration=1,type='image',thumbnail=None) for index,item in enumerate(selected)]
    return {"entry":{"images":[item["value"] for item in items],"sequence_index":req.get("reference_sequence_index")},
            "prompt":{DIRECTOR:{"inputs":{"timeline_data":json.dumps({"items":items})}}}}


def release_photo_references(req):
    ids=req.get("ids")
    if not isinstance(ids,list) or any(not isinstance(key,str) for key in ids):raise ValueError("사진 준비 정보를 확인해 주세요.")
    with PHOTO_REFERENCE_LOCK:
        for key in ids:PHOTO_REFERENCES.pop(key,None)
    # Queued graphs use the uploaded files, so only release temporary metadata.
    return {"ok":True}


def person_canvas(aspect,resolution,sizes,items,raws,index,reference,cache=None,mode="REF2VA"):
    target=canvas(aspect,resolution,sizes[index])
    if aspect=="auto":return target,"auto",False
    from person_framing import detect_bounds,crop_contains,MODEL_NAME
    selected=[0,1] if mode=="FL2VA" else [index]
    for n in selected:
        item=items[n]
        if "person_bounds" not in item:
            try:
                def detect():
                    raw=raws[n] if raws else input_bytes(item["value"])
                    return detect_bounds(raw,os.path.join(ROOT,"models","person_detection",MODEL_NAME))
                item["person_bounds"]=cache.get(("person",item["value"]),detect) if cache is not None else detect()
            except Exception:item["person_bounds"]=None  # Detection failure means no forced crop.
    if all(crop_contains(sizes[n],target,items[n]["person_bounds"]) for n in selected):
        return target,aspect,False
    original=canvas("auto",resolution,sizes[index])
    # Grid rounding can still crop a tight edge. Look only near the original
    # canvas, without raising its pixel budget, and validate all endpoint people.
    def safe(size):
        for n in selected:
            bounds=items[n]["person_bounds"]
            if bounds is None:
                # Unknown people require the original aspect (within grid rounding).
                if abs((size[0]/size[1])/(sizes[n][0]/sizes[n][1])-1)>.025:return False
            elif not crop_contains(sizes[n],size,bounds):return False
        return True
    if safe(original):return original,"auto",True
    candidates=[(w,h) for w in range(max(MULT,original[0]-2*MULT),original[0]+2*MULT+1,MULT)
                for h in range(max(MULT,original[1]-2*MULT),original[1]+2*MULT+1,MULT)
                if w*h<=original[0]*original[1] and abs((w/h)/(sizes[index][0]/sizes[index][1])-1)<=.025 and safe((w,h))]
    # A rounded 3:4 canvas can miss the nearest exact 3:4 grid by more than
    # two cells. Also try the largest exact original ratio within the budget.
    from math import gcd,isqrt
    sw,sh=sizes[index];divisor=gcd(sw,sh);uw,uh=sw//divisor,sh//divisor
    scale=isqrt(original[0]*original[1]//(uw*uh*MULT*MULT))
    if scale:
        exact=(uw*scale*MULT,uh*scale*MULT)
        if safe(exact):candidates.append(exact)
    if candidates:
        chosen=min(candidates,key=lambda size:(abs((size[0]/size[1])/(sizes[index][0]/sizes[index][1])-1),-(size[0]*size[1])))
        return chosen,"auto",True
    raise ValueError("이 사진 조합은 원본 비율에서도 인물이 잘릴 수 있어 등록하지 않았습니다. 첫·끝 사진을 같은 비율로 맞춰 주세요.")


def build_and_queue(req, reference=None, prepare_only=False, queue_first=False, build_cache=None):
    if "reference_ids" in req:
        if reference or req.get("edit_id") or req.get("photo_sequence") or int(req.get("count") or 1)!=1:
            raise ValueError("폴더별 번갈아 등록은 한 번에 한 작업씩 새로 추가합니다.")
        reference=pooled_photo_reference(req)
    protect_person=req.get("protect_person",False)
    if type(protect_person) is not bool:raise ValueError("인물 보호 설정을 확인해 주세요.")
    edit_id = req.get("edit_id")
    sequence = req.get("photo_sequence") is True
    if queue_first and (edit_id or sequence or prepare_only):
        raise ValueError("1순위 우선추가는 새 작업 등록에서만 사용할 수 있습니다.")
    if sequence and (edit_id or req.get("mode", "REF2VA") != "REF2VA"):
        raise ValueError("사진 순차 추가는 참조 사진 방식의 새 작업에서 사용할 수 있습니다.")
    if edit_id and int(req.get("count") or 1) != 1:
        raise ValueError("대기 항목 수정은 한 번에 1개만 가능합니다.")
    text = (req.get("prompt") or "").strip()
    if not text:
        raise ValueError("프롬프트가 비어 있습니다.")
    mode = req.get("mode") or "REF2VA"
    imgs = reference["entry"]["images"] if reference else req.get("images") or []
    need = {"REF2VA": (1, 9), "FL2VA": (2, 2), "I2VA": (1, 1)}.get(mode)
    if not need:
        raise ValueError(f"지원하지 않는 모드: {mode}")
    if not need[0] <= len(imgs) <= need[1]:
        raise ValueError({"REF2VA": "사진은 1~9장 넣어 주세요.", "FL2VA": "첫·끝 프레임 사진 2장이 필요합니다.",
                          "I2VA": "첫 프레임 사진 1장이 필요합니다."}[mode])
    duration = float(req.get("duration") or 5)
    if not 1 <= duration <= 15:
        raise ValueError("길이는 1~15초 사이로 정해 주세요(H3 최대 15초).")
    # 반복: 같은 구성으로 시드만 바꿔 count 개를 대기열에 넣는다.
    # 시드를 적었으면 그 값부터 1씩 늘리고(재현 가능), 비웠으면 매번 랜덤.
    # 사진을 올리기 전에 확인한다(잘못된 값 때문에 쓰지 않을 사진이 input 폴더에 남지 않게).
    try:
        count = len(imgs) if sequence else int(req.get("count") or 1)
    except (TypeError, ValueError, OverflowError):
        count = 0
    if not 1 <= count <= 20:
        raise ValueError("반복 횟수는 1~20 사이로 정해 주세요.")
    seed = str(req.get("seed") or "").strip()
    if seed:
        try:
            first_seed = int(seed)
        except ValueError:
            raise ValueError("시드는 숫자로 적어 주세요(비우면 랜덤).") from None
        # 0 은 SeedControl 이 스스로 랜덤을 뽑는 값이라 이력에 적힌 시드로 재현되지 않는다. 범위는 노드의 64비트 한도.
        if first_seed < 1 or first_seed + count - 1 > 2**64 - 1:
            raise ValueError("시드는 1 이상의 정수로 적어 주세요(비우면 랜덤).")
        seeds = [first_seed + i for i in range(count)]
    else:
        seeds = [random.randint(1, 2**53) for _ in range(count)]

    def read_template():
        with open(TEMPLATE, encoding="utf-8-sig") as handle:
            return json.load(handle)
    cached = build_cache.get if build_cache is not None else lambda key,read:read()
    p = cached(("template",TEMPLATE),read_template)

    # --- 모델·샘플링·LoRA (값만 바꿈) ---
    models = cached(("options","models"),lambda:set(object_options("UNETLoader", "unet_name")))
    model = req.get("model") or p[LOADERS[1]]["inputs"]["unet_name"]
    if model not in models:
        raise ValueError(f"모델 파일이 목록에 없습니다: {model}")
    mc = cached(("model",model),lambda:card_for("model", model))
    if mc["auto"].get("h3") is False or mc["auto"].get("fmt") == "gguf":
        raise ValueError(f"이 화면에서 쓸 수 없는 모델입니다: {mc['auto'].get('note')}")
    for k in LOADERS:
        p[k]["inputs"]["unet_name"] = model
    # 요청에 없는 샘플링 값은 틀 값이 아니라 고른 모델의 권장값으로 채운다. 틀 값은 틀을 뽑을 때의 한 모델(터보) 기준이라,
    # 다른 모델을 값 없이 요청하면 터보 8스텝·shift 10/3 으로 도는 일이 있었다. 권장값을 모르면 틀 값이 남는다.
    auto = mc.get("effective") or {}
    steps = int(req.get("steps") or auto.get("steps") or p[SCHED]["inputs"]["steps"])
    if not 1 <= steps <= 60:
        raise ValueError("스텝은 1~60 사이로 정해 주세요.")
    p[SCHED]["inputs"]["steps"] = steps
    if req.get("scheduler") or auto.get("scheduler"):
        p[SCHED]["inputs"]["scheduler"] = req.get("scheduler") or auto["scheduler"]
    if req.get("sampler"):
        if str(req["sampler"]).endswith("_cfg_pp"):      # h3_sampler_broken 과 같은 규칙(저장된 설정·이력에서 올 수 있다)
            raise ValueError(f"샘플러 {req['sampler']} 는 CFG 가 없는 H3 에서 결과 영상이 깨집니다. euler 같은 다른 샘플러를 골라 주세요.")
        p[SAMPLER]["inputs"]["sampler_name"] = req["sampler"]
    elif auto.get("sampler"):
        p[SAMPLER]["inputs"]["sampler_name"] = auto["sampler"]
    for k in ("shift_video", "shift_audio"):
        value = req.get(k) if req.get(k) not in (None, "") else auto.get(k)
        if value not in (None, ""):
            p[SHIFT]["inputs"][k] = float(value)
    # 스케줄러가 shift 노드 뒤 모델을 받아야 Shift Video 가 영상 sigma 스케줄에 반영된다
    # (shift 앞 모델이면 H3 기본값 12 로 고정되고 화면 값은 오디오 환산에만 쓰여 어긋난다).
    p[SCHED]["inputs"]["model"] = [SHIFT, 0]
    # 속도 노드: 결과가 같은 청크 피드포워드는 항상, 결과가 달라지는 가속은 요청의 speed 로 고른 작업에만.
    # 이 함수만 떼어 쓰는 곳(시험 등)에서는 add_speed_nodes 가 없을 수 있다.
    speed_mode = req.get("speed") or ""
    if not isinstance(speed_mode, str) or speed_mode not in ("", "sparse", "sparse_cache"):
        raise ValueError("속도 우선 옵션을 확인해 주세요.")
    speed = globals().get("add_speed_nodes")
    if speed:
        speed(p, lambda cls: cached(("node", cls), lambda: node_available(cls)), speed_mode)
    elif speed_mode:
        raise ValueError("이 서버는 '속도 우선' 옵션을 지원하지 않습니다.")
    loras = [x for x in (req.get("loras") or []) if x.get("name")]
    if len(loras) > LORA_SLOTS:
        raise ValueError(f"LoRA 는 최대 {LORA_SLOTS}개까지입니다.")
    known = cached(("options","loras"),lambda:set(object_options("LoraLoaderModelOnly", "lora_name")))
    rows = []
    for x in loras:
        if x["name"] not in known:
            raise ValueError(f"LoRA 파일이 목록에 없습니다: {x['name']}")
        if cached(("lora",x["name"]),lambda:card_for("lora", x["name"]))["auto"].get("h3") is False:
            raise ValueError(f"H3 용이 아닌 LoRA 입니다: {x['name']}")
        rows.append({"on": True, "lora": x["name"], "str": float(x.get("strength", 1)), "vs": 1, "as": 1})
    rows += [{"on": True, "lora": "None", "str": 1, "vs": 1, "as": 1}] * (LORA_SLOTS - len(rows))
    p[LORA]["inputs"]["stack_data"] = json.dumps(rows)

    # --- 사진·프롬프트 ---
    items, sizes, names, raws = [], [], [], []
    face_items, face_cropped, face_unavailable = [], 0, None
    # 얼굴인식강화(선택): 참조 방식에서 사진 2장 이상일 때만, 사진 2부터 얼굴 주변을 잘라 보조 참조로 쓴다.
    # 첫·끝 장면 방식의 사진은 실제 프레임이라 자르지 않는다. 대기항목 수정은 원래 사진을 그대로 쓴다.
    face_mode = req.get("face_boost") is True and mode == "REF2VA" and len(imgs) > 1 and not reference
    if face_mode:
        from face_references import ensure_available, crop_reference, MODEL_NAME
        face_model_path = os.path.join(ROOT, 'models', 'face_detection', MODEL_NAME)
        try:
            ensure_available(face_model_path)
        except ValueError as exc:
            # 검출 모델·OpenCV 가 없으면 등록 전체를 막지 않고 원본 사진으로 진행한다(화면에 이유 표시)
            face_mode, face_unavailable = False, str(exc)
    if reference:
        previous = json.loads(reference["prompt"][DIRECTOR]["inputs"]["timeline_data"])["items"]
        for i, name in enumerate(imgs):
            item = next((item for item in previous if item.get("value") == name), None)
            if item is None:
                raise ValueError("원래 사진 정보를 찾지 못해 이 항목은 수정하지 않았습니다.")
            items.append(dict(item, slot=i, order=i, start=i))
            names.append(name)
            sizes.append((item["source_width"], item["source_height"]))
    for i, data_url in enumerate([] if reference else imgs):
        head, b64 = data_url.split(",", 1)
        # EXIF 방향이 걸린 사진은 화소를 세워서 올린다(Director 는 EXIF 방향을 무시한다). 그 밖의 사진은 받은 그대로.
        raw, ext, display_size = upright_photo(base64.b64decode(b64))
        raws.append(raw)
        sizes.append(display_size)
        names.append(upload(raw, ext))
        # REF2VA: slot = 사진 번호 / FL2VA: slot 0 = 첫 프레임, 1 = 끝 프레임 / I2VA: slot 0
        # id 는 사진 이름에서 만든다(임의 값이면 같은 사진·같은 문구의 재등록도 그래프가 달라져 인코딩을 다시 돈다)
        items.append({"id": f"image-{names[-1].rsplit('.', 1)[0].rsplit('_', 1)[-1]}-{i}", "enabled": True, "order": i, "slot": i,
                      "start": i, "duration": 1, "type": "image", "value": names[-1], "thumbnail": None,
                      "source_width": display_size[0], "source_height": display_size[1]})
        if face_mode and not sequence and i == 0:
            face_items.append(items[-1])  # 일반 생성의 사진 1은 원본(순차 추가는 사진마다 사진 1이 될 수 있어 모두 준비)
        elif face_mode:
            cropped = crop_reference(raw, face_model_path)
            if cropped is None:
                face_items.append(items[-1])
            else:
                crop_raw, crop_size = cropped
                face_items.append(dict(items[-1], value=upload(crop_raw, 'png'),
                                       source_width=crop_size[0], source_height=crop_size[1]))
                face_cropped += 1

    aspect = req.get("aspect") or "auto"
    resolution = req.get("resolution") or "auto"
    w, h = canvas(aspect, resolution, sizes[0])

    d = p[DIRECTOR]["inputs"]
    if face_mode and not sequence:
        items = [items[0]] + face_items[1:]
        names = [item["value"] for item in items]
    tl = json.loads(d["timeline_data"])
    tl["items"] = items
    tl["builder_state"]["duration"] = duration
    tl["builder_state"]["mode"] = mode
    tl["resolution"].update(aspect=aspect, resolution=resolution if resolution in RES_MP else "auto",
                            input_scaling="Auto" if mode=="REF2VA" else "Fill and crop")
    bs = json.loads(d["builder_state"])
    bs.update(duration=duration, mode=mode)

    def set_prompt(job_text):
        tl["builder_state"]["simple_prompt"] = job_text
        tl["resolved_prompt"] = job_text
        tl["continuity"]["continuation_prompt"] = job_text
        bs.update(simple_prompt=job_text)
        d.update(prompt=job_text, timeline_data=json.dumps(tl, ensure_ascii=False), builder_state=json.dumps(bs, ensure_ascii=False))

    FACE_SIDE_TOKEN = "{{face_side}}"
    # 얼굴 방향: 프롬프트에 {{face_side}} 가 있으면 사진 1을 재서 left/right 로 바꾼다(모델에게 판단시키지 않음)
    side_cache = {}
    def face_side_for(index):
        if FACE_SIDE_TOKEN not in text:
            return (reference["entry"].get("face_side") or None) if reference else None
        key = (names[index] if sequence else names[0])
        if key not in side_cache:
            saved_side = (reference["entry"].get("face_side") or {}) if reference else {}
            if saved_side.get("used") in ("left","right"):
                side_cache[key] = dict(saved_side)
                return side_cache[key]
            if reference:
                try:
                    picture = input_bytes(imgs[0])
                except (urllib.error.URLError, OSError):
                    picture = None
            else:
                picture = raws[index] if sequence else raws[0]
            side_cache[key] = judge_face_side(picture) if picture else {"side": "unavailable", "offset": None, "used": "right"}
        return side_cache[key]

    d.update(mode=mode, width=w, height=h, duration=duration)
    set_prompt(text.replace(FACE_SIDE_TOKEN, (face_side_for(0) or {}).get("used", "right")))
    anchor = bool(req.get("anchor")) and mode == "REF2VA"
    if anchor:
        add_anchor(p, names[0])
    classes = {k: v["class_type"] for k, v in p.items()}
    jobs = []
    def make_entries(done):
        now = time.time()
        return [{"id": j["id"], "t": now, "seed": j["seed"], "state": "queued", "video": None, "error": None,
               "mode": mode, "model": model, "steps": steps,
               "sampler": p[SAMPLER]["inputs"]["sampler_name"], "scheduler": p[SCHED]["inputs"]["scheduler"],
               "shift_video": p[SHIFT]["inputs"]["shift_video"], "shift_audio": p[SHIFT]["inputs"]["shift_audio"], "shift_applied": True,
               "speed": speed_mode,
               "loras": [{"name": x["name"], "strength": float(x.get("strength", 1))} for x in loras],
               "aspect": j.get("actual_aspect",aspect), "requested_aspect":aspect,"protect_person":protect_person,"framing_fallback":j.get("framing_fallback",False), "resolution": resolution, "duration": duration, "width": j["width"], "height": j["height"],
               "count": count, "anchor": anchor, "prompt": text, "images": j["images"], "face_side": j.get("face_side"),
               "sequence_index": j["sequence_index"], "ui": req.get("ui")} for j in done]
    priority_number = None
    try:
        for index, s in enumerate(seeds):
            job_names = names[index:] + names[:index] if sequence else names
            job_w, job_h = canvas(aspect, resolution, sizes[index] if sequence else sizes[0])
            actual_aspect,fallback=aspect,False
            if protect_person:
                (job_w,job_h),actual_aspect,fallback=person_canvas(aspect,resolution,sizes,items,raws,index if sequence else 0,reference,build_cache,mode)
            d.update(width=job_w,height=job_h)
            tl["resolution"]["aspect"]=actual_aspect
            # Bounds are metadata on original files, not replacement/cropped photos.
            if not sequence:tl["items"]=items
            set_prompt(text.replace(FACE_SIDE_TOKEN,(face_side_for(index if sequence else 0) or {}).get("used","right")))
            if sequence:
                order = list(range(index, len(items))) + list(range(index))
                rotated = [items[index]] + [(face_items[i] if face_mode else items[i]) for i in order[1:]]
                job_names = [item['value'] for item in rotated]
                tl["items"] = [dict(item, slot=i, order=i, start=i) for i, item in enumerate(rotated)]
                d.update(width=job_w, height=job_h)
                set_prompt(text.replace(FACE_SIDE_TOKEN, (face_side_for(index) or {}).get("used", "right")))
                if anchor:
                    p[ANCHOR_IMG]["inputs"]["image"] = job_names[0]
            p[SEED]["inputs"]["seed_value"] = s
            if prepare_only:
                if count != 1 or edit_id and not reference:
                    raise ValueError("별도 워크플로 준비는 한 편씩 진행합니다.")
                prepared = {"prompt":p,"images":list(names),"width":job_w,"height":job_h,"seed":s}
                if edit_id:
                    job = {"id":edit_id,"seed":s,"width":job_w,"height":job_h,"model":model,"steps":steps,
                           "anchor":anchor,"face_side":face_side_for(0),"images":list(names),"actual_aspect":actual_aspect,"framing_fallback":fallback,
                           "sequence_index":reference["entry"].get("sequence_index")}
                    entry = make_entries([job])[0]
                    entry.update(t=reference["entry"]["t"],edited_at=time.time())
                    prepared.update(job=job,entry=entry)
                return prepared
            if edit_id:
                r = replace_queued_prompt(edit_id, p, expected_graph=reference["prompt"] if reference else None)
            elif queue_first:
                r = queue_prompt_first(p, slots=count, number=priority_number)
                priority_number = r["number"] + 1
            else:
                r = json.load(comfy("/prompt", json.dumps({"prompt": p, "client_id": CLIENT_ID}).encode(),
                                   {"Content-Type": "application/json"}))
            if r.get("node_errors") and not edit_id:
                raise ValueError(json.dumps(r["node_errors"], ensure_ascii=False)[:500])
            with PLOCK:
                PROGRESS.setdefault(r["prompt_id"],{"pct":0.0,"label":"대기"})["classes"]=classes
            jobs.append({"id": r["prompt_id"], "seed": s, "width": job_w, "height": job_h,
                         "model": model, "steps": steps, "anchor": anchor, "actual_aspect":actual_aspect,"framing_fallback":fallback,"prompt_verified": bool(edit_id and r.get("prompt_verified")), "face_side": face_side_for(index if sequence else 0),
                         "images": list(job_names), "sequence_index": index + 1 if sequence else reference["entry"].get("sequence_index") if reference else None})
    except Exception as exc:
        # 여러 편 등록 중 실패: 이미 ComfyUI 에 들어간 작업은 이력에 남겨 추적·중지·결과 연결이 되게 한다
        if jobs and not edit_id:
            try:
                hist_add(make_entries(jobs))
            except OSError:
                print("이력 파일 저장 실패: 등록된 작업은 메모리의 이력에 남아 다음 저장 때 기록됩니다.", flush=True)
            reason = comfy_rejection(exc) if isinstance(exc, urllib.error.HTTPError) else exc
            raise ValueError(f"{len(jobs)}개는 대기열에 등록했고 그다음 등록에서 실패했습니다: {reason}") from exc
        raise
    now = time.time()
    entries = make_entries(jobs)
    if edit_id:
        with HLOCK:
            entry = next((e for e in HIST_DB if e["id"] == edit_id), None)
            if entry is None:
                entry = entries[0]
                HIST_DB.append(entry)
            else:
                entries[0]["t"] = entry["t"]
                entry.update(entries[0])
            entry["edited_at"] = now
            entry.pop("t_end", None)
            try:
                _save_json(HIST, HIST_DB)
            except OSError:
                # 수정은 이미 ComfyUI 대기열에 반영됐다. 바뀐 항목은 메모리의 이력에 있어 다음 저장 때 기록된다.
                print("이력 파일 저장 실패: 수정한 작업은 메모리의 이력에 남아 다음 저장 때 기록됩니다.", flush=True)
    else:
        try:
            hist_add(entries)
        except OSError:
            # 작업은 이미 ComfyUI 대기열에 있다. 여기서 실패로 답하면 화면이 등록 실패로 보고 다시 넣어 같은 작업이 두 번 생긴다.
            # 항목은 메모리의 이력에 들어가 있어 다음 저장 때 함께 기록된다.
            print("이력 파일 저장 실패: 등록된 작업은 메모리의 이력에 남아 다음 저장 때 기록됩니다.", flush=True)
    return {"jobs": jobs, "id": jobs[0]["id"], "seed": jobs[0]["seed"], "width": jobs[0]["width"], "height": jobs[0]["height"],
            "model": os.path.basename(model.replace("\\", "/")), "steps": steps, "loras": len(loras), "mode": mode,
            "anchor": anchor, "face_crops": dict({"cropped": face_cropped, "original": (len(imgs) if sequence else len(imgs) - 1) - face_cropped},
                               **({"unavailable": face_unavailable} if face_unavailable else {}))
            if face_mode or face_unavailable else None}


def bulk_queue_context():
    pending = sorted(json.load(comfy("/queue"))["queue_pending"], key=lambda item: item[0])
    with HLOCK:
        entries = {entry["id"]: entry for entry in HIST_DB}
        owned = [(position, item[1]) for position, item in enumerate(pending, 1) if item[1] in entries]
        first = json.loads(json.dumps(entries[owned[0][1]])) if owned else None
    if first is not None:
        first.update(state="queued", position=owned[0][0])
    return {"ids": [pid for _, pid in owned], "total": len(owned), "first": first}


def commit_bulk_history(changes):
    with HLOCK:
        by_id = {entry["id"]:entry for entry in HIST_DB}
        for change in changes:
            current = by_id.get(change["id"])
            if current is None:continue  # Never resurrect deleted history.
            # Status polling can observe a fast start/finish before this checkpoint.
            status_keys = ("state","video","error","t_end","generation_started_at","generation_finished_at","generation_seconds")
            status = {key:current[key] for key in status_keys if key in current} if current.get("state") in ("running","done") else {}
            current.update(change["entry"])
            if status:current.update(status)
            else:current.pop("t_end",None)
        _save_json(HIST,HIST_DB)
    with PLOCK:
        for change in changes:
            if "prompt" in change:
                classes = {key:node["class_type"] for key,node in change["prompt"].items() if isinstance(node,dict) and "class_type" in node}
                if classes:PROGRESS.setdefault(change["id"],{"pct":0.0,"label":"대기"})["classes"] = classes


def bulk_queue_editor():
    return QueueBulkEditor(comfy,QUEUE_EDIT_LOCK,os.path.join(HERE,"queue-edit-recovery"),_save_json,commit_bulk_history)


def bulk_edit_queue(req):
    ids = req.get("edit_ids")
    apply_current=req.get("apply_current",False)
    if type(apply_current) is not bool:raise ValueError("현재 설정 적용 상태를 확인해 주세요.")
    fields = ["content","model","video","anchor"] if apply_current else req.get("bulk_fields")
    all_pending = req.get("all_pending", False)
    if not isinstance(all_pending, bool):
        raise ValueError("전체 대기항목 선택 상태가 올바르지 않습니다.")
    if not all_pending and (not isinstance(ids, list) or not ids or not all(isinstance(pid, str) for pid in ids)):
        raise ValueError("수정할 대기 항목을 선택해 주세요.")
    if not isinstance(fields, list) or not fields or set(fields) - {"content", "model", "video", "anchor"}:
        raise ValueError("적용할 수정 항목을 선택해 주세요.")
    if "anchor" in fields and not isinstance(req.get("anchor"), bool):
        raise ValueError("첫 장면 고정 상태가 올바르지 않습니다.")
    incoming=req.get("ui") or {}
    if not isinstance(incoming,dict) or not isinstance(incoming.get("f",{}),dict):
        raise ValueError("현재 화면 설정 형식을 확인해 주세요.")
    if "content" in fields and (not isinstance(req.get("prompt"),str) or not req["prompt"].strip()):
        raise ValueError("프롬프트가 비어 있습니다.")
    pending = {item[1]: item for item in sorted(json.load(comfy("/queue"))["queue_pending"], key=lambda item: item[0])}
    with HLOCK:
        owned = {e["id"]: e for e in HIST_DB}
        entries = {pid:json.loads(json.dumps(owned[pid])) for pid in (pending if all_pending else dict.fromkeys(ids)) if pid in owned}
    if all_pending:
        ids = [pid for pid in pending if pid in entries]
    with BULK_PROGRESS.operation(len(set(ids)),all_pending=all_pending) as report:
        updated, failed = [], []
        cache = BuildCache()
        editor = bulk_queue_editor()
        staged = []
        def flush():
            if not staged:return
            verified, errors = editor.apply(staged)
            for change in verified:
                updated.append(dict(change["job"],prompt_verified=True,loras=change["entry"].get("loras",[])))
                report.advance(True,verified=True)
            failed.extend(errors)
            for error in errors:report.advance(False,error=error.get("error"))
            staged.clear()
        for pid in dict.fromkeys(ids):
            if pid not in pending or pid not in entries:
                failed.append({"id": pid, "error": "이미 시작됐거나 대기열에서 빠진 항목입니다."})
                report.advance(False,error=failed[-1]["error"])
                continue
            try:
                entry = entries[pid]
                values = dict(entry, edit_id=pid, count=1, photo_sequence=False)
                ui = json.loads(json.dumps(entry.get("ui") or {}))
                if not isinstance(ui,dict) or not isinstance(ui.get("f",{}),dict):raise ValueError("저장된 화면 설정을 읽지 못했습니다.")
                form = dict(ui.get("f") or {})
                incoming = req.get("ui") or {}
                if "content" in fields:
                    values["prompt"] = req.get("prompt")
                    # 화면은 첫 대상의 사진 수 기준으로 얼굴 참조 문구를 만든다 → 대상의 사진 수에 맞는 버전으로 바꿔 쓴다
                    variants = req.get("prompt_by_count")
                    if isinstance(variants, dict) and entry.get("mode") == "REF2VA":
                        chosen = variants.get(str(len(entry.get("images") or [])))
                        if isinstance(chosen, str) and chosen.strip():
                            values["prompt"] = chosen
                    for key in ("subject", "summary", "style", "keep", "sound", "music"):
                        if key in incoming.get("f", {}): form[key] = incoming["f"][key]
                    for key in ("shots", "actionMode", "final", "oneTake"):
                        if key in incoming: ui[key] = incoming[key]
                if "model" in fields:
                    for key in ("model", "steps", "sampler", "scheduler", "shift_video", "shift_audio", "loras", "speed"):
                        if key in req: values[key] = req[key]
                    if "trig" in incoming: ui["trig"] = incoming["trig"]
                if "anchor" in fields:
                    values["anchor"] = req["anchor"]
                if "video" in fields:
                    for key in ("aspect", "resolution", "duration", "protect_person"):
                        if key in req:
                            values[key] = req[key]
                            form[key] = req[key]
                ui["f"] = form
                values["ui"] = ui
                result = build_and_queue(values, reference={"entry": entry, "prompt": pending[pid][2]},prepare_only=True,build_cache=cache)
                staged.append({"id":pid,"before":pending[pid][2],"prompt":result["prompt"],"entry":result["entry"],"job":result["job"]})
            except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
                failed.append({"id": pid, "error": str(exc)})
                report.advance(False,error=exc)
            if len(staged)>=25:flush()
        flush()
        return {"jobs": updated, "failed": failed, "failure_reasons":report.snapshot()["failure_reasons"], "bulk_edit": True, "all_pending": all_pending, "apply_current":apply_current,"target_count": len(set(ids)), "verified_count": sum(bool(job.get("prompt_verified")) for job in updated)}


def face_detector_ready():
    try:
        from face_references import ensure_available, MODEL_NAME
        ensure_available(os.path.join(ROOT, 'models', 'face_detection', MODEL_NAME))
        return True
    except (ValueError, ImportError):
        return False


def add_anchor(p, image_name):
    """참조 방식에서 사진 1 을 영상 0번째 프레임에 고정한다(ComfyUI 네이티브 MiniMaxH3AddGuide).
    참조 사진은 모두 그대로 쓰이고(얼굴 등), 첫 장면만 사진 1 로 못 박는다."""
    if p[GUIDER]["inputs"].get("conditioning") != [GUIDE, 0] or p[GUIDE]["class_type"] != "MiniMaxH3DirectorGuide":
        raise ValueError("템플릿 구조가 예상과 달라 '사진 1 첫 장면 고정'을 쓸 수 없습니다(ARCHITECTURE §2 확인).")
    p[ANCHOR_IMG] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
    p[ANCHOR] = {"class_type": "MiniMaxH3AddGuide",
                 "inputs": {"positive": [GUIDE, 0], "latent": [GUIDE, 1], "vae": [VIDEO_VAE, 0],
                            "image": [ANCHOR_IMG, 0], "frame_idx": 0}}
    p[GUIDER]["inputs"]["conditioning"] = [ANCHOR, 0]


NODE_KNOWN = {}        # 노드 종류 -> (있는지, 확인한 시각). ComfyUI 에 그 노드가 설치돼 있는지


def node_available(cls):
    """ComfyUI 에 이 노드 종류가 있는지(설치된 커스텀 노드 버전에 따라 다르다). 있다는 답은 계속, 없다는 답은 5분만 믿는다."""
    known = NODE_KNOWN.get(cls)
    if known and (known[0] or time.time() - known[1] < 300):
        return known[0]
    found = cls in json.load(comfy(f"/object_info/{cls}"))
    NODE_KNOWN[cls] = (found, time.time())
    return found


def add_speed_nodes(p, available=node_available, mode=""):
    """속도 노드를 shift 노드와 미리보기 노드 사이에 차례로 끼운다(값이 아니라 노드가 늘어나는 변경 — AGENTS.md 의 예외 목록 참고).

    1) 항상(결과가 같다): MiniMaxChunkFeedForward(KJNodes). H3 블록의 피드포워드를 토큰 묶음으로 나눠 계산한다. 토큰 행은 서로
       독립이고 int8 활성 양자화도 행 단위라 결과가 같다(같은 시드로 실측해 프레임이 완전히 같음을 확인). 순간 메모리가 줄어 16GB
       카드에서 가중치가 VRAM 에 더 머물고, 5초 768x960 에서 스텝당 19.12초 → 17.85초(-6.6%)였다(docs/PERFORMANCE.md).
       끄려면 환경 변수 SIMPLEUI_CHUNK_FF=0. 노드가 없는 ComfyUI 나 예상과 다른 틀이면 넣지 않는다(생성을 막지 않는다).
    2) mode 가 "sparse"·"sparse_cache" 일 때만(결과가 기본과 달라진다 — 사용자가 고른 작업에만):
       BlockSparseAttention(ComfyUI 코어, sol-attn): 어텐션을 점수가 높은 블록만 정확히 계산한다. 스텝의 앞 20% 는 그대로 둔다.
       MiniMaxH3Cache(DaSiWa): 변화가 작은 스텝은 블록 계산을 건너뛰고 앞 스텝의 결과를 다시 쓴다. 이 노드는 H3 의 계산 함수(_forward)를
       자기 사본으로 바꿔 끼우는데, 그 사본은 코어가 희소 어텐션에 넘겨주는 토큰 배치 정보(minimax_h3_layout)와 블록별 어텐션 지정을
       전달하지 않는다. 그래서 캐시를 함께 쓰면 9004 의 sink_conditioning(문구·참조·소리 행을 정확히 계산)은 효과가 없고
       희소 어텐션은 일반 경로로만 돈다. 노드 순서를 바꿔도 같다(시안용이라고 안내하는 이유).
       고른 방식의 노드가 이 ComfyUI 에 없으면 조용히 빼지 않고 오류로 알린다.
    반환: 끼운 노드 종류 목록."""
    preview = p.get(PREVIEW)
    if not preview or preview["inputs"].get("model") != [SHIFT, 0] or any(key in p for key in (CHUNK_FF, SPARSE, STEP_CACHE)):
        if mode:
            raise ValueError("템플릿 구조가 예상과 달라 '속도 우선' 옵션을 쓸 수 없습니다(ARCHITECTURE §2 확인).")
        return []
    wanted = SPEED_MODES.get(mode, ()) if mode else ()
    if mode and not wanted:
        raise ValueError("속도 우선 옵션을 확인해 주세요.")
    for cls in wanted:
        if not available(cls):
            raise ValueError(f"이 ComfyUI 에 {cls} 노드가 없어 고른 '속도 우선' 옵션을 쓸 수 없습니다. 기본으로 바꿔 주세요.")
    added, source = [], [SHIFT, 0]
    chunked = os.environ.get("SIMPLEUI_CHUNK_FF", "1").strip().lower() not in ("0", "off", "false", "no")
    if chunked:
        try:
            chunked = available("MiniMaxChunkFeedForward")
        except (OSError, ValueError, KeyError):
            chunked = False                  # 확인하지 못했으면 이 노드 없이 보낸다(생성을 막지 않는다)
    if chunked:
        p[CHUNK_FF] = {"class_type": "MiniMaxChunkFeedForward", "inputs": {"model": source, "chunks": 4, "seq_threshold": 4096}}
        source = [CHUNK_FF, 0]
        added.append("MiniMaxChunkFeedForward")
    if "BlockSparseAttention" in wanted:
        p[SPARSE] = {"class_type": "BlockSparseAttention", "inputs": {
            "model": source, "selection": "sol-attn", "selection.tau": 1.3, "start_percent": 0.2, "end_percent": 1.0, "dense_blocks": "",
            "min_tokens": 12288, "extra_tokens": 256, "sink_conditioning": "exact_kv_and_rows", "verbose": False}}
        source = [SPARSE, 0]
        added.append("BlockSparseAttention")
    if "MiniMaxH3Cache" in wanted:
        p[STEP_CACHE] = {"class_type": "MiniMaxH3Cache", "inputs": {"model": source, "reuse_threshold": 0.05, "start_percent": 0.15,
                                                                     "end_percent": 0.9, "max_steps": 2, "device": "auto", "verbose": False}}
        source = [STEP_CACHE, 0]
        added.append("MiniMaxH3Cache")
    preview["inputs"]["model"] = source
    return added


def speed_modes_available():
    """이 ComfyUI 에서 고를 수 있는 '속도 우선' 방식(필요한 노드가 모두 있는 것만). 확인에 실패하면 없는 것으로 본다."""
    modes = []
    for mode, classes in SPEED_MODES.items():
        try:
            if all(node_available(cls) for cls in classes):
                modes.append(mode)
        except (OSError, ValueError, KeyError):
            pass
    return modes


def video_of(entry):
    for g in (entry.get("outputs", {}).get(SAVE, {}) or {}).get("gifs", []) or []:
        return {"filename": g["filename"], "subfolder": g.get("subfolder", ""), "type": g.get("type", "output")}
    return None


def status(pid):
    st = _status(pid)
    hist_result(pid, st)
    return st


def _queue_state(pid, q):
    """대기열 스냅샷에서 실행 중·대기 상태를 찾는다(없으면 None)."""
    if any(x[1] == pid for x in q.get("queue_running", [])):
        with PLOCK:
            st = PROGRESS.get(pid) or {}
            timing={key:st[key] for key in ("generation_started_at","elapsed_estimated") if key in st}
        return {"state": "running", "pct": round(st.get("pct", 0)), "label": st.get("label", ""),**timing}
    pend = [x[1] for x in sorted(q.get("queue_pending", []), key=lambda x: x[0])]
    if pid in pend:
        return {"state": "queued", "position": pend.index(pid) + 1}
    return None


def execution_timing(entry):
    """Native execution timestamps only; never infer runtime from queue/file dates."""
    started=finished=None
    for message in (entry.get("status") or {}).get("messages",[]):
        if not isinstance(message,(list,tuple)) or len(message)!=2 or not isinstance(message[1],dict):continue
        kind,data=message;stamp=data.get("timestamp")
        if type(stamp) not in (int,float) or not math.isfinite(stamp) or stamp<0:continue
        stamp=stamp/1000
        if kind=="execution_start":started=stamp;finished=None
        elif kind in ("execution_success","execution_error","execution_interrupted") and started is not None and stamp>=started:finished=stamp
    if started is None or finished is None:return {}
    return {"generation_started_at":started,"generation_finished_at":finished,"generation_seconds":round(finished-started,3)}


def _status(pid, q=None):
    held = backend_restart_hold(pid)
    if held:
        with PLOCK:
            if pid in PROGRESS:
                PROGRESS[pid]["pct"] = 0.0
        return held
    # 대기열 스냅샷으로 먼저 판정한다(대기·실행 중인 작업은 history 에 아직 없다). 스냅샷은 1초 동안 여러 조회가
    # 나눠 쓰므로, 화면이 작업마다·창마다 물어도 ComfyUI 의 전체 대기열은 초당 한 번만 받는다.
    # 대기열에 없을 때만 history 를 묻는다: 작업은 대기열에서 빠지는 순간 history 에 적히므로 그 사이의 빈틈이 없다.
    if q is None:
        snapshot = globals().get("queue_snapshot")
        q = snapshot() if snapshot else json.load(comfy("/queue"))
    found = _queue_state(pid, q)
    if found:
        return found
    h = json.load(comfy(f"/history/{urllib.parse.quote(pid)}"))
    if pid in h:
        e = h[pid]
        st = e.get("status", {})
        if st.get("status_str") == "success":
            return {"state": "done", "video": video_of(e), **execution_timing(e)}
        msg = ""
        for m in st.get("messages", []):
            if m[0] == "execution_error":
                msg = m[1].get("exception_message", "")
            elif m[0] == "execution_interrupted":
                msg = "중지됨(이 화면의 중지 버튼이나 ComfyUI 화면에서 멈춤)"
        return {"state": "error", "error": msg or st.get("status_str", "error"), **execution_timing(e)}
    # 대기열에도 이력에도 없다. 판정에 쓴 스냅샷은 최대 1초 묵은 것일 수 있으므로(다른 곳에서 방금 등록한 작업),
    # '찾을 수 없음'으로 답하기 전에 새 스냅샷으로 한 번 더 본다. 사라진 작업이 많아도 0.2초에 한 번만 받는다.
    snapshot = globals().get("queue_snapshot")
    return (snapshot and _queue_state(pid, snapshot(max_age=0.2))) or {"state": "unknown"}


def status_many(ids):
    """여러 작업의 상태를 한 번에 돌려준다(화면이 추적 중인 작업 수만큼 요청을 보내지 않게).

    대기열 스냅샷 하나로 대기·실행 중인 작업을 판정하고, 대기열에 없는 작업만 history 를 한 번씩 묻는다.
    """
    ids = list(dict.fromkeys(pid for pid in ids if isinstance(pid, str) and 0 < len(pid) <= 100))
    if not ids or len(ids) > 200:
        raise ValueError("상태를 확인할 작업을 1~200개로 지정해 주세요.")
    q = None if backend_restart_hold() else queue_snapshot()
    jobs = {}
    for pid in ids:
        jobs[pid] = _status(pid, q)
        hist_result(pid, jobs[pid])
    return {"jobs": jobs}


def hist_list(offset, limit, identity=None):
    """최근 순. 아직 결과가 없는 항목은 지금 상태를 물어 채운다(ComfyUI 가 잊은 작업은 '결과 없음')."""
    offset, limit = max(0, offset), max(1, limit)
    with HLOCK:
        if identity is not None and (not isinstance(identity,str) or not identity or len(identity)>100):raise ValueError("작업 ID를 확인해 주세요.")
        items = [entry for entry in reversed(HIST_DB) if identity is None or entry["id"]==identity]
        # 이 페이지만 복사해 둔다: 응답을 만드는 동안 다른 요청이 같은 항목을 고쳐도(상태·수정) 직렬화가 깨지지 않게
        page = json.loads(json.dumps(items[offset:offset + limit]))
    q = None  # 페이지마다 대기열은 한 번만 받는다(대기 수백 건이면 항목마다 받던 것이 수백 번이 됐다)
    for i, e in enumerate(page):
        if e.get("state") in ("queued", "running"):
            try:
                if q is None:
                    snapshot = globals().get("queue_snapshot")
                    q = snapshot() if snapshot else json.load(comfy("/queue"))
                st = _status(e["id"], q)
            except Exception:  # noqa: BLE001 — ComfyUI 꺼짐: 지금 상태만 모름
                continue
            if st["state"] == "unknown":
                st = {"state": "lost", "error": "결과 없음(ComfyUI 재시작 등으로 중단)"}
            hist_result(e["id"], st)
            with HLOCK:
                # 방금 적힌 결과(끝난 시각·생성 시간)까지 담도록 최신 항목을 다시 복사한다
                live = next((entry for entry in HIST_DB if entry["id"] == e["id"]), None)
                e = json.loads(json.dumps(live)) if live is not None else e
            page[i] = dict(e, **{k: v for k, v in st.items() if k in ("state", "video", "error", "pct", "position")})
    return {"items": page, "total": len(items)}


def gallery_progress():
    """Return progress and regeneration states, without prompts, images or result paths."""
    with GALLERY_PROGRESS_LOCK:
        now = time.monotonic()
        if GALLERY_PROGRESS_CACHE["value"] is not None and now - GALLERY_PROGRESS_CACHE["at"] < 2:
            return GALLERY_PROGRESS_CACHE["value"]
        snapshot = globals().get("queue_snapshot")
        state = snapshot() if snapshot else json.load(comfy("/queue", timeout=8))
        running, pending = state.get("queue_running", []), state.get("queue_pending", [])
        active = {item[1] for item in running + pending}
        with HLOCK:
            unfinished = [(entry["id"], entry.get("t", 0), bool((entry.get("ui") or {}).get("regeneration"))) for entry in HIST_DB
                          if (entry.get("state") in ("queued", "running") or (entry.get("state") == "done" and not entry.get("video")))
                          and entry["id"] not in active]
        # A gallery-only session must also record completion and its source-image link.
        # Include ordinary jobs, with bounded round-robin checks so old unknown IDs
        # cannot indefinitely block newly completed videos from receiving a source.
        cursor = GALLERY_PROGRESS_CACHE.get("completion_cursor", 0) % max(1, len(unfinished))
        batch = (unfinished[cursor:] + unfinished[:cursor])[:8]
        GALLERY_PROGRESS_CACHE["completion_cursor"] = (cursor + len(batch)) % max(1, len(unfinished))
        for pid, created_at, regenerated in batch:
            if time.time() - created_at < 2:
                continue
            result = _status(pid, state)
            if result["state"] in ("done", "error", "lost"):
                hist_result(pid, result)
            if regenerated and result["state"] == "unknown" and time.time() - created_at > 30:
                hist_result(pid, {"state": "lost", "error": "대기열에서 작업을 찾지 못했습니다."})
        with PLOCK:
            current_progress=(PROGRESS.get(running[0][1]) or {}) if running else {}
            value=None if current_progress.get("elapsed_only") else current_progress.get("pct")
        timing={"elapsed_seconds":None,"elapsed_estimated":False}
        if running:
            pid=running[0][1]
            with HLOCK:
                recorded=next((e.get("generation_started_at") for e in HIST_DB if e["id"]==pid),None)
            with PLOCK:
                progress=PROGRESS.setdefault(pid,{"classes":{},"pct":0.0,"label":"","elapsed_only":True})
                started=progress.get("generation_started_at")
                if type(started) not in (int,float) or not math.isfinite(started) or started<0:
                    exact=type(recorded) in (int,float) and math.isfinite(recorded) and recorded>=0
                    started=recorded if exact else time.time()
                    progress.update(generation_started_at=started,elapsed_estimated=not exact)
                timing={"elapsed_seconds":max(0,round(time.time()-started,3)),"elapsed_estimated":bool(progress.get("elapsed_estimated"))}
        pct = max(0, min(100, round(value))) if isinstance(value, (int, float)) else None
        with HLOCK:
            jobs = [{"id": entry["id"], "state": "running" if any(item[1] == entry["id"] for item in running)
                     else "queued" if entry["id"] in active else entry.get("state", "unknown"),
                     "completed_at": entry.get("t_end", 0)} for entry in HIST_DB if (entry.get("ui") or {}).get("regeneration")]
        result = {"running": bool(running), "pct": pct, "pending": len(pending), "jobs": jobs,**timing}
        GALLERY_PROGRESS_CACHE.update(at=time.monotonic(), value=result)
        return result


def track_story_job(pid,graph):
    with PLOCK:
        PROGRESS.setdefault(pid,{"pct":0.0,"label":"대기"})["classes"]={key:node["class_type"] for key,node in graph.items()}


STORIES=StoryProjects(os.path.join(HERE,"story_data"),OUTPUT,
    lambda request,reference:build_and_queue(request,reference,prepare_only=True),
    comfy,upload,_status,track_story_job,client_id=CLIENT_ID)


def production_queue_snapshot():
    # Only queue order/identity/state/progress leave this function; graphs stay local.
    raw=json.load(comfy("/queue"))
    with HLOCK: owned={entry["id"] for entry in HIST_DB}
    rows=[]
    for key,state in (("queue_running","running"),("queue_pending","queued")):
        for position,item in enumerate(sorted(raw.get(key,[]),key=lambda row:row[0]),1):
            if item[1] not in owned:continue
            with PLOCK: pct=PROGRESS.get(item[1],{}).get("pct",0)
            rows.append({"id":item[1],"state":state,"position":position,"pct":pct})
    return {"items":rows,"running_count":sum(row["state"]=="running" for row in rows),"pending_count":sum(row["state"]=="queued" for row in rows),"other_count":len(raw.get("queue_running",[]))+len(raw.get("queue_pending",[]))-len(rows)}


def production_queue_item(args,snapshot):
    rows=[row for row in snapshot["items"] if row["state"]=="queued"]
    target=next((row for row in rows if row["id"]==args.get("id") or type(args.get("position")) is int and row["position"]==args["position"]),None)
    if not target:raise ValueError("지정한 대기 항목을 찾지 못했습니다.")
    raw=json.load(comfy("/queue"))
    native=next((item for item in raw.get("queue_pending",[]) if item[1]==target["id"]),None)
    if native is None:raise ValueError("대기 상태가 바뀌었습니다. 다시 조회해 주세요.")
    with HLOCK:
        entry=next((item for item in HIST_DB if item["id"]==target["id"]),None)
        if not entry:raise ValueError("이 화면의 대기 항목만 조회할 수 있습니다.")
        result={key:entry[key] for key in ("id","mode","duration","model","steps","sampler","scheduler","shift_video","shift_audio","loras","seed","anchor","width","height") if key in entry}
        ui=entry.get("ui") or {}
        result["ui"]={key:ui[key] for key in ("f","shots","final","actionMode","oneTake","trig","faceBoost") if key in ui}
    # Actual queued text, not a possibly stale editor/history string.
    result["prompt"]=native[2][DIRECTOR]["inputs"]["prompt"]
    result["prompt_hash"]=hashlib.sha256(result["prompt"].encode()).hexdigest()
    return result


def production_read_api(path,args):
    if path not in PRODUCTION_READS or not path.startswith("/api/"):raise ValueError("허용되지 않은 앱 조회입니다.")
    if any(not isinstance(key,str) or not isinstance(value,(str,int,float,bool)) for key,value in args.items()):raise ValueError("조회 인수를 확인해 주세요.")
    args=dict(args)
    if path in ("/api/history","/api/gallery"):args["limit"]=min(20,max(1,int(args.get("limit",10))))
    url="http://127.0.0.1:"+str(PORT)+path+("?"+urllib.parse.urlencode(args) if args else "")
    with urllib.request.urlopen(url,timeout=20) as response:
        if "application/json" not in response.headers.get("Content-Type",""):raise ValueError("텍스트 정보만 조회할 수 있습니다.")
        data=response.read(8*1024*1024+1)
        if len(data)>8*1024*1024:raise ValueError("조회 범위를 줄여 주세요.")
        return json.loads(data)


def production_validate_write(action,snapshot):
    if action["path"] not in PRODUCTION_WRITES:raise ValueError("허용되지 않은 앱 실행입니다.")
    args=json.loads(action["args"])
    if not isinstance(args,dict):return  # A local binding is checked once materialized.
    path=action["path"]
    if path not in ("/api/cancel","/api/queue/restart","/api/history/delete","/api/queue/bulk-edit","/api/production-assistant/patch-queue"):return
    previous={row["id"]:row["state"] for row in snapshot["items"]}
    current={row["id"]:row["state"] for row in production_queue_snapshot()["items"]}
    ids=args.get("ids") or args.get("edit_ids") or ([args["id"]] if args.get("id") else [])
    if not isinstance(ids,list) or any(not isinstance(pid,str) for pid in ids):raise ValueError("대상을 확인해 주세요.")
    if args.get("all") and previous!=current:raise ValueError("대기열이 바뀌었습니다. 전체 삭제 대상을 다시 확인해 주세요.")
    for pid in ids:
        if pid in previous and previous[pid]!=current.get(pid):raise ValueError("대상의 실행 상태가 바뀌었습니다. 다시 조회해 주세요.")
        if path in ("/api/cancel","/api/queue/restart","/api/production-assistant/patch-queue") and pid not in previous:raise ValueError("조회한 작업만 제어할 수 있습니다.")


def production_prompt_graph(graph,text):
    """Keep the Director widget and its model-effective simple builder in sync."""
    if not isinstance(text,str) or len(text)>80000:raise ValueError("프롬프트 형식을 확인해 주세요.")
    graph=json.loads(json.dumps(graph));d=graph[DIRECTOR]["inputs"]
    def object_value(raw):
        try:value=json.loads(raw or "{}")
        except (TypeError,ValueError):raise ValueError("프롬프트 구성 정보 형식을 확인해 주세요.") from None
        if not isinstance(value,dict):raise ValueError("프롬프트 구성 정보 형식을 확인해 주세요.")
        return value
    builder=object_value(d.get("builder_state"))
    builder.update(prompt_mode="simple",simple_prompt=text)
    if "timeline_data" in d:
        timeline=object_value(d["timeline_data"])
        embedded=timeline.get("builder_state",{})
        if not isinstance(embedded,dict):raise ValueError("프롬프트 구성 정보 형식을 확인해 주세요.")
        embedded.update(prompt_mode="simple",simple_prompt=text)
        timeline.update(builder_state=embedded,resolved_prompt=text)
        if "continuity" in timeline:
            if not isinstance(timeline["continuity"],dict):raise ValueError("프롬프트 구성 정보 형식을 확인해 주세요.")
            timeline["continuity"]["continuation_prompt"]=text
        d["timeline_data"]=json.dumps(timeline,ensure_ascii=False)
    override=d.get("external_prompt_overwrite")
    if override and not isinstance(override,str):raise ValueError("연결된 외부 프롬프트 입력은 이 방식으로 수정할 수 없습니다.")
    if override:d["external_prompt_overwrite"]=text
    d.update(prompt=text,builder_state=json.dumps(builder,ensure_ascii=False))
    return graph


def production_face_side(text,entry):
    """대기 그래프에 넣을 글의 {{face_side}} 를 등록할 때와 같은 규칙으로 left/right 로 바꾼다(모델에 자리표시가 그대로 들어가지 않게).
    그 작업을 등록할 때 재 둔 방향이 이력에 있으면 그 값, 없으면 사진 1을 다시 재고, 그것도 안 되면 right(등록 때의 기본값).
    반환: (그래프에 넣을 글, 이력에 적을 방향 또는 None). 이력의 글은 자리표시를 그대로 둔다(등록 때와 같다)."""
    token="{{face_side}}"
    if token not in text:return text,None
    side=(entry or {}).get("face_side")
    if not isinstance(side,dict) or side.get("used") not in ("left","right"):
        side={"side":"unavailable","offset":None,"used":"right"}
        images=(entry or {}).get("images") or []
        measure,fetch=globals().get("judge_face_side"),globals().get("input_bytes")
        if images and measure and fetch:
            try:side=measure(fetch(images[0]))
            except (urllib.error.URLError,OSError,ValueError,TypeError):pass
    return text.replace(token,side["used"]),side


def production_repair_prompt_state(dry_run=True):
    """Align previously saved edits only; expose counts, never work text or IDs."""
    if type(dry_run) is not bool:raise ValueError("검사 옵션을 확인해 주세요.")
    raw=json.load(comfy("/queue"))
    with HLOCK:entries={e["id"]:json.loads(json.dumps(e)) for e in HIST_DB}
    counts={"checked":0,"eligible":0,"repaired":0,"failed":0,"dry_run":dry_run}
    for row in raw.get("queue_pending",[]):
        entry=entries.get(row[1]);d=row[2].get(DIRECTOR,{}).get("inputs",{})
        if not entry or not isinstance(d.get("prompt"),str):continue
        counts["checked"]+=1
        try:builder=json.loads(d.get("builder_state") or "{}")
        except (ValueError,TypeError):continue
        if not isinstance(builder,dict) or builder.get("prompt_mode")!="simple" or not isinstance(builder.get("simple_prompt"),str) or builder["simple_prompt"]==d["prompt"]:continue
        if not entry.get("edited_at") or entry.get("prompt")!=d["prompt"] or (entry.get("ui") or {}).get("final")!=d["prompt"]:continue
        counts["eligible"]+=1
        if dry_run:continue
        try:
            graph=production_prompt_graph(row[2],d["prompt"])
            result=replace_queued_prompt(row[1],graph,expected_graph=row[2])
            if not result.get("prompt_verified"):raise ValueError("반영 확인 실패")
            counts["repaired"]+=1
        except (OSError,ValueError):counts["failed"]+=1
    return counts


def production_write_api(path,args,snapshot):
    if path not in PRODUCTION_WRITES:raise ValueError("허용되지 않은 앱 실행입니다.")
    if path=="/api/production-assistant/patch-queue":
        from production_assistant import replacement
        edits=args.get("edits");full=args.get("prompt")
        if "prompt" in args:
            if "edits" in args or not isinstance(full,str) or not full.strip() or len(full)>80000:raise ValueError("교체할 최종 프롬프트를 확인해 주세요.")
        elif not isinstance(edits,list) or not 1<=len(edits)<=12 or any(not isinstance(edit,dict) or not isinstance(edit.get("before"),str) or not isinstance(edit.get("after"),str) for edit in edits):
            raise ValueError("교체할 문구를 확인해 주세요.")
        change={"prompt":full} if "prompt" in args else {"edits":edits}
        # One assistant action can target the whole queue. Keep each graph's own
        # settings; use the same bounded native transactions as the current-form button.
        if "ids" in args or "all_pending" in args:
            all_pending=args.get("all_pending",False);ids=args.get("ids")
            if type(all_pending) is not bool or args.get("id") or all_pending and ids is not None:
                raise ValueError("일괄 수정할 범위를 확인해 주세요.")
            if not all_pending and (not isinstance(ids,list) or not ids or any(not isinstance(pid,str) or not pid for pid in ids)):
                raise ValueError("일괄 수정할 대기 항목을 지정해 주세요.")
            raw=json.load(comfy("/queue"))
            pending={row[1]:row for row in sorted(raw.get("queue_pending",[]),key=lambda row:row[0])}
            with HLOCK:
                owned={entry["id"] for entry in HIST_DB}
                entries={entry["id"]:json.loads(json.dumps(entry)) for entry in HIST_DB if entry["id"] in pending}
            known={row["id"] for row in snapshot["items"] if row["state"]=="queued"}
            if not all_pending and any(pid not in known or pid not in owned for pid in ids):
                raise ValueError("조회한 대기 항목만 지정 수정할 수 있습니다.")
            targets=[pid for pid in pending if pid in owned] if all_pending else list(dict.fromkeys(ids))
            with BULK_PROGRESS.operation(len(targets),all_pending=all_pending) as report:
                jobs=[];failed=[];staged=[]
                editor=bulk_queue_editor()
                def flush():
                    if not staged:return
                    verified,errors=editor.apply(staged)
                    for change in verified:
                        jobs.append({"ok":True,"id":change["id"],"prompt_verified":True})
                        report.advance(True,verified=True)
                    failed.extend(errors)
                    for error in errors:report.advance(False,error=error.get("error"))
                    staged.clear()
                for pid in targets:
                    row=pending.get(pid)
                    if row is None:
                        failed.append({"id":pid,"error":"이미 시작됐거나 대기열에서 빠진 항목입니다."});report.advance(False,error=failed[-1]["error"]);continue
                    try:
                        original=row[2][DIRECTOR]["inputs"]["prompt"]
                        digest=snapshot.get("prompt_hashes",{}).get(pid)
                        if digest and hashlib.sha256(original.encode()).hexdigest()!=digest:
                            raise ValueError("조회 후 문구가 바뀌었습니다. 다시 조회해 주세요.")
                        updated=full if "prompt" in args else original
                        for edit in edits or []:updated=replacement(updated,edit["before"],edit["after"])
                        entry=json.loads(json.dumps(entries[pid]))
                        resolved,side=production_face_side(updated,entry)
                        graph=production_prompt_graph(row[2],resolved)
                        entry.update(prompt=updated,edited_at=time.time())
                        if side:entry["face_side"]=side
                        if not isinstance(entry.get("ui"),dict):entry["ui"]={}
                        entry["ui"]["final"]=updated
                        staged.append({"id":pid,"before":row[2],"prompt":graph,"entry":entry})
                    except (ValueError,OSError,KeyError,TypeError,AttributeError) as exc:
                        failed.append({"id":pid,"error":str(exc)});report.advance(False,error=exc)
                    if len(staged)>=25:flush()
                flush()
                return {"ok":not failed,"bulk_edit":True,"all_pending":all_pending,"target_count":len(targets),
                        "updated_count":len(jobs),"jobs":jobs,"failed":failed,"failure_reasons":report.snapshot()["failure_reasons"],
                        "verified_count":sum(bool(job.get("prompt_verified")) for job in jobs)}
        pid=args.get("id")
        if not snapshot.get("prompt_hashes",{}).get(pid):raise ValueError("수정 전 해당 대기 항목을 먼저 조회해 주세요.")
        raw=json.load(comfy("/queue"));row=next((item for item in raw.get("queue_pending",[]) if item[1]==pid),None)
        if row is None:raise ValueError("대기 상태가 바뀌었습니다. 실행 중인 작업은 수정하지 않았습니다.")
        original=row[2][DIRECTOR]["inputs"]["prompt"]
        if hashlib.sha256(original.encode()).hexdigest()!=snapshot["prompt_hashes"][pid]:raise ValueError("조회 후 문구가 바뀌었습니다. 다시 조회해 주세요.")
        updated=full if "prompt" in args else original
        for edit in edits or []:
            updated=replacement(updated,edit["before"],edit["after"])
        with HLOCK:saved=next((json.loads(json.dumps(entry)) for entry in HIST_DB if entry["id"]==pid),None)
        resolved,side=production_face_side(updated,saved)
        graph=production_prompt_graph(row[2],resolved)
        result=replace_queued_prompt(pid,graph,expected_graph=row[2])
        with HLOCK:
            for entry in HIST_DB:
                if entry["id"]==pid:
                    entry["prompt"]=updated;entry.setdefault("ui",{})["final"]=updated;entry["edited_at"]=time.time()
                    if side:entry["face_side"]=side
                    break
            _save_json(HIST,HIST_DB)
        return {"ok":True,"id":pid,"prompt_verified":bool(result.get("prompt_verified"))}
    if path=="/api/cancel":
        # A pending job starting during the race must never be interrupted.
        ids=args.get("ids") or ([args["id"]] if args.get("id") else [])
        if not ids:raise ValueError("중지할 대상을 지정해 주세요.")
        original={row["id"]:row["state"] for row in snapshot["items"]}
        with QUEUE_EDIT_LOCK:
            production_validate_write({"path":path,"args":json.dumps(args)},snapshot)
            headers={"Content-Type":"application/json"}
            comfy("/queue",json.dumps({"delete":ids}).encode(),headers)
            for pid in ids:
                if original.get(pid)=="running":comfy("/interrupt",json.dumps({"prompt_id":pid}).encode(),headers)
        after=json.load(comfy("/queue"));active={item[1] for item in after.get("queue_running",[])+after.get("queue_pending",[])}
        cancelled=[]
        for pid in ids:
            if original.get(pid)!="queued" or pid in active:continue
            observed=_status(pid,after)
            if observed["state"]=="unknown":cancelled.append(pid)
            elif observed["state"] in ("done","error"):hist_result(pid,observed)
        if cancelled:
            with HLOCK:
                for entry in HIST_DB:
                    if entry["id"] in cancelled:entry.update(state="error",error="제작 도우미에서 취소됨",t_end=time.time())
                _save_json(HIST,HIST_DB)
        return {"ok":True,"requested":len(ids),"cancelled_ids":cancelled,"stop_requested_ids":[pid for pid in ids if original.get(pid)=="running"],"skipped_started_ids":[pid for pid in ids if original.get(pid)=="queued" and pid in active]}
    request=urllib.request.Request("http://127.0.0.1:"+str(PORT)+path,json.dumps(args,ensure_ascii=False).encode(),{"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(request,timeout=3600 if path=="/api/queue/bulk-edit" else 120) as response:return json.load(response)


PRODUCTION_ASSISTANT=ProductionAssistant(PROMPT_HELPER,production_read_api,production_queue_snapshot,production_queue_item,production_validate_write,production_write_api,chat=ProductionChat(os.path.join(HERE,"production-chat.json")))


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        # 글 위주의 응답(이력·모델 목록·갤러리 목록)은 압축해 보낸다. 휴대폰·원격 접속에서 차이가 크다.
        # 아주 작은 응답은 이득이 없고, 사진이 실린 큰 응답은 잘 줄지 않으면서 CPU 만 쓰므로 그대로 보낸다.
        packed = 1024 <= len(b) <= 1024 * 1024 and self._accepts_gzip()
        if packed:
            import gzip
            b = gzip.compress(b, 5)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if packed:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _accepts_gzip(self):
        """요청이 gzip 응답을 받겠다고 했는지(Accept-Encoding). q=0 은 거절이고, gzip 을 직접 적은 쪽이 * 보다 우선한다."""
        wanted = {}
        for token in str((getattr(self, "headers", None) or {}).get("Accept-Encoding") or "").lower().split(","):
            name, _, params = token.partition(";")
            try:
                wanted[name.strip()] = float(params.partition("q=")[2].strip()) if "q=" in params else 1.0
            except ValueError:   # 값이 비었거나 숫자가 아니면 거절로 본다
                wanted[name.strip()] = 0.0
        return wanted.get("gzip", wanted.get("*", 0.0)) > 0

    _packed_pages = {}   # 화면 파일의 압축본: 경로 → ((수정 시각, 크기), gzip 바이트). 파일이 바뀔 때만 다시 압축한다

    def _page(self, source, content_type):
        """화면 파일(HTML·JS)을 보낸다. 받는 쪽이 gzip 을 받으면 압축본을 보낸다(일반 화면을 여는 데 약 300KB → 90KB)."""
        packed = self._accepts_gzip()
        info = os.stat(source)
        key = (info.st_mtime_ns, info.st_size)
        cached = self._packed_pages.get(source) if packed else None
        if cached and cached[0] == key:
            body = cached[1]
        else:
            with open(source, "rb") as page:
                body = page.read()
            if packed:
                import gzip
                body = gzip.compress(body, 6)
                self._packed_pages[source] = (key, body)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        if packed:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def parse_request(self):
        """요청 줄·헤더를 읽은 직후, 본문을 읽기 전에 받지 않을 POST 를 거른다."""
        if not super().parse_request():
            return False
        self._headers_flushed = False   # 위에서 '100 Continue' 를 보냈더라도 그것은 최종 응답이 아니다
        if self.command == "POST":
            rejected = self._post_rejection()
            if rejected:
                self._reject(*rejected)
                return False
        return True

    def end_headers(self):
        self._headers_flushed = True
        super().end_headers()

    def _reject(self, code, reason, discard):
        """본문을 읽지 않고 거절한다. 이 연결은 다시 쓰지 않는다(남은 본문이 다음 요청으로 읽히지 않게)."""
        import time
        body = json.dumps({"error": reason}, ensure_ascii=False).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            # 읽지 않은 본문을 남긴 채 닫으면 받는 쪽에서 안내 응답보다 연결 초기화가 먼저 보일 수 있다.
            # 작은 본문만, 정해진 시간 안에서만 읽어 버린다.
            deadline = time.monotonic() + 2
            while discard > 0 and time.monotonic() < deadline:
                self.connection.settimeout(max(0.05, min(0.5, deadline - time.monotonic())))
                chunk = self.rfile.read1(min(discard, 65536))
                if not chunk:
                    break
                discard -= len(chunk)
        except OSError:
            pass   # 받을 쪽이 이미 떠났거나 더 보내지 않는다
        self.close_connection = True

    def _post_rejection(self):
        """받지 않을 POST 면 (상태 코드, 안내문, 읽어서 버릴 본문 바이트 수), 받아도 되면 None."""
        lengths = [value.strip(" \t") for value in self.headers.get_all("Content-Length") or []]
        # 본문 경계가 모호한 요청(조각 전송, 길이 두 개, 숫자가 아닌 길이)은 남은 바이트가 다음 요청으로 읽힐 수 있어 받지 않는다.
        # 길이는 ASCII 숫자 18자리까지만 받는다(그 이상은 어차피 한도를 넘고, 끝없는 자릿수는 변환하지 않는다).
        if (self.headers.get("Transfer-Encoding") is not None or len(lengths) > 1
                or (lengths and not (lengths[0].isascii() and lengths[0].isdigit() and len(lengths[0]) <= 18))):
            return 400, "요청 길이를 확인하지 못했습니다.", 0
        length = int(lengths[0]) if lengths else 0
        origin = self.headers.get("Origin")
        site = self.headers.get("Sec-Fetch-Site")
        # 로그인이 없는 서버라, 브라우저로 연 다른 웹 페이지가 이 주소로 몰래 POST(이력 삭제·작업 중지 등)를 보내는 것을 막는다.
        # Origin 이 없는 요청(스크립트·서버 내부 호출)은 받되, 브라우저가 같은 사이트 요청이 아니라고 표시한 것은 받지 않는다.
        if (origin is not None and not self._same_origin(origin)) or (
                origin is None and site is not None and site.strip(" \t").lower() not in ("same-origin", "none")):
            return (403, "다른 사이트에서 보낸 요청은 처리하지 않습니다. 이 화면을 연 주소 그대로 사용해 주세요(프록시를 쓰면 SIMPLEUI_TRUSTED_ORIGINS 에 화면 주소를 적습니다).",
                    length if length <= 1024 * 1024 else 0)
        try:
            limit = max(1, int(os.environ.get("SIMPLEUI_MAX_BODY_MB") or 1024))
        except ValueError:
            limit = 1024
        if length > limit * 1024 * 1024:
            return 413, f"요청이 너무 큽니다(최대 {limit}MB). 사진 수나 크기를 줄여 주세요.", 0
        return None

    def _same_origin(self, origin):
        """브라우저가 붙인 Origin 이 이 요청이 도착한 주소(Host)와 호스트·포트까지 같은지.

        Host 에 포트가 없으면 Origin 의 스킴 기본 포트로 온 것으로 본다(브라우저는 기본 포트일 때만 포트를 뺀다).
        X-Forwarded-Host 는 주소를 바꿔 전달하는 프록시용이다. 다른 사이트의 페이지는 이 헤더를 붙여 보낼 수 없다
        (붙이면 브라우저가 사전 확인 요청을 보내고, 이 서버는 그 요청을 허용하지 않는다).
        """
        defaults = {"http": 80, "https": 443}
        trusted = {value.strip().lower().rstrip("/") for value in (os.environ.get("SIMPLEUI_TRUSTED_ORIGINS") or "").split(",") if value.strip()}
        if "*" in trusted or origin.strip().lower().rstrip("/") in trusted:
            return True
        try:
            page = urllib.parse.urlsplit(origin.strip())
            if page.scheme not in defaults or not page.hostname:
                return False   # "null"(파일·샌드박스 문서) 등
            default = defaults[page.scheme]
            wanted = (page.hostname.rstrip("."), default if page.port is None else page.port)
            for host in [self.headers.get("Host")] + (self.headers.get("X-Forwarded-Host") or "").split(","):
                if not host or not host.strip():
                    continue
                arrived = urllib.parse.urlsplit(f"{page.scheme}://{host.strip()}")
                if ((arrived.hostname or "").rstrip("."), default if arrived.port is None else arrived.port) == wanted:
                    return True
        except ValueError:
            pass   # 형식이 잘못된 주소·포트
        return False

    @staticmethod
    def _attachment(name):
        """내려받기 이름. 헤더를 깨는 글자(줄바꿈·따옴표)를 빼고, 한글 이름은 RFC 5987 형식으로 함께 싣는다."""
        name = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
        name = "".join(ch for ch in name if ch >= " " and ch not in '"\x7f').strip() or "video.mp4"
        plain = name.encode("ascii", "replace").decode().replace("?", "_")
        return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{urllib.parse.quote(name, safe='')}"

    @staticmethod
    def _error_text(error):
        """화면에 보일 오류 문구. 서버의 전체 경로(사용자 폴더 이름 포함)는 파일 이름만 남긴다."""
        import re
        if isinstance(error, str):
            text = error
        elif isinstance(error, OSError) and getattr(error, "filename", None):
            text = f"{error.strerror or type(error).__name__}: {os.path.basename(str(error.filename))}"
        elif isinstance(error, KeyError):
            text = f"필요한 값이 없습니다: {error.args[0] if error.args else ''}"
        else:
            text = str(error) or type(error).__name__
        # 문구에 섞인 경로에서는 이 서버가 아는 폴더(ComfyUI 폴더, 사용자 홈)의 앞부분만 지운다.
        # 경로처럼 보이는 글을 추측해 고치지 않으므로 다른 문구·주소는 바뀌지 않는다.
        roots = {os.path.dirname(os.path.abspath(str(globals().get("HERE") or "."))), os.path.expanduser("~")}
        for root in sorted((root for root in roots if len(root) > 3), key=len, reverse=True):
            # 구분자는 \ 와 / 가 섞이거나 겹쳐 적혀도(repr) 같은 폴더로 본다. 이름이 이어지는 이웃 폴더(ComfyUI-backup)는 건드리지 않는다.
            names = [re.escape(name) for name in re.split(r"[\\/]+", root) if name]
            pattern = (r"[\\/]+" if root[:1] in "\\/" else r"(?<![A-Za-z0-9])") + r"[\\/]+".join(names) + r"(?:[\\/]+|(?=$|[\s'\"<>|,;)\]]))"
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        return text.encode("utf-8", "replace").decode("utf-8")   # 짝 없는 대리 문자로 응답 인코딩이 깨지지 않게

    def _fail(self, error, code):
        """오류 응답. 이미 응답을 내보내기 시작했다면 두 번째 응답을 섞지 않고 연결을 닫아 끊겼음을 알린다."""
        if getattr(self, "_headers_flushed", False):
            self.close_connection = True
            return
        self._headers_buffer = []   # send_response 뒤 end_headers 전에 실패한 경우의 반쯤 쌓인 헤더를 버린다
        try:
            self._json({"error": self._error_text(error)}, code)
        except OSError:
            self.close_connection = True   # 받을 쪽이 이미 떠남

    def _relay(self, response, disposition=None):
        """ComfyUI /view 응답(영상)을 그대로 전달한다. Range 응답의 상태·헤더를 유지한다.

        길이를 모르거나 알린 길이만큼 오지 않았으면 연결을 닫는다. 열어 둔 연결에서 덜 온 본문 뒤에
        다음 응답이 이어지면 받는 쪽이 영상의 끝과 끊김을 구분하지 못한다.
        """
        with response:
            length = (response.headers.get("Content-Length") or "").strip()
            self.send_response(response.status)
            for key in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                if response.headers.get(key):
                    self.send_header(key, response.headers[key])
            if disposition:
                self.send_header("Content-Disposition", disposition)
            if not length.isdigit():
                self.send_header("Connection", "close")
            self.end_headers()
            sent = 0
            while chunk := response.read(1 << 16):
                self.wfile.write(chunk)
                sent += len(chunk)
            if not length.isdigit() or sent != int(length):
                self.close_connection = True

    def do_GET(self):
        try:
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            if u.path in ("/","/story","/gallery"):
                source=INDEX if u.path=="/" else os.path.join(HERE,"story.html" if u.path=="/story" else "gallery.html")
                self._page(source, "text/html; charset=utf-8")
            elif u.path == "/bulk-progress.js":
                self._page(os.path.join(HERE,"bulk-progress.js"), "text/javascript; charset=utf-8")
            elif u.path == "/queue-pause.js":
                self._page(os.path.join(HERE,"queue-pause.js"), "text/javascript; charset=utf-8")
            elif u.path == "/production-assistant.js":
                self._page(os.path.join(HERE,"production_assistant.js"), "text/javascript; charset=utf-8")
            elif u.path == "/api/production-assistant/conversation":
                self._json(PRODUCTION_ASSISTANT.conversation(revision=q.get("revision"),session=q.get("session")))
            elif u.path == "/api/production-assistant/status":
                self._json(PROMPT_HELPER.status(q.get("id")))
            elif u.path == "/api/queue/bulk-progress":
                self._json(BULK_PROGRESS.snapshot())
            elif u.path == "/api/queue/pause":
                self._json(queue_pause())
            elif u.path == "/api/health":
                # sequence_face_crop = 이 서버가 얼굴 크롭을 아는 버전인지(화면의 버전 확인용),
                # face_detector_ready = 지금 실제로 크롭할 수 있는지(모델·OpenCV 준비 여부)
                self._json({"ok": True, "sequence_face_crop": True, "face_detector_ready": face_detector_ready(),
                            "production_assistant":True,"shared_production_chat":True,"backend_restart_guard": True, "backend_restarting": bool(backend_restart_hold())})
            elif u.path == "/api/status":
                self._json(status_many(q["ids"].split(",")) if "ids" in q else status(q["id"]))
            elif u.path == "/api/history":
                self._json(hist_list(int(q.get("offset") or 0), min(100, int(q.get("limit") or 20)),q.get("id")))
            elif u.path == "/api/queue/bulk-context":
                self._json(bulk_queue_context())
            elif u.path == "/api/gallery":
                with HLOCK:
                    metadata = [{**{key: entry[key] for key in ("id", "mode", "video", "images", "width", "height", "duration", "model", "steps", "seed", "loras", "generation_seconds") if key in entry},
                                 "regenerated": bool((entry.get("ui") or {}).get("regeneration"))}
                                for entry in HIST_DB if entry.get("video")]
                self._json(GALLERY.list(q.get("offset", 0), q.get("limit", 48), q.get("mode", "all"),
                                        q.get("order", "newest"), q.get("q", ""), q.get("known", ""), metadata, q.get("focus")))
            elif u.path == "/api/gallery/progress":
                self._json(gallery_progress())
            elif u.path == "/api/gallery/thumbnail":
                try:
                    b = GALLERY.thumbnail(q.get("id"), q.get("v"))
                except (FileNotFoundError, urllib.error.HTTPError):
                    return self._json({"error": "원본 이미지 정보가 없거나 사진을 불러올 수 없습니다."}, 404)
                self.send_response(200)
                self.send_header("Content-Type", "image/webp")
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "private, max-age=31536000, immutable")
                self.end_headers()
                self.wfile.write(b)
            elif u.path == "/api/translation/status":
                self._json({"ready": TRANSLATOR.ready(), "cpu_only": True})
            elif u.path == "/api/prompt-helper/config":
                self._json({"grok":{"installed":PROMPT_HELPER.grok.exe.is_file(),"signed_in":PROMPT_HELPER.grok.ready()}})
            elif u.path == "/api/prompt-helper/status":
                self._json(PROMPT_HELPER.status(q.get("id")))
            elif u.path == "/api/story/project":
                self._json(STORIES.get(q.get("id")))
            elif u.path == "/api/story/video":
                video=STORIES.video(q.get("id"),q.get("clip"))
                query=urllib.parse.urlencode(video)
                headers={"Range":self.headers["Range"]} if self.headers.get("Range") else {}
                try: response=comfy("/view?"+query,None,headers)
                except urllib.error.HTTPError as error: response=error
                self._relay(response,"attachment; filename=story-video.mp4" if q.get("download") else None)
            elif u.path == "/api/ui-state":
                have = {}
                for part in UI_STATE_PARTS:
                    try: have[part] = int(q.get(part, -1))
                    except (TypeError, ValueError): have[part] = -1
                self._json(ui_state_get(have))
            elif u.path == "/api/settings":
                with SETTINGS_LOCK:
                    settings = _load_json(SETTINGS, {})
                if "name" in q:
                    if q["name"] not in settings:
                        return self._json({"error": "저장된 설정을 찾지 못했습니다."}, 404)
                    self._json(settings[q["name"]])
                else:
                    self._json({"items": [{"name": name, "saved_at": value["saved_at"]} for name, value in sorted(settings.items(), key=lambda item: item[1]["saved_at"], reverse=True)]})
            elif u.path == "/api/input":
                # 이력 불러오기용: 이 화면이 올린 사진만(ComfyUI input 폴더의 simpleui_*)
                name = q.get("name", "")
                if not re.fullmatch(r"simpleui_[0-9a-f]{10}\.(jpg|png|webp)", name):
                    raise ValueError("이 화면이 올린 사진이 아닙니다.")
                try:
                    if q.get("thumbnail") == "1":
                        b, content_type = input_thumbnail(name), "image/webp"
                    else:
                        with comfy("/view?" + urllib.parse.urlencode({"filename": name, "type": "input"})) as response:
                            b, content_type = response.read(), response.headers.get("Content-Type", "image/jpeg")
                except urllib.error.HTTPError:
                    return self._json({"error": "사진 파일이 없습니다(input 폴더에서 지워짐)."}, 404)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(b)))
                if q.get("thumbnail") == "1":
                    self.send_header("Cache-Control", "private, max-age=86400")
                self.end_headers()
                self.wfile.write(b)
            elif u.path == "/api/catalog":
                self._json(catalog())
            elif u.path == "/api/fetch-state":
                self._json({f"{k}|{n}": v for (k, n), v in list(FETCH.items())})   # 조회 중 작업 스레드가 항목을 더해도 안전하게
            elif u.path == "/api/video":
                qs = urllib.parse.urlencode({k: q.get(k, "") for k in ("filename", "subfolder", "type")})
                hdr = {"Range": self.headers["Range"]} if self.headers.get("Range") else {}
                try:
                    r = comfy("/view?" + qs, None, hdr)
                except urllib.error.HTTPError as e:
                    r = e
                self._relay(r, self._attachment(q.get("filename")) if q.get("download") else None)
            else:
                self._json({"error": "not found"}, 404)
        except (ConnectionError, BrokenPipeError):
            # 받는 쪽이 떠났거나 ComfyUI 가 보내다 끊겼다. 반쯤 보낸 응답 뒤에 다음 응답이 이어지지 않게 연결을 닫는다.
            self.close_connection = True
        except urllib.error.HTTPError as e:
            self._fail(comfy_rejection(e), 502)
        except urllib.error.URLError as e:
            self._fail(f"ComfyUI(8188)에 연결할 수 없습니다: {e.reason}", 502)
        except ValueError as e:
            self._fail(e, 400)
        except Exception as e:  # noqa: BLE001
            self._fail(e, 500)

    def do_POST(self):
        try:
            if self.path != "/api/ui-state" and globals().get("backend_restart_hold", lambda: None)():
                self._json({"error":"영상 서버 재시작 중입니다. 대기열 복구가 끝난 뒤 다시 시도해 주세요."}, 503)
                return
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/photo-references":
                self._json(prepare_photo_reference(body))
            elif self.path == "/api/photo-references/release":
                self._json(release_photo_references(body))
            elif self.path == "/api/generate":
                self._json(build_and_queue(body))
            elif self.path == "/api/generate/priority":
                self._json(build_and_queue(body, queue_first=True))
            elif self.path == "/api/queue/pause":
                self._json(queue_pause(body))
            elif self.path == "/api/production-assistant/conversation":
                self._json(PRODUCTION_ASSISTANT.conversation(body))
            elif self.path == "/api/production-assistant/start":
                self._json(PRODUCTION_ASSISTANT.start(body))
            elif self.path == "/api/production-assistant/repair-prompt-state":
                self._json(production_repair_prompt_state(body.get("dry_run",True)))
            elif self.path == "/api/production-assistant/claim":
                self._json(PRODUCTION_ASSISTANT.claim(body))
            elif self.path == "/api/production-assistant/finish":
                self._json(PRODUCTION_ASSISTANT.finish(body))
            elif self.path == "/api/production-assistant/execute":
                self._json(PRODUCTION_ASSISTANT.execute_api(body))
            elif self.path == "/api/translate":
                try:
                    self._json(TRANSLATOR.translate(body.get("text"), body.get("engine", "quality")))
                except TranslationBusy as error:
                    self._json({"error": str(error), "busy": True}, 409)
            elif self.path == "/api/prompt-helper/start":
                if body.get("engine") != "grok": TRANSLATOR.pause()
                self._json(PROMPT_HELPER.start(body))
            elif self.path == "/api/prompt-helper/cancel":
                self._json(PROMPT_HELPER.cancel(body.get("id")))
            elif self.path == "/api/story/save":
                self._json(STORIES.save(body))
            elif self.path == "/api/story/generate":
                self._json(STORIES.start(body.get("id"),body.get("index")))
            elif self.path == "/api/story/approve":
                self._json(STORIES.approve(body.get("id"),body.get("index")))
            elif self.path == "/api/story/merge":
                self._json(STORIES.start_merge(body.get("id")))
            elif self.path == "/api/story/cancel":
                self._json(STORIES.cancel(body.get("id")))
            elif self.path == "/api/queue/bulk-edit":
                self._json(bulk_edit_queue(body))
            elif self.path == "/api/queue/restart":
                self._json(restart_running_prompt(body.get("id")))
            elif self.path == "/api/settings/save":
                self._json(save_settings(body.get("name"), body.get("data")))
            elif self.path == "/api/settings/rename":
                self._json(rename_settings(body.get("name"), body.get("new_name")))
            elif self.path == "/api/settings/delete":
                self._json(delete_settings(body.get("name")))
            elif self.path == "/api/ui-state":
                result = ui_state_save(body)
                self._json(result, 409 if result.get("conflict") else 200)
            elif self.path == "/api/card/fetch":
                kind, name = body.get("kind"), body.get("name")
                if kind not in DIRS or not resolve(kind, name or ""):
                    raise ValueError("목록에 없는 파일입니다.")
                queue_fetch(kind, name)
                self._json({"ok": True})
            elif self.path == "/api/card/save":
                kind, name = body.get("kind"), body.get("name")
                if kind not in DIRS or not resolve(kind, name or ""):
                    raise ValueError("목록에 없는 파일입니다.")
                allowed = {"model": ("steps", "sampler", "scheduler", "shift_video", "shift_audio"),
                           "lora": ("strength", "steps", "trigger")}[kind]
                vals = {k: body["values"][k] for k in allowed if k in (body.get("values") or {})}
                if "trigger" in vals:   # LoRA 트리거 단어(쉼표로 여러 개). 빈 값이면 지움
                    vals["trigger"] = ", ".join(w.strip() for w in str(vals["trigger"])[:200].split(",") if w.strip())
                with CLOCK:
                    card = CARD_DB[kind].setdefault(name, {})
                    # 기존 사용자 값에 덮어쓴다(강도만 저장해도 트리거가 지워지지 않게)
                    card["user"] = {k: v for k, v in {**(card.get("user") or {}), **vals}.items() if v not in ("", None)}
                    _save_json(CARDS, CARD_DB)
                self._json(card_for(kind, name))
            elif self.path == "/api/preset/save":
                self._json(save_preset(body.get("name"), body.get("data")))
            elif self.path == "/api/preset/delete":
                self._json(delete_preset(body.get("name")))
            elif self.path == "/api/history/delete":
                self._json(delete_history(body))
            elif self.path == "/api/gallery/update":
                self._json(GALLERY.update(body))
            elif self.path == "/api/gallery/regenerate":
                self._json(regenerate_gallery(body))
            elif self.path == "/api/open-folder":
                folder = os.path.join(OUTPUT, "video", datetime.date.today().isoformat())
                os.startfile(folder if os.path.isdir(folder) else os.path.join(OUTPUT, "video"))
                self._json({"ok": True})
            elif self.path == "/api/open-models":
                sub = {"model": "diffusion_models", "lora": "loras"}.get(body.get("kind"), "")
                os.startfile(os.path.join(MODELS, sub))
                self._json({"ok": True})
            elif self.path == "/api/cancel":
                # 이 화면에서 만든 그 작업만 멈춘다(다른 작업은 건드리지 않음)
                ids = [x for x in (body.get("ids") or [body.get("id")]) if x]
                if ids:
                    hdr = {"Content-Type": "application/json"}
                    with QUEUE_EDIT_LOCK:
                        comfy("/queue", json.dumps({"delete": ids}).encode(), hdr)      # 아직 안 돈 것부터 빼고
                        for pid in ids:                                                  # 돌고 있는 것만 멈춤
                            comfy("/interrupt", json.dumps({"prompt_id": pid}).encode(), hdr)
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)
        except urllib.error.HTTPError as e:
            self._fail(comfy_rejection(e), 502)
        except urllib.error.URLError as e:
            self._fail(f"ComfyUI(8188)에 연결할 수 없습니다: {e.reason}", 502)
        except Exception as e:  # noqa: BLE001
            self._fail(e, 400)

    def log_message(self, fmt, *a):
        # 요청 한 건에 한 줄만 남긴다. 오류 응답은 오류 기록(a[0] 이 숫자)과 요청 기록이 따로 오므로 요청 기록만 쓴다.
        # 잘못된 요청은 command·path 가 없을 수 있다(예: https 로 잘못 접속한 브라우저의 TLS 바이트).
        # 예전에는 여기서 예외가 나 요청마다 스택이 찍혔다.
        if not str(fmt).startswith('"%s"'):
            return
        line = a[0] if a and isinstance(a[0], str) else ""
        # 자주 부르는 조회만 숨긴다(이력 삭제 같은 POST 는 남김)
        if line.startswith("GET ") and any(s in line for s in ("/api/production-assistant/status", "/api/production-assistant/conversation", "/api/status", "/api/fetch-state", "/api/history", "/api/input", "/api/video", "/api/gallery", "/api/queue/bulk-context", "/api/ui-state")):
            return
        command, path = getattr(self, "command", None), getattr(self, "path", None)
        if command and path:
            # 경로만 남긴다: 주소의 ?뒤에는 저장 설정 이름·파일 이름 같은 값이 실릴 수 있다
            print("%s %s" % (command, str(path).split("?", 1)[0]), flush=True)
        else:
            print("알 수 없는 요청을 거절했습니다(http:// 주소로 접속했는지 확인).", flush=True)


if __name__ == "__main__":
    try:
        recovered = bulk_queue_editor().recover({entry["id"]:entry for entry in HIST_DB})
        if recovered:print(f"대기열 수정 이력 복구: {recovered}개",flush=True)
    except (OSError,ValueError,KeyError,TypeError):
        print("대기열 수정 이력 복구 보류: 복구 사본을 유지합니다.",flush=True)
    for client_id in set([CLIENT_ID, *RESTART_CLIENT_IDS]):
        threading.Thread(target=ws_loop, args=(client_id,), daemon=True).start()
    threading.Thread(target=fetch_worker, daemon=True).start()
    print(f"H3 간단 화면: http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
