# H3 영상 만들기 (ComfyUI + MiniMax H3 + DaSiWa)

사진 몇 장과 짧은 설명으로 **소리까지 들어간 5초 안팎의 영상**을 내 PC에서 만드는 구성입니다.
복잡한 ComfyUI 화면 대신 **간단 화면**(`http://127.0.0.1:8190`)에서 사진·내용·모델만 고르면 됩니다.

```
브라우저(간단 화면 :8190) ──> simple_ui/server.py ──> ComfyUI(:8188) ──> GPU
                                   │ DaSiWa 워크플로 틀(template_api.json)에 값만 채워서 넘김
                                   └ models 폴더의 모델·LoRA 를 자동으로 목록화
```

- 모델 파일(수십 GB)은 이 저장소에 없습니다. [`models.json`](models.json)의 링크로 받습니다(스크립트 제공).
- 설계·동작 원리는 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), AI 에이전트용 작업 안내는 [AGENTS.md](AGENTS.md).

## 필요한 것

| 항목 | 기준 (실제로 돌린 PC) | 비고 |
|---|---|---|
| OS | Windows 11 | 스크립트가 PowerShell·.bat 기준 |
| GPU | NVIDIA RTX 5060 Ti 16GB | RTX 50(블랙웰)이 아니면 텍스트 모델을 바꿔야 함 → [MODELS](docs/MODELS.md#gpu별-주의) |
| RAM | 64GB | 16GB GPU 에 다 안 들어가는 모델을 RAM 으로 넘겨 씀 |
| 디스크 | 필수 약 40GB, 선택까지 약 105GB | |
| 도구 | git, Python 3.12(또는 uv), 웹 브라우저 | Civitai 계정(무료) — DaSiWa 모델 받을 때 로그인 필요 |

> **라이선스 확인**: MiniMax H3 모델은 *MiniMax H3 Community License* 를 따릅니다. 이 라이선스에는 사용 지역을 제한하는 조항이 있으니 받기 전에 원문을 직접 확인하고 판단하세요. DaSiWa 모델·워크플로·노드도 각자 라이선스가 있습니다(링크는 [docs/MODELS.md](docs/MODELS.md)).

## 설치 (새 PC)

PowerShell 에서 이 폴더(`comfyui-h3-video`)로 이동한 뒤:

```powershell
# 1) ComfyUI + 커스텀 노드 + 간단 화면 설치 (기본 위치: %USERPROFILE%\ComfyUI)
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#    다른 위치:  ... -File scripts\setup.ps1 -ComfyDir D:\ComfyUI

# 2) 모델 받기 (Hugging Face 파일은 자동, 끝나면 sha256 검증)
python scripts\get_models.py --comfy "$env:USERPROFILE\ComfyUI"
#    → Civitai 파일(DaSiWa)은 로그인이 필요해서 링크만 출력됩니다.
#      브라우저로 받은 뒤(다운로드 폴더에 그대로 두면 됨) 같은 명령을 한 번 더 실행하면
#      제자리로 옮기고 검증합니다.
#    선택 파일(기본 모델·터보 LoRA·DaSiWa v4)까지:  --all
#    받지 않고 상태만 보기:                          --check
```

설치 스크립트는 ComfyUI·PyTorch·커스텀 노드를 **원본 PC 와 같은 버전**([versions.json](versions.json))으로 맞춥니다.

## 실행

1. `ComfyUI\start_comfyui.bat` — ComfyUI 켜기(창을 닫으면 꺼짐). `http://127.0.0.1:8188` 이 열리면 준비 완료.
   다른 방법으로 켜더라도 `PYTHONIOENCODING=utf-8` 은 꼭 설정하세요(한국어 Windows 에서 DaSiWa 노드가 안 불러와지는 문제 방지).
2. `ComfyUI\simple_ui\start.bat` — 간단 화면을 켜고 브라우저로 `http://127.0.0.1:8190` 을 엽니다.

> 간단 화면 HTML 파일을 더블클릭해서 열면(file://) 동작하지 않습니다. 꼭 주소로 여세요.

## 간단 화면 사용법

| 칸 | 하는 일 |
|---|---|
| 맨 위 방식 | **참조 사진으로 만들기**(사진 1~9장의 사람·사물을 등장시킴) / **첫·끝 장면으로 만들기**(사진 1장=시작 장면, 2장이면 두 번째가 끝 장면) |
| 1. 사진 | 끌어다 놓기·클릭·Ctrl+V. 사진이 클수록·선명할수록 결과가 좋음 |
| 2. 내용 | 한 줄 요약, 장면별 동작(시각+동작), 분위기·카메라, 유지할 것, 소리. **"따봉 예시로 채우기"** 로 형식을 볼 수 있음. 영어가 더 잘 통함 |
| 3. 모델 | 저장한 조합(칩) → 모델 → 속도·품질(빠르게/보통/품질) → LoRA(+ 추가) → 고급 설정(접힘) |
| 4. 설정 | 화면비, 화질(초안/기본/720p/1080p), 길이(1~15초, H3 최대), 시드, **반복**(시드만 바꿔 여러 개) |
| 오른쪽 | 영상 만들기, 진행률, 중지, 결과 재생·다운로드, 결과 폴더 열기 |

- **반복**: 시드를 비우면 매번 랜덤, 적으면 그 값부터 1씩 늘려 만듭니다. 결과마다 시드가 표시되니 마음에 든 시드를 다시 쓰면 같은 결과가 나옵니다.
- **초안**: 약 0.4MP(예: 576×736, 1:1 이면 640×640)로 작게 만들어 기본보다 약 40% 빨리 끝납니다. 프롬프트·동작이 원하는 대로 나오는지 먼저 볼 때 씁니다. 화질을 바꾸면 같은 시드라도 다른 영상이 나오니, 마음에 들면 원하는 화질로 다시 반복을 돌리세요.
- **만드는 중에 또 만들기**: 작업이 돌고 있을 때 버튼이 **대기열에 추가**로 바뀝니다. 누르면 그때 화면 구성으로 작업이 대기열 뒤에 붙고, 결과 목록에 이어서 나옵니다. 다른 설정·사진으로 바꿔 가며 여러 개를 쌓아 둘 수 있습니다.
- **새로고침해도 그대로**: 사진·내용·장면·시드·직접 고친 프롬프트·모델 구성, 만드는 중인 작업의 진행률과 마지막 결과가 다시 나타납니다. 이 브라우저에만 남습니다(`127.0.0.1` 과 `localhost` 도 서로 다른 곳으로 취급).
- **작업 이력**(오른쪽 아래): 만들 때의 사진·설정·프롬프트와 결과 영상을 함께 남깁니다. **보기**(큰 화면 재생)·**다운로드**·**불러오기**(그때 구성을 칸에 다시 채움, 시드까지 그대로라 같은 결과 재현)·**프롬프트**(그때 최종 프롬프트)·**삭제**/**전체 지우기**. 기록을 지워도 영상 파일은 결과 폴더에 남습니다. 이력은 이 PC 의 `simple_ui\history.json`.
- **조합 저장**: 모델·스텝·LoRA 구성을 이름 붙여 저장하고 칩 한 번으로 불러옵니다. 기본으로 *DaSiWa v5 터보 8스텝(품질)*, *DaSiWa v4 터보 4스텝(빠름)* 이 들어 있습니다.
- 결과 영상: `ComfyUI\output\video\날짜\` 에 저장됩니다.

## 새 모델·LoRA 추가 (코드 수정 없음)

1. 받은 파일을 넣습니다 — 모델: `ComfyUI\models\diffusion_models\`, LoRA: `ComfyUI\models\loras\`
2. 간단 화면에서 **↻ 폴더 다시 읽기**
3. 목록에 뜨면 고르기. H3 용이 아닌 파일은 "쓸 수 없음"으로 표시됩니다.

이름·트리거 단어·제작자 설명은 Civitai 에서 자동으로 가져오고(LoRA 는 자동, 모델은 고급 설정의 버튼), 스텝·강도는 파일 이름과 설명문으로 추정해 채웁니다. 틀리면 화면에서 고친 뒤 **"기본값으로 저장"** 하면 다음부터 그 값이 들어갑니다. 판정 규칙은 [ARCHITECTURE.md › 모델 카드](docs/ARCHITECTURE.md#5-모델-카드-파일별-기본값)에 있습니다.

지원 안 함: GGUF 모델, H3 가 아닌 모델(Wan·LTX 등), 별도 노드가 필요한 LoRA(그 노드 없이 LoRA 만 적용됨).

## 폴더 구조

```
comfyui-h3-video/
├─ README.md            ← 지금 문서(사람용)
├─ AGENTS.md            ← AI 에이전트용 작업 안내·규칙
├─ models.json          ← 모델·LoRA 목록(링크·위치·크기·sha256)
├─ versions.json        ← ComfyUI·PyTorch·커스텀 노드 고정 버전
├─ scripts/
│  ├─ setup.ps1         ← 새 PC 설치
│  ├─ get_models.py     ← 모델 받기·검증
│  └─ start_comfyui.bat ← ComfyUI 실행(설치 시 ComfyUI 폴더로 복사)
├─ simple_ui/           ← 간단 화면(설치 시 ComfyUI\simple_ui 로 복사)
│  ├─ server.py         ← 로컬 서버(표준 라이브러리 + Pillow·aiohttp)
│  ├─ index.html        ← 화면(외부 라이브러리 없음)
│  ├─ template_api.json ← DaSiWa 워크플로 API 틀(개인 프롬프트·사진 제거)
│  ├─ cards.seed.json   ← 모델별 기본값 초기값
│  ├─ presets.seed.json ← 조합 초기값
│  └─ start.bat
└─ docs/
   ├─ ARCHITECTURE.md   ← 설계·데이터 흐름·API·노드 지도
   ├─ MODELS.md         ← 모델 설명·선택 가이드·GPU별 주의·라이선스 링크
   ├─ PERFORMANCE.md    ← 실측 시간·장비별 추정
   └─ TROUBLESHOOTING.md← 자주 생기는 문제와 해결
```
