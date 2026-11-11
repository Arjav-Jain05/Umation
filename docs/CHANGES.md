# CHANGES: Layered Local-Only Pipeline Upgrade

This file documents every decision, modification, default choice, and replaced component during the upgrade to the v4 local-only layered pipeline.

## Initial Setup (Phase 0)
- **Branch**: `feature/final-local-layered` created from master.
- **Spec**: Copied `ANTIGRAVITY_PROMPT_FINAL_v4.md` to `docs/SPEC.md`.
- **Checklist**: Created `docs/CHECKLIST.md` tracking all requirements by phase.
- **Weights directory**: `D:\Open_Source_Weights` confirmed with >170 GB free space.
- **Execution model**: Phased, autonomous loop with automated selftests per phase.

## Phase 1: Core Clips (Usable Product)
- **Network Guard**: Implemented `app/core/network_guard.py` patching `socket.create_connection` to strictly block all cloud AI domains (`google.genai`, `api.openai.com`, `anthropic.com`, etc.) while permitting local loopback (`127.0.0.1:11434`).
- **Local Model Layer**: Implemented `llm/` package with `OllamaProvider`, `LocalModelManager`, and `config/models.yaml` defining fallback chains with automatic context window truncation, repair retries, and strict `keep_alive: 0` memory unloading.
- **Client Replacement**: Replaced `GeminiClient` with `LocalLLMClient` in `app/core/gemini_client.py`. Supported all caller signatures including `generate_json`, `generate_text`, `call_json`, `call_text`, `generate_image`.
- **Cloud Purge**: Removed all cloud SDK imports (`google-genai`) and external API keys from `app/`, `config/`, and `web/`.
- **Local File Ingestion**: Updated `s1_ingest/source_check.py`, `s1_ingest/download.py`, and `s3_build/segments.py` to allow direct local file processing (`.mp4`, `.wav`) without network overhead.
- **Resilience and Tiers**: Added `quality_threshold`, `tier_s/a/b/c` thresholds, and Tier C fallback to `app/pipeline/s2_select/planner.py` ensuring robust clip selection.
- **End-to-End Validation**: Ran 5-minute video `samples/sample_5min.mp4` through full pipeline under offline network guard. Verified 9:16 vertical render (1080x1920) with ASS subtitles and peak VRAM of 1234 MB (ceiling: 7.5 GB).

## Phase 2: Live Quality Slider, Candidates Store & Caption Presets
- **Candidates Store (SQLite)**: Created `candidates` table and index in `app/core/db.py`. Added `upsert_candidate`, `list_candidates`, and `update_candidate_selection` in `app/core/models.py`. In `planner.py`, all nominated/judged candidates are persisted with their complete score breakdowns (`llm`, `audio`, `heat`, `final_score`, etc.) into SQLite.
- **Client Quality Slider**: Added `#slider-panel` in `web/job.html` and interactive filtering logic in `web/js/job.js`. Moving the slider dynamically filters in-memory candidates with zero model calls or backend round-trips. Includes histogram distribution, Otsu suggest chip, and duration estimates.
- **7 Selectable Caption Presets**: Added `modern_box`, `classic_yellow`, `minimal_shadow`, `cyan`, `yellow_box`, `neon_green`, and `red_gaming` to `app/pipeline/s3_build/captions.py`.
- **API Endpoints**: Added `GET /api/jobs/{id}/candidates` (with `/projects/{id}/candidates` alias) and `POST /api/jobs/{id}/render` (with `/projects/{id}/render` alias) for selective re-renders based on threshold, pinned clips, and excluded clips.
- **Automated Verification**: Created `tests/test_phase_2_slider.py` and implemented Phase 2 gate checks in `scripts/selftest.py`. Verified all 4 gate tests pass.
