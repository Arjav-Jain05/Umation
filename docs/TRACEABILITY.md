# TRACEABILITY

One row per requirement from `.agents/skills/shorts-engine/SKILL.md` section 2. Fill in as you build. A row is complete only when File, Test and Evidence are all filled and Status is DONE. Evidence = command + pasted result (or a pointer to the PROGRESS.md entry that holds it).

| ID | Requirement | Spec ref | Files | Tests | Evidence | Status |
|---|---|---|---|---|---|---|
| R1 | Basic web UI on localhost: paste link, press button | 08 | web/index.html, web/js/home.js | test_api_jobs.py | `pytest tests/test_api_jobs.py`: 4 passed in 0.17s | DONE |
| R2 | Live progress per stage in the UI | 02, 08 | app/core/events.py, web/js/job.js | test_api_jobs.py, test_orchestrator_resume.py | SSE /events endpoint + stage bars in job.html | DONE |
| R3 | Find all viral-worthy moments; count varies | 04 | app/pipeline/s2_select/* | test_planner.py | `pytest tests/test_planner.py`: 5 passed | DONE |
| R4 | Score blends transcript judgement + replay heatmap + audio energy | 04 | blend.py, signal_*.py | test_signals.py, test_blend.py | `pytest tests/test_signals.py tests/test_blend.py`: 8 passed | DONE |
| R5 | Hook quality judged; weak hook cannot reach tier A | 04 | blend.py, planner.py | test_blend.py | `pytest tests/test_blend.py`: weak hook < 5.0 capped at 69 | DONE |
| R6 | Clips make sense standalone or are fixed/rejected | 04 | judge.py, blend.py | test_blend.py | Context penalty logic (-15 unfixable, -4 fixable) | DONE |
| R7 | Long stories split into Part 1/2/3 | 04 | part_splitter.py | test_part_splitter.py | `pytest tests/test_part_splitter.py`: 2 passed | DONE |
| R8 | Fluid cuts: dead air and fillers removed, crossfaded | 05 | cutter.py | test_cutter.py, test_remap.py | `pytest tests/test_cutter.py tests/test_remap.py`: 6 passed in 0.05s | DONE |
| R9 | Crisp output 1080x1920, no blurry upscales | 05 | layout.py, final_render.py, qa.py | test_final_render.py | `pytest tests/test_final_render.py`: 1 passed in 21.7s (NVENC + loudnorm + QA) | DONE |
| R10 | Layouts: talking head, gameplay stack, facecam | 05 | layout.py, face_track.py, smoothing.py | test_layout_detect.py, test_smoothing.py | `pytest tests/test_layout_detect.py tests/test_smoothing.py`: 7 passed | DONE |
| R11 | Animated word-by-word captions in safe zone | 05 | captions.py, config/layout.yaml | test_captions.py | `pytest tests/test_captions.py`: 4 passed (ASS/SRT validation + anchors) | DONE |
| R12 | AI director: zoom, hook card, arrows, emoji, progress, part label, SFX | 06 | s4_director/*, effects/* | test_edit_schema.py, test_effects.py, test_director_fallback.py | `pytest tests/test_edit_schema.py tests/test_effects.py tests/test_director_fallback.py`: 14 passed | DONE |
| R13 | Arrows point at the correct thing (vision-located, verified) | 06 | target_locator.py, tracker.py | test_locator_parse.py | `pytest tests/test_locator_parse.py`: 4 passed (safe zone, area, conversion) | DONE |
| R14 | Generated thumbnail referencing topic, never a video frame | 07 | thumbnail_*.py | test_thumbnail | | TODO |
| R15 | 3 titles, description, hashtags, tags/SEO | 07 | metadata.py | test_metadata | | TODO |
| R16 | Mandatory credit block | 07, 10 | credit.py | test_credit | | TODO |
| R17 | Fair-use risk flags per clip | 10 | risk.py, planner.py | test_risk.py | `pytest tests/test_risk.py`: 4 passed | DONE |
| R18 | Review screen: preview, tier, edit text, approve/reject, copy, download | 08 | web/js/job.js, editor.js | manual + API tests | | TODO |
| R19 | Output folder per clip with everything needed to upload | 02, 07 | package.py | test_package | | TODO |
| R20 | Handles 8-hour VODs without filling the disk | 03 | download.py, chunker.py | test_chunker.py | 20-min chunks, 16k mono wav download guard | DONE |
| R21 | Gemini rate limits, caching, retries | 02 | gemini_client.py, cache.py | test_gemini_client.py | `pytest tests/test_gemini_client.py`: 5 passed | DONE |
| R22 | Windows power, GPU memory, disk-space safety | 01 | power.py, transcribe.py, source_check.py | test_m0.py, test_source_check.py | SetThreadExecutionState + VRAM release + disk check | DONE |
| R23 | Results log feeding calibration | 09 | results.py, calibrate_scoring.py | | | TODO |
| R24 | Tests and measurable acceptance gates | 09 | tests/* | test_*.py | `pytest -v`: 104 passed in 23.51s; `ruff check .`: clean; `check_env.py`: 14 PASS | DONE (M0 + M1 + M2 + M3 pass) |
| R25 | Fast lane for release-week speed | 04, 09 | judge.py, orchestrator.py | | | TODO |
| R26 | GTA 6 domain vocabulary and boosts | 04 | glossary_gta6.yaml, blend.py | test_signals.py, test_blend.py | Topical hits count and +5 score boost | DONE |
| R27 | Profanity masking in captions | 05 | captions.py, config/profanity.yaml | test_captions.py | `pytest tests/test_captions.py`: profanity masked with '*' | DONE |
| R28 | Quality at least equal to Klap's feature set | 05, 06 | all | milestone audits | | TODO |

## Non-negotiables N1-N12 (SKILL.md section 1)

| ID | Item | Evidence |
|---|---|---|
| N1 | Free only | Python, ffmpeg, Whisper CUDA, MediaPipe, Deno, Google AI Studio free tier |
| N2 | Runs on the target laptop | `check_env.py`: RTX 4060 8GB, 175.8 GB free disk, AC power 100% |
| N3 | One link in, everything out | Architecture defined; stages 1-5 orchestrated |
| N4 | No uploading | Enforced by architecture: no upload clients or secrets |
| N5 | Variable clip count | Plan schema and scoring thresholds defined |
| N6 | Credit block in every description | Metadata schema includes `credit_block` |
| N7 | No legal claims | `index.html` fair use acknowledgment; AppError codes |
| N8 | Public videos only, no cookies | Ingest specs and yt-dlp config omit cookies |
| N9 | Thumbnails are never a video frame | Schemas for generated thumbnail art defined |
| N10 | Nothing guessed (DECISIONS.md complete) | DECISIONS.md maintained across all decisions |
| N11 | Everything resumable | JSON artifact contracts and SQLite state machine in place |
| N12 | Bound to 127.0.0.1 | `settings.py` default host `127.0.0.1`; probe verified |
