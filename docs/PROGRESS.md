# PROGRESS

Read this FIRST at the start of every session. Update at the end of every unit of work.

## Understanding summary (written in Phase 0, 2026-11-10)

1. **What we're building:** A free, local Windows web app (`FastAPI` + plain HTML/JS, bound to `127.0.0.1`) that takes one YouTube link and produces upload-ready vertical shorts — variable clip count, 9:16 layout, animated captions, AI-directed effects, generated thumbnails, titles/descriptions/tags, and a mandatory credit block. Tuned for GTA 6 clipping. User always uploads manually; the app never touches any platform API.
2. **Non-negotiables (N1–N12):** Free tools only; runs on RTX 4060 / 16 GB RAM; one link in → everything out; no uploading; variable clip count (no hardcoded "top N"); credit block in every description; no legal claims ("fair use"); public videos only, no cookies; thumbnails are generated art never cut from video; nothing guessed (all decisions logged); every stage resumable from JSON artifacts; server bound to 127.0.0.1 only.
3. **Pipeline order (10 named stages):** `source_check` → `audio_download` (16 kHz WAV) → `transcribe` (faster-whisper CUDA) → `nominate` (Gemini per 20-min chunk) → `judge` (Gemini rubric ×2) → `plan` (blend signals, tiers, dedupe) → `segments` (download only needed video ranges) → `build` (cut, layout, captions, per clip) → `direct` (edit list, effects, per clip) → `package` (metadata, credit, thumbnails, per clip).
4. **Tech stack:** Python 3.12 (3.11 fallback for MediaPipe), FastAPI + uvicorn, SQLite WAL, Pydantic v2 for every artifact, faster-whisper on CUDA float16, yt-dlp + Deno, ffmpeg (Gyan full build, NVENC), MediaPipe Tasks (face detector), OpenCV contrib (CSRT tracker), Pillow, `google-genai` (Gemini 2.5 Flash), scipy/soundfile for audio, ruff + pytest.
5. **Architecture:** Single Python process; one worker thread processes one job at a time; API thread never blocks; progress via SSE (`/api/jobs/{id}/events`); SQLite stores job/clip state; JSON artifacts in `data/work/{job_id}/` drive resumability.
6. **Data contracts:** All artifacts are Pydantic v2 models in `app/core/schemas.py` with `schema_version=1`. Times are float seconds (source timeline), rounded to 3 decimals. Artifact writes are atomic (`*.tmp` then `os.replace`). The `JobContext` object is the only way stages read/write artifacts.
7. **Resumability (N11):** Each stage skips if its output artifact already exists and validates. On app restart, any `running` job reverts to `queued`. Cancel flag is checked between stages and inside long loops.
8. **Gemini client rules:** Token-bucket rate limiter at `GEMINI_RPM` (default 8). Exponential backoff on 429/5xx (2–32 s, max 5 attempts). JSON output validated with Pydantic; one retry with error appended on failure. Response cache via `cache` table (sha256 key). Daily quota pause: job status stays `queued` with a message. Model names never hard-coded — always from `.env`.
9. **GPU / resource safety:** Whisper model loaded only during transcribe stage, then `del model; gc.collect()` to free VRAM. NVENC for final render. `SetThreadExecutionState` prevents sleep during jobs. Free-disk check before every download (minimum `MIN_FREE_GB` = 30 GB free beyond job estimate).
10. **Selection scoring blend:** `final_score = w_llm × llm_score + w_heat × heat + w_audio × audio_score + w_speech × speech_ratio + w_topic × topical_hits`. Clips above threshold 60 become clips; tiers: A ≥ 80, B ≥ 70, C ≥ 60. No hardcoded count — every clip above the bar is included (soft cap 40 as safety net).
11. **ffmpeg Windows gotcha:** The `subtitles`/`ass` filter breaks on Windows with `C:`-prefixed absolute paths. Solution: run ffmpeg with `cwd` set to the working folder and pass relative filenames. Fonts go in `fonts/` subdirectory with `fontsdir=fonts`.
12. **Folder structure:** Project root = workspace root. Key paths managed only via `app/core/paths.py`. All settings from `config/settings.py` (loaded from `.env`). All prompts are plain-text `.md` files in `prompts/`, never inlined in code.
13. **Six gated milestones (M0–M5):** M0 scaffold/environment; M1 ingest+selection+basic UI; M2 build clips; M3 AI director+effects; M4 packaging+thumbnails+feedback; M5 review editor+polish+performance. Each ends with a gate checklist; must stop and get user approval before continuing.
14. **Testing and verification:** Three passes per unit: build (spec), test (pytest + ruff), reviewer (hostile: bad input, Windows paths with spaces/unicode, no GPU, Gemini 429, cancel mid-run). Evidence = pasted command output only. TRACEABILITY.md maps all 28 requirements to files, tests, and evidence.
15. **Fair-use policy:** App shows risk flags and credit block; never claims "fair use" or "no copyright infringement intended". Clips with almost no commentary (pure gameplay footage) are high-risk and cannot reach tier A. Blocklisted channels refused. Thumbnails never use real people's likenesses, official logos, or key art.

---

## Phase 1 downloads and tools
- [x] Git, Python 3.12, FFmpeg (NVENC), Deno, Node LTS installed and checked (evidence below)
- [x] venv + requirements installed (Python 3.12.10, all packages green)
- [x] Whisper CUDA check (PASS: CUDA float16 tiny model transcribed silence successfully)
- [x] Models and fonts downloaded (PASS: blaze_face, Anton, Montserrat-ExtraBold, NotoColorEmoji)
- [x] Gemini key set and models confirmed (PASS: key valid, model returned response)
- [x] `python scripts/check_env.py` has no FAIL (14 PASS, 0 WARN, 0 FAIL)

### Phase 1 Verification Evidence

#### Tool Versions:
- **git**: `git version 2.53.0.windows.2`
- **python**: `Python 3.12.10` (at `C:\Users\Jaina\AppData\Local\Programs\Python\Python312\python.exe` and in `.venv`)
- **ffmpeg**: `ffmpeg version N-121583-g4348bde2d2-20251031 Copyright (c) 2000-2025 the FFmpeg developers`
- **NVENC encoder**: `h264_nvenc` present; 1s hardware test encode: `frame=30 fps=0.0 q=15.0 speed=3.06x`
- **deno**: `deno 2.9.8 (stable, release, x86_64-pc-windows-msvc)`
- **node / npx**: `node v24.16.0`, `npx 11.13.0`
- **nvidia-smi**: `NVIDIA GeForce RTX 4060 Laptop GPU, 621.14, 8188 MiB`

#### Pip List Excerpt (.venv):
```
fastapi                0.162.2
faster-whisper         1.2.1
google-genai           3.0.0
mediapipe              1.2.2
nvidia-cublas-cu12     12.9.2.10
nvidia-cuda-nvrtc-cu12 12.9.86
nvidia-cudnn-cu12      9.28.1.4
opencv-contrib-python  5.0.0.93
pillow                 13.0.0
pydantic               2.14.3
pydantic_core          2.50.4
pytest                 9.2.0
ruff                   0.17.4
yt-dlp                 2026.10.26
```

#### Assets Downloaded:
- `assets/models/blaze_face_short_range.tflite` (224.4 KB)
- `assets/fonts/Anton-Regular.ttf` (166.8 KB)
- `assets/fonts/Montserrat-ExtraBold.ttf` (444.8 KB)
- `assets/fonts/NotoColorEmoji.ttf` (24,739.0 KB)

#### `python scripts/check_env.py` Output:
```
CHECK                     | STATUS   | DETAIL                                        | FIX                           
--------------------------+----------+-----------------------------------------------+-------------------------------
Python version            | PASS     | Python 3.12.10                                |                               
Disk space                | PASS     | 175.8 GB free on D:                           |                               
FFmpeg version            | PASS     | ffmpeg version N-121583-g4348bde2d2-20251031  |                               
NVENC hardware encode     | PASS     | h264_nvenc encoder test succeeded             |                               
NVIDIA GPU                | PASS     | NVIDIA GeForce RTX 4060 Laptop GPU, 8188 MiB  |                               
Deno (yt-dlp JS runtime)  | PASS     | deno 2.9.8 (stable, release, x86_64-pc-window |                               
yt-dlp package            | PASS     | yt-dlp 2026.10.26 (15d old)                   |                               
faster-whisper CUDA       | PASS     | CUDA float16 tiny model transcribed silence s |                               
MediaPipe face detector   | PASS     | MediaPipe 1.2.2 with model present            |                               
OpenCV contrib (CSRT)     | PASS     | OpenCV 5.0.0 with CSRT tracker                |                               
Pillow fonts              | PASS     | Anton, Montserrat, and NotoColorEmoji loaded  |                               
Gemini API key            | PASS     | Key valid; test model 'gemini-2.5-flash' retu |                               
Power source              | PASS     | AC connected (100% charged)                   |                               
HTTP Port                 | PASS     | 127.0.0.1:8000 is free                        |                               
```

---

## Phase 2 skills
- [x] Searched skills for all 17 stack items (see SKILLS-TO-INSTALL.md)
- [x] Vetted and installed 8 trusted skills (list in INSTALLED-SKILLS.md)
- [x] Skills verified in workspace `.agents/skills/`

## Milestones
- [x] M0 scaffold and environment: completed, 10/10 tests pass, ruff clean, server probed (approved by user, tagged m0-pass)
- [x] M1 ingest, selection, basic UI: completed, 62/62 tests pass, ruff clean, server + fixtures verified (awaiting user approval at M1 gate)
- [ ] M2 build clips: gate passed, user approved
- [ ] M3 director and effects: gate passed, user approved
- [ ] M4 packaging, thumbnails, results: gate passed, user approved
- [ ] M5 editor, polish, performance: gate passed, user approved
- [ ] Final audit (TRACEABILITY complete, smoke test, README)

## Log (newest first)
| Date | Milestone/module | What was done | Evidence | Unverified / open issues |
|---|---|---|---|---|
| 2026-11-10 | M1 complete | Implemented full M1 ingest, selection, worker, orchestrator, and web dashboard: `config/{scoring,glossary_gta6,source_policy}.yaml`, `prompts/{nominate_candidates,judge_candidate,plan_parts}.md`, `app/core/{cache,power,events,gemini_client,worker}.py`, `app/utils/{timecode,text,ffmpeg}.py`, `app/pipeline/context.py`, `app/pipeline/s1_ingest/{source_check,download,tidy_transcript,transcribe}.py`, `app/pipeline/s2_select/{chunker,refine,signal_heatmap,signal_audio,signal_speech,blend,risk,part_splitter,nominate,judge,planner}.py`, `app/pipeline/orchestrator.py`, `app/api/jobs.py`, `web/{index.html,job.html,js/api.js,js/home.js,js/job.js}`, `scripts/make_fixtures.py`, `scripts/dev_smoke_test.py`. Implemented 14 test modules in `tests/`. | `pytest -v`: 62 passed in 1.05s; `ruff check .`: All checks passed; `check_env.py`: 14 PASS; `make_fixtures.py`: synthetic.mp4, heatmap_100.json, gemini JSON fixtures generated. | None. At M1 gate waiting for user approval. |
| 2026-11-10 | M0 complete | Scaffolded project: `pyproject.toml`, `.gitignore`, `start.bat`, `requirements.lock`, `README.md`. Implemented `config/settings.py`, `app/core/{paths,errors,db,models,schemas}.py`, `app/utils/logging_setup.py`, `app/api/system.py`, `app/main.py`, `web/{index.html,css/style.css}`, `scripts/update_ytdlp.py`. Created test suite `tests/test_m0.py`. Ran ruff and pytest. Probed live server. | `pytest -v`: 10 passed; `ruff check .`: All checks passed; `check_env.py`: 14 PASS; probe `/api/health`: 200 `{"ok":true,"version":"1.0.0"}`; probe `/web/index.html`: 200. | None. At M0 gate waiting for user approval. |
| 2026-11-10 | Phase 2 complete | Vetted and installed 8 skills into `.agents/skills/`: fastapi, ffmpeg, pytest, sqlite, ruff, pydantic, git-commit-pro, gemini-api-dev. Logged in `INSTALLED-SKILLS.md`. | Verified SKILL.md in all 8 directories. | Ready for Milestone M0. |
| 2026-11-10 | Phase 1 complete | User set Gemini key in `.env`. All 14 checks in `check_env.py` PASS with 0 FAIL, 0 WARN. | Full table pasted above. | Ready for Phase 2 skills. |
| 2026-11-10 | Phase 1 | Installed Python 3.12, Deno 2.9.8, created venv, installed requirements, cuBLAS/cuDNN, downloaded all models/fonts. Run `check_env.py`. | Tool outputs recorded above. | Awaiting key in `.env`. |
| 2026-11-10 | Phase 0 | Read AGENTS.md, all rules, SKILL.md, refs 01+02, all docs files. Wrote 15-line summary to PROGRESS.md. | All files confirmed readable; file listing pasted to agent context. | Resolved: MediaPipe works on 3.12; all fonts found and loaded. |
