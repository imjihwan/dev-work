"""MiniMax H3 간단 입력 화면 (기본 http://127.0.0.1:8190).

template_api.json = 원본 DaSiWa 워크플로를 ComfyUI 에서 한 번 실행한 API 프롬프트(노드 구조의 틀).
이 화면은 틀의 노드 구조는 그대로 두고 값만 바꿔서 ComfyUI(8188)에 넘긴다:
  사진·프롬프트·화면비·해상도·길이·시드 + 모드(REF2VA/FL2VA/I2VA)·모델 파일·스텝·샘플러·shift·LoRA(최대 10).

모델·LoRA 목록은 ComfyUI 가 보는 models 폴더 목록을 그대로 쓰고, 파일마다 '카드'(cards.json)에
자동 판정(파일 헤더)·Civitai 정보(해시 조회)·사용자 기본값을 모아 둔다. 조합은 presets.json.
"""
import base64, datetime, hashlib, html, io, json, os, queue, random, re, struct, threading, time
import urllib.error, urllib.parse, urllib.request, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import lru_cache

from PIL import Image, ImageOps
from prompt_helper import PromptHelper
from local_translate import LocalTranslator, TranslationBusy
from story import StoryProjects
from gallery import VideoGallery

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
    with PLOCK:
        st = PROGRESS.get(pid)
        if st is None:
            return
        if t == "execution_start":
            st["pct"] = 0.0
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
    return urllib.request.urlopen(req, timeout=timeout)


@lru_cache(maxsize=256)
def input_thumbnail(name, size=192):
    with comfy("/view?" + urllib.parse.urlencode({"filename": name, "type": "input"})) as response:
        with Image.open(response) as source, ImageOps.exif_transpose(source) as image:
            image.thumbnail((size, size))
            with io.BytesIO() as output:
                image.save(output, format="WEBP", quality=75, method=1)
                return output.getvalue()


def upload(raw, ext):
    name = f"simpleui_{uuid.uuid4().hex[:10]}.{ext}"
    bnd = uuid.uuid4().hex
    body = (f'--{bnd}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + raw + f"\r\n--{bnd}--\r\n".encode()
    return json.load(comfy("/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={bnd}"}))["name"]


# =====================================================================
# 모델·LoRA 카드
# =====================================================================
CLOCK = threading.RLock()
DIRS = {"model": ("diffusion_models", "unet"), "lora": ("loras",)}


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


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
        data = _load_json(UI_STATE, {})
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
        settings = _load_json(SETTINGS, {})
        settings[name] = {"data": data, "saved_at": time.time()}
        _save_json(SETTINGS, settings)
    return {"ok": True, "name": name}


def rename_settings(name, new_name):
    name = str(name or '').strip()
    new_name = str(new_name or '').strip()
    if not new_name or len(new_name) > 60:
        raise ValueError('새 설정 이름은 1~60자로 입력해 주세요.')
    with SETTINGS_LOCK:
        settings = _load_json(SETTINGS, {})
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
        settings = _load_json(SETTINGS, {})
        if name not in settings:
            raise ValueError('저장된 설정을 찾지 못했습니다.')
        del settings[name]
        _save_json(SETTINGS, settings)
    return {'ok': True, 'name': name}


def _seed(path):
    """처음 설치한 PC: cards.json / presets.json 이 없으면 함께 배포한 *.seed.json 으로 시작."""
    seed = path.replace(".json", ".seed.json")
    if not os.path.exists(path) and os.path.exists(seed):
        _save_json(path, _load_json(seed, {}))


_seed(CARDS)
_seed(PRESETS)

# ---------- 작업 이력: 생성할 때의 설정·프롬프트·사진 ↔ 결과 영상 (history.json, 이 PC 에만) ----------
HIST = os.path.join(HERE, "history.json")
HLOCK = threading.Lock()
HIST_DB = _load_json(HIST, [])         # 오래된 것 → 최근 순
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
            links = [{**{key: e[key] for key in ("video", "images") if key in e},
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
                update = e.get("state") != st["state"] or (st.get("video") and e.get("video") != st["video"])
                if update:
                    e.update(state=st["state"], video=st.get("video") or e.get("video"), error=st.get("error"), t_end=time.time())
                    _save_json(HIST, HIST_DB)
                if e.get("video"):
                    changed = {key: e[key] for key in ("video", "images", "regenerated") if key in e}
                    changed["regenerated"] = bool(e.get("regenerated") or (e.get("ui") or {}).get("regeneration"))
                break
    if changed is not None:
        # 갤러리 연결은 이력 잠금을 푼 뒤에: 갤러리 잠금을 기다리는 동안 이력·상태 조회가 막히지 않게
        try:
            GALLERY.remember([changed])
        except OSError:
            pass  # A later gallery refresh can retry saving the association.
CARD_DB = _load_json(CARDS, {"model": {}, "lora": {}})
CARD_DB.setdefault("model", {})
CARD_DB.setdefault("lora", {})
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
        e = {"steps": a.get("steps_hint") or (4 if turbo else 20),
             "sampler": "euler" if turbo else "res_multistep", "scheduler": "simple",
             "shift_video": 10.0, "shift_audio": 3.0}
        if c.get("steps"):
            e["steps"] = c["steps"]
    else:
        e = {"strength": c.get("strength", 1.0), "steps": a.get("steps_hint") if a.get("turbo") else None}
    e.update({k: v for k, v in u.items() if v is not None})
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


def catalog():
    models = object_options("UNETLoader", "unet_name")
    loras = object_options("LoraLoaderModelOnly", "lora_name")
    out = {"models": [card_for("model", n) for n in models], "loras": [card_for("lora", n) for n in loras],
           "samplers": object_options("KSamplerSelect", "sampler_name"),
           "schedulers": object_options("BasicScheduler", "scheduler"),
           "presets": _load_json(PRESETS, {}), "default": template_defaults(),
           "capabilities": {"queue_edit": True, "bulk_edit": True, "bulk_edit_all": True, "photo_sequence": True, "saved_settings": True, "restart_running": True, "priority_queue": True}}
    # 작은 LoRA 는 처음 보면 Civitai 정보를 자동으로 가져온다(큰 본체 모델은 버튼으로)
    for c in out["loras"]:
        if "civitai" not in c and c["fetch"]["state"] == "idle" and (c["auto"].get("size_gb") or 99) < 4:
            queue_fetch("lora", c["name"])
            c["fetch"] = FETCH[("lora", c["name"])]
    return out


# =====================================================================
# 생성
# =====================================================================
def replace_queued_prompt(pid, prompt):
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
                                    "prompt": prompt, "client_id": CLIENT_ID}).encode(), headers))
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
        return json.loads(json.dumps(entry))


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
        referenced = [int(value) for value in re.findall(r"<Picture\s*(\d+)>", source["prompt"], re.I)]
        if referenced and max(referenced) > len(target["images"]):
            raise ValueError("복사할 프롬프트가 대상에 없는 참조 사진 번호를 사용합니다. 다른 영상을 골라 주세요.")
        values = dict(target, count=1, edit_id=None, photo_sequence=False, prompt=source["prompt"])
        for key in ("model", "steps", "sampler", "scheduler", "shift_video", "shift_audio", "loras"):
            values[key] = source[key]
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
        items = []
        for index, name in enumerate(target["images"]):
            if not isinstance(name, str) or not re.fullmatch(r"simpleui_[0-9a-f]{10}\.(jpg|png|webp)", name):
                raise ValueError("원래 참조 사진 정보를 확인할 수 없습니다.")
            with comfy("/view?" + urllib.parse.urlencode({"filename": name, "type": "input"})) as response:
                with Image.open(response) as image:
                    width, height = image.size
            items.append({"id": "image-" + uuid.uuid4().hex, "enabled": True, "order": index, "slot": index,
                          "start": index, "duration": 1, "type": "image", "value": name, "thumbnail": None,
                          "source_width": width, "source_height": height})
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


def build_and_queue(req, reference=None, prepare_only=False, queue_first=False):
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

    with open(TEMPLATE, encoding="utf-8-sig") as handle:
        p = json.load(handle)

    # --- 모델·샘플링·LoRA (값만 바꿈) ---
    models = set(object_options("UNETLoader", "unet_name"))
    model = req.get("model") or p[LOADERS[1]]["inputs"]["unet_name"]
    if model not in models:
        raise ValueError(f"모델 파일이 목록에 없습니다: {model}")
    mc = card_for("model", model)
    if mc["auto"].get("h3") is False or mc["auto"].get("fmt") == "gguf":
        raise ValueError(f"이 화면에서 쓸 수 없는 모델입니다: {mc['auto'].get('note')}")
    for k in LOADERS:
        p[k]["inputs"]["unet_name"] = model
    steps = int(req.get("steps") or p[SCHED]["inputs"]["steps"])
    if not 1 <= steps <= 60:
        raise ValueError("스텝은 1~60 사이로 정해 주세요.")
    p[SCHED]["inputs"]["steps"] = steps
    if req.get("scheduler"):
        p[SCHED]["inputs"]["scheduler"] = req["scheduler"]
    if req.get("sampler"):
        p[SAMPLER]["inputs"]["sampler_name"] = req["sampler"]
    for k in ("shift_video", "shift_audio"):
        if req.get(k) not in (None, ""):
            p[SHIFT]["inputs"][k] = float(req[k])
    loras = [x for x in (req.get("loras") or []) if x.get("name")]
    if len(loras) > LORA_SLOTS:
        raise ValueError(f"LoRA 는 최대 {LORA_SLOTS}개까지입니다.")
    known = set(object_options("LoraLoaderModelOnly", "lora_name"))
    rows = []
    for x in loras:
        if x["name"] not in known:
            raise ValueError(f"LoRA 파일이 목록에 없습니다: {x['name']}")
        if card_for("lora", x["name"])["auto"].get("h3") is False:
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
        raw = base64.b64decode(b64)
        raws.append(raw)
        im = Image.open(io.BytesIO(raw))
        display_size = ImageOps.exif_transpose(im).size if sequence else im.size
        sizes.append(display_size)
        ext = {"PNG": "png", "WEBP": "webp"}.get(im.format, "jpg")
        names.append(upload(raw, ext))
        # REF2VA: slot = 사진 번호 / FL2VA: slot 0 = 첫 프레임, 1 = 끝 프레임 / I2VA: slot 0
        items.append({"id": f"image-{uuid.uuid4().int % 10**13}-{i}", "enabled": True, "order": i, "slot": i,
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
    tl["resolution"].update(aspect=aspect, resolution=resolution if resolution in RES_MP else "auto")
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
            return None
        key = (names[index] if sequence else names[0])
        if key not in side_cache:
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
    # 반복: 같은 구성으로 시드만 바꿔 count 개를 대기열에 넣는다.
    # 시드를 적었으면 그 값부터 1씩 늘리고(재현 가능), 비웠으면 매번 랜덤.
    count = len(imgs) if sequence else int(req.get("count") or 1)
    if not 1 <= count <= 20:
        raise ValueError("반복 횟수는 1~20 사이로 정해 주세요.")
    seed = str(req.get("seed") or "").strip()
    seeds = [int(seed) + i for i in range(count)] if seed else [random.randint(1, 2**53) for _ in range(count)]
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
               "shift_video": p[SHIFT]["inputs"]["shift_video"], "shift_audio": p[SHIFT]["inputs"]["shift_audio"],
               "loras": [{"name": x["name"], "strength": float(x.get("strength", 1))} for x in loras],
               "aspect": aspect, "resolution": resolution, "duration": duration, "width": j["width"], "height": j["height"],
               "count": count, "anchor": anchor, "prompt": text, "images": j["images"], "face_side": j.get("face_side"),
               "sequence_index": j["sequence_index"], "ui": req.get("ui")} for j in done]
    priority_number = None
    try:
        for index, s in enumerate(seeds):
            job_names = names[index:] + names[:index] if sequence else names
            job_w, job_h = canvas(aspect, resolution, sizes[index] if sequence else sizes[0])
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
                if count != 1 or edit_id:
                    raise ValueError("별도 워크플로 준비는 한 편씩 진행합니다.")
                return {"prompt":p,"images":list(names),"width":w,"height":h,"seed":s}
            if edit_id:
                r = replace_queued_prompt(edit_id, p)
            elif queue_first:
                r = queue_prompt_first(p, slots=count, number=priority_number)
                priority_number = r["number"] + 1
            else:
                r = json.load(comfy("/prompt", json.dumps({"prompt": p, "client_id": CLIENT_ID}).encode(),
                                   {"Content-Type": "application/json"}))
            if r.get("node_errors") and not edit_id:
                raise ValueError(json.dumps(r["node_errors"], ensure_ascii=False)[:500])
            with PLOCK:
                PROGRESS[r["prompt_id"]] = {"classes": classes, "pct": 0.0, "label": "대기"}
            jobs.append({"id": r["prompt_id"], "seed": s, "width": job_w, "height": job_h,
                         "model": model, "steps": steps, "anchor": anchor, "prompt_verified": bool(edit_id and r.get("prompt_verified")), "face_side": face_side_for(index if sequence else 0),
                         "images": list(job_names), "sequence_index": index + 1 if sequence else reference["entry"].get("sequence_index") if reference else None})
    except Exception as exc:
        # 여러 편 등록 중 실패: 이미 ComfyUI 에 들어간 작업은 이력에 남겨 추적·중지·결과 연결이 되게 한다
        if jobs and not edit_id:
            hist_add(make_entries(jobs))
            raise ValueError(f"{len(jobs)}개는 대기열에 등록했고 그다음 등록에서 실패했습니다: {exc}") from exc
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
            _save_json(HIST, HIST_DB)
    else:
        hist_add(entries)
    return {"jobs": jobs, "id": jobs[0]["id"], "seed": jobs[0]["seed"], "width": w, "height": h,
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


def bulk_edit_queue(req):
    ids = req.get("edit_ids")
    fields = req.get("bulk_fields")
    all_pending = req.get("all_pending", False)
    if not isinstance(all_pending, bool):
        raise ValueError("전체 대기항목 선택 상태가 올바르지 않습니다.")
    if not all_pending and (not isinstance(ids, list) or not ids or not all(isinstance(pid, str) for pid in ids)):
        raise ValueError("수정할 대기 항목을 선택해 주세요.")
    if not isinstance(fields, list) or not fields or set(fields) - {"content", "model", "video", "anchor"}:
        raise ValueError("적용할 수정 항목을 선택해 주세요.")
    if "anchor" in fields and not isinstance(req.get("anchor"), bool):
        raise ValueError("첫 장면 고정 상태가 올바르지 않습니다.")
    pending = {item[1]: item for item in sorted(json.load(comfy("/queue"))["queue_pending"], key=lambda item: item[0])}
    with HLOCK:
        entries = {e["id"]: json.loads(json.dumps(e)) for e in HIST_DB}
    if all_pending:
        ids = [pid for pid in pending if pid in entries]
    updated, failed = [], []
    for pid in dict.fromkeys(ids):
        if pid not in pending or pid not in entries:
            failed.append({"id": pid, "error": "이미 시작됐거나 대기열에서 빠진 항목입니다."})
            continue
        entry = entries[pid]
        values = dict(entry, edit_id=pid, count=1, photo_sequence=False)
        ui = json.loads(json.dumps(entry.get("ui") or {}))
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
            for key in ("model", "steps", "sampler", "scheduler", "shift_video", "shift_audio", "loras"):
                if key in req: values[key] = req[key]
            if "trig" in incoming: ui["trig"] = incoming["trig"]
        if "anchor" in fields:
            values["anchor"] = req["anchor"]
        if "video" in fields:
            for key in ("aspect", "resolution", "duration"):
                if key in req:
                    values[key] = req[key]
                    form[key] = req[key]
        ui["f"] = form
        values["ui"] = ui
        try:
            result = build_and_queue(values, reference={"entry": entry, "prompt": pending[pid][2]})
            updated.extend(dict(job, loras=values.get("loras", [])) for job in result["jobs"])
        except (ValueError, OSError) as exc:
            failed.append({"id": pid, "error": str(exc)})
    return {"jobs": updated, "failed": failed, "bulk_edit": True, "all_pending": all_pending, "target_count": len(set(ids)), "verified_count": sum(bool(job.get("prompt_verified")) for job in updated)}


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
        return {"state": "running", "pct": round(st.get("pct", 0)), "label": st.get("label", "")}
    pend = [x[1] for x in sorted(q.get("queue_pending", []), key=lambda x: x[0])]
    if pid in pend:
        return {"state": "queued", "position": pend.index(pid) + 1}
    return None


def _status(pid, q=None):
    held = backend_restart_hold(pid)
    if held:
        with PLOCK:
            if pid in PROGRESS:
                PROGRESS[pid]["pct"] = 0.0
        return held
    # 이미 받은 대기열 스냅샷이 있으면 그걸로 먼저 판정(대기·실행 중인 작업은 history 에 아직 없다)
    if q is not None:
        found = _queue_state(pid, q)
        if found:
            return found
    h = json.load(comfy(f"/history/{urllib.parse.quote(pid)}"))
    if pid in h:
        e = h[pid]
        st = e.get("status", {})
        if st.get("status_str") == "success":
            return {"state": "done", "video": video_of(e)}
        msg = ""
        for m in st.get("messages", []):
            if m[0] == "execution_error":
                msg = m[1].get("exception_message", "")
            elif m[0] == "execution_interrupted":
                msg = "중지됨(이 화면의 중지 버튼이나 ComfyUI 화면에서 멈춤)"
        return {"state": "error", "error": msg or st.get("status_str", "error")}
    if q is None:
        q = json.load(comfy("/queue"))
    return _queue_state(pid, q) or {"state": "unknown"}


def hist_list(offset, limit):
    """최근 순. 아직 결과가 없는 항목은 지금 상태를 물어 채운다(ComfyUI 가 잊은 작업은 '결과 없음')."""
    with HLOCK:
        items = list(reversed(HIST_DB))
    page = items[offset:offset + limit]
    q = None  # 페이지마다 대기열은 한 번만 받는다(대기 수백 건이면 항목마다 받던 것이 수백 번이 됐다)
    for i, e in enumerate(page):
        if e.get("state") in ("queued", "running"):
            try:
                if q is None:
                    q = json.load(comfy("/queue"))
                st = _status(e["id"], q)
            except Exception:  # noqa: BLE001 — ComfyUI 꺼짐: 지금 상태만 모름
                continue
            if st["state"] == "unknown":
                st = {"state": "lost", "error": "결과 없음(ComfyUI 재시작 등으로 중단)"}
            hist_result(e["id"], st)
            page[i] = dict(e, **{k: v for k, v in st.items() if k in ("state", "video", "error", "pct", "position")})
    return {"items": page, "total": len(items)}


def gallery_progress():
    """Return progress and regeneration states, without prompts, images or result paths."""
    with GALLERY_PROGRESS_LOCK:
        now = time.monotonic()
        if GALLERY_PROGRESS_CACHE["value"] is not None and now - GALLERY_PROGRESS_CACHE["at"] < 2:
            return GALLERY_PROGRESS_CACHE["value"]
        state = json.load(comfy("/queue", timeout=8))
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
            value = (PROGRESS.get(running[0][1]) or {}).get("pct") if running else None
        pct = max(0, min(100, round(value))) if isinstance(value, (int, float)) else None
        with HLOCK:
            jobs = [{"id": entry["id"], "state": "running" if any(item[1] == entry["id"] for item in running)
                     else "queued" if entry["id"] in active else entry.get("state", "unknown"),
                     "completed_at": entry.get("t_end", 0)} for entry in HIST_DB if (entry.get("ui") or {}).get("regeneration")]
        result = {"running": bool(running), "pct": pct, "pending": len(pending), "jobs": jobs}
        GALLERY_PROGRESS_CACHE.update(at=time.monotonic(), value=result)
        return result


def track_story_job(pid,graph):
    with PLOCK:
        PROGRESS[pid]={"classes":{key:node["class_type"] for key,node in graph.items()},"pct":0.0,"label":"대기"}


STORIES=StoryProjects(os.path.join(HERE,"story_data"),OUTPUT,
    lambda request,reference:build_and_queue(request,reference,prepare_only=True),
    comfy,upload,_status,track_story_job,client_id=CLIENT_ID)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        try:
            if u.path in ("/","/story","/gallery"):
                source=INDEX if u.path=="/" else os.path.join(HERE,"story.html" if u.path=="/story" else "gallery.html")
                with open(source,"rb") as page: b=page.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
            elif u.path == "/api/health":
                # sequence_face_crop = 이 서버가 얼굴 크롭을 아는 버전인지(화면의 버전 확인용),
                # face_detector_ready = 지금 실제로 크롭할 수 있는지(모델·OpenCV 준비 여부)
                self._json({"ok": True, "sequence_face_crop": True, "face_detector_ready": face_detector_ready(),
                            "backend_restart_guard": True, "backend_restarting": bool(backend_restart_hold())})
            elif u.path == "/api/status":
                self._json(status(q["id"]))
            elif u.path == "/api/history":
                self._json(hist_list(int(q.get("offset") or 0), min(100, int(q.get("limit") or 20))))
            elif u.path == "/api/queue/bulk-context":
                self._json(bulk_queue_context())
            elif u.path == "/api/gallery":
                with HLOCK:
                    metadata = [{**{key: entry[key] for key in ("id", "mode", "video", "images", "width", "height", "duration", "model", "steps", "seed", "loras") if key in entry},
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
                with response:
                    self.send_response(response.status)
                    for key in ("Content-Type","Content-Length","Content-Range","Accept-Ranges"):
                        if response.headers.get(key): self.send_header(key,response.headers[key])
                    if q.get("download"): self.send_header("Content-Disposition","attachment; filename=story-video.mp4")
                    self.end_headers()
                    while chunk:=response.read(65536): self.wfile.write(chunk)
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
                self._json({f"{k}|{n}": v for (k, n), v in FETCH.items()})
            elif u.path == "/api/video":
                qs = urllib.parse.urlencode({k: q.get(k, "") for k in ("filename", "subfolder", "type")})
                hdr = {"Range": self.headers["Range"]} if self.headers.get("Range") else {}
                try:
                    r = comfy("/view?" + qs, None, hdr)
                except urllib.error.HTTPError as e:
                    r = e
                self.send_response(r.status)
                for k in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                    if r.headers.get(k):
                        self.send_header(k, r.headers[k])
                if q.get("download"):
                    self.send_header("Content-Disposition", f'attachment; filename="{q.get("filename")}"')
                self.end_headers()
                while chunk := r.read(1 << 16):
                    self.wfile.write(chunk)
            else:
                self._json({"error": "not found"}, 404)
        except (ConnectionError, BrokenPipeError):
            pass
        except urllib.error.URLError as e:
            self._json({"error": f"ComfyUI(8188)에 연결할 수 없습니다: {e}"}, 502)
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        try:
            if self.path != "/api/ui-state" and globals().get("backend_restart_hold", lambda: None)():
                self._json({"error":"영상 서버 재시작 중입니다. 대기열 복구가 끝난 뒤 다시 시도해 주세요."}, 503)
                return
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/generate":
                self._json(build_and_queue(body))
            elif self.path == "/api/generate/priority":
                self._json(build_and_queue(body, queue_first=True))
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
                name = (body.get("name") or "").strip()[:60]
                if not name:
                    raise ValueError("조합 이름을 적어 주세요.")
                ps = _load_json(PRESETS, {})
                ps[name] = body.get("data") or {}
                _save_json(PRESETS, ps)
                self._json(ps)
            elif self.path == "/api/preset/delete":
                ps = _load_json(PRESETS, {})
                ps.pop(body.get("name"), None)
                _save_json(PRESETS, ps)
                self._json(ps)
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
        except urllib.error.URLError as e:
            self._json({"error": f"ComfyUI(8188)에 연결할 수 없습니다: {e}"}, 502)
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 400)

    def log_message(self, fmt, *a):
        line = a[0] if a else ""
        # 자주 부르는 조회만 숨긴다(이력 삭제 같은 POST 는 남김)
        if not (line.startswith("GET ") and any(s in line for s in ("/api/status", "/api/fetch-state", "/api/history", "/api/input", "/api/video", "/api/gallery", "/api/queue/bulk-context", "/api/ui-state"))):
            print("%s %s" % (self.command, self.path), flush=True)


if __name__ == "__main__":
    for client_id in set([CLIENT_ID, *RESTART_CLIENT_IDS]):
        threading.Thread(target=ws_loop, args=(client_id,), daemon=True).start()
    threading.Thread(target=fetch_worker, daemon=True).start()
    print(f"H3 간단 화면: http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
