# 문제 해결

실제로 겪은 증상 위주로 정리했습니다. "원인"에 근거 수준을 붙였습니다(실측 / 코드 / 추정).

## 화면·실행

| 증상 | 원인 | 해결 |
|---|---|---|
| `실패: Failed to fetch` | HTML 파일을 더블클릭해서 `file://` 로 열었음 (실측) | `http://127.0.0.1:8190` 으로 열기. 화면도 이 경우 버튼을 막고 안내함 |
| "모델 목록을 못 읽었습니다" | ComfyUI(8188)가 꺼져 있음 | `start_comfyui.bat` 먼저 실행 |
| ComfyUI 로그에 `Cannot import … ComfyUI-DaSiWa-Nodes … 'cp949' codec can't encode` → Director 노드 없음 오류 | 한국어 Windows 콘솔(cp949)에서 DaSiWa 노드가 이모지를 출력하다 실패 (실측) | `start_comfyui.bat` 으로 켜기(안에서 `PYTHONIOENCODING=utf-8` 설정). 직접 켤 땐 먼저 `set PYTHONIOENCODING=utf-8` |
| 생성하자마자 "파일 없음" 오류 | 모델이 `models.json` 의 `dest` 와 다른 폴더(특히 `MiniMaxH3/` 하위 폴더 누락) | `python scripts/get_models.py --comfy <폴더> --check` 로 위치 확인 |
| 새로 넣은 모델·LoRA 가 안 보임 | 목록은 화면을 열 때 읽음 | **↻ 폴더 다시 읽기** |
| LoRA 가 "쓸 수 없음" | H3 용이 아님(파일 구조로 판정) 또는 GGUF | H3 용 LoRA 를 쓰기. Wan·LTX·SDXL 용은 못 씀 |
| 중지했는데 ComfyUI 화면의 다른 작업은 계속 돎 | 의도된 동작. 이 화면에서 만든 작업만 멈춤 (코드) | 다른 작업은 ComfyUI 화면에서 멈추기 |

## 결과 품질

| 증상 | 원인 | 해결 |
|---|---|---|
| 이마에 띠·모자 같은 없던 물건이 생김 | 아주 작은 사진(예: 180×270)이라 모델이 머리 주변을 지어냄 (실측) | 큰 사진 쓰기. "유지할 것"에 `Do not add any hat, headband, accessory…` (따봉 예시에 이미 포함) |
| 영상 끝에 옷이 바뀜 | 참조 사진 여러 장의 옷이 서로 다르고, 프롬프트가 "모든 사진의 대상"을 따라가게 했음 (실측) | 지금 화면은 여러 장이면 "옷·머리·배경은 사진 1 에서만"으로 자동 작성. 옷이 같은 사진을 쓰면 더 확실 |
| 사람이 화면 밖으로 나간 뒤 배경이 뭉개짐 | 사진에 없던 뒷배경을 지어내야 함 + 원본 배경이 흐린 아웃포커스 + 4스텝·낮은 해상도 + 영상 끝으로 갈수록 사진 영향 약해짐 (추정) | 완전히 나가기 전에 끝내기("가장자리까지 걸어가다 몸이 반쯤 걸친 채 끝"), 배경이 단순·선명한 사진, 길이 줄이기, 720p |
| 품질이 들쭉날쭉 | 설정은 같아도 사진 해상도·프롬프트·시드가 다름 (실측: 설정 비교) | **반복** 으로 시드 여러 개 뽑고 좋은 시드를 다시 쓰기 |
| 한글 프롬프트가 덜 정확 | 모델이 영어 문장에 더 익숙함 (추정) | 핵심 동작은 영어로. 한글도 동작은 함 |

## 설치·다운로드

| 증상 | 원인 | 해결 |
|---|---|---|
| Civitai 링크가 로그인 페이지로 감 | DaSiWa 파일은 로그인 사용자만 받을 수 있음 (실측: 307 → /login) | 브라우저로 로그인 후 받기 → 다운로드 폴더에 둔 채 `get_models.py` 다시 실행 |
| `get_models.py` 가 "다운로드 폴더 파일이 다름" | 아직 받는 중(`.crdownload`)이거나 손상 | 다 받아진 뒤 다시 실행. 계속 다르면 다시 받기 |
| curl 로 Civitai 접속 시 `CRYPT_E_NO_REVOCATION_CHECK` | 회사망 등에서 Windows 인증서 폐기 확인 실패 | curl 에 `--ssl-no-revoke`. `get_models.py` 는 Python 이라 해당 없음 |
| "You need pytorch with cu130 or higher" 경고 | PyTorch 가 CUDA 13 빌드가 아님 | `setup.ps1` 로 다시 설치(PyTorch 2.14.1+cu130) |
| `llama-cpp-python` 빌드 실패 | DaSiWa 노드 requirements 에 있으나 이 구성에서 안 씀 | `setup.ps1` 은 건너뜀(versions.json `skip_requirements`) |
| 생성 중 메모리 부족 | 16GB GPU + RAM 부족 | RAM 64GB 권장. 다른 GPU 프로그램 종료, 화질 "기본", 길이 줄이기, w4a8 판 사용 |
