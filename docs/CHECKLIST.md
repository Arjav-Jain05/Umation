# Project Checklist: Layered Local-Only Shorts Engine

Extracted from `docs/SPEC.md`.

## Phase 0: Preflight and Environment
- [x] Audit repository: map all cloud LLM calls, pipeline stages, render pipeline, and web UI
- [x] Git branch `feature/final-local-layered` checked out
- [x] Machine constraints verified: RTX 4060 (8 GB VRAM), 16 GB RAM, D: drive free space >= 60 GB
- [x] Weights directory structure verified at `D:\Open_Source_Weights` (`ollama`, `huggingface`, `modelscope`, `torch`, `whisper`, `onnx`, `manifest.json`)
- [x] Environment variables set in `.env` and system: `WEIGHTS_DIR`, `OLLAMA_MODELS`, `HF_HOME`, `HF_HUB_CACHE`, `MODELSCOPE_CACHE`, `TORCH_HOME`, `HF_HUB_OFFLINE=1`
- [x] Ollama service configured and running pointing to `D:\Open_Source_Weights\ollama`
- [x] Core model weights verified / downloaded (`scripts/download_weights.py --core`):
  - [x] faster-whisper `large-v3` / `large-v3-turbo` in `D:\Open_Source_Weights\whisper`
  - [x] Primary LLM `qwen3.5:9b` (Q4_K_M, 6.6 GB)
  - [x] Secondary LLM configured
- [x] Write `scripts/check_local_setup.py` (PASS/FAIL with exact remediation hints)
- [x] Write `scripts/selftest.py --phase 0` (and framework for all phases)
- [x] Gate 0 Verification:
  - [x] All checks PASS in `python scripts/check_local_setup.py`
  - [x] Ollama models stored on D: drive
  - [x] 10-second audio transcribes on CUDA GPU with faster-whisper
  - [x] Primary LLM returns schema-valid JSON for test prompt
  - [x] nvidia-smi shows process active on NVIDIA RTX 4060 GPU
  - [x] Peak VRAM under 7.5 GB
  - [x] Git commit and tag `phase-0-pass`

## Phase 1: Core Clips (Usable Product)
- [x] Cloud code purge: remove all Gemini / OpenAI / Anthropic imports, keys, client classes, and references
- [x] Network guard implementation and test (assert zero non-localhost outbound requests during AI pipeline)
- [x] Layer 0 Transcription: faster-whisper `large-v3-turbo` / `large-v3`, word timestamps, explicit GPU release after use
- [x] Layer 2 Single Proposer: local LLM with Ollama JSON schema structured output (`qwen3.5:9b`)
- [x] Layer 7 Boundary snapping: sentence boundary snap (+0.3s padding), 20-60s target (max 90s, min 12s)
- [x] Basic NVENC render: `h264_nvenc` with fallback to `libx264`, word-synced ASS captions with absolute PTS alignment
- [x] Results saved to disk (video, transcript, metadata)
- [x] Gate 1 Verification:
  - [x] End-to-end run on 5-minute sample produces at least 1 valid 9:16 vertical short
  - [x] Burned-in captions in sync with audio
  - [x] Network guard test passes with network disabled
  - [x] Peak VRAM < 7.5 GB (measured: 1234 MB)
  - [x] Grep confirms zero cloud AI references remaining
  - [x] Git commit and tag `phase-1-pass`

## Phase 2: Slider, Candidates Store, Caption Presets
- [x] Candidate store database / schema: persist all candidates with full score breakdown above floor (default 35)
- [x] Scoring skeleton (Layer 6 baseline)
- [x] Quality-threshold slider UI (0-100, default 65, instant client-side filtering)
- [x] Slider unit/browser test: verify dragging slider triggers ZERO model calls
- [x] Candidate score histogram with threshold marker and S/A/B/C tier coloring
- [x] Threshold presets: Strict (80), Balanced (65), Loose (50), and "Suggest" (distribution elbow)
- [x] Relative mode toggle (keep top X% of video)
- [x] Borderline candidates drawer with manual pin / exclude checkboxes
- [x] 7 Caption style presets (modern box, classic yellow outline, minimal shadow, cyan, yellow box, neon green, red/gaming)
- [x] "Render selected" workflow (`GET /projects/{id}/candidates`, `POST /projects/{id}/render`)
- [x] Gate 2 Verification:
  - [x] Candidate store accurately saves all candidates above floor
  - [x] Slider changes rendered count instantly with 0 backend model calls
  - [x] Only pinned/selected candidates are rendered
  - [x] Browser smoke test drives slider and verifies UI behavior
  - [x] Git commit and tag `phase-2-pass`

## Phase 3: Audience Signals and Sensors
- [ ] Audience signals (yt-dlp):
  - [ ] Most replayed heatmap normalized 0-1
  - [ ] Timestamped comments extraction & 10s binning
  - [ ] Chat replay processing (messages/s, spikes, hype words)
  - [ ] Chapters soft boundaries
  - [ ] Fail-soft: mark missing signals as missing, never 0
- [ ] Layer 1 Sensors:
  - [ ] SenseVoice voice emotion & sound events (laughter, applause, crying)
  - [ ] AST sound event detection (explosions, gunshots, screams, siren, etc.) or YAMNet fallback
  - [ ] Loudness / energy profile (ebur128 / RMS)
  - [ ] Text emotion per sentence
  - [ ] Hype lexicon & pace (WPM, exclamation density)
  - [ ] Scene cuts (PySceneDetect) & motion energy (2 fps frame diff)
  - [ ] Topic boundaries & dedup (bge-small-en-v1.5 embeddings)
- [ ] Hot-zone map generation & per-second timeline text generator for LLM
- [ ] Fusion v1 with automatic weight redistribution when signals are missing
- [ ] Gate 3 Verification:
  - [ ] Each sensor runs individually on 2-min sample and emits valid track
  - [ ] Videos with no heatmap/comments run without failure
  - [ ] Fusion weights re-normalize dynamically
  - [ ] Git commit and tag `phase-3-pass`

## Phase 4: Multi-Model Quality
- [ ] Second proposer (different model family) with candidate deduplication & agreement scoring (>50% overlap)
- [ ] Layer 3 Critic & Arc stitcher (thinking mode enabled, narrow questions, Part 1/2/3 splits)
- [ ] Layer 4 Head-to-head rerank (shuffled batches of 5-6, 3 shuffles, 2-3 judges, 0-100 rerank score)
- [ ] Hardened LocalModelManager (`llm/`):
  - [ ] Provider interface with Ollama backend
  - [ ] Chain of fallback models from `config/models.yaml`
  - [ ] CUDA OOM recovery: unload, context reduction (8192 -> 4096), next model fallback
  - [ ] Retries with backoff and jitter
  - [ ] JSON repair mechanism
  - [ ] Unload between heavy stages (`keep_alive: 0`)
- [ ] Model bake-off harness (`scripts/bakeoff.py`)
- [ ] Feedback collection (`feedback/ratings.jsonl`) & ranker training (`scripts/train_ranker.py`)
- [ ] Gate 4 Verification:
  - [ ] Model manager failure tests pass (OOM, timeout, bad JSON, model missing)
  - [ ] Rerank position-bias test passes
  - [ ] Ablation study (Qwen-only vs two proposers vs full funnel) on test sample
  - [ ] Git commit and tag `phase-4-pass`

## Phase 5: Visual Layer, Metadata, Thumbnails, Polish
- [ ] Layer 5 Visual Evidence:
  - [ ] SigLIP 2 zero-shot frame classification (1 fps inside shortlist)
  - [ ] RapidOCR on-screen trigger words inside candidate ranges
  - [ ] Optional SmolVLM2 tie-breaker
- [ ] Layer 8 Metadata Ensemble:
  - [ ] Title generation & judge pass (<70 chars, high curiosity, true to content)
  - [ ] Description, hashtags, and mandatory creator credit block
  - [ ] Fair use & source policy (`docs/SOURCE_POLICY.md`)
- [ ] Layer 9 Thumbnails:
  - [ ] SDXL Turbo/Lightning or FLUX.1 schnell topic background art
  - [ ] Unload diffusion model, Pillow headline render
  - [ ] Fallback procedural gradient + text
- [ ] Game profiles (`profiles/gaming_gta6.yaml`, `profiles/default.yaml`)
- [ ] Pipeline speed presets (Fast, Balanced, Best) and per-layer toggles
- [ ] Gate 5 Verification:
  - [ ] Full end-to-end run on 5-minute sample
  - [ ] 60-minute stress test run
  - [ ] Peak VRAM verified < 7.5 GB throughout
  - [ ] Documentation complete (`README.md`, `docs/MODELS.md`, `docs/REFERENCES.md`, `docs/CHANGES.md`)
  - [ ] Git commit and tag `phase-5-pass`
