# 01. Environment and setup

Contents: 1 Target machine · 2 Tool installs · 3 Python env and packages · 4 GPU and Whisper · 5 yt-dlp and JavaScript runtime · 6 `.env` · 7 `check_env.py` spec · 8 Safety (disk, power, VRAM) · 9 `start.bat` · 10 Fonts and models

## 1. Target machine

- ASUS TUF F15, Windows (assume 11, confirm with `ver`), NVIDIA RTX 4060 Laptop **8 GB VRAM**, 16 GB RAM, 1 TB SSD.
- The "8 GB iGPU" is shared system memory. Ignore it for compute.
- Laptop must be on AC power and in the "Best performance" power mode during jobs. Warn in the UI if on battery (`psutil.sensors_battery()` is not None and `power_plugged` is False).
- RAM budget: leave >= 4 GB free. Never decode whole videos into memory; always stream frames.

## 2. Tool installs (PowerShell, one time)

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id Gyan.FFmpeg -e
winget install --id DenoLand.Deno -e
```
Open a new terminal afterwards. Verify:
```powershell
python --version      # 3.12.x
ffmpeg -version
ffmpeg -hide_banner -encoders | findstr nvenc     # must list h264_nvenc
ffprobe -version
deno --version
nvidia-smi
```
If `h264_nvenc` is missing, the ffmpeg build is wrong: reinstall the Gyan "full" build and update the NVIDIA driver (Game Ready or Studio, current).

## 3. Python environment and packages

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt` (unpinned first; after M0 passes, run `pip freeze > requirements.lock` and commit it):
```
fastapi
uvicorn[standard]
pydantic>=2
python-dotenv
pyyaml
httpx
tenacity
psutil
yt-dlp
faster-whisper
google-genai
mediapipe
opencv-contrib-python
numpy
scipy
soundfile
pillow
rapidfuzz
pytest
ruff
```
`requirements-optional.txt` (not installed by default): `diffusers`, `torch` (local SDXL fallback, M4), `realesrgan` (optional upscale, M5), `openai-whisper` is NOT used.

Rules: install `opencv-contrib-python` only (never together with `opencv-python`); trackers live in contrib. If `mediapipe` has no wheel for the installed Python, drop to 3.11 and log it in `DECISIONS.md`.

## 4. GPU and Whisper

- faster-whisper uses CTranslate2. On Windows it needs the NVIDIA cuBLAS and cuDNN DLLs. Follow the current faster-whisper README. A common route is `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` and adding their `bin` folders to the DLL search path at startup (`os.add_dll_directory`). **Verify against the installed version's README; do not assume.**
- `check_env.py` loads the `tiny` model on `device="cuda", compute_type="float16"` and transcribes 1 s of silence. If this fails: report FAIL with the exact exception and set `WHISPER_DEVICE=cpu`, `WHISPER_COMPUTE=int8`, `WHISPER_MODEL=small` as the automatic fallback; the UI shows a yellow warning "GPU transcription unavailable, slower".
- VRAM: `large-v3` float16 needs about 4-5 GB. Always release the model after the transcription stage (`del model; gc.collect()`) before NVENC-heavy stages. If CUDA out-of-memory occurs, retry once with `compute_type="int8_float16"`, then `medium`.

## 5. yt-dlp and JavaScript runtime

- Keep yt-dlp current: `python scripts/update_ytdlp.py` runs `pip install -U yt-dlp` and prints the version. The app calls it automatically (once per day max) before the first job of the day, behind setting `AUTO_UPDATE_YTDLP=true`.
- YouTube extraction can require an external JavaScript runtime. Recent yt-dlp versions look for Deno; if extraction fails with a message about JavaScript runtime, signatures or n-challenge, ensure Deno is installed and on PATH, update yt-dlp, retry once. Verify in current yt-dlp docs.
- Never pass cookies by default (N8). A `COOKIES_FROM_BROWSER` setting may exist but defaults to empty and the UI never mentions it.

## 6. `.env` (copy from `.env.example`)

```
GEMINI_API_KEY=
GEMINI_MODEL_TEXT=gemini-2.5-flash
GEMINI_MODEL_IMAGE=gemini-2.5-flash-image
GEMINI_RPM=8
GEMINI_TIMEOUT_S=120
WHISPER_MODEL=large-v3
WHISPER_DEVICE=cuda
WHISPER_COMPUTE=float16
WHISPER_LANGUAGE=auto
PROJECT_DOMAIN=gta6
DATA_DIR=./data
OUTPUT_DIR=./output
MAX_SOURCE_HEIGHT=1080
MAX_SOURCE_HOURS=12
MIN_FREE_GB=30
AUTO_UPDATE_YTDLP=true
HOST=127.0.0.1
PORT=8000
```
Model names are defaults only. `check_env.py` calls `client.models.list()` and prints whether the configured text and image models exist; if not, it prints the newest available names containing `flash` and `image` and tells the user to update `.env`. Never auto-switch silently.

## 7. `scripts/check_env.py` spec

Prints a table: `CHECK | STATUS | DETAIL | FIX`. Statuses `PASS`, `WARN`, `FAIL`. Exit code 1 if any FAIL. Checks, in order:

1. Python version in {3.11, 3.12}.
2. Free disk on `DATA_DIR` drive >= `MIN_FREE_GB` (WARN) and >= 10 GB (FAIL).
3. `ffmpeg`, `ffprobe` on PATH, versions.
4. `h264_nvenc` encoder listed; then a 1-second NVENC test encode of `testsrc` succeeds.
5. `nvidia-smi` runs; prints GPU name and total VRAM.
6. Deno on PATH (WARN if missing).
7. `yt-dlp` importable; version; days since release (WARN if > 60 days).
8. faster-whisper CUDA test (section 4).
9. MediaPipe import and face-detector model file present in `assets/models/` (FAIL with fix `python scripts/download_models.py`).
10. OpenCV import, `cv2.TrackerCSRT_create` exists (FAIL otherwise: contrib missing).
11. Pillow can load `assets/fonts/*.ttf` (WARN if fonts missing, fix `scripts/download_models.py --fonts`).
12. `GEMINI_API_KEY` present; one tiny generation call returns text; configured models exist (section 6).
13. Running on AC power (WARN).
14. Port free.

The same logic backs `GET /api/system/check` (JSON list) and the UI banner.

## 8. Safety: disk, power, VRAM

- **Disk guard:** before download, estimate need = audio (0.05 GB per hour) + segment downloads (1.2 GB per hour of source at 1080p, but only for planned segments) + 2 GB working. If free disk < estimate + `MIN_FREE_GB`, fail the job with: "Not enough disk space: need about X GB free, have Y GB. Delete old jobs or change DATA_DIR."
- **Power:** while a job runs, call `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` via `ctypes.windll.kernel32` (module `app/core/power.py`); clear it when idle. This stops sleep mid-job.
- **Thermals:** no special code. Log GPU temperature from `nvidia-smi` at stage boundaries.
- **Cleanup:** `data/work/<job_id>/segments` and raw audio are deleted when the user clicks "Clean up" or after `CLEAN_AFTER_DAYS` (default 7). `output/` is never auto-deleted.

## 9. `start.bat`

```bat
@echo off
cd /d %~dp0
if not exist .venv ( python -m venv .venv )
call .venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
python scripts\check_env.py
start "" http://127.0.0.1:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
(`check_env` failures print but do not block start; the UI banner shows them.)

## 10. Fonts and models (`scripts/download_models.py`)

Downloads into `assets/`:
- `models/blaze_face_short_range.tflite` (MediaPipe face detector for the Tasks API). Verify the current official download URL from MediaPipe docs.
- `fonts/Montserrat-ExtraBold.ttf` and `fonts/Anton-Regular.ttf` (both SIL Open Font License, from Google Fonts' GitHub).
- `fonts/NotoColorEmoji.ttf` (for emoji pop; Pillow needs the CBDT bitmap size 109).
The script verifies file sizes > 10 KB and prints source URLs. It must not run on import.
