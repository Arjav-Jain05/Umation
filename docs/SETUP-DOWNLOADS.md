# SETUP-DOWNLOADS: everything to install or download

Rules: official sources only. Tell the user what each command installs and why. Run ONE command at a time, wait for it, run the check, record the result in `docs/PROGRESS.md`. The user approves terminal prompts. If a check fails, fix it before continuing. Spec detail: `.agents/skills/shorts-engine/references/01-environment-and-setup.md`.

Legend: **[agent]** the agent runs it (user approves). **[user]** only the user can do it.

## A. System tools (Windows, PowerShell)

| # | Tool | Command [agent] | Check |
|---|---|---|---|
| 1 | Git | `winget install --id Git.Git -e` | `git --version` |
| 2 | Python 3.12 | `winget install --id Python.Python.3.12 -e` | `python --version` shows 3.12.x |
| 3 | FFmpeg (full build, NVENC) | `winget install --id Gyan.FFmpeg -e` | `ffmpeg -version`; `ffmpeg -hide_banner -encoders` lists `h264_nvenc` |
| 4 | Deno (JavaScript runtime for yt-dlp) | `winget install --id DenoLand.Deno -e` | `deno --version` |
| 5 | Node.js LTS (only for the `npx skills` installer) | `winget install --id OpenJS.NodeJS.LTS -e` | `node --version`, `npx --version` |
| 6 | NVIDIA driver [user] | install the current driver from nvidia.com or GeForce Experience | `nvidia-smi` shows RTX 4060 |
Open a new terminal after installs so PATH updates. If `winget` is missing, tell the user (App Installer from Microsoft Store).

## B. Python environment [agent]

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```
Check: `pip list` shows fastapi, uvicorn, yt-dlp, faster-whisper, google-genai, mediapipe, opencv-contrib-python, numpy, scipy, soundfile, pillow, rapidfuzz, pytest, ruff. If `mediapipe` fails on 3.12, retry with Python 3.11 and log it. Never install `opencv-python` together with `opencv-contrib-python`.
After M0 passes: `pip freeze > requirements.lock`.

## C. GPU libraries for Whisper [agent]

faster-whisper needs cuBLAS and cuDNN on Windows. Read the **installed** faster-whisper README for the current instructions; a common route:
```powershell
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```
then make their `bin` folders visible via `os.add_dll_directory` at app start. Check: `scripts/check_env.py` GPU Whisper test PASS (loads `tiny` on CUDA float16). If it fails: use the documented CPU fallback (`small`, `int8`) and warn the user.

## D. Models and fonts [agent, via `scripts/download_models.py`]

| File | Source | Check |
|---|---|---|
| `assets/models/blaze_face_short_range.tflite` | MediaPipe official model storage (verify the URL in the current MediaPipe Face Detector docs; it has been `https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite`) | file > 100 KB; loads in MediaPipe |
| `assets/fonts/Anton-Regular.ttf` | Google Fonts repository (OFL) | opens in Pillow |
| `assets/fonts/Montserrat-ExtraBold.ttf` | official Montserrat repository or Google Fonts download; must be a **static** font, not a variable font | opens in Pillow; if only variable fonts are available, use Anton for captions and log it |
| `assets/fonts/NotoColorEmoji.ttf` | official Noto Emoji repository; must be the **bitmap (CBDT)** build that Pillow can render at size 109 | renders a test emoji; if not, skip the emoji effect and log it |
| Whisper `large-v3` weights | downloaded automatically by faster-whisper on first transcription (about 3 GB, needs internet and disk) | first `check_env` GPU test uses `tiny`; the user is told that the first real run downloads 3 GB |
Print each source URL and the file size. Never download from random mirrors.

## E. Keys and accounts [user]

1. Create a free Gemini API key in Google AI Studio. Put it in `.env` as `GEMINI_API_KEY=...`. Never paste the key in chat or commit it.
2. Run `python scripts/check_env.py`: it lists the models available to the key. If `GEMINI_MODEL_TEXT` or `GEMINI_MODEL_IMAGE` do not exist, update `.env` with a current name containing `flash` / `image`. Free-tier limits change: check the AI Studio rate-limit page; set `GEMINI_RPM` below the limit.

## F. Optional downloads (only when the milestone says so)

- M4 local image fallback: `pip install -r requirements-optional.txt` (diffusers, torch). Large (several GB). Only if `LOCAL_IMAGE_FALLBACK=true` is wanted. Install the CUDA build of torch from the official PyTorch instructions.
- M5 upscaler: `realesrgan` and its weights from the official repository. Only for approved clips.

## G. Disk budget the user should know

Whisper model 3 GB; Python env 3-6 GB; per job: audio 0.05 GB/h of source, segments about 1.2 GB per source hour (only planned ranges), outputs about 20-60 MB per clip. Keep 30 GB free.

## H. Completion check for Phase 1

Paste into `docs/PROGRESS.md`: outputs of `git --version`, `python --version`, `ffmpeg -version` (first line), NVENC encoder line, `deno --version`, `nvidia-smi` GPU name, `pip list` excerpt, and `python scripts/check_env.py` table. Ask the user to confirm before Phase 2.
