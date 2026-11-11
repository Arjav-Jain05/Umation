# Shorts Engine (Offline & Unlimited Local Edition)

Free, 100% local Windows web app (FastAPI + vanilla HTML/CSS/JS on `127.0.0.1:8000`) that turns a single YouTube link or local video file into upload-ready vertical shorts: variable clip count, Part 1/2/3 splits, face-aware 9:16 layouts, 7 animated caption presets, AI director effects, generated thumbnails, and metadata with mandatory creator credit block. Tuned for GTA 6 and gaming clipping.

**Zero Cloud AI Runtime Calls:** The entire pipeline runs completely offline on your local GPU/CPU with Ollama and faster-whisper. No cloud API keys, subscriptions, or upload bandwidth required.

**The user uploads manually. The app never uploads anything to any platform.**

---

## 1. Offline / Unlimited Mode

In this edition, all cloud dependencies (Gemini, OpenAI, Anthropic) have been purged and replaced with an audience-aware, layered, local open-source pipeline:

1. **Local Audio Transcription (Layer 0):** `faster-whisper` (`large-v3-turbo` / `large-v3`) running on NVIDIA CUDA float16. Model is loaded only during the transcribe stage and freed immediately (`keep_alive: 0`).
2. **Audience-First Signals (Section 4):** YouTube most replayed heatmap (normalized 0-1), timestamped comments extraction with like weighting in 10s bins, live stream chat replay activity spikes and hype keyword detection, and chapter boundaries as soft topic breaks. Fail-soft: missing signals are marked missing, never 0.
3. **Multi-Signal Layer 1 Sensors:**
   - **Acoustic Loudness & Z-Scores:** RMS energy profiling, peak bursts, and silence-to-explosion suspense/payoff detection.
   - **Sound Events Detection:** AudioSet acoustic feature classifier for explosions, gunshots, screams, laughter, cheering, tire squeals, and sirens.
   - **Voice Emotion & Hype Lexicon:** Speaking pace (WPM), exclamation density, and RapidFuzz matching against gaming glossaries (`profiles/gaming_gta6.yaml`).
   - **Visual Motion & Scene Cuts:** 2 fps OpenCV grayscale frame difference and color histogram scene cut detection.
   - **Topic Segmentation & Dedup:** Sentence similarity topic boundary segmentation and candidate agreement dedup (>50% time overlap).
4. **Local LLM Proposers & Critic (Layer 2 & 3):** Ollama daemon on `127.0.0.1:11434` running `qwen3.5:9b` (Q4_K_M) with fallback chains, automatic CUDA OOM recovery, and context window reduction.
5. **Head-to-Head Tournament Reranker (Layer 4):** Shuffled batch tournaments (5-6 clips per batch, multiple random shuffles) eliminating LLM presentation position bias.
6. **Layer 6 Dynamic Fusion:** Composite viral quality scoring ($0-100$) with dynamic weight redistribution when audience signals are unavailable.
7. **Live Quality Slider UI:** Drag the threshold slider ($0-100$) on the results page to filter candidates in real time with **ZERO model calls**. Preset chips: Strict (80), Balanced (65), Loose (50), and Otsu Suggest.
8. **7 Caption Presets:** Select from `modern_box`, `classic_yellow`, `minimal_shadow`, `cyan`, `yellow_box`, `neon_green`, and `red_gaming`.
9. **Hardware Encoding:** Ultra-fast 1080x1920 9:16 rendering with `h264_nvenc` and synchronized ASS subtitles using absolute PTS alignment.
10. **Calibrated Personal Ranker:** Collects thumbs up/down feedback into `feedback/ratings.jsonl` and trains a `HistGradientBoostingClassifier` with feature importance audits (`scripts/train_ranker.py`).

---

## 2. Requirements

- **Operating System:** Windows 11 (64-bit).
- **GPU:** NVIDIA GeForce RTX 4060 (8 GB VRAM) with NVIDIA driver 621.14+ (Strict peak VRAM ceiling: < 7.5 GB).
- **Python:** 3.12 (specifically tested on Python 3.12.10).
- **Local AI Daemon:** [Ollama](https://ollama.com/) running on `127.0.0.1:11434` with model `qwen3.5:9b`.
- **System Tools:**
  - `ffmpeg` (Gyan full build with `h264_nvenc` support) and `ffprobe` in `PATH`.
  - `deno` in `PATH` (used as the secure JS challenge solver for `yt-dlp`).
- **Disk Space:** At least 60 GB free on `D:\Open_Source_Weights` for offline model weights.

---

## 3. Installation & Setup

1. **Clone the repository:**
   ```powershell
   git clone <repo-url>
   cd Umation
   ```
2. **Activate Python virtual environment:**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
3. **Verify weights directory:**
   Ensure `D:\Open_Source_Weights` exists with:
   - `whisper/` (faster-whisper `large-v3` / `large-v3-turbo`)
   - `ollama/` (`qwen3.5:9b`)
4. **Start the Ollama daemon:**
   ```powershell
   $env:OLLAMA_MODELS = "D:\Open_Source_Weights\ollama"
   $env:OLLAMA_HOST = "127.0.0.1:11434"
   ollama serve
   ```
5. **Run the preflight verification:**
   ```powershell
   python scripts/selftest.py --phase 0
   ```

---

## 4. Launching the App

1. Start the application server:
   ```powershell
   .\start.bat
   ```
   Or launch directly via uvicorn:
   ```powershell
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
2. Open your browser at `http://127.0.0.1:8000`.

---

## 5. Using the App

1. **Paste a YouTube Link or Local File:** Paste a URL (e.g. `https://www.youtube.com/watch?v=...`) or a local video path (`samples/sample_5min.mp4`).
2. **Acknowledge Fair Use:** Tick the mandatory responsibility checkbox confirming you understand fair use and attribution requirements (`docs/SOURCE_POLICY.md`).
3. **Select Pipeline Preset:**
   - **Fast:** Whisper, Audio Energy, Single Proposer, Layer 6 Fusion.
   - **Balanced:** Adds Critic, Story Arc Stitcher, and Tournament Reranker.
   - **Best:** Full funnel including Layer 5 Visual Evidence, Metadata Ensemble, and Thumbnails.
4. **Click "Find viral clips":** The pipeline transcribes, senses, nominates, judges, and populates the candidate store.
5. **Adjust Live Quality Slider:** On the results page, drag the slider to filter clips instantly with zero model calls. Use preset chips (Strict 80, Balanced 65, Loose 50, Otsu Suggest) or pin borderline clips.
6. **Click "Render selected":** NVENC hardware renders your selected clips with burned-in animated captions and packages them for upload.
7. **Rate Clips:** Click thumbs up/down to log training feedback into `feedback/ratings.jsonl`.

---

## 6. Output Folder Structure

Final packages are saved locally under:
```
output/<slug>-<video_id>/<clip_id>_<tier>[_part<k>of<n>]/
  clip.mp4                # 1080x1920 vertical short (H.264 / AAC)
  cover_9x16.jpg          # 1080x1920 cover image for Reels / Shorts
  thumb_16x9.jpg          # 1280x720 horizontal thumbnail
  metadata.txt            # Ready-to-copy title, description, tags, hashtags, credit
  metadata.json           # Structured JSON artifact with review info and layer scores
  captions.srt            # Clean subtitle file
  edit_list.json          # Directed effects event timeline
  credit.txt              # Factual credit and source attribution block
  notes.txt               # Clip production notes, tier, and score breakdown
```

---

## 7. Quality Gate Verification

To verify all pipeline phases:
```powershell
python scripts/selftest.py --phase 0   # Environment, GPU, Whisper CUDA, Ollama JSON
python scripts/selftest.py --phase 1   # Cloud code purge, network guard, NVENC render
python scripts/selftest.py --phase 2   # Candidate store, zero-model slider, 7 caption presets
python scripts/selftest.py --phase 3   # Audience signals, Layer 1 sensors, dynamic fusion
python scripts/selftest.py --phase 4   # Multi-model agreement, critic, rerank, ranker training
python scripts/selftest.py --phase 5   # Visual evidence, metadata, thumbnails, presets
python scripts/selftest.py --all       # Full gate test suite across all 6 phases
```

---

## 8. Documentation Index

- `docs/SPEC.md`: Full specification (`ANTIGRAVITY_PROMPT_FINAL_v4.md`).
- `docs/SOURCE_POLICY.md`: Creator attribution, fair use reality, and risk assessment policy.
- `docs/MODELS.md`: Local models registry, sizes, licenses, and verified peak VRAM.
- `docs/REFERENCES.md`: Architecture analysis of reference open-source clipping projects.
- `docs/ABLATION_REPORT.md`: Comparative ablation report (Qwen-only vs Dual Proposers vs Full Funnel).
- `docs/CHANGES.md`: Complete audit of all architectural upgrades across Phases 0–5.
- `docs/PROGRESS.md`: Real-time phase milestone log with verified command outputs.
