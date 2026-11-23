# 모델·LoRA 안내

파일 목록·링크·sha256 의 원본은 [`models.json`](../models.json) 입니다(이 문서는 사람이 읽기 쉽게 풀어 쓴 것).
받기·검증은 `python scripts/get_models.py --comfy <ComfyUI 폴더>`.

## 필수 (간단 화면 기본값이 쓰는 것)

| 역할 | 파일 | 넣을 곳 | 크기 | 받는 곳 |
|---|---|---|---|---|
| 영상 생성 본체 | `dasiwa_minimax_h3_ref2va_v5xs_pruned_graviton_turbo_int8_row-wise_convrot_runtime_mixed.safetensors` | `models/diffusion_models/MiniMaxH3/` | 19.5GB | [Civitai · DaSiWa GXS v5 Turbo](https://civitai.com/models/2877206?modelVersionId=3457969) (로그인 필요) |
| 텍스트·사진 이해 | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `models/text_encoders/` | 14.6GB | [Hugging Face · Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors) |
| 영상 디코더 | `minimax_h3_video_vae_int8_convrot.safetensors` | `models/vae/MiniMaxH3/` | 2.6GB | [Comfy-Org/MiniMax-H3 · vae](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/vae/minimax_h3_video_vae_int8_convrot.safetensors) |
| 소리 디코더 | `minimax_h3_audio_vae_fp32.safetensors` | `models/vae/MiniMaxH3/` | 0.6GB | [Comfy-Org/MiniMax-H3 · vae](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/vae/minimax_h3_audio_vae_fp32.safetensors) |
| 생성 중 미리보기 | `taeh3.safetensors` | `models/vae_approx/` | 9MB | [Kijai/MiniMax-H3-TAE](https://huggingface.co/Kijai/MiniMax-H3-TAE/blob/main/vae_approx/taeh3.safetensors) |

> 폴더 이름(`MiniMaxH3/` 하위 폴더 포함)은 템플릿에 적힌 경로와 같아야 합니다. 다르면 ComfyUI 가 "파일 없음" 오류를 냅니다.

## 선택

| 역할 | 파일 | 넣을 곳 | 크기 | 받는 곳 |
|---|---|---|---|---|
| DaSiWa GXS v5 일반판(동작 비교, 25스텝) | `dasiwa_minimax_h3_ref2va_v5xs_pruned_graviton_int8_row-wise_convrot_runtime_mixed.safetensors` | `models/diffusion_models/MiniMaxH3/` | 19.5GiB | [Civitai · DaSiWa GXS v5 일반판](https://civitai.com/models/2877206?modelVersionId=3457966) · [INT8 파일](https://civitai.com/api/download/models/3457966?fileId=3359509) (로그인 필요) |
| DaSiWa 이전 버전(빠름, 4스텝) | `dasiwa_minimax_h3_ref2va_v4_pruned_turbo_int8.safetensors` | `models/diffusion_models/MiniMaxH3/` | 19.5GB | [Civitai · Hybrid v4 Turbo](https://civitai.com/models/2877206?modelVersionId=3392061) |
| 기본 H3 · 참조 사진용(터보 아님) | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | `models/diffusion_models/MiniMaxH3/` | 19.5GB | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors) |
| 기본 H3 · 첫·끝 장면용(터보 아님) | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | `models/diffusion_models/MiniMaxH3/` | 19.5GB | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors) |
| 터보 LoRA · 참조 사진 4스텝 | `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` | `models/loras/` | 1.8GB | [Comfy-Org/MiniMax-H3 · loras](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors) |
| 터보 LoRA · 첫·끝 장면 8스텝 | `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` | `models/loras/` | 1.8GB | [Comfy-Org/MiniMax-H3 · loras](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors) |
| 실사 사람 LoRA (fal) — 얼굴 클로즈업·피부·표정·영화 조명 | `h3-realism-people-t2v-i2v-r2v.safetensors` | `models/loras/` | 125MB | [fal/MiniMax-H3-Realism-People-LoRA](https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA) — 트리거 `r34l1sm`(Civitai 에 등록이 안 돼 있어 `cards.seed.json` 에 기본값으로 넣어 둠 → 고르면 자동으로 들어감), 강도 1.0(약하게 0.6~0.8). 이 PC 에서 아직 생성 결과 미확인 |
| 영화 질감 LoRA (Cinematic Official Release) | `电影感loraV1.0正式版_剪枝与非剪枝通用.safetensors` | `models/loras/` | 296MB | [Civitai 2937713](https://civitai.com/models/2937713) (로그인 필요) — 트리거 없음, 강도 0.7(움직임 많으면 0.5). 개인 제작자(TuTu_1018)가 올린 것으로 MiniMax 공식 배포가 아니다(이름의 "Official Release" 는 제작자 자신의 정식판이라는 뜻, 2026-11-23 Civitai 확인). 이 PC 에서 아직 생성 결과 미확인 |

기본 H3 모델은 터보가 아니라서 그대로 쓰면 20스텝 이상(5배 이상 느림)이 필요합니다. 터보 LoRA 를 같이 넣으면 4~8스텝으로 돌아갑니다(아래 실측 참고).

## 어떤 걸 쓸까

**DaSiWa v5 일반 25스텝 (동작 비교)** 조합은 일반판 INT8·`res_multistep/simple`·LoRA 없음으로(shift 는 모델 자동값 11/4) 비교를 시작한다. 기존 터보 기본값과 대기열은 바꾸지 않는다. 체크포인트 파일이 없는 조합을 선택하면 다른 모델에 설정만 적용하지 않고 안내한다. 다운로드 후 `python scripts/get_models.py --comfy ComfyUI --only dasiwa_v5_int8`로 SHA256을 확인하고 설치한다. 일반판 파일은 20,967,668,928바이트이며 SHA256은 `a1602bd7780c6fa920ffefb567a9bd19612f846421eefc0d98479934daa9ddbb`다. 일반판이 동작 지시를 더 잘 따르는지는 별도 비교가 필요하며 실제 영상 품질은 아직 검증하지 않았다.

**Shift 값 주의(2026-11-23 수정)**: 그 전에는 스케줄러가 shift 노드 앞 모델에 연결돼 있어, 화면의 Video shift 와 상관없이 영상 스케줄이 H3 기본값 12 로 돌았다(터보·일반 모두). 이제는 화면 값이 그대로 쓰인다. 고급 설정을 건드리지 않으면 모델별 자동값(작성자 권장 범위의 가운데: 일반 11/4, 터보 7/4)이 들어간다. 예전 일괄 기본값 10/3 이 모델 기본값·조합에 저장돼 있으면 효과가 없던 값이라 서버 시작 때 지운다. 수정 전 결과를 같은 시드로 재현하려면 영상 shift 12 를 쓴다(이력 불러오기·재생성은 자동으로 12).

이 일반판에는 [동일 바이트의 공개 Hugging Face 미러](https://huggingface.co/zzb1420/MiniMax-H3-ref2va-V5xs-INT8)를 추가했다. Civitai 파일이 Downloads에 없으면 설치 도구가 미러의 고정 커밋 `ed6b8c670ef5500576b0faba37f5e318ad0983e9`에서 직접 받는다. 원본 크기·SHA256은 그대로 사용하며 전체 검증을 마친 `.part`만 최종 모델 파일로 교체한다. 사용자 로그인이나 휴대폰 중계 다운로드가 필요 없다.

| 하고 싶은 것 | 고를 것 | 실측(5초 영상, RTX 5060 Ti 16GB) |
|---|---|---|
| 기본 · 품질 | DaSiWa v5 터보 8스텝 | 241초 |
| 빠르게 시안 | DaSiWa v5 터보 4스텝 또는 v4 터보 4스텝 | v4 4스텝 100~186초 |
| 시작·끝 장면을 정확히 지정 | 첫·끝 장면 방식 + DaSiWa(혼합 모델) 또는 기본 FL2VA + fl2v 터보 LoRA 8스텝 | 기본 FL2VA + LoRA 274초(불러오기 포함) |
| 원본(MiniMax 공식) 그대로 | 기본 REF2VA + ref2v 터보 LoRA 4스텝 | 132초 |

- DaSiWa 는 MiniMax H3 를 공동체가 섞어 다듬은 모델입니다(REF2VA + FL2VA 혼합, 소리·목소리 개선 주장). 제작자 안내: GXS v5 Turbo 는 4스텝=빠른 미리보기(소리 품질 저하), 6스텝=기본, 8스텝=품질.
- DaSiWa 는 int8·w6a8·w4a8 만 배포합니다(2026-11 기준, bf16·fp8 없음). int8 이 가장 정밀한 판입니다.

## 모델·LoRA 조사 메모 (2026-11-23 확인)

출처는 각 저장소·모델 페이지의 공개 정보다. 실측한 것은 [PERFORMANCE.md](PERFORMANCE.md)에 따로 적는다.

**DaSiWa GXS v5 Turbo(기본 모델)**
- 구성(모델 페이지 원문): "Graviton Merge: DaSiWa v4 x DaSiWa v5 x Singularity v2 + Pika-H3-Flex-HD-Turbo (REF2VA)". 파일 이름의 `ref2va` 는 방식 제한이 아니다(참조·첫끝 장면·글만으로 모두 쓴다).
- 작성자 권장: `euler/simple` 또는 `LCM/simple`, 영상 shift 6~12, 소리 shift 3~5, 스텝 4(빠른 미리보기, 소리 품질 저하)·6(기본)·8(품질). 일반판은 `res_multistep/simple` 또는 `euler/simple`, shift 10~12/3~5, 20~25스텝.
- **터보 모델에 터보 LoRA 를 또 얹지 않는다.** 이 모델에 들어 있는 Pika H3 Flex 의 ComfyUI 공식 문서가 "turbo 나 Lightning LoRA 를 위에 겹치지 말 것"이라고 안내한다(가속이 이중으로 걸린다). 모델 페이지 댓글에서도 작성자가 같은 답을 했다고 전해진다. 화면이 이 조합을 고르면 알려 준다.
- int8 이 기본 파일이다. 모델 페이지 댓글로 전해진 작성자 설명으로는 w6a8(15.6GB)은 제약이 큰 장비용이고 w4a8(11.7GB)은 int8 화질을 넘지 못한다(댓글은 로그인 없이 자동으로 확인할 수 없어 직접 확인하지 못했다).

**H3 권장값(ComfyUI 공식 문서·설치본 노드 소스)**
- 기준 캔버스는 16:9 에서 1344×768(짧은 변 768, 약 1.03MP), 변은 32의 배수, 24fps, 길이는 17k+5 프레임 격자(ComfyUI 문서). 노드 설명에 따르면 124프레임이 약 5초이고 학습 범위는 약 124~362프레임(5~15초)이다.
- 이 틀은 CFG 없이(BasicGuider, 조건 하나) 돈다. 설치본의 H3 모델 코드에는 가이던스 세기 입력이 없어 네거티브 프롬프트도 쓰이지 않는다.
- 참조 사진 방식의 터보(4스텝 LoRA)는 "빠르지만 참조·소리가 약하다, 참조가 유지돼야 하면 20~25스텝"이라고 문서가 안내한다. 스타일 LoRA 는 참조와 경쟁하므로 낮은 강도(약 0.5)를 권한다.
- 얼굴이 무너지는 문제는 MiniMax 가 인정하고 "체계적으로 해결 중"이라고 답한 알려진 한계다(2026-08-20, 일정 없음). 사용자 경험으로는 넓은 구도에서 두드러지고 가까운·중간 구도가 안정적이다.

**LoRA**
- 실사 사람 LoRA(fal): 트리거 `r34l1sm` 을 프롬프트 앞쪽에. 제작자 안내는 강도 1.0 이 의도값, 가볍게는 0.6~0.8. 176개 실사 인물 클립으로 학습(rank 32). 제작자가 fp16/fp8 기준으로 만들었다고 했고, pruned int8 에서 물체가 사라지거나 참조 방식에서 팔다리가 어긋난다는 사용자 보고가 있다 — 참조 사진과 같이 쓸 때는 0.5~0.7 부터 시험해 본다.
- 터보 LoRA(기본 H3 모델과 함께 쓰는 것) 신판 — `lightx2v/Minimax-h3-Turbo`. 이 저장소가 받게 해 둔 `ref2v 4step v0.1`·`fl2v 8step v1.0` 은 544p 로 학습한 초기판이다.

| 파일(ComfyUI 형식) | 크기 | sha256 | 올린 날 | 비고 |
|---|---:|---|---|---|
| `minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors` | 1,956,193,000 | `6a56f41ab4229c9dd845b9501bbd475ee57e112d846cf2e819d534a1ae928c5a` | 2026-09-03 | 참조 사진용으로 사용자 평이 가장 안정적(참조·목소리 유지) |
| `minimax_h3_ref2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors` | 1,956,193,000 | `e56863a7524e0300729cbb7b64cc8b548d90698c1abbf7d83898b0122fbe1e81` | 2026-10-20 | 말소리가 흐트러진다는 보고 1건 |
| `minimax_h3_ref2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors` | 1,956,193,000 | `b4da466e43588004097dfbcde245ccc439c34a26bc997cb76a0b53a1d549ea0d` | 2026-10-20 | 흐림·떨림 보고 |
| `minimax_h3_fl2v_turbo_8step_v1.2_768p_comfyui_bf16.safetensors` | 2,115,772,012 | `2d8e2235c2f24c44507ab762f7b48e6f80dcd6cca3d304b9eb80212be2d93fd2` | 2026-11-12 | pruned 모델과 층 모양이 맞지 않는다는 안내(pruned 용은 Kijai 저장소) |

이 표의 파일은 아직 `models.json` 에 넣지 않았다(이 PC 에서 생성 결과를 확인한 뒤 넣는다).

## GPU별 주의

| 장비 | 바꿔야 하는 것 |
|---|---|
| RTX 50 (블랙웰) | 그대로 |
| RTX 30·40 | 텍스트 모델 `nvfp4` 는 블랙웰 전용 기능이라 느리거나 안 될 수 있음 → 같은 저장소의 `qwen3vl_32b_minimax_h3_int8_convrot.safetensors`(27.1GB) 로 바꾸고 템플릿 CLIPLoader 값(`1512:2587`)도 그 이름으로 |
| VRAM 24GB 이상 | 그대로(더 빠름). 1080p·긴 영상에 유리 |
| Apple Silicon(맥) | 확인 안 됨. ComfyUI 코드상 int8 모델은 맥 GPU 에서 fp16 으로 풀어 계산하는 경로가 있으나 실측 안 함. 텍스트 모델 nvfp4 는 맥에서 막힐 가능성이 높고, `comfy kitchen attention`·fp16 누적 설정도 바꿔야 할 수 있음 → [PERFORMANCE.md](PERFORMANCE.md) |

## 라이선스·출처

| 대상 | 링크 |
|---|---|
| MiniMax H3 (본체·텍스트 모델·VAE) | [MiniMaxAI/MiniMax-H3](https://huggingface.co/MiniMaxAI/MiniMax-H3) — *MiniMax H3 Community License*. 사용 지역 제한 조항이 있으니 원문 확인 |
| ComfyUI 용 변환 파일 | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) |
| DaSiWa 모델 | [Civitai 2877206](https://civitai.com/models/2877206) |
| DaSiWa 워크플로(템플릿 원본) | [darksidewalker/dasiwa-comfyui-workflows · C-MMH3-33](https://github.com/darksidewalker/dasiwa-comfyui-workflows/tree/main/C-MMH3) |
| DaSiWa 노드 | [darksidewalker/ComfyUI-DaSiWa-Nodes](https://github.com/darksidewalker/ComfyUI-DaSiWa-Nodes) (GPL-3.0) |
| 미리보기 디코더 | [Kijai/MiniMax-H3-TAE](https://huggingface.co/Kijai/MiniMax-H3-TAE) |

## models.json 에 파일 추가하기

새 PC 에서도 자동으로 받게 하려면 `models.json` 의 `files` 에 항목을 더합니다.

```json
{
  "id": "짧은_영문_id",
  "role": "역할 설명(한글)",
  "required": false,
  "source": "hf",                         // 또는 "civitai"
  "repo": "Owner/Repo", "path": "저장소 안 경로",          // hf 일 때
  "page": "Civitai 페이지", "url": "https://civitai.com/api/download/models/<버전>?fileId=<파일>", // civitai 일 때
  "filename": "실제 파일명.safetensors",
  "dest": "models/loras",                 // ComfyUI 폴더 기준
  "size": 1234567890,                     // 바이트
  "sha256": "소문자 hex"
}
```
- Hugging Face: `https://huggingface.co/api/models/<repo>/tree/main?recursive=true&expand=true` 의 `size`·`lfs.oid` 가 크기·sha256.
- Civitai: `https://civitai.com/api/v1/model-versions/<버전 id>` 의 `files[].id`·`sizeKB`·`hashes.SHA256`.
