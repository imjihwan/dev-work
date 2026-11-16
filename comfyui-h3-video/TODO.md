# 후속 확인

- [ ] iPad 실기기에서 단독/동시 재생, 페이지 경계 스와이프, 백그라운드 복귀를 사용자 확인으로 검증한다. 현재 완료된 것은 가짜 DOM 및 버퍼 수명 검사다.
- [ ] 새 PC의 빈 설치 폴더에서 설치 재현성을 검증한다. 모델과 개인 데이터는 별도로 준비한다.
- [ ] CPU 프롬프트 도우미의 속도·문장 상세도·동작 시간 검토를 합성 예제로 계속 평가한다.

네 편 이어 만들기, 갤러리·설정 복사 재생성, 전체 대기항목 일괄수정은 구현되어 있다. 사용법과 제약은 README 및 docs 문서를 따른다. 실제 개인 작업이나 결과물을 자동 점검 대상으로 삼지 않는다.

## 미구현: 참조 사진 업스케일 (SeedVR2)

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
