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
| DaSiWa 이전 버전(빠름, 4스텝) | `dasiwa_minimax_h3_ref2va_v4_pruned_turbo_int8.safetensors` | `models/diffusion_models/MiniMaxH3/` | 19.5GB | [Civitai · Hybrid v4 Turbo](https://civitai.com/models/2877206?modelVersionId=3392061) |
| 기본 H3 · 참조 사진용(터보 아님) | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | `models/diffusion_models/MiniMaxH3/` | 19.5GB | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors) |
| 기본 H3 · 첫·끝 장면용(터보 아님) | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | `models/diffusion_models/MiniMaxH3/` | 19.5GB | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors) |
| 터보 LoRA · 참조 사진 4스텝 | `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` | `models/loras/` | 1.8GB | [Comfy-Org/MiniMax-H3 · loras](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors) |
| 터보 LoRA · 첫·끝 장면 8스텝 | `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` | `models/loras/` | 1.8GB | [Comfy-Org/MiniMax-H3 · loras](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors) |
| 실사 사람 LoRA (fal) — 얼굴 클로즈업·피부·표정·영화 조명 | `h3-realism-people-t2v-i2v-r2v.safetensors` | `models/loras/` | 125MB | [fal/MiniMax-H3-Realism-People-LoRA](https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA) — 프롬프트 맨 앞에 `r34l1sm`(Civitai 에 없어 화면이 트리거를 자동으로 못 넣음 → 직접 입력), 강도 1.0(약하게 0.6~0.8). 이 PC 에서 아직 생성 결과 미확인 |
| 영화 질감 LoRA (Cinematic Official Release) | `电影感loraV1.0正式版_剪枝与非剪枝通用.safetensors` | `models/loras/` | 296MB | [Civitai 2937713](https://civitai.com/models/2937713) (로그인 필요) — 트리거 없음, 강도 0.7(움직임 많으면 0.5). 올린 사람이 MiniMax 공식인지는 미확인. 이 PC 에서 아직 생성 결과 미확인 |

기본 H3 모델은 터보가 아니라서 그대로 쓰면 20스텝 이상(5배 이상 느림)이 필요합니다. 터보 LoRA 를 같이 넣으면 4~8스텝으로 돌아갑니다(아래 실측 참고).

## 어떤 걸 쓸까

| 하고 싶은 것 | 고를 것 | 실측(5초 영상, RTX 5060 Ti 16GB) |
|---|---|---|
| 기본 · 품질 | DaSiWa v5 터보 8스텝 | 241초 |
| 빠르게 시안 | DaSiWa v5 터보 4스텝 또는 v4 터보 4스텝 | v4 4스텝 100~186초 |
| 시작·끝 장면을 정확히 지정 | 첫·끝 장면 방식 + DaSiWa(혼합 모델) 또는 기본 FL2VA + fl2v 터보 LoRA 8스텝 | 기본 FL2VA + LoRA 274초(불러오기 포함) |
| 원본(MiniMax 공식) 그대로 | 기본 REF2VA + ref2v 터보 LoRA 4스텝 | 132초 |

- DaSiWa 는 MiniMax H3 를 공동체가 섞어 다듬은 모델입니다(REF2VA + FL2VA 혼합, 소리·목소리 개선 주장). 제작자 안내: GXS v5 Turbo 는 4스텝=빠른 미리보기(소리 품질 저하), 6스텝=기본, 8스텝=품질.
- DaSiWa 는 int8·w6a8·w4a8 만 배포합니다(2026-11 기준, bf16·fp8 없음). int8 이 가장 정밀한 판입니다.

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
