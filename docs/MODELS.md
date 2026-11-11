# Local Models Registry

Record of all weights, sources, revisions, licenses, VRAM usage, and verification status.
Root weights directory: `D:\Open_Source_Weights`

| Layer | Model Name / ID | Purpose | Source / URL | Format / Quant | Size (Disk) | Est / Peak VRAM | License | Status |
|-------|-----------------|---------|--------------|----------------|-------------|-----------------|---------|--------|
| L0 | faster-whisper `large-v3-turbo` | Audio Transcription | Systran / HuggingFace | CTranslate2 int8_float16 | ~1.6 GB | ~2.5 GB | MIT | Pending |
| L2/L4 | Qwen3.5 9B (`qwen3.5:9b` or `qwen2.5:7b`) | Primary Proposer / Judge | Ollama Library | Q4_K_M | ~5.5 GB | ~6.2 GB | Apache-2.0 | Pending |
| L2/L4 | Gemma 4 E4B (`gemma4:e4b` or verified) | Secondary Proposer / Critic | Ollama Library | Q4_K_M | ~3.5-5 GB | ~5.0 GB | Apache-2.0 | Pending |
| L1 | SenseVoice-Small | Speech Emotion & Acoustic Events | FunAudioLLM / ModelScope / HF | ONNX / PyTorch | ~234 MB | CPU or ~0.5 GB | Apache-2.0 | Pending |
| L1 | AST (`ast-finetuned-audioset-10-10-0.4593`) | Sound Event Detection | HuggingFace (MIT) | PyTorch / ONNX | ~346 MB | CPU or ~0.6 GB | BSD-3 | Pending |
| L1 | `bge-small-en-v1.5` | Semantic Topics & Candidate Dedup | BAAI / HuggingFace | ONNX / PyTorch | ~130 MB | CPU | MIT | Pending |
| L1 | `emotion-english-distilroberta-base` | Text Sentiment / Emotion | HuggingFace | PyTorch / ONNX | ~320 MB | CPU | Apache-2.0 | Pending |
| L5 | SigLIP 2 (`siglip2-base-patch16-224`) | Visual Action & Negative Filtering | Google / HuggingFace | PyTorch / ONNX | ~800 MB | ~1.5 GB | Apache-2.0 | Pending |
| L5 | RapidOCR | On-Screen Text / OCR Triggers | RapidAI | ONNX | ~20 MB | CPU | Apache-2.0 | Pending |
| L9 | SDXL Turbo / Lightning / Procedural | Thumbnail Generation | StabilityAI / ByteDance | Safetensors / GGUF | ~2.5-4 GB | ~5.5 GB (unloaded after) | Open / Permissive | Pending |
