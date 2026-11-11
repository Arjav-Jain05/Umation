# Shorts Engine (Offline & Unlimited Local Edition)

Free, 100% local Windows web app (FastAPI + vanilla HTML/CSS/JS on `127.0.0.1:8000`) that turns a single YouTube link or local video file into upload-ready vertical shorts: variable clip count, Part 1/2/3 splits, face-aware 9:16 layouts, 7 animated caption presets, AI director effects, generated thumbnails, and metadata with mandatory creator credit block. Tuned for GTA 6 and gaming clipping.

**Zero Cloud AI Runtime Calls:** The entire pipeline runs completely offline on your local GPU/CPU with Ollama and faster-whisper. No cloud API keys, subscriptions, or upload bandwidth required.

**The user uploads manually. The app never uploads anything to any platform.**

---

## 1. Offline Multi-Model Stack (Prompt v6)

In this edition, all cloud dependencies have been eliminated and replaced with an audience-aware, layered, local open-source multi-model stack running within an 8 GB VRAM budget:

1. **Local Audio Transcription (Layer 0):** `faster-whisper-large-v3-turbo` running on NVIDIA CUDA float16. Delivers 17.2x real-time transcription (34.9s for a 10-minute video) at 3,282 MB peak VRAM without CUDA OOM.
2. **Grammar & Sentence Integrity (Layer 1 Perception):** `segment-any-text` (`sat-3l-sm` ONNX) running on CPUExecutionProvider in 3.2s with zero GPU VRAM impact, plus VAD pause snapping and strict tail-word cleanup. Eliminates mid-sentence cuts (0.0% mid-sentence rate).
3. **Story Segmentation (Layer 1):** BAAI `bge-small-en-v1.5` ONNX computing 384d sentence embeddings on CPU with TextTiling topic-shift depth detection. Long videos are chunked into coherent story blocks rather than fixed token windows.
4. **Audience-First Signals & Sensors:**
   - **Acoustic Loudness & Z-Scores:** RMS energy profiling, peak bursts, and silence-to-explosion suspense/payoff detection.
   - **Sound Events Detection:** AudioSet acoustic feature classifier for explosions, gunshots, screams, laughter, cheering, tire squeals, and sirens.
   - **Voice Emotion & Hype Lexicon:** Speaking pace (WPM), exclamation density, and glossary matching.
   - **Visual Motion & Scene Cuts:** OpenCV grayscale frame difference and color histogram scene cut detection.
5. **Local LLM Proposer & 2-Judge Completeness Committee (Layer 2 & 4):**
   - Proposer: `qwen3.5:9b` proposing moments by sentence IDs seeded with audio event timestamps.
   - Cross-Family Committee: Pass 1 on `qwen3.5:9b` (Qwen family) and Pass 2 on `gemma4:e4b` (Gemma family) in independent fresh contexts. Disagreements trigger L6 boundary repair.
6. **Strict Part-Splitting Policy (Task C):**
   - Default: NO splitting.
   - Split ONLY if duration > 90s, tightening fails, and a valid cliffhanger exists (`cliffhanger`, `tension_peak`, `pending_reveal`, `question_posed`).
   - Hard minimum 25s per part; max 4 parts. Every non-final part ends with a 1.8s hold frame and *"Part X is on the channel ▶"*; Parts 2+ open with a "PART X" badge.
7. **Fast Single-Pass NVENC Render (Task A):**
   - One FFmpeg NVENC process per clip with `-ss` before `-i`, downscaled bokeh background blur (270x480 -> 1080x1920), and burned ASS subtitles.
   - Renders a 60s clip in ~30s (all 10 clips of a 10-minute video render in 5 minutes 1 second).
8. **Topic-Derived Thumbnails & 160px OCR Verification (Task D):**
   - Factual concept briefs derived from clip transcripts and entities.
   - Anton / Bebas Neue OFL bold typography with drop shadow and outline.
   - RapidOCR 160px mobile preview verification: 100% OCR readability.
9. **Automated Audit:** `python scripts/eval_clips.py <work_dir>` validates hard gates (0% mid-sentence cuts, 0% bad conjunction tails, 0 parts under 25s, 100% OCR readability).

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
