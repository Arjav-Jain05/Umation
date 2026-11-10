# TRACEABILITY

One row per requirement from `.agents/skills/shorts-engine/SKILL.md` section 2. Fill in as you build. A row is complete only when File, Test and Evidence are all filled and Status is DONE. Evidence = command + pasted result (or a pointer to the PROGRESS.md entry that holds it).

| ID | Requirement | Spec ref | Files | Tests | Evidence | Status |
|---|---|---|---|---|---|---|
| R1 | Basic web UI on localhost: paste link, press button | 08 | web/index.html, web/js/home.js | test_api_jobs | | TODO |
| R2 | Live progress per stage in the UI | 02, 08 | app/core/events.py, web/js/job.js | | | TODO |
| R3 | Find all viral-worthy moments; count varies | 04 | s2_select/* | test_planner | | TODO |
| R4 | Score blends transcript judgement + replay heatmap + audio energy | 04 | blend.py, signal_*.py | test_signals, test_blend | | TODO |
| R5 | Hook quality judged; weak hook cannot reach tier A | 04 | blend.py, planner.py | test_blend | | TODO |
| R6 | Clips make sense standalone or are fixed/rejected | 04 | judge.py | | | TODO |
| R7 | Long stories split into Part 1/2/3 | 04 | part_splitter.py | test_part_splitter | | TODO |
| R8 | Fluid cuts: dead air and fillers removed, crossfaded | 05 | cutter.py | test_cutter | | TODO |
| R9 | Crisp output 1080x1920, no blurry upscales | 05 | layout.py, final_render.py, qa.py | test_final_render | | TODO |
| R10 | Layouts: talking head, gameplay stack, facecam | 05 | layout.py, face_track.py | test_layout_detect | | TODO |
| R11 | Animated word-by-word captions in safe zone | 05 | captions.py | test_captions | | TODO |
| R12 | AI director: zoom, hook card, arrows, emoji, progress, part label, SFX | 06 | s4_director/* | test_edit_schema, test_effects | | TODO |
| R13 | Arrows point at the correct thing (vision-located, verified) | 06 | target_locator.py, tracker.py | test_locator_parse | | TODO |
| R14 | Generated thumbnail referencing topic, never a video frame | 07 | thumbnail_*.py | test_thumbnail | | TODO |
| R15 | 3 titles, description, hashtags, tags/SEO | 07 | metadata.py | test_metadata | | TODO |
| R16 | Mandatory credit block | 07, 10 | credit.py | test_credit | | TODO |
| R17 | Fair-use risk flags per clip | 10 | risk.py | test_risk | | TODO |
| R18 | Review screen: preview, tier, edit text, approve/reject, copy, download | 08 | web/js/job.js, editor.js | manual + API tests | | TODO |
| R19 | Output folder per clip with everything needed to upload | 02, 07 | package.py | test_package | | TODO |
| R20 | Handles 8-hour VODs without filling the disk | 03 | download.py, segments.py, chunker.py | long-video test | | TODO |
| R21 | Gemini rate limits, caching, retries | 02 | gemini_client.py, cache.py | test_gemini_client | | TODO |
| R22 | Windows power, GPU memory, disk-space safety | 01 | power.py, transcribe.py, source_check.py | | | TODO |
| R23 | Results log feeding calibration | 09 | results.py, calibrate_scoring.py | | | TODO |
| R24 | Tests and measurable acceptance gates | 09 | tests/* | test_m0.py | `pytest -v`: 10 passed in 0.42s; `ruff check .`: clean; `check_env.py`: 14 PASS | PARTIAL (M0 pass) |
| R25 | Fast lane for release-week speed | 04, 09 | judge.py, orchestrator.py | | | TODO |
| R26 | GTA 6 domain vocabulary and boosts | 04 | glossary_gta6.yaml, blend.py | test_signals | | TODO |
| R27 | Profanity masking in captions | 05 | captions.py, text.py | test_captions | | TODO |
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
