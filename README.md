# Shorts Engine

Free, local Windows web app (FastAPI + vanilla HTML/CSS/JS on `127.0.0.1:8000`) that turns a single YouTube link (video or finished livestream VOD) into upload-ready vertical shorts (variable clip count, Part 1/2/3 splits, face-aware 9:16 layouts, animated captions, AI director effects, generated thumbnails, and metadata with mandatory credit block). Tuned for GTA 6 clipping.

**The user uploads manually. The app never uploads anything to any platform.**

---

## 1. Requirements

- **Operating System:** Windows 11 (64-bit).
- **GPU:** NVIDIA GeForce RTX 4060 (8 GB VRAM) or compatible NVIDIA GPU with up-to-date Game Ready / Studio drivers.
- **Python:** 3.12 (specifically tested on Python 3.12.10).
- **System Tools:**
  - `ffmpeg` (Gyan full build with `h264_nvenc` support) and `ffprobe` in `PATH`.
  - `deno` in `PATH` (used as the secure JS challenge solver for `yt-dlp`).
- **Disk Space:** At least 30 GB free on the target working drive.
- **API Key:** Free Gemini API key from [Google AI Studio](https://aistudio.google.com/).

---

## 2. Installation

1. **Clone the repository:**
   ```powershell
   git clone <repo-url>
   cd Umation
   ```
2. **Create Python 3.12 virtual environment:**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
3. **Install system binaries (if not already installed):**
   ```powershell
   winget install --id Gyan.FFmpeg -e
   winget install --id DenoLand.Deno -e
   ```
4. **Download bundled models & fonts:**
   ```powershell
   python scripts/download_models.py
   ```

---

## 3. First Run

1. Copy `.env.example` to `.env`:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Open `.env` in a text editor and paste your Google AI Studio API key:
   ```env
   GEMINI_API_KEY=AIzaSy...
   ```
3. Verify your environment passes all checks:
   ```powershell
   python scripts/check_env.py
   ```
4. Launch the application:
   - Double-click `start.bat`, or run:
     ```powershell
     .\start.bat
     ```
   - The app will automatically open your browser at `http://127.0.0.1:8000`.

---

## 4. Using the App

1. **Paste a YouTube URL:** Video or finished livestream VOD (e.g. `https://www.youtube.com/watch?v=...`).
2. **Acknowledge Fair Use:** Tick the mandatory responsibility checkbox confirming you understand fair use and credit policies.
3. **Configure Options (optional):** Choose minimum tier threshold (A, B, C), layout override (gameplay, facecam, talking head), max duration (20–90 s), effect preferences, **Fast lane** (single-round judging for rapid release-week turnaround), and **Second look** (rescues borderline clips scoring 52–59).
4. **Click "Find viral clips":** The pipeline ingests audio, transcribes with Whisper on CUDA, nominates and judges moments with Gemini, blends YouTube replay heatmaps, cuts video ranges, and packages vertical clips.
5. **Review, Edit & Export:**
   - **Interactive Editor:** Click "Edit Clip" on any card to trim start/end boundaries, click transcript words to jump playback or toggle caption emphasis styling, and customize or delete AI director effect overlays. Click "Save & Re-render" to rebuild the clip in seconds.
   - **Bulk Actions:** Approve or reject multiple clips, click "Download all approved" for a streaming `.zip` bundle, or click "Open output folder" to inspect files in Windows Explorer.
   - **Log Performance & Calibrate:** Once uploaded manually, click "Log result" on a clip to enter its view/like counts. Run `python scripts/calibrate_scoring.py` to recalibrate score blending weights using Spearman rank correlation.

---

## 5. Output Folder Structure

Final output packages are saved locally under:
```
output/<slug>-<video_id>/<clip_id>_<tier>[_part<k>of<n>]/
  clip.mp4                # 1080x1920 vertical short (H.264 / AAC)
  cover_9x16.jpg          # 1080x1920 cover image for Reels / Shorts
  thumb_16x9.jpg          # 1280x720 horizontal thumbnail
  metadata.txt            # Ready-to-copy title, description, tags, hashtags, credit
  metadata.json           # Structured JSON artifact with review info
  captions.srt            # Clean subtitle file
  edit_list.json          # Directed effects event timeline
  credit.txt              # Factual credit and source attribution block
  notes.txt               # Clip production notes, tier, and score breakdown
```

---

## 6. Troubleshooting

| Symptom | Likely Cause | Resolution |
|---|---|---|
| `h264_nvenc` fails | Outdated GPU driver or wrong ffmpeg build | Update NVIDIA drivers; reinstall Gyan FFmpeg full build. Automatic fallback to `libx264` is supported. |
| Whisper `cudnn`/`cublas` DLL error | Missing CUDA DLLs in environment | Verify `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` are installed in `.venv`. |
| Transcript repetition loops | Hallucination loop on low audio | Pipeline enforces `condition_on_previous_text=False` and Silero VAD filtering. |
| Captions missing in video | Windows path colon (`C:`) issue in filter | Ass filter runs with relative paths and `fontsdir=fonts`. |
| Captions display wrong font | Missing system or asset font | Ensure fonts exist in `assets/fonts/` and run `python scripts/download_models.py`. |
| Clip starts with silence | Refine hook trim not applied | Pipeline trims leading silence based on Whisper word timestamps. |
| Face crop jitters | Smoothing disabled or low window | Exponential moving average and dead-zone smoothing are enforced in `layout.py`. |
| Gemini returns invalid JSON | Schema violation or temperature high | Structured JSON mode enforced; code automatically retries with schema error appended. |
| Job stuck at 0% | Worker thread dead or hung | Inspect `data/logs/app.log`; restart app and job will automatically resume. |
| YouTube 403 / extraction error | Outdated `yt-dlp` extractor | Run `python scripts/update_ytdlp.py` and ensure Deno is installed. |
| Disk space filling up | Segments retained after processing | Use the "Clean up" button in the UI or adjust `CLEAN_AFTER_DAYS` in `.env`. |

---

## 7. Privacy: What Goes to Gemini?

- **Local Execution:** Audio downloading, transcription (`faster-whisper`), video cutting, face detection (`MediaPipe`), layouts, captions, effects composition, and final rendering run 100% locally on your machine. No video or audio is ever uploaded to external cloud services.
- **External Calls (Gemini API):**
  - Plain-text transcript chunks (20-minute windows) for moment nomination and judging.
  - Video title and chapter headings for topic context.
  - Short prompts for title, description, and thumbnail concept generation.
- **API Keys:** Stored strictly in local `.env`; never transmitted to third parties, logged, or checked into version control.

---

## 8. Safe Working Practice & Fair Use Policy

1. **Credit Block Mandatory:** Every generated description includes a complete, attribution block linking to the original creator's channel and video.
2. **Risk Flags:** The engine flags potential fair-use risks (e.g. low commentary, music-heavy segments, unverified claims) directly in the UI.
3. **No Automatic Uploading:** The application has no upload features, credentials, or API integrations with YouTube or Instagram. You must review and upload clips manually.
4. **Legal Disclaimer:** The tool assists with formatting, clipping, and fair-use attribution but does not provide legal advice.
