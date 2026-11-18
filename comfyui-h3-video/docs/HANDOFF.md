# H3 영상 UI · Grok 도우미 인수인계

작성일: 2026-11-19, Asia/Seoul. 사용자 작업 내용·사진·영상·결과 파일 목록은 포함하지 않는다.

## 가장 먼저 지킬 조건

- 사용자의 실제 작업 문구·작업 내역·사진·결과물은 열람하거나 언급하지 않는다. 점검은 소스, 자원 수치, 상태 메타데이터, 합성 입력으로 한다.
- 실제 서비스 화면을 브라우저로 열지 않는다. 화면 시험은 가짜 데이터와 별도 환경만 사용한다.
- 영상 생성 중인 ComfyUI를 임의로 중지·재시작하지 않는다. 워크플로·모델·LoRA·첫 장면 고정·대기열 내용이나 순서를 임의로 바꾸지 않는다.
- Git에는 코드·공개 문서만 올린다. 설치본·계정·모델·LoRA·사진·결과·개인 상태 파일은 제외한다.
- 웹앱 안의 Grok 도우미는 사용자가 요청한 현재 입력·최종 문구·필요한 대기 항목을 조회할 수 있다. 이는 Codex가 실제 작업을 열람해도 된다는 뜻이 아니다.

## 위치와 실행 환경

- 프로젝트: `C:\Users\Totoro\Documents\Codex\comfyui-h3-video`
- 공개 소스: `simple_ui/`; 실행 복사본: `ComfyUI/simple_ui/`
- Python: `ComfyUI/.venv/Scripts/python.exe -X utf8`
- 사용자 UI: `http://127.0.0.1:8190/`; ComfyUI: `http://127.0.0.1:8188/`
- 외부 접근은 Tailscale을 사용한다. 이 문서에 특정 PC의 외부 주소·계정 정보는 적지 않는다.
- 저장소: `imjihwan/dev-work`, `main`, 프로젝트 하위 경로 `comfyui-h3-video/`
- 이 PC는 일반 Git 체크아웃이 아니므로 GitHub Git 데이터 API로 공개 파일만 게시해 왔다. 다른 프로젝트의 트리는 유지한다.

확인한 하드웨어: Ryzen 5 7500F(6코어/12스레드), RAM 약 32GiB, RTX 4060 Ti 전용 VRAM 8GiB, Gigabyte B650M K. 작업 관리자의 공유 GPU 메모리는 전용 VRAM 용량과 다르다.

## 유지하는 구성

- MiniMax H3 / DaSiWa 기반 생성, 일반·갤러리·4편 이어 만들기 탭.
- 대기열 편집·전체 일괄수정·우선 추가·사진 순차/개별 등록·얼굴 보조 크롭·갤러리 재생/재생성.
- 모델·노드 구성의 기준은 `versions.json`, `models.json`, `docs/ARCHITECTURE.md`, `AGENTS.md`다.
- 2B 로컬 도우미 가중치는 사용자 요청으로 삭제했다. 일반·이어 만들기 선택 목록에서도 제거했고 기본 설치로 다시 받지 않는다.
- DutchIT 8B CPU 도우미는 남아 있다. 영상 생성과 GPU를 공유하지 않지만 RAM·CPU 자원은 공유한다.

## AI 연결에 대한 최종 결정

**Grok으로 유지한다. Claude로 전환하지 않는다.**

Claude 연결을 잠깐 시험했으나 사용자가 취소했다. 그때 바꾼 소스는 원복했으며 서비스에 Claude 연결을 배포하지 않았다. 사용자가 직접 한 별도 Claude CLI 로그인은 앱 전환과 별개다. 계정 파일을 읽거나 로그아웃하지 않는다.

- Grok CLI: 공식 `@xai-official/grok` 1.0.89.
- 실행 파일: `local-prompt-helper/grok-cli/bin/grok.exe`
- 앱 전용 계정: `local-prompt-helper/grok-account/`
- 로그인: `Connect-Grok.ps1`. API 키로 자동 전환하지 않는다.
- 모델: **grok-4.7**. 2026-11-19 사용자 계정에서 `grok models`로 조회한 사용 가능 목록에는 이 모델 하나만 표시됐다. 더 높은 모델로 바꿨다고 주장하지 않는다.
- 사용자는 구독했으며 품질 좋은 모델을 선호한다. 기본 추론 강도는 **high / 정밀**을 유지한다. 빠른 모드를 기본으로 강제하지 않는다.

공식 근거: [CLI 옵션](https://docs.x.ai/build/cli/reference), [추론 강도](https://docs.x.ai/developers/model-capabilities/text/reasoning).

## 대화형 제작 도우미

- PC에서는 오른쪽에 붙는 대화창, 모바일·아이패드에서는 넓은 대화 화면.
- 질문·답변·변경 전후·실행 결과를 대화 안에 표시한다.
- 최근 최대 100개 메시지와 미전송 입력을 같은 브라우저·접속 주소의 localStorage에 저장한다. 다른 기기·LAN 주소·Tailscale 주소 사이에는 자동 동기화하지 않는다.
- 새로고침 후 이전 변경안은 읽기 전용이다. 실행 ID·DOM 대상·사진 바인딩을 저장하거나 복원한 변경안을 자동 실행하지 않는다.
- **새 대화**는 저장된 대화와 채팅 초안을 지운다. 영상 폼·대기열·결과는 지우지 않는다.
- 최근 대화 중 최대 12개 메시지를 다음 요청의 맥락으로 전달한다.

## Grok 속도 개선 작업

사용자 요청: 응답을 빠르게 하되 실제 작업·결과물을 확인하지 말 것. 이후 품질 좋은 모델을 써 달라는 요구가 추가됐다.

변경 범위:

1. 모델은 Grok 4.7 그대로, 기본 **정밀(high)**. **최대(xhigh)·균형(medium)·빠르게(low)**를 선택할 수 있게 한다.
2. 초기 대기열 전달을 상태 메타데이터 20개로 제한하고 전체 수와 다음 페이지 여부를 제공한다. 원본 전체 스냅샷은 호스트가 보관하므로 대상 확인·순서·동시 변경 보호는 유지한다.
3. 추가 목록은 페이지별, 특정 항목은 번호/ID로 조회한다. 사진·실행 그래프를 모델에 넘기지 않는다.
4. 한 요청 안의 동일 조회 결과를 재사용하고 중복 결과를 누적하지 않는다. 다른 사용자 요청 사이에는 캐시를 공유하지 않는다.
5. 프롬프트 문자열은 자르거나 다시 쓰지 않는다. JSON 직렬화 공백과 반복되는 false UI 플래그만 줄인다.
6. 대기 중 준비·조회·Grok 응답·변경안 검사 단계와 경과 시간을 표시하고, 응답 확인 간격을 1.3초에서 0.6초로 줄인다.

개선 전 합성 요청 1쌍에서는 같은 Grok 4.7의 기본 추론이 8.81초, low가 6.58초였다. 이는 서로 다른 추론 강도의 소규모 관찰이며 구조 최적화의 동일 품질 속도 향상 수치가 아니다. 실제 사용자 작업의 속도를 측정한 것도 아니다. 정밀 모드의 시간 감소나 일정한 배수를 보장하지 않는다.

구조 개선 후 별도 합성 요청은 정밀(high) 8.42초, 빠르게(low) 4.74초였고 모두 길이 하나만 정확히 수정했다. 입력 직렬화 비교는 23,180자에서 12,194자로 약 47% 줄었다. 횟수가 적고 서버 상태가 변하므로 처리 시간 차이를 일반화하지 않는다. 기본 정밀 모드를 유지한다.

검증·배포 상태는 아래 상태 절과 Git 커밋을 함께 확인한다.

## 변경 파일 지도

| 파일 | 역할 |
|---|---|
| `simple_ui/grok_cli.py` | CLI 명령, 추론 강도, 계정 환경 분리, 제한 시간, JSON 응답 검증 |
| `simple_ui/production_assistant.py` | 앱 API 조회·계획, 페이지별 목록, 실행 중복 방지·원문 검증 |
| `simple_ui/production_assistant.js` | 대화창, 브라우저 저장·복원, 실행 제안 카드, 진행 단계 |
| `simple_ui/prompt_helper.py` | 별도 프롬프트 작성·수정·동작/시간 검토 |
| `scripts/test_grok_cli.py` | 가짜 CLI 전송 검증 |
| `scripts/test_production_assistant.py` | 가짜 앱·대기열 검증 |
| `scripts/test_production_assistant.cjs` | 가짜 DOM·API·저장소 검증 |
| `scripts/prepare_source_release.py` | 공개 파일 허용 목록과 배포본 검증 |

CLI의 기본 도구·파일·셸·웹·MCP·스킬·하위 에이전트는 제거한다. CLI 결과의 인증 방식과 도구 목록을 확인한 뒤 JSON 계획만 사용한다. 계획을 받는 것과 앱에 적용하는 것은 별도다. 원문·참조 사진·실행 상태가 바뀌면 오래된 변경안은 거절하고, 결과 불명인 실행은 자동 재시도하지 않는다.

## 안전한 검증과 반영

```powershell
.\ComfyUI\.venv\Scripts\python.exe -X utf8 -m unittest discover -s scripts -p test_grok_cli.py -q
.\ComfyUI\.venv\Scripts\python.exe -X utf8 -m unittest discover -s scripts -p test_production_assistant.py -q
node scripts/test_production_assistant.cjs
```

실제 Grok 시험은 별도 임시 폴더의 합성 UI 값·가짜 대기열·합성 문구만 사용한다. 실제 생성이나 사용자 대기열 제어는 하지 않는다.

소스와 실행 복사본은 검증한 파일만 반영한다. Python 변경은 UI 프로세스 재시작이 필요하다. 진행률 메타데이터를 인계하고 이어 만들기 작업이 활성 상태면 먼저 재시작하지 않는다. ComfyUI 프로세스와 생성 대기열은 유지한다. UI 재시작 도구의 출력에 작업 문구·사진 경로·결과 파일명을 내보내지 않는다.

## 이 문서 작성 시점 상태

- Grok·대화 저장은 이미 서비스에 반영되어 있다. Claude 전환은 취소·원복 상태다.
- Grok 응답 개선을 서비스에 반영했다. UI 프로세스만 재시작했고 ComfyUI 프로세스는 유지했다. Python 70개 테스트와 가상 DOM 회귀 검증을 통과했다. 가상 입력으로 Grok 실제 호출도 검증했다.
- 직전 공개 커밋: `db2c365222c7cfb227c869e0cbc954ad38e10d1c` (대화·초안 유지).

## 구독 갱신 뒤 인증 확인

사용자 요청으로 전용 Grok 계정을 기기 인증으로 다시 로그인했다. 새 CLI 프로세스의 모델 목록도 `grok-4.7` 하나였다. 사용자의 최종 결정은 **그냥 4.7 유지**다. 구독 상품이나 Fast 변형으로 임의 변경하지 않는다. CLI 모델 목록은 웹 화면의 모델 선택지와 같다고 가정하지 않는다.

공식 문서: [CLI 모델·명령](https://docs.x.ai/build/cli/reference), [추론 강도](https://docs.x.ai/developers/model-capabilities/text/reasoning), [Grok 4.7](https://docs.x.ai/developers/grok-4-7).
