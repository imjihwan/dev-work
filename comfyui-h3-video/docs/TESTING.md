# 개인 데이터 없이 검증하기

테스트는 저장소 `simple_ui/`를 읽는다. ComfyUI 실행, 모델 다운로드, 실제 작업 이력이나 미디어 열람이 필요하지 않다. API 테스트는 가짜 서버 응답과 임시 파일을 사용하고 UI 테스트는 Node.js의 가짜 DOM/플레이어를 사용한다.

Python 3.12 이상과 Node.js를 준비한다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m unittest discover -s scripts -p "test_*.py"
Get-ChildItem scripts\test_*.cjs | ForEach-Object { node $_.FullName; if ($LASTEXITCODE -ne 0) { throw 'UI test failed' } }
```

Python 패키지가 이미 준비된 설치본에서는 `ComfyUI/.venv/Scripts/python.exe`를 사용해도 된다. 테스트 대상 소스는 여전히 저장소 `simple_ui/`다. 일부 Python 테스트는 `GALLERY_TEST_SOURCE` 또는 `REFERENCE_TEST_SOURCE`, Node UI 테스트는 첫 번째 파일 경로 인자로 격리된 스테이징 소스를 지정할 수 있다.

FFmpeg가 PATH에 있으면 네 편 병합 테스트가 임시 폴더에 단색 영상과 무음 오디오를 생성해 길이·화면 크기·오디오 트랙을 검사한다. 없으면 해당 테스트만 건너뛴다. 이 합성 테스트는 실제 생성 모델을 사용하지 않는다.

고정된 DaSiWa 커스텀 노드가 설치되어 있으면 네이티브 그래프 검증기와의 통합 검사 2개도 실행한다. 소스만 있는 환경에서는 이 2개만 건너뛰며 나머지 가짜 백엔드 검사는 그대로 실행한다.

주요 검사 범위:

- 대기열 수정 중 작업이 시작되는 경우, ID·순서·사진·시드 보존, 전체 대기 대상의 저장 시 재확인.
- 이력 삭제 연동, 재시작 중복 방지, 화면 서버 재시작 진행률 인계.
- 갤러리 설정 복사·재생성 중복 방지·완료 표시·자동 갱신·스와이프·선택 재생.
- 1,001개 합성 이력 행에서 미리보기 동시 로딩 상한, 화면 밖/숨김 상태의 버퍼 해제, 터치의 가짜 hover 방지.
- 프롬프트 도우미의 고정 조건 보존·부분 수정·동작과 시간 검토, 직접 수정한 최종 프롬프트 동기화.
- 네 단계 생성의 사용자 확정, 후속 단계 재검토, 실패/재시작 중복 제출 방지, 합성 영상 병합.

코드·가짜 DOM 테스트 통과는 실제 iPad 재생, 생성 모델의 영상 품질 또는 모든 장치의 메모리 사용량을 보장하는 측정 결과가 아니다. 실제 작업 내용이 필요한 검증은 사용자 요청 없이 수행하지 않는다.
