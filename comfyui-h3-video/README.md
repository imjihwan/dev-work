# ComfyUI H3 Video

ComfyUI와 DaSiWa MiniMax H3 워크플로 위에서 사진을 영상으로 만드는 로컬 웹 화면이다. 일반 생성, 네 편 이어 만들기, 결과 갤러리를 별도 탭으로 제공한다. PC에서 실행하고 같은 집 네트워크의 휴대폰·iPad로 접속할 수 있다.

이 저장소에는 코드·문서·비어 있는 워크플로 틀과 공개 모델 다운로드 명세만 둔다. 모델·LoRA 가중치, 사진·영상·오디오, 작업 이력·저장 설정·프로젝트·갤러리 상태, 로그·백업은 포함하지 않는다.

## 주요 기능

- 일반 생성: 사진 참조, 첫 장면 고정, 장면별 동작·시간, 모델·LoRA·시드·길이·화질 설정, 최종 프롬프트 확인, 설정 저장·불러오기.
- 대기열: 번호 표시, **1순위 우선추가**, 개별 수정, 체크한 항목 일괄수정, **전체 대기항목 일괄수정**, 사진 순서를 회전하는 순차 추가, 사진마다 하나씩 추가하는 개별 일괄 추가. 폴더·하위 폴더의 사진을 모아서 등록하거나 여러 폴더를 끌어놓을 수 있다. 우선추가는 실행 중인 작업을 유지하고 새 작업을 대기열 맨 앞에 넣으며, 반복 생성 순서도 유지한다. 개별 사진 추가에는 기존 100장 제한이 없다.
- 작업 이력: 무한 스크롤, 당시 설정 확인, 설정 불러오기, 현재 작업 재시작, 선택한 영상 최대 3개 함께 재생. 이력 삭제는 연결된 ComfyUI 대기열·이력에도 반영하며 출력 파일을 직접 지우지 않는다.
- 프롬프트 도우미: [Grok CLI 계정 로그인](docs/GROK_CLI.md) / DutchIT H3 8B / 기존 2B 선택. Grok은 외부 텍스트 처리·설명 대화·미적용 초안 이어 수정, 기존 두 모델은 로컬 CPU 실행. 상세 초안 작성, 현재 문장에서 요청한 부분만 수정, 동작·시간 흐름 검토. 고정된 인물·유지 조건·장소·분위기·카메라 칸은 변경하지 않는다. DutchIT는 RAM 여유 8GB가 필요하다.
- 장면별 동작은 시간별 입력 또는 **한 칸으로 작성**을 선택할 수 있다. 한 칸에서는 시간 표기 없이 전체 흐름을 적고 내부적으로 0초 시작 구간 하나를 사용한다.
- [한국어 번역 미리보기](docs/LOCAL_TRANSLATION.md): 입력 원문을 유지한 채 로컬 CPU로 번역을 확인한다. 정밀(기본)/빠르게 선택, 긴 글 분할·진행 표시·문단 캐시·선택 부분 번역을 지원한다.
- 네 편 이어 만들기: 약 5초씩 네 편을 사용자 확인 단계에 따라 순차 생성하고 약 20초로 병합한다. 다음 편은 직전 확정 영상의 연속성과 공통 원본 참조를 사용한다.
- 갤러리: 원본 첫 사진 썸네일, 자동 갱신, 즐겨찾기·휴지통·복원, 좌우 스와이프, 선택 영상 동시 재생, 설정을 다른 영상에서 가져와 우선 재생성, 현재 작업 진행률.

사용 방법은 [UI 안내](docs/UI.md), [프롬프트 도우미](docs/PROMPT_HELPER.md), [네 편 이어 만들기](docs/STORY.md)에 정리했다. 코드 구조는 [ARCHITECTURE](docs/ARCHITECTURE.md), 최근 변경은 [CHANGELOG](CHANGELOG.md)를 참고한다.

여러 장으로 같은 인물의 얼굴을 참조하는 방법과 현재 처리 방식은 [얼굴 참조 안내](docs/FACE_REFERENCES.md)를 참고한다.

## 설치와 실행

Windows, NVIDIA GPU, Git, Python 3.12 또는 uv가 필요하다. 고정된 ComfyUI·커스텀 노드·PyTorch 버전은 `versions.json`을 사용한다. 설치 스크립트는 모델을 자동으로 받지 않는다.

프로젝트 폴더에서 실행한다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -ComfyDir "$PWD\ComfyUI"
.\ComfyUI\.venv\Scripts\python.exe scripts\get_models.py --comfy .\ComfyUI --all
```

Civitai에서 직접 받아야 하는 파일은 다운로드 안내를 따른다. 브라우저 로그인은 사용자가 진행한다. 파일 위치·검증 방법은 [모델 안내](docs/MODELS.md)와 `models.json`을 참고한다. 명세 파일의 파일명·다운로드 주소·해시는 설치 정보이며 모델 파일 자체가 아니다.

**ComfyUI 위치 규칙**: 실행·설치 스크립트(`Start`/`Stop`/`Restart-H3-UI`/`Complete-Models.ps1`, `install_*.py`, `prepare_ui_restart.py`)는 `-ComfyDir`(또는 `--comfy`)로 준 폴더를 쓰고, 없으면 이 프로젝트 안의 `ComfyUI` 폴더, 그것도 없으면 `%USERPROFILE%\ComfyUI`(setup.ps1 기본값)를 쓴다. 프롬프트 도우미 파일(`local-prompt-helper`)은 **ComfyUI 폴더와 같은 위치**에 설치되고, 화면도 그 위치에서 찾는다. `simple_ui/`를 고친 뒤에는 ComfyUI 쪽 `simple_ui`로 복사(setup.ps1 이 하는 복사)한 다음 `Restart-H3-UI.ps1` 을 실행해야 반영된다.

로컬 CPU 프롬프트 도우미는 별도로 준비한다.

```powershell
.\ComfyUI\.venv\Scripts\python.exe scripts\install_prompt_helper.py            # 다른 위치면 --comfy <ComfyUI 폴더>
```

```powershell
powershell -ExecutionPolicy Bypass -File Start-H3-Video.ps1 -NoBrowser
```

PC 화면은 `http://127.0.0.1:8190/`이다. 다른 기기는 같은 네트워크에서 `http://<PC의 LAN IPv4 주소>:8190/`으로 접속한다. 필요한 경우 Windows 방화벽에서 TCP 8190을 집 네트워크 범위에 허용한다. ComfyUI 8188은 PC 내부용으로 유지한다. 현재 UI에는 별도 로그인 기능이 없으므로 인터넷 포트 포워딩 대상으로 사용하지 않는다.

## 업데이트와 검증

수정 소스는 `simple_ui/`, 실제 실행 복사본은 `ComfyUI/simple_ui/`에 있다. 코드만 업데이트하며 이력·저장 설정·프로젝트 폴더를 덮어쓰지 않는다. 화면 파일만 바뀌었으면 새로고침으로 반영된다. Python 서버 변경은 UI 서버 재시작이 필요하며, 실행 중인 ComfyUI를 함께 재시작하지 않는다.

[검증 안내](docs/TESTING.md)의 테스트는 가짜 대기열·합성 데이터로 실행하며 개인 작업이나 실제 모델 생성에 접근하지 않는다. 테스트 기본 경로는 설치 복사본 대신 저장소의 `simple_ui/`를 사용한다.

저장소에 올릴 때는 [소스 배포 안내](docs/SOURCE_RELEASE.md)를 따른다. 개인 PC의 작업 데이터와 모델을 Git에 추가하거나 업데이트 검증에 사용하지 않는다.
