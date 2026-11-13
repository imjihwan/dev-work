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

from PIL import Image

COMFY = "http://127.0.0.1:8188"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEMPLATE = os.path.join(HERE, "template_api.json")
INDEX = os.path.join(HERE, os.environ.get("SIMPLEUI_INDEX", "index.html"))
PORT = int(os.environ.get("SIMPLEUI_PORT", "8190"))
CARDS = os.path.join(HERE, "cards.json")
PRESETS = os.path.join(HERE, "presets.json")
OUTPUT = os.path.join(ROOT, "output")
MODELS = os.path.join(ROOT, "models")
DIRECTOR, SEED, SAVE = "2730", "2739", "2568"
LOADERS = ("1512:2586", "1512:2588")      # Director 의 fl2va_model / ref2va_model 입력(선택된 모드 쪽만 실제로 불러옴)
SCHED, SAMPLER, SHIFT, LORA = "1512:2590", "1512:2598", "1512:2692", "2678"
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


def ws_loop():
    import asyncio, aiohttp

    async def run():
        while True:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(f"ws://127.0.0.1:8188/ws?clientId={CLIENT_ID}", heartbeat=30) as ws:
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
HIST_MAX = 1000


def hist_add(entries):
    with HLOCK:
        HIST_DB.extend(entries)
        del HIST_DB[:-HIST_MAX]
        _save_json(HIST, HIST_DB)


def hist_result(pid, st):
    """작업이 끝나면(완료·오류) 이력에 결과를 적는다. 상태가 바뀔 때만 파일에 쓴다."""
    if st.get("state") not in ("done", "error", "lost"):
        return
    with HLOCK:
        for e in HIST_DB:
            if e["id"] == pid and e.get("state") != st["state"]:
                e.update(state=st["state"], video=st.get("video"), error=st.get("error"), t_end=time.time())
                _save_json(HIST, HIST_DB)
                return
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
    p = json.load(open(TEMPLATE, encoding="utf-8-sig"))
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
           "presets": _load_json(PRESETS, {}), "default": template_defaults()}
    # 작은 LoRA 는 처음 보면 Civitai 정보를 자동으로 가져온다(큰 본체 모델은 버튼으로)
    for c in out["loras"]:
        if "civitai" not in c and c["fetch"]["state"] == "idle" and (c["auto"].get("size_gb") or 99) < 4:
            queue_fetch("lora", c["name"])
            c["fetch"] = FETCH[("lora", c["name"])]
    return out


# =====================================================================
# 생성
# =====================================================================
def build_and_queue(req):
    text = (req.get("prompt") or "").strip()
    if not text:
        raise ValueError("프롬프트가 비어 있습니다.")
    mode = req.get("mode") or "REF2VA"
    imgs = req.get("images") or []
    need = {"REF2VA": (1, 9), "FL2VA": (2, 2), "I2VA": (1, 1)}.get(mode)
    if not need:
        raise ValueError(f"지원하지 않는 모드: {mode}")
    if not need[0] <= len(imgs) <= need[1]:
        raise ValueError({"REF2VA": "사진은 1~9장 넣어 주세요.", "FL2VA": "첫·끝 프레임 사진 2장이 필요합니다.",
                          "I2VA": "첫 프레임 사진 1장이 필요합니다."}[mode])
    duration = float(req.get("duration") or 5)
    if not 1 <= duration <= 15:
        raise ValueError("길이는 1~15초 사이로 정해 주세요(H3 최대 15초).")

    p = json.load(open(TEMPLATE, encoding="utf-8-sig"))

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
    items, sizes, names = [], [], []
    for i, data_url in enumerate(imgs):
        head, b64 = data_url.split(",", 1)
        raw = base64.b64decode(b64)
        im = Image.open(io.BytesIO(raw))
        sizes.append(im.size)
        ext = {"PNG": "png", "WEBP": "webp"}.get(im.format, "jpg")
        names.append(upload(raw, ext))
        # REF2VA: slot = 사진 번호 / FL2VA: slot 0 = 첫 프레임, 1 = 끝 프레임 / I2VA: slot 0
        items.append({"id": f"image-{uuid.uuid4().int % 10**13}-{i}", "enabled": True, "order": i, "slot": i,
                      "start": i, "duration": 1, "type": "image", "value": names[-1], "thumbnail": None,
                      "source_width": im.size[0], "source_height": im.size[1]})

    aspect = req.get("aspect") or "auto"
    resolution = req.get("resolution") or "auto"
    w, h = canvas(aspect, resolution, sizes[0])

    d = p[DIRECTOR]["inputs"]
    tl = json.loads(d["timeline_data"])
    tl["items"] = items
    tl["builder_state"]["simple_prompt"] = text
    tl["builder_state"]["duration"] = duration
    tl["builder_state"]["mode"] = mode
    tl["resolved_prompt"] = text
    tl["continuity"]["continuation_prompt"] = text
    tl["resolution"].update(aspect=aspect, resolution=resolution if resolution in RES_MP else "auto")
    bs = json.loads(d["builder_state"])
    bs.update(simple_prompt=text, duration=duration, mode=mode)
    d.update(mode=mode, prompt=text, width=w, height=h, duration=duration,
             timeline_data=json.dumps(tl, ensure_ascii=False), builder_state=json.dumps(bs, ensure_ascii=False))
    # 반복: 같은 구성으로 시드만 바꿔 count 개를 대기열에 넣는다.
    # 시드를 적었으면 그 값부터 1씩 늘리고(재현 가능), 비웠으면 매번 랜덤.
    count = int(req.get("count") or 1)
    if not 1 <= count <= 20:
        raise ValueError("반복 횟수는 1~20 사이로 정해 주세요.")
    seed = str(req.get("seed") or "").strip()
    seeds = [int(seed) + i for i in range(count)] if seed else [random.randint(1, 2**53) for _ in range(count)]
    classes = {k: v["class_type"] for k, v in p.items()}
    jobs = []
    for s in seeds:
        p[SEED]["inputs"]["seed_value"] = s
        r = json.load(comfy("/prompt", json.dumps({"prompt": p, "client_id": CLIENT_ID}).encode(),
                            {"Content-Type": "application/json"}))
        if r.get("node_errors"):
            raise ValueError(json.dumps(r["node_errors"], ensure_ascii=False)[:500])
        with PLOCK:
            PROGRESS[r["prompt_id"]] = {"classes": classes, "pct": 0.0, "label": "대기"}
        jobs.append({"id": r["prompt_id"], "seed": s})
    now = time.time()
    hist_add([{"id": j["id"], "t": now, "seed": j["seed"], "state": "queued", "video": None, "error": None,
               "mode": mode, "model": model, "steps": steps,
               "sampler": p[SAMPLER]["inputs"]["sampler_name"], "scheduler": p[SCHED]["inputs"]["scheduler"],
               "shift_video": p[SHIFT]["inputs"]["shift_video"], "shift_audio": p[SHIFT]["inputs"]["shift_audio"],
               "loras": [{"name": x["name"], "strength": float(x.get("strength", 1))} for x in loras],
               "aspect": aspect, "resolution": resolution, "duration": duration, "width": w, "height": h,
               "count": count, "prompt": text, "images": names, "ui": req.get("ui")} for j in jobs])
    return {"jobs": jobs, "id": jobs[0]["id"], "seed": jobs[0]["seed"], "width": w, "height": h,
            "model": os.path.basename(model.replace("\\", "/")), "steps": steps, "loras": len(loras), "mode": mode}


def video_of(entry):
    for g in (entry.get("outputs", {}).get(SAVE, {}) or {}).get("gifs", []) or []:
        return {"filename": g["filename"], "subfolder": g.get("subfolder", ""), "type": g.get("type", "output")}
    return None


def status(pid):
    st = _status(pid)
    hist_result(pid, st)
    return st


def _status(pid):
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
    q = json.load(comfy("/queue"))
    if any(x[1] == pid for x in q.get("queue_running", [])):
        with PLOCK:
            st = PROGRESS.get(pid) or {}
        return {"state": "running", "pct": round(st.get("pct", 0)), "label": st.get("label", "")}
    pend = [x[1] for x in sorted(q.get("queue_pending", []), key=lambda x: x[0])]
    if pid in pend:
        return {"state": "queued", "position": pend.index(pid) + 1}
    return {"state": "unknown"}


def hist_list(offset, limit):
    """최근 순. 아직 결과가 없는 항목은 지금 상태를 물어 채운다(ComfyUI 가 잊은 작업은 '결과 없음')."""
    with HLOCK:
        items = list(reversed(HIST_DB))
    page = items[offset:offset + limit]
    for i, e in enumerate(page):
        if e.get("state") in ("queued", "running"):
            try:
                st = _status(e["id"])
            except Exception:  # noqa: BLE001 — ComfyUI 꺼짐: 지금 상태만 모름
                continue
            if st["state"] == "unknown":
                st = {"state": "lost", "error": "결과 없음(ComfyUI 재시작 등으로 중단)"}
            hist_result(e["id"], st)
            page[i] = dict(e, **{k: v for k, v in st.items() if k in ("state", "video", "error", "pct")})
    return {"items": page, "total": len(items)}


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
            if u.path == "/":
                b = open(INDEX, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
            elif u.path == "/api/status":
                self._json(status(q["id"]))
            elif u.path == "/api/history":
                self._json(hist_list(int(q.get("offset") or 0), min(100, int(q.get("limit") or 20))))
            elif u.path == "/api/input":
                # 이력 불러오기용: 이 화면이 올린 사진만(ComfyUI input 폴더의 simpleui_*)
                name = q.get("name", "")
                if not re.fullmatch(r"simpleui_[0-9a-f]{10}\.(jpg|png|webp)", name):
                    raise ValueError("이 화면이 올린 사진이 아닙니다.")
                try:
                    r = comfy("/view?" + urllib.parse.urlencode({"filename": name, "type": "input"}))
                except urllib.error.HTTPError:
                    return self._json({"error": "사진 파일이 없습니다(input 폴더에서 지워짐)."}, 404)
                b = r.read()
                self.send_response(200)
                self.send_header("Content-Type", r.headers.get("Content-Type", "image/jpeg"))
                self.send_header("Content-Length", str(len(b)))
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
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/generate":
                self._json(build_and_queue(body))
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
                           "lora": ("strength", "steps")}[kind]
                vals = {k: body["values"][k] for k in allowed if k in (body.get("values") or {})}
                with CLOCK:
                    CARD_DB[kind].setdefault(name, {})["user"] = vals
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
                # 기록만 지운다. 결과 영상·사진 파일은 그대로 둔다.
                ids = set(body.get("ids") or [])
                with HLOCK:
                    if body.get("all"):
                        HIST_DB.clear()
                    else:
                        HIST_DB[:] = [e for e in HIST_DB if e["id"] not in ids]
                    _save_json(HIST, HIST_DB)
                    total = len(HIST_DB)
                self._json({"ok": True, "total": total})
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
        if not any(s in (a[0] if a else "") for s in ("/api/status", "/api/fetch-state", "/api/history", "/api/input")):
            print("%s %s" % (self.command, self.path), flush=True)


if __name__ == "__main__":
    threading.Thread(target=ws_loop, daemon=True).start()
    threading.Thread(target=fetch_worker, daemon=True).start()
    print(f"H3 간단 화면: http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
