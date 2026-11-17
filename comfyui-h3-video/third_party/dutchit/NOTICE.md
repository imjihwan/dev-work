# DutchIT H3 prompt adapter

Upstream: https://huggingface.co/DutchIT/minimax-prompt-enhancer

Pinned revision: `4c42ae0ac9a5310c6d9487fb060e728cf02b92fd`.
Author/project: DutchIT; upstream README also links to `royen99/minimax-h3-prompt-enhancer`.
License: Apache License 2.0; the upstream license is retained in `LICENSE.txt`.
`Modelfile.ref.txt` is an unmodified copy of the pinned reference-mode recipe, retained for provenance. It is not executed or sent wholesale to the local model.

Local modifications (2026-11-17):

- Adapt the reference-mode role/timeline/audio guidance to the existing editor's JSON draft and exact-substring edit interfaces.
- Keep subject definitions, retention conditions, location/camera and one-take settings under the host editor's control. Do not migrate existing form state, saved bundles, jobs or workflows.
- Remove automatic age/ethnicity inference, secondary-picture role guessing, example-driven cuts, default durations and word-count padding.
- Use an on-demand CPU-only llama.cpp process, two threads and a memory guard. Preserve a separately selected legacy engine; never silently fall back to it.
- Process text only. The optional upstream image-input capability is not enabled; no images, history, results or queue contents are sent to the writing model.

The upstream project supplies prompting recipes, not newly trained model weights. The base model is Huihui-Qwen3-VL-8B-Instruct-abliterated, derived from Qwen3-VL-8B-Instruct. The pinned GGUF conversion is published by mradermacher; URL, size and SHA256 are recorded in `models.json`.
