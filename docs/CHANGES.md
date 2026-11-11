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

## Phase 3: Audience Signals and Sensors
- **Audience Signals Module**: Implemented `app/pipeline/s1_ingest/audience.py` parsing YouTube normalized most replayed heatmap (0-1), timestamped comments extraction with like weighting and 10s binning, live chat replay processing (density spikes and hype keyword detection e.g. "pog", "clip it", "lmao"), and chapters as soft topic boundaries. Strictly implements fail-soft: missing signals are marked `available=False` and `None` score rather than filling with zeros.
- **Layer 1 Acoustic & Prosodic Sensors**: Implemented `app/pipeline/sensors/audio_energy.py` (RMS loudness profiling, z-scores, peak bursts, and silence-to-explosion suspense/payoff detection), `app/pipeline/sensors/sound_events.py` (acoustic feature detection for gaming audio events like explosions, gunshots, screams, laughter, cheering, tire squeals, sirens), and `app/pipeline/sensors/voice_emotion.py` (speaking pace in WPM, exclamation/question density, and hype lexicon matching).
- **Layer 1 Visual & Semantic Sensors**: Implemented `app/pipeline/sensors/scene_motion.py` (2 fps video frame difference motion energy track and histogram scene cut detection with cv2) and `app/pipeline/sensors/topic_segmenter.py` (sentence similarity topic boundary segmentation and candidate deduplication).
- **Timeline Synthesis**: Implemented `app/pipeline/sensors/timeline_generator.py` synthesizing discrete timeline events and multi-sensor hot-zone maps for LLM prompt context.
- **Layer 6 Dynamic Fusion**: Implemented `app/pipeline/s2_select/fusion.py` calculating the multi-signal quality score with automatic dynamic weight redistribution when optional signals are missing.
- **Profiles**: Added `profiles/default.yaml` and `profiles/gaming_gta6.yaml`.
- **Automated Verification**: Created `tests/test_phase_3_signals.py` (10 tests passing) and implemented Phase 3 gate checks in `scripts/selftest.py` (4 PASS, 0 FAIL).

## Phase 4: Multi-Model Quality
- **Hardened Model Manager**: Updated `llm/manager.py` with automatic context reduction upon CUDA OOM (4096 -> 2048), exponential retry backoff with jitter, schema repair retries with error feedback, and sequential fallback across model chains defined in `config/models.yaml`.
- **Multi-Proposer Agreement**: Added `agreement_count` and `proposers` to `Candidate` in `app/core/schemas.py`. Candidates proposed by multiple models overlapping >50% increment `agreement_count = 2`, while novel candidates from either model are preserved.
- **Layer 3 Critic & Arc Stitcher**: Implemented `app/pipeline/s2_select/critic.py` evaluating candidates on hook strength, standalone clarity, and payoff delivery. Added `stitch_story_arcs` grouping narrative arcs into Part 1/2/3 splits.
- **Layer 4 Head-to-Head Tournament Reranker**: Implemented `app/pipeline/s2_select/rerank.py` executing shuffled tournament comparisons across batches of 5-6 candidates to eliminate presentation position bias.
- **Calibrated Personal Ranker**: Implemented `app/core/feedback.py` logging thumbs up/down into `feedback/ratings.jsonl` and `scripts/train_ranker.py` training a `HistGradientBoostingClassifier` with feature importance audits.
- **Model Bake-Off Harness**: Implemented `scripts/bakeoff.py` benchmarking candidate LLMs on prompt validity rate, latency, token throughput, and Spearman rank correlation.
- **Automated Verification**: Created `tests/test_phase_4_multi_model.py` (7 tests passing) and added Phase 4 gate checks to `scripts/selftest.py` (4 PASS, 0 FAIL).

## Phase 5: Visual Layer, Metadata, Thumbnails, Polish
- **Layer 5 Visual Evidence**: Implemented `app/pipeline/sensors/visual_evidence.py` providing 1 fps frame sampling inside candidate shortlist ranges, dead footage detection (static frames variance < 2.0 or black frames mean < 8.0), optical motion action scoring (0-100), and on-screen trigger word detection with RapidOCR/fallback regexes.
- **Layer 8 Metadata Ensemble & Creator Credit**: Updated `app/pipeline/s5_package/metadata.py` enforcing strict title length limits (<70 chars), generating high-curiosity titles, 15 hashtags, and source risk notes. Verified `app/pipeline/s5_package/credit.py` enforcing mandatory creator credit blocks. Added `docs/SOURCE_POLICY.md` explaining fair use reality and creator rights.
- **Layer 9 Artwork Thumbnails**: Updated `app/pipeline/s5_package/thumbnail_generate.py` generating both 1280x720 (16:9 standard) and 1080x1920 (9:16 vertical cover) artwork using procedural gradients and vector art, verified against video frame leakage using perceptual average hash (ahash distance > 8).
- **Pipeline Presets**: Updated `app/core/schemas.py` with `JobOptions.apply_preset()` supporting `fast`, `balanced`, and `best` modes.
- **Ablation Study**: Implemented `scripts/ablation.py` comparing Variant A (Qwen-only), Variant B (Dual Proposers), and Variant C (Full Funnel), and documented results in `docs/ABLATION_REPORT.md`.
- **Offline Documentation**: Updated `docs/MODELS.md` with verified local weights storage and measured VRAM usage, and updated `README.md` to document strict offline operation.
- **Automated Verification**: Created `tests/test_phase_5_visual_metadata.py` (7 tests passing) and added Phase 5 gate checks to `scripts/selftest.py` (4 PASS, 0 FAIL). Full system gate check `scripts/selftest.py --all` passes all 24 checks across Phases 0 to 5.
