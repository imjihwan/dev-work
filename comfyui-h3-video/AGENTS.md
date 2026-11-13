# AGENTS.md — AI 에이전트용 작업 안내

이 폴더를 다루는 AI(코딩 에이전트·챗봇)를 위한 문서입니다. 사람용 안내는 [README.md](README.md), 설계는 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## 이 프로젝트는

- 로컬 PC 에서 ComfyUI + MiniMax H3(DaSiWa 워크플로)로 사진 → 소리 포함 영상을 만드는 구성과, 그 위의 **간단 화면**(simple_ui).
- 간단 화면은 DaSiWa 워크플로를 한 번 실행해 뽑은 API 프롬프트(`simple_ui/template_api.json`)를 **틀**로 쓰고, 값만 바꿔 ComfyUI 에 넘긴다.
- 사용자는 한국어 사용자. 화면 문구·보고는 한국어로.

## 반드시 지킬 것

1. **워크플로 구성요소를 임의로 바꾸지 않는다.** 사용자가 "DaSiWa 워크플로"를 쓰겠다고 했으면 모델·노드·텍스트 모델·VAE 를 다른 것으로 바꿔 끼우지 않는다. 파일이 없거나 막히면 바꾸지 말고 **무엇이 없는지 보고하고 받을지 묻는다.**
2. **템플릿 노드 구조를 바꾸지 않는다.** 노드 추가·삭제·연결 변경 금지. 바꿀 수 있는 것은 [ARCHITECTURE §2](docs/ARCHITECTURE.md#2-템플릿-노드-지도)의 입력값뿐. 새 기능에 노드가 필요하면 별도 틀을 만들자고 제안한다.
3. **모델·LoRA 파일은 저장소에 넣지 않는다.** 링크·크기·sha256 을 `models.json` 에 적는다.
4. **개인 데이터를 커밋하지 않는다.** 사진(`ComfyUI/input`), 결과 영상, `cards.json`/`presets.json`(PC별 상태), 개인 프롬프트가 든 템플릿. 템플릿을 다시 뽑으면 `timeline_data.items`·프롬프트 칸을 비운다.
5. **실존 인물 사진**은 사용자 본인 또는 동의받은 사진일 때만 사실적 영상으로 만든다.
6. **Civitai 로그인·캡차는 사람이 한다.** 자격 증명을 입력하지 않는다. 받은 파일은 `get_models.py` 로 검증·이동.
7. 라이선스 판단(MiniMax H3 사용 지역 조항 등)은 사용자 몫. 알리기만 하고 임의로 파일을 지우지 않는다.

## 코드 지도

| 파일 | 내용 | 고칠 때 볼 곳 |
|---|---|---|
| `simple_ui/server.py` | HTTP 서버(ThreadingHTTPServer), ComfyUI 호출, 진행률(WebSocket), 모델 카드, 조합, 반복 | 상단 상수(노드 ID) · `analyze()`·`effective()`(판정 규칙) · `build_and_queue()`(값 채우기) |
| `simple_ui/index.html` | 화면 전체. 상태 객체 `S`(mode, model, steps, sampler, scheduler, shift_*, loras{name:strength}, trig), 카탈로그 `CAT` | `build()`(프롬프트 조립) · `drawModelCard()` 계열 · `poll()`(반복 진행) |
| `simple_ui/template_api.json` | DaSiWa C-MMH3-33 API 프롬프트 | 노드 ID 는 ARCHITECTURE §2 |
| `models.json` | 받을 파일 목록 | MODELS.md 마지막 절 |
| `versions.json` | 고정 버전 | 올릴 땐 실제로 돌려 본 뒤 |
| `scripts/setup.ps1` · `get_models.py` | 설치·모델 받기 | |

## 자주 하는 작업

**기본 모델 바꾸기** — `template_api.json` 의 `1512:2586`·`1512:2588` `unet_name` 과 `1512:2590` `steps` 를 같이 바꾼다. 해당 파일이 `models.json` 에 `required: true` 로 있어야 새 PC 에서 받아진다. `presets.seed.json`·`cards.seed.json` 도 맞춘다.

**템플릿 다시 뽑기(DaSiWa 워크플로가 바뀌었을 때)** — ComfyUI 에서 새 워크플로를 한 번 실행 → `GET /history?max_items=1` 의 `prompt[2]` 를 저장 → 노드 ID 가 바뀌었으면 `server.py` 상수와 ARCHITECTURE §2 를 고침 → 개인 프롬프트·사진 비우기 → 아래 검증.

**새 모드·입력 추가** — Director 가 지원하는 모드: `T2VA, I2VA, FL2VA, L2VA, REF2VA, Image Inpaint`(DaSiWa 노드 `nodes_minimax_h3_director.py`). 모드별 사진 slot 규칙과 프롬프트 머리말은 DaSiWa 의 `js/minimax_h3_director.js` `builderPromptForWidget()` 를 따라 한다.

**판정 규칙 손보기** — 파일 이름 패턴 규칙은 `server.py analyze()`(방식·터보·스텝 힌트)와 `index.html friendlyModel()/friendlyLora()`(표시 이름) 두 곳에 있다. 둘을 같이 본다.

## 검증 방법 (고친 뒤 최소)

```bash
# 문법
<ComfyUI>/.venv/Scripts/python.exe -m py_compile simple_ui/server.py
python -c "import re;s=open('simple_ui/index.html',encoding='utf-8').read();open('ui.js','w',encoding='utf-8').write(re.search(r'<script>(.*)</script>',s,re.S).group(1))" && node --check ui.js
# 서버가 ComfyUI 목록을 읽는지
curl -s http://127.0.0.1:8190/api/catalog | python -c "import sys,json;d=json.load(sys.stdin);print(len(d['models']),len(d['loras']),d['default'])"
# 모델 파일 상태
python scripts/get_models.py --comfy <ComfyUI> --all --check --fast
```
그리고 **실제 생성 1회**(5초, 기본 화질)로 결과 파일이 나오는지 본다. ComfyUI 대기열은 사용자와 공유하므로, 사용자가 돌리는 작업이 있으면 끝난 뒤에 넣고, 중지는 자기 작업 id 로만 한다.

## 알려진 함정

- ComfyUI 는 반드시 `PYTHONIOENCODING=utf-8` 로 켠다. 한국어 Windows(cp949)에서는 DaSiWa 노드가 시작 로그의 이모지 때문에 import 에 실패한다(`start_comfyui.bat` 이 설정함).
- `setup.ps1` 은 UTF-8 **BOM** 으로 저장해야 Windows PowerShell 5.1 이 한글을 깨뜨리지 않는다.
- 템플릿 JSON 은 UTF-8 BOM 이 있을 수 있다 → `encoding="utf-8-sig"` 로 읽는다.
- 모델 경로 구분자는 ComfyUI 목록 그대로(Windows 는 `MiniMaxH3\\파일`). 직접 문자열을 만들지 말고 `/object_info` 목록 값에서 고른다.
- 텍스트 모델 `nvfp4` 는 블랙웰 전용 가속. 다른 GPU 는 int8 판으로(MODELS.md).
- DaSiWa 모델 입력 두 개는 lazy — 모드에 맞는 하나만 불러온다. 두 로더에 같은 파일을 넣는 이유.
- `DaSiWa_SeedControl` 은 `seed_value` 가 0 이고 random 모드일 때만 스스로 랜덤을 뽑는다. 서버는 항상 1 이상을 넣는다.
- ComfyUI `/interrupt` 에 `prompt_id` 를 주면 그 작업이 돌 때만 멈춘다(다른 작업 보호).
- 대기열에서 지운 작업·ComfyUI 재시작 전 작업은 history 에 없어 `/api/status` 가 `unknown` — 화면은 중지 시 직접 "중지됨", 그 밖엔 `unknown` 5번 연속이면 "작업을 찾을 수 없음"으로 끝낸다.
- H3 모델 어텐션은 템플릿의 `ModelAttentionBackend`(`comfy kitchen attention`)가 정한다. `--use-sage-attention` 같은 실행 옵션은 H3 본체에 적용되지 않는다(실측: 속도 변화 없음, 결과만 달라짐). 속도 개선을 시도할 땐 이 노드 값을 먼저 확인.
- 길이는 1~15초(H3 최대). 프레임 수는 17k+5 단위로 맞춰진다.
