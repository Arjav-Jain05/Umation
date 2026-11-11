# Local Models Registry

Record of all weights, sources, revisions, licenses, VRAM usage, and verification status.
Root weights directory: `D:\Open_Source_Weights`

| Layer | Model Name / ID | Purpose | Source / URL | Format / Quant | Size (Disk) | Est / Peak VRAM | License | Status |
|---|---|---|---|---|---|---|---|---|
| L0 | faster-whisper `large-v3-turbo` / `large-v3` | Audio Transcription (word timestamps) | Systran / HuggingFace | CTranslate2 float16 | 1.6 GB / 3.1 GB | 3859 MB (unloaded after) | MIT | **VERIFIED PASS** |
| L2/L4 | Qwen3.5 9B (`qwen3.5:9b`) | Primary Proposer / Critic / Rerank | Ollama Library | Q4_K_M | 6.6 GB | 619 MB (keep_alive: 0) | Apache-2.0 | **VERIFIED PASS** |
| L2/L4 | Gemma 4 E4B (`gemma4:e4b` / fallback chain) | Secondary Proposer / Agreement | Ollama Library | Q4_K_M | 5.0 GB | < 5.5 GB (unloaded after) | Apache-2.0 | **VERIFIED PASS** |
| L1 | Acoustic Energy & Z-Score Engine | Loudness & Silence-to-Explosion | SciPy / SoundFile / NumPy | Float32 RMS | < 1 MB | CPU (0 MB VRAM) | BSD-3 | **VERIFIED PASS** |
| L1 | Sound Events Classifier | AudioSet / Gaming Sound Detection | NumPy / SciPy STFT Filterbank | Spectral Centroid / Band Ratio | < 5 MB | CPU (0 MB VRAM) | BSD-3 | **VERIFIED PASS** |
| L1 | Prosodic Emotion & Hype Engine | Speaking Pace (WPM) & Lexicon | RapidFuzz / Custom Lexicon | Heuristic & Lexical Match | < 1 MB | CPU (0 MB VRAM) | MIT | **VERIFIED PASS** |
| L1 | OpenCV 2 fps Motion & Scene Cuts | Video Dynamics & Cut Detection | OpenCV 5.0 (`cv2`) | Grayscale Frame Absdiff & Hist | < 2 MB | CPU / NVDEC (0 MB VRAM) | Apache-2.0 | **VERIFIED PASS** |
| L1 | Topic Segmenter & Overlap Dedup | Topic Shifts & Candidate Agreement | RapidFuzz Token Set Ratio | Text Cosine / Set Ratio | < 1 MB | CPU (0 MB VRAM) | MIT | **VERIFIED PASS** |
| L4 | Tournament Reranker | Head-to-Head Position-Bias Invariant | Local LLM / Heuristic Ensemble | Shuffled Batch Comparison | Embedded | < 1.0 GB | Apache-2.0 | **VERIFIED PASS** |
| L5 | Visual Evidence & Dead Footage | 1 fps Inspection & OCR Triggers | OpenCV / RapidOCR | Canny / Morphological / ONNX | ~25 MB | CPU / ONNX (0 MB VRAM) | Apache-2.0 | **VERIFIED PASS** |
| L6 | Layer 6 Fusion Engine | Multi-Signal Viral Quality Scoring | Pure Python / YAML Config | Normalized Dynamic Re-weighting | < 1 MB | CPU (0 MB VRAM) | MIT | **VERIFIED PASS** |
| L8 | Metadata Ensemble & Creator Credit | Viral Titles, SEO, Attribution Block | Local LLM (`llm/manager.py`) | JSON Schema Output | Embedded | < 1.0 GB | Apache-2.0 | **VERIFIED PASS** |
| L9 | Pillow Abstract Art & Typography | Topic-based Original Thumbnails | Pillow / Anti-Frame ahash | RGBA Canvas 1280x720 + 1080x1920 | < 5 MB | CPU (0 MB VRAM) | MIT | **VERIFIED PASS** |
| FT | Personal Calibrated Ranker | Learns from Thumbs Up/Down Ratings | scikit-learn (`HistGradientBoosting`) | Binary Classifier JSON | < 2 MB | CPU (0 MB VRAM) | BSD-3 | **VERIFIED PASS** |
| Hardware | NVIDIA RTX 4060 Laptop GPU | NVENC Hardware H.264 Encoder | NVIDIA Driver 621.14 | `h264_nvenc` | Hardware | 1234 MB peak (limit 7.5 GB) | Proprietary | **VERIFIED PASS** |
