# Local Models Registry

Record of all weights, sources, revisions, licenses, VRAM usage, and verification status.
Root weights directory strictly: `D:\Open_Source_Weights`

## 1. Inventory & Physical Disk Paths on D:

| Layer | Model Name / ID | Purpose | Source / URL | Format / Quant | Physical Local Path | Size (Disk) | Est / Peak VRAM | License | Status |
|---|---|---|---|---|---|---|---|---|---|
| **L0** | faster-whisper `large-v3-turbo` | Audio Transcription (word timestamps) | mobiuslabsgmbh / HuggingFace | CTranslate2 float16 | `D:\Open_Source_Weights\whisper\models--mobiuslabsgmbh--faster-whisper-large-v3-turbo` | 1.61 GB | ~3.8 GB (unloaded after) | MIT | **VERIFIED PASS** |
| **L0** | faster-whisper `large-v3` | Audio Transcription (full precision backup) | Systran / HuggingFace | CTranslate2 float16 | `D:\Open_Source_Weights\whisper\models--Systran--faster-whisper-large-v3` | 3.08 GB | ~4.2 GB (unloaded after) | Apache-2.0 | **VERIFIED PASS** |
| **L0** | faster-whisper `tiny` | Fast / CPU Fallback Transcription | Systran / HuggingFace | CTranslate2 int8 | `D:\Open_Source_Weights\whisper\models--Systran--faster-whisper-tiny` | 78 MB | < 0.5 GB | Apache-2.0 | **VERIFIED PASS** |
| **L1** | MediaPipe BlazeFace | Face detection & facecam crop tracking | Google MediaPipe | TFLite Short Range | `D:\Open_Source_Weights\models\blaze_face_short_range.tflite` | 229 KB | 0 MB (CPU LiteRT) | Apache-2.0 | **VERIFIED PASS** |
| **L1** | BGE Small (`BAAI/bge-small-en-v1.5`) | Sentence embeddings, topic shifts & dedup | BAAI / HuggingFace | Safetensors / PyTorch | `D:\Open_Source_Weights\huggingface\models--BAAI--bge-small-en-v1.5` | 401 MB | 0 MB (CPU) | MIT | **VERIFIED PASS** |
| **L1** | DistilRoBERTa Emotion (`j-hartmann/emotion-english-distilroberta-base`) | Sentence-level text emotion analysis | j-hartmann / HuggingFace | Safetensors / PyTorch | `D:\Open_Source_Weights\huggingface\models--j-hartmann--emotion-english-distilroberta-base` | 659 MB | 0 MB (CPU) | MIT | **VERIFIED PASS** |
| **L1** | Audio Spectrogram Transformer (`MIT/ast-finetuned-audioset-10-10-0.4593`) | Sound event detection (explosions, gunshots, screams, laughter) | MIT / HuggingFace | PyTorch Model | `D:\Open_Source_Weights\huggingface\models--MIT--ast-finetuned-audioset-10-10-0.4593` | 692 MB | 0 MB (CPU/GPU) | BSD-3 | **VERIFIED PASS** |
| **L2/L4** | Qwen 3.5 9B (`qwen3.5:9b`) | Primary Proposer / Critic / Arc Stitcher / Rerank | Ollama Library | Q4_K_M GGUF | `D:\Open_Source_Weights\ollama\blobs` | 6.6 GB | 7230 MB peak, 0 MB unloaded (`keep_alive: 0`) | Apache-2.0 | **VERIFIED PASS** |
| **L2/L4** | Gemma 4 E4B (`gemma4:e4b`) | Secondary Proposer / Critic / Rerank Judge | Ollama Library | Q4_K_M GGUF | `D:\Open_Source_Weights\ollama\blobs` | 6.6 GB | 5590 MB peak, 0 MB unloaded (`keep_alive: 0`) | Apache-2.0 | **VERIFIED PASS** |
| **L5** | SigLIP (`google/siglip-base-patch16-224`) | Zero-shot visual action & dead footage filter | Google / HuggingFace | Safetensors / PyTorch | `D:\Open_Source_Weights\huggingface\models--google--siglip-base-patch16-224` | 1.62 GB | 0 MB (CPU/GPU) | Apache-2.0 | **VERIFIED PASS** |
| **L5** | RapidOCR & Canny Filter | On-screen trigger words & edge complexity | RapidOCR / OpenCV | ONNX / OpenCV Canny | Embedded in Python runtime | < 25 MB | 0 MB (CPU) | Apache-2.0 | **VERIFIED PASS** |
| **L6** | Layer 6 Fusion Engine | Multi-signal virality score blending | Umation Pipeline | YAML Config Math | `config/scoring.yaml` | < 1 MB | 0 MB (CPU) | MIT | **VERIFIED PASS** |
| **L8** | Metadata Ensemble & Creator Credit | Viral titles, descriptions, hashtags & attribution | Local LLM (`llm/manager.py`) | JSON Schema | `D:\Open_Source_Weights\ollama` | Embedded | < 1.0 GB | Apache-2.0 | **VERIFIED PASS** |
| **L9** | Pillow Abstract Art & Typography | Topic-based original art (anti-frame check) | Umation Pipeline | RGBA Canvas | `app/pipeline/s5_package/` | < 5 MB | 0 MB (CPU) | MIT | **VERIFIED PASS** |
| **FT** | Personal Calibrated Ranker | Learns from creator ratings | scikit-learn | HistGradientBoosting | `feedback/` | < 2 MB | 0 MB (CPU) | BSD-3 | **VERIFIED PASS** |

## 2. Model Loading & Offline Strategy
- **Zero Cloud**: Application runs with `HF_HUB_OFFLINE=1` and strictly calls `http://127.0.0.1:11434` for Ollama.
- **VRAM Ceiling**: Stays below 7.5 GB peak on NVIDIA RTX 4060 (8 GB VRAM).
- **GPU Stage Isolation**:
  1. Whisper transcribes audio -> explicitly released via `del model; gc.collect(); torch.cuda.empty_cache()`.
  2. Ollama loads LLM with `keep_alive: 0` -> unloads immediately upon completion of generation task.
  3. Video rendering uses `h264_nvenc` hardware NVENC encoder, consuming < 1.3 GB VRAM.
