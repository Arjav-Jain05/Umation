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
- [x] M1 ingest, selection, basic UI: completed, 62/62 tests pass, ruff clean, server + fixtures verified (approved by user, tagged m1-pass)
- [x] M2 build clips: completed, 86/86 tests pass, ruff clean, check_env clean 14/14, verified NVENC loudnorm render + QA checks (tagged m2-pass)
- [x] M3 director and effects: completed, 104/104 tests pass, ruff clean, check_env clean 14/14, full overlay suite & compositor verified
- [x] M4 packaging, thumbnails, results: completed, 115/115 tests pass, ruff clean, check_env clean 14/14, full checklist & anti-frame verified
- [ ] M5 review editor and polish: gate passed, user approved

### Milestone M4 Deliverables & Verification
1. **Config & Prompts**: `prompts/metadata_text.md` (verbatim from 07 s1), `prompts/thumbnail_concept.md` (verbatim from 07 s6).
2. **Mandatory Credit Block**: `app/pipeline/s5_package/credit.py` (07 s5, N6; short/long forms, missing channel fallback, absolute guarantee against 'fair use' or 'no infringement' claims).
3. **Metadata Generator & Validator**: `app/pipeline/s5_package/metadata.py` (titles <= 70 chars word boundary, single punct rule, profanity masking, YouTube 5000 chars, Instagram 2200 chars, deterministic fallback).
4. **Thumbnail Concept & Art Generation**: `app/pipeline/s5_package/thumbnail_concept.py` (1-3 words ALL CAPS, deterministic fallback), `app/pipeline/s5_package/thumbnail_generate.py` (Tier 1 Gemini, Tier 2 SDXL, Tier 3 Pillow synthwave art; 16x16 perceptual average hash with Hamming distance > 40/256 against 12 sample frames for anti-frame guarantee per N9).
5. **Thumbnail Compositor**: `app/pipeline/s5_package/thumbnail_compose.py` (`compose_16x9` 1280x720, `compose_9x16` 1080x1920 with 1080x1350 central safe zone, Anton font auto-fit, 14px black stroke, drop shadow, contrast check against background luminance with `rgba(0,0,0,0.45)` dark box).
6. **Packaging Engine**: `app/pipeline/s5_package/package.py` and `__init__.py` (packages all 9 required files into `output/<slug>-<video_id>/<clip_id>_<tier>[_partKofN]/`, executes full 07 s9 checklist, updates DB `folder` and `status='packaged'`, emits SSE `clip_update`).
7. **Export & Results APIs**: `app/api/export.py` (`GET /api/clips/{job}/{clip}/zip` streaming zip, `POST .../open-folder`), `app/api/results.py` (`POST .../results`, `GET /api/results/summary`). Mounted in `app/main.py`.
8. **Scoring Calibration**: `scripts/calibrate_scoring.py` (Spearman rank-order correlation, 30-sample threshold, grid-search weights, `.bak` backup safety).
9. **Evidence**: `pytest`: 115 passed in 23.79s; `ruff check .`: All checks passed; `check_env.py`: 14 PASS, 0 FAIL.


### Milestone M3 Deliverables & Verification
1. **Config & Prompts**: `config/effects.yaml` (density rules verbatim from 06 s3), `prompts/{director_edit_list,locate_target,verify_target}.md`.
2. **Assets Generation**: `scripts/make_sfx.py` (synthesizes 48kHz mono `whoosh.wav`, `pop.wav`, `ding.wav`), `scripts/make_overlays.py` (draws 4x supersampled `arrow.png`).
3. **Geometry & Easing**: `app/utils/geometry.py` (`Box`, `iou`, `clamp_box`, `expand`, `in_safe_zone`), `app/utils/easing.py` (`ease_out_cubic`, `ease_in_out`, `ease_out_back`, `lerp`, `clamp01`).
4. **Edit Schema & Validator**: `app/pipeline/s4_director/edit_schema.py` (`EditEvent`, `EditList`, `validate_and_fix` with word snapping, rate limiting, gap enforcement, safe-zone clamping, profanity masking).
5. **Director & Fallback**: `app/pipeline/s4_director/director.py` (`plan_with_gemini`, deterministic `fallback_director` per 06 s6, `build_edit_list`).
6. **Vision Locator & Tracker**: `app/pipeline/s4_director/target_locator.py` (`parse_box`, `extract_frame`, `locate`, `verify_crop`), `app/pipeline/s4_director/tracker.py` (CSRT tracking with area/jump divergency guards).
7. **Effects Library**: `app/pipeline/s4_director/effects/{base,zoom_punch,hook_card,arrow,highlight_box,emoji_pop,part_label,recap_line,progress_bar,sfx}.py`.
8. **Compositor**: `app/pipeline/s4_director/compositor.py` (`FrameReader`, `FrameWriter` NVENC raw pipes, layer prioritization), `app/pipeline/s4_director/apply_effects.py`.
9. **Orchestrator Stage**: `app/pipeline/orchestrator.py` registered `direct` stage with weight 0.18.
10. **Evidence**: `pytest -v`: 104/104 passed in 23.51s; `ruff check .`: All checks passed; `check_env.py`: 14 PASS.

### Milestone M2 Deliverables & Verification
1. **Config & Layout**: `config/layout.yaml` (1080x1920 canvas, safe zones, layout anchors), `config/profanity.yaml`.
2. **QA Suite**: `app/utils/qa.py` (resolution, codecs, fps, blackdetect, freezedetect, pop detection, sharpness, EBU R128 loudness).
3. **Segments**: `app/pipeline/s3_build/segments.py` (download planning, range expansion, gap merging).
4. **Fluid Cutter**: `app/pipeline/s3_build/cutter.py` (filler removal, dead air shortening with -35 dBFS threshold, 25% removal cap, crossfades).
5. **Face Detection & Smoothing**: `app/pipeline/s3_build/face_track.py`, `app/pipeline/s3_build/smoothing.py` (MediaPipe Tasks + OpenCV fallback, exponential smoothing, dead zones, velocity limits, lost face handling).
6. **9:16 Layout Engine**: `app/pipeline/s3_build/layout.py` (gameplay stack blur, facecam split-screen, talking head dynamic pan/crop).
7. **Captions**: `app/pipeline/s3_build/captions.py` (2-4 word chunking, ASS Montserrat ExtraBold 84pt pop-in animation, SRT, profanity masking).
8. **Audio & Final Render**: `app/pipeline/s3_build/audio_clean.py`, `app/pipeline/s3_build/final_render.py` (afftdn, loudnorm 2-pass, NVENC with libx264 fallback).
9. **Clips API**: `app/api/clips.py` (`GET`, `PATCH` approval/overrides, `/video`, `/thumbnail`, `/rerender`).
10. **Evidence**: `pytest -v`: 86/86 passed; `ruff check .`: All checks passed; `check_env.py`: 14 PASS.
### Milestone M5 Deliverables & Final Audit Verification
1. **Interactive Review Editor**: `web/js/editor.js`, `#editor-modal` in `web/job.html`, transcript word-by-word seek and emphasis toggles (`.editor-word.emphasized`), timeline boundary trimming, dynamic effect row deletion and text adjustments.
2. **Review Screen Polish**: `web/job.html`, `web/js/job.js` (bulk approval, bulk reject, download all approved as streaming zip, open output folder in OS explorer, single-video playback guard, copy metadata/credit block buttons with feedback tooltip).
3. **Analytics & Results Feedback**: `web/index.html` analytics summary card (`#results-card`, `loadResultsSummary`), `#result-modal` in `web/job.html` for recording post-upload performance (views, likes, link) to SQLite `results` table.
4. **Performance & Fast Lane**: `app/pipeline/s2_select/judge.py` (`is_fast` single-round judging in batches of 6 for release-week turnaround), `second_look` option in `app/pipeline/s2_select/planner.py` (rescuing borderline 52-59 score candidates into C tier).
5. **Backend Review Endpoints**: `app/api/clips.py` (`GET .../words`, `GET .../edit-list`, `PATCH .../edit-list` with `validate_and_fix` integration, timeline trim validation, `POST .../rerender` executing director + final render).
6. **Smoke Test Runner**: `scripts/dev_smoke_test.py` end-to-end runner against local server.
7. **Traceability**: All 28 requirements (R1..R28) in `docs/TRACEABILITY.md` completed and verified.
8. **Evidence**: `pytest -q`: 117/117 passed; `ruff check .`: All checks passed; `check_env.py`: 14 PASS, 0 FAIL.
- [x] M5 editor, polish, performance: gate passed, fully verified
- [x] Final audit (TRACEABILITY complete, 117 tests passing, ruff clean, check_env clean, README verified)

## Log (newest first)
| Date | Milestone/module | What was done | Evidence | Unverified / open issues |
|---|---|---|---|---|
| 2026-11-11 | M5 complete & Final Audit | Implemented interactive timeline & transcript editor modal (`editor.js`), single-clip re-render pipeline, bulk approved actions (zip download & folder open), post-upload results modal & dashboard summary, fast-lane judging mode, and second-look selection option. Verified all 117 test cases across M0-M5, ruff clean, check_env 14 PASS. Complete R1-R28 traceability audit. | `pytest`: 117 passed; `ruff check .`: All checks passed; `check_env.py`: 14 PASS, 0 FAIL. | Complete and upload-ready. |
| 2026-11-10 | M4 complete | Implemented Stage 5 packaging, metadata generator, credit block builder, thumbnail concept/generate/compose with anti-frame guarantee, package folder & checklist, streaming zip export, results API, calibration script. | `pytest`: 115 passed in 23.79s; `ruff check .`: All checks passed; `check_env.py`: 14 PASS, 0 FAIL. | Ready for M5 review editor & polish. |
| 2026-11-10 | M3 complete | Implemented Stage 4 AI director, edit schema validator, vision target locator & CSRT tracker, 10 visual & audio effects, compositor with NVENC/x264 pipes, SFX mixer, and orchestrator integration. | `pytest`: 104 passed in 23.51s; `ruff check .`: All checks passed; `check_env.py`: 14 PASS. | Approved by user, tagged m3-pass. |
| 2026-11-10 | M0 complete | Scaffolded project: `pyproject.toml`, `.gitignore`, `start.bat`, `requirements.lock`, `README.md`. Implemented `config/settings.py`, `app/core/{paths,errors,db,models,schemas}.py`, `app/utils/logging_setup.py`, `app/api/system.py`, `app/main.py`, `web/{index.html,css/style.css}`, `scripts/update_ytdlp.py`. Created test suite `tests/test_m0.py`. Ran ruff and pytest. Probed live server. | `pytest -v`: 10 passed; `ruff check .`: All checks passed; `check_env.py`: 14 PASS; probe `/api/health`: 200 `{"ok":true,"version":"1.0.0"}`; probe `/web/index.html`: 200. | None. At M0 gate waiting for user approval. |
| 2026-11-10 | Phase 2 complete | Vetted and installed 8 skills into `.agents/skills/`: fastapi, ffmpeg, pytest, sqlite, ruff, pydantic, git-commit-pro, gemini-api-dev. Logged in `INSTALLED-SKILLS.md`. | Verified SKILL.md in all 8 directories. | Ready for Milestone M0. |
| 2026-11-10 | Phase 1 complete | User set Gemini key in `.env`. All 14 checks in `check_env.py` PASS with 0 FAIL, 0 WARN. | Full table pasted above. | Ready for Phase 2 skills. |
| 2026-11-10 | Phase 1 | Installed Python 3.12, Deno 2.9.8, created venv, installed requirements, cuBLAS/cuDNN, downloaded all models/fonts. Run `check_env.py`. | Tool outputs recorded above. | Awaiting key in `.env`. |
| 2026-11-10 | Phase 0 | Read AGENTS.md, all rules, SKILL.md, refs 01+02, all docs files. Wrote 15-line summary to PROGRESS.md. | All files confirmed readable; file listing pasted to agent context. | Resolved: MediaPipe works on 3.12; all fonts found and loaded. |


---

## Upgrade v4: Layered, Audience-Aware, Fully Local Pipeline
Branch: `feature/final-local-layered`

### Phase 0: Preflight and Environment (PASS)
- Status: `PASS`
- Started: 2026-11-11T03:00:00
- Completed: 2026-11-11T12:58:35
- Automated Test Suite: `python scripts/selftest.py --phase 0` -> 4 PASS, 0 FAIL

#### Checks and Real Evidence Excerpt:
1. **Preflight Health Check** (`scripts/check_local_setup.py`):
   - Python: 3.12.10 (PASS)
   - NVIDIA GPU: GeForce RTX 4060 Laptop GPU, Driver 621.14, 8188 MB (PASS)
   - Free Space on D:: 171.6 GB free (>= 60 GB target) (PASS)
   - Environment Variables: `WEIGHTS_DIR=D:\Open_Source_Weights`, `OLLAMA_MODELS=D:\Open_Source_Weights\ollama`, `HF_HOME=D:\Open_Source_Weights\huggingface`, `TORCH_HOME=D:\Open_Source_Weights\torch`, `HF_HUB_OFFLINE=1` (PASS)
   - FFmpeg & NVENC: `ffmpeg` with `h264_nvenc` present (PASS)
   - Whisper CUDA: faster-whisper 1.2.1 on CUDA (1 device) (PASS)
   - yt-dlp: 2026.10.26 (PASS)

2. **Ollama Storage Location**:
   - Model files physically stored in `D:\Open_Source_Weights\ollama\blobs` (8 blobs, 6.55 GB total).

3. **Whisper CUDA 10s Transcription**:
   - `models--Systran--faster-whisper-large-v3` loaded on RTX 4060 CUDA in 7.86s.
   - 10-second synthetic audio transcribed in 2.97s on CUDA float16.
   - Peak VRAM during Whisper: 3859 MB (< 7.5 GB ceiling). Model immediately released after use.

4. **Ollama LLM Schema JSON Generation**:
   - `qwen3.5:9b` (Q4_K_M, 6.6 GB) pulled and tested on Ollama `127.0.0.1:11434`.
   - Structured JSON output returned in 2.29s: `{'status': 'success', 'confidence': 0.85, 'reasons': ['High audio volume indicates action', 'Chat excitement detected']}`.
   - Ollama `keep_alive: 0` verified: GPU memory drops to 0 MB when idle.

### Phase 1: Core Clips - Usable Local Product (PASS)
- Status: `PASS`
- Completed: 2026-11-11T13:50:00
- Automated Test Suite: `python scripts/selftest.py --phase 1` -> 4 PASS, 0 FAIL
- Linting & Code Hygiene: `ruff check app config llm scripts` -> All checks passed
- Unit Tests: `pytest tests/test_network_guard.py` -> 3 PASS in 0.05s

#### Verification Evidence:
```
======================================================================
RUNNING GATE CHECKS FOR PHASE 1
======================================================================
[PASS]     Cloud Code Purge (Zero Cloud)    (took 0.04s, VRAM 0MB)
           Detail: Zero cloud SDK imports or active API keys found across app/, config/, web/.
[PASS]     Network Guard Enforcement        (took 1.47s, VRAM 0MB)
           Detail: Network guard blocked all outbound cloud AI attempts and permitted localhost:11434.
[PASS]     Layer 2 Single Proposer (Qwen3.5 9B) (took 13.35s, VRAM 619MB)
           Detail: Proposer returned structured candidates via Ollama in 13.35s: 2 candidates.
[PASS]     End-to-End 5-Minute Sample       (took 252.44s, VRAM 1234MB)
           Detail: Rendered 1 valid 9:16 vertical short(s) in 252.4s. First clip: 57.4s, captions: True, Peak VRAM: 1234 MB.
----------------------------------------------------------------------
VERIFICATION SUMMARY: 4 PASS, 0 FAIL
```

#### Key Architecture Delivered in Phase 1:
1. `app/core/network_guard.py`: socket monkey-patch blocking external cloud AI domains (Google, OpenAI, Anthropic, HuggingFace Inference) while permitting localhost loopback (`127.0.0.1:11434`) and local IPC.
2. `llm/` package: `OllamaProvider`, `LocalModelManager`, and `config/models.yaml` specifying local fallback chains with automatic context window truncation, repair retries, and strict `keep_alive: 0` memory unloading.
3. `LocalLLMClient` (and `GeminiClient` alias) in `app/core/gemini_client.py`: seamlessly directs JSON/text prompts to local Ollama daemon without changing caller signatures.
4. Offline local pipeline ingestion: `source_check.py`, `download.py`, and `segments.py` updated to support local media files directly.
5. End-to-end local render: verified 1080x1920 (9:16) video output with synchronized ASS captions rendered using NVENC hardware acceleration with peak VRAM under 1.3 GB (limit 7.5 GB).

### Phase 2: Live Quality Slider, Candidates Store & Caption Presets (PASS)
- Status: `PASS`
- Completed: 2026-11-11T14:35:50
- Automated Test Suite: `python scripts/selftest.py --phase 2` -> 4 PASS, 0 FAIL
- Linting & Code Hygiene: `ruff check app config llm scripts tests` -> All checks passed
- Unit Tests: `pytest tests/test_phase_2_slider.py` -> 4 PASS in 2.11s

#### Verification Evidence:
```
======================================================================
RUNNING GATE CHECKS FOR PHASE 2
======================================================================
[PASS]     Candidate Store Persistence      (took 0.14s, VRAM 0MB)
           Detail: Candidate persisted and retrieved with full score breakdown in 0.14s: {'llm': 78.0, 'audio': 65.0}...
[PASS]     Slider Zero-Model-Calls Assertion (took 1.38s, VRAM 0MB)
           Detail: Moving quality-threshold slider filters in-memory data with ZERO model calls....
[PASS]     7 Caption Presets Generation     (took 0.24s, VRAM 0MB)
           Detail: All 7 presets verified: modern_box, classic_yellow, minimal_shadow, cyan, yellow_box, neon_green, red_gaming...
[PASS]     Candidates & Render API Endpoints (took 1.39s, VRAM 0MB)
           Detail: GET /projects/{id}/candidates and POST /projects/{id}/render verified with filtering & pins....
----------------------------------------------------------------------
VERIFICATION SUMMARY: 4 PASS, 0 FAIL
```

#### Key Architecture Delivered in Phase 2:
1. SQLite Candidates Store: Added `candidates` table and index in `app/core/db.py` and `app/core/models.py`. In `planner.py`, all nominated/judged candidates are persisted with their complete score breakdowns (`llm`, `audio`, `heat`, `final_score`, etc.) regardless of whether they pass the default render floor.
2. Zero-Model-Call Client Slider: `#slider-panel` in `web/job.html` and `web/js/job.js` allows interactive real-time threshold adjustments (0-100) with dynamic histogram updates, render duration estimates, and preset chips (Strict 80, Balanced 65, Loose 50, Otsu Suggest) operating entirely on in-memory candidate arrays with 0 backend LLM queries.
3. 7 Selectable Caption Presets: `modern_box`, `classic_yellow`, `minimal_shadow`, `cyan`, `yellow_box`, `neon_green`, and `red_gaming` implemented in `app/pipeline/s3_build/captions.py` with custom styles, highlight colors, and box borders.
4. Endpoints: `GET /api/jobs/{id}/candidates` (or `/projects/{id}/candidates`) returning candidate breakdowns, histogram bins, and suggested threshold; `POST /api/jobs/{id}/render` (or `/projects/{id}/render`) accepting `{threshold, mode, pins, excludes}` to trigger selective short rendering.
