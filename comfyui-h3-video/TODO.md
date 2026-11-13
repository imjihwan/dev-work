# TODO

아직 만들지 않은 기능. 위에서부터 순서대로 진행한다. 각 항목은 **실제 생성으로 확인해야 완료**로 본다.

## 1. 이어 만들기 (긴 영상)

H3 는 한 번에 최대 15초. 그보다 긴 영상은 DaSiWa **Continuity**(앞 영상의 끝 프레임·소리를 이어받아 다음 구간을 만듦)로 이어 붙인다. 지금 간단 화면은 틀의 이어 붙이기 설정을 늘 "새로 만들기"로 보내서 이 기능을 못 쓴다.

### 1-1. "이 결과에서 이어서 만들기" (수동)
- [ ] 생성할 때 결과 저장(checkpoint capture)을 켜서 이어 붙일 수 있게 남기기
- [ ] 결과·작업 이력에 **"이어서 만들기"** 버튼 → 다음 동작 프롬프트·길이를 적고 그 결과 뒤에 붙여 생성
- [ ] 옵션: 연결 구간 길이(5·22·39·56·73프레임, 기본 22), **참조 사진 유지**(얼굴 일관성), 출력(전체 이어진 영상 / 새 구간만)
- [ ] 같은 지점에서 다시 뽑기(DaSiWa 의 sibling reroll)

### 1-2. 긴 시나리오 → 자동 이어 만들기
- [ ] 장면 시각이 15초를 넘는 시나리오를 받으면 장면 경계에서 **10~15초 구간**으로 자동 분할(장면 중간은 자르지 않음)
- [ ] 구간 1 = 새로 생성, 구간 2부터 = 앞 구간에서 이어서. 앞 결과가 있어야 다음을 만들 수 있으므로 **서버가 하나 끝날 때마다 다음 구간을 대기열에 넣음**
- [ ] 구간마다 그 구간 장면만 담은 프롬프트(시각은 구간 기준으로 다시 계산), 참조 사진 유지
- [ ] 진행 표시(구간 n / 전체), 중간 실패·중지 처리, 새로고침 후에도 이어서 진행

### 1-3. 결과 정리
- [ ] 구간을 한 편으로 합친 결과 보기(DaSiWa "Join clips" 또는 전체 타임라인 출력), 구간별 영상도 유지
- [ ] **"이 구간부터 다시"** — 뒤 구간은 앞 구간에 기대므로 중간 구간을 바꾸면 그 뒤를 다시 만든다
- [ ] 작업 이력에 구간 묶음(체인)으로 기록

### 참고 (이미 확인한 것)
- 틀 안에 이어 붙이기 노드가 이미 있음: `DaSiWaH3ContinuitySegmentPrepare`(`1512:2796`)·`SegmentDecode`(`1512:2671`)·`ContinuityPublish`(`2797`).
- Director(`2730`) `timeline_data.continuity` 필드: `version`(3), `operation`(`new`/`continue`), `capture`, `source_kind`(`checkpoint` 등), `source_id`, `source_video_id`, `session`, `overlap_frames`(5·22·39·56·73), `extension_frames`(17 배수, 연결+새 프레임 ≤ 362), `use_references`, `output_mode`(`full`/`segment`), `continuation_prompt`, `idea`. 코드: `custom_nodes/ComfyUI-DaSiWa-Nodes/nodes/h3_continuity/core.py` `parse_settings()`, 문서: 같은 저장소 `docs/h3_continuity.md`.
- 이어 붙일 때 첫·끝 장면 사진 고정은 항상 건너뜀(문서). 장소를 바꾸려면 걸어서 이동하는 등 연결 동작이 필요.
- 예상 한계(추정): 이음새 앞뒤는 자연스럽고, 구간이 많을수록 배경·색감·옷이 조금씩 달라짐. 30초~1분은 대체로 유지.
- 예상 시간(추정, RTX 5060 Ti): 10초 구간 1개 ≈ 10~15분 → 40초 ≈ 40~60분. 15초 한 번(768×928, 8스텝)은 약 15분(5초의 4~5배).

## 2. 참조 사진 업스케일 (SeedVR2)

원본 사진이 작거나 흐리면 영상도 그만큼 나빠진다(180×270 사진에서 없던 머리띠가 생긴 사례). 사진을 넣을 때 먼저 키워서 쓰게 한다.

- [ ] 간단 화면 사진 칸에 **"선명하게 키우기"** — 짧은 변이 작은 사진(예: 768 미만)은 안내하고, 누르면 SeedVR2 로 키운 사진으로 바꿔 넣기(원본도 보관, 되돌리기)
- [ ] 목표 크기: 짧은 변 1024~1536 정도(영상 기본은 짧은 변 768, `ref_image_size=max` 도 2048 까지만 씀)
- [ ] 모델: 16GB GPU 기준 **SeedVR2 1.4B 경량판**(2.7GB, 한 번에 처리) 또는 7B fp8. `models.json` 에 선택 항목으로 추가
- [ ] 얼굴이 원본과 같은지 비교 화면(전·후 나란히)

### 참고 (이미 확인한 것)
- 이 ComfyUI(0.45)에 SeedVR2 노드가 기본으로 있음: `SeedVR2Preprocess`·`SeedVR2Conditioning`·`SeedVR2PostProcessing`·`SeedVR2TemporalChunk`·`SeedVR2TemporalMerge`(`comfy_extras/nodes_seedvr.py`). ComfyUI 템플릿 "SeedVR2: 이미지 업스케일" 있음.
- 고른 이유: 원본 구조를 지키는 **보수적** 업스케일러라 얼굴이 덜 바뀜. SUPIR·Flux 타일 업스케일은 디테일을 새로 그려 얼굴이 다른 사람처럼 될 위험, CodeFormer·GFPGAN 같은 얼굴 복원도 얼굴을 바꾸는 경향이 있어 참조용으로 제외. ESRGAN 계열(4x-UltraSharp 등)은 빠르지만 흐린 사진은 흐린 채로 커짐.
- 출처: [ComfyUI v0.28.0 SeedVR2 기본 지원](https://comfyui-wiki.com/en/news/2026-07-15-comfyui-v0-28-0) · [SeedVR2-1.4B 경량판](https://comfyui-wiki.com/en/news/2026-07-29-seedvr2-1-4b-distilled-upscaler) · [ComfyUI SeedVR2 이미지 업스케일 템플릿](https://comfy.org/ko/workflows/utility_seedvr2_image_upscale-857e50707831/) · [The Complete AI Upscaling Handbook (2026.2)](https://blog.comfy.org/p/upscaling-in-comfyui)

## 보류한 아이디어 (필요해지면)

- [ ] **강도 비교**: 같은 시드로 LoRA 강도만 바꿔 여러 개 만들기(예: 0 / 0.5 / 0.8 / 1.0)
- [ ] LoRA 강도 칸에 **음수** 허용(애니↔실사 슬라이더 LoRA 처럼 음수로 쓰는 것)
- [ ] 다른 장비 실측: Mac(M5 Max·Ultra)·RTX Spark — 지금 [PERFORMANCE.md](docs/PERFORMANCE.md) 는 추정
- [ ] '사진 1 첫 장면 고정'·실사 LoRA 2종의 결과 정리(현재 실험 단계)
