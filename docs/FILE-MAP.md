# FILE-MAP: every file in shorts-engine

How to use: before writing a file, read its row here AND the spec section it names. Names and signatures are the contract; do not rename without updating this file, tests and callers. `M` = milestone that creates it. `Spec` = reference file in `.agents/skills/shorts-engine/references/`. All stage modules expose `run(ctx: JobContext) -> None` unless stated. Types are Pydantic models from `app/core/schemas.py`.

Table of contents: 1 Root · 2 config · 3 prompts · 4 app/core · 5 app/api · 6 app/utils · 7 pipeline s1 · 8 s2 · 9 s3 · 10 s4 · 11 s5 · 12 orchestrator · 13 web · 14 scripts · 15 tests · 16 assets · 17 docs · 18 runtime folders

## 1. Root files

| File | M | Purpose | Notes |
|---|---|---|---|
| `AGENTS.md` | pre | contract | given |
| `README.md` | M0, final M5 | install, run, troubleshoot, privacy | sections: Requirements, Install, First run, Using the app, Output folder, Troubleshooting (table from 09), Privacy (what goes to Gemini), Safe working practice (10 s8) |
| `start.bat` | M0 | one-click launcher | exact content in 01 s9 |
| `requirements.txt` | M0 | runtime deps | list in 01 s3; `requirements.lock` after M0 |
| `requirements-optional.txt` | M0 | `diffusers`, `torch`, `realesrgan` | not installed by default |
| `.env.example` | M0 | all env vars with defaults | list in 01 s6 plus `SMALL_VIDEO_MIN=40`, `CLEAN_AFTER_DAYS=7`, `MAX_CLIPS_SOFT=40`, `LOCAL_IMAGE_FALLBACK=false` |
| `.gitignore` | M0 | ignores | see rule 30 |
| `pyproject.toml` | M0 | ruff + pytest config | ruff line length 100; pytest `testpaths=["tests"]`, `-q` |

## 2. `config/`

| File | M | Content |
|---|---|---|
| `settings.py` | M0 | `class Settings` (dataclass or pydantic-settings) with every `.env` key typed; `get_settings() -> Settings` (cached); loads `.env` via python-dotenv; derives `data_dir`, `output_dir` as absolute `Path`; validates ranges (e.g. `GEMINI_RPM` 1..60). Spec 01 s6. |
| `scoring.yaml` | M1 | exact YAML in 04 s12 |
| `layout.yaml` | M2 | canvas 1080x1920, safe zone (top 220, bottom 420, sides 60, right extra 100), layout rects and caption anchors from 05 s5 |
| `effects.yaml` | M3 | density rules exactly from 06 s3 |
| `source_policy.yaml` | M1 | exact YAML in 10 s3 |
| `glossary_gta6.yaml` | M1 | exact YAML in 04 s13 |
| `profanity.yaml` | M2 | `words: [...]` list of English profanity (lower-case stems) and `mask_char: "*"` |

## 3. `prompts/` (plain text, loaded via `load_prompt(name)`; text exactly as in the spec)

| File | M | Spec |
|---|---|---|
| `nominate_candidates.md` | M1 | 04 s3 |
| `judge_candidate.md` | M1 | 04 s5 |
| `plan_parts.md` | M1 | 04 s9 |
| `director_edit_list.md` | M3 | 06 s4 |
| `locate_target.md` | M3 | 06 s7 (two prompts: locate, verify; separate files `locate_target.md`, `verify_target.md`) |
| `metadata_text.md` | M4 | 07 s1 |
| `thumbnail_concept.md` | M4 | 07 s6 |

## 4. `app/core/`

| File | M | Public API (signatures) | Notes |
|---|---|---|---|
| `paths.py` | M0 | `data_dir()`, `output_dir()`, `job_dir(job_id)`, `clip_dir(job_id, clip_id)`, `output_clip_dir(video_slug, video_id, clip_id, tier, part=None)`, `assets_dir()`, `prompts_dir()`, `ensure(path) -> Path` | the ONLY place paths are built |
| `errors.py` | M0 | `class AppError(Exception)` with `code, message, hint`; subclasses from 02 s9 | `to_api(err) -> dict` |
| `db.py` | M0 | `init_db()`, `get_conn()`, `transaction()` (context manager), `now_iso()` | SQLite WAL, `check_same_thread=False`, row factory dict; schema SQL from 02 s5 |
| `models.py` | M0 | CRUD helpers: `create_job`, `get_job`, `list_jobs`, `update_job(job_id, **fields)`, `upsert_clip`, `list_clips`, `get_clip`, `update_clip`, `add_result`, `list_results` | no ORM; plain SQL |
| `schemas.py` | M0 | Pydantic v2 models: `SourceInfo, Word, Sentence, Transcript, Chunk, Candidate, JudgedItem, Signals, Clip, Plan, Segment, WordClip, EditEvent, EditList, Metadata, JobOptions, JobCreate, JobOut, ClipOut, ErrorOut`; `read_artifact(path, Model)`, `write_artifact(path, obj)` (atomic) | every artifact has `schema_version=1` |
| `cache.py` | M1 | `make_key(*parts) -> str`, `cache_get(key) -> str|None`, `cache_set(key, value)` | table `cache` |
| `events.py` | M1 | `class Broadcaster`: `publish(job_id, event, data)`, `subscribe(job_id) -> AsyncIterator`; module singleton `broadcaster` | thread-safe (worker thread publishes, async API consumes via `asyncio.Queue` + `loop.call_soon_threadsafe`) |
| `gemini_client.py` | M1 | `class GeminiClient(settings, cache)`: `generate_json(prompt, schema_model, *, temperature, cache_key=None, images=None, system=None)`, `generate_text(...)`, `generate_image(prompt, aspect)`; `class FakeGeminiClient` for tests | rules in 02 s8 |
| `power.py` | M1 | `@contextmanager keep_awake()`; `on_battery() -> bool` | `ctypes.windll.kernel32.SetThreadExecutionState` |
| `worker.py` | M1 | `class Worker`: `start()`, `stop()`, `wake()`; loop picks oldest `queued` job, builds `JobContext`, calls `run_pipeline(ctx)`; on start resets `running` -> `queued` | one thread |

## 5. `app/api/` and `app/main.py`

| File | M | Endpoints / functions |
|---|---|---|
| `main.py` | M0 | `create_app() -> FastAPI`; lifespan: `init_db`, start `Worker`; mounts `/web` (StaticFiles `web/`), `/files/output` (read-only `output/`); redirect `/` to `/web/index.html`; includes routers; exception handler mapping `AppError` to error JSON; `app = create_app()` |
| `api/system.py` | M0 | `GET /api/health`, `GET /api/system/check` (calls shared function from `scripts/check_env.py` via `app/core` import, not subprocess), `POST /api/system/open-folder` |
| `api/jobs.py` | M1 | `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/events` (SSE with 15 s heartbeat), `POST /cancel`, `POST /cleanup`, `POST /resume`, `GET /api/jobs/{id}/clips`; URL validator `parse_youtube_url(url) -> str` lives in `app/pipeline/s1_ingest/source_check.py` and is imported |
| `api/clips.py` | M2 | `GET /api/clips/{job}/{clip}`, `PATCH ...`, `POST .../rerender`, `PATCH .../edit-list` (M5) |
| `api/export.py` | M4 | `GET /api/clips/{job}/{clip}/zip` (streaming zip) |
| `api/results.py` | M4 | `POST /api/clips/{job}/{clip}/results`; `GET /api/results/summary` |

## 6. `app/utils/`

| File | M | API |
|---|---|---|
| `logging_setup.py` | M0 | `setup_logging(settings)`; rotating file `data/logs/app.log` (5 x 5 MB) + console; `get_logger(name, job=None, clip=None)` returns `LoggerAdapter` |
| `ffmpeg.py` | M1 | `run_ffmpeg(args: list[str], *, cwd=None, timeout=3600, check=True) -> CompletedProcess` (adds `-hide_banner -y`); `probe(path) -> ProbeInfo(duration, width, height, fps, has_audio, vcodec, acodec)`; `nvenc_args(cq=19, preset="p5")`; `loudnorm_measure(audio_path) -> dict`; `extract_frame(video, t, out_path, max_side=None)`; `has_encoder(name) -> bool`; `FfmpegFailed` on error with stderr tail |
| `timecode.py` | M1 | `fmt_hms(seconds) -> str`, `fmt_ms(seconds)`, `parse_hms`, `Remapper(keep_intervals)` with `.remap(t_source) -> float` and `.total_duration` |
| `text.py` | M1 | `slugify(text, max_len=60)`, `mask_profanity(text, words)`, `strip_punct(word)`, `is_filler(word)`, `truncate_words(text, max_chars)` |
| `geometry.py` | M3 | `Box(x1,y1,x2,y2)`, `iou(a,b)`, `clamp_box(box, w, h)`, `in_safe_zone(box, layout_cfg)`, `expand(box, pct)` |
| `easing.py` | M3 | `ease_out_cubic`, `ease_in_out`, `ease_out_back`, `lerp`, `clamp01` |
| `qa.py` | M2 | `check_clip_file(path) -> QAReport(passed, failures[])` implementing 09 s6 (probe checks, loudness, blackdetect, freezedetect, pop check, sharpness) |

## 7. `app/pipeline/s1_ingest/` (spec 03)

| File | M | API |
|---|---|---|
| `source_check.py` | M1 | `parse_youtube_url(url) -> str` (raises `InvalidUrl`); `run(ctx)`: yt-dlp metadata to `SourceInfo`, rules 1-7, policy match, heatmap, warnings |
| `download.py` | M1 | `download_audio(ctx) -> Path` (`audio.wav`); `download_range(url, s, e, out_path, max_height, progress_cb)` used by segments; `get_ydl_opts(...)`; `run(ctx)` is the `audio_download` stage |
| `transcribe.py` | M1 | `split_audio_chunks(audio, chunk_s=1800, overlap_s=15) -> list[AudioChunk]`; `transcribe_chunk(model, chunk, lang, prompt) -> list[Word]`; `merge_chunks(...)` with overlap de-dup; `release_model()`; `run(ctx)` writes `transcript.json` after `tidy` |
| `tidy_transcript.py` | M1 | `build_sentences(words) -> list[Sentence]`; `detect_fillers(words) -> list[int]`; `write_debug_txt(...)` |

## 8. `app/pipeline/s2_select/` (spec 04)

| File | M | API |
|---|---|---|
| `chunker.py` | M1 | `make_chunks(sentences, minutes=20, overlap_s=90) -> list[Chunk]`; `render_chunk_text(chunk, sentences, heat_peaks) -> str`; `mark_dead_regions(sentences)` |
| `nominate.py` | M1 | `run(ctx)`: per chunk call Gemini (prompt A), validate, merge duplicates, write `candidates.json` |
| `refine.py` | M1 | `refine_candidate(cand, sentences, max_clip_s) -> Candidate|None` (steps 1-6 of 04 s4) |
| `judge.py` | M1 | `run(ctx)`: batches of 4 (6 in fast mode), 2 runs, average, compute `llm_score`; write `judged.json` |
| `signal_heatmap.py` | M1 | `heat_score(window, heatmap, avg_seg) -> float|None` |
| `signal_audio.py` | M1 | `frame_db(audio_path) -> np.ndarray` (streamed), `audio_score(window, db, baseline) -> (score, bursts)` |
| `signal_speech.py` | M1 | `speech_ratio(words, s, e)`, `topical_hits(text, glossary)` |
| `blend.py` | M1 | `blend(judged, signals, cfg, domain) -> float` (formula 04 s7) |
| `planner.py` | M1 | `plan_clips(judged, signals, cfg, options) -> Plan` (threshold, tiers, dedupe, soft cap); `run(ctx)` computes signals, writes `signals.json`, `plan.json` |
| `part_splitter.py` | M1 | `split_story(clip, sentences, gemini) -> list[Clip]` with validation |
| `risk.py` | M1 | `assess(clip, source_info, policy) -> (level, flags)` |

## 9. `app/pipeline/s3_build/` (spec 05)

| File | M | API |
|---|---|---|
| `segments.py` | M2 | `plan_segments(clips, source_duration, small_video_min) -> list[Segment]`; `run(ctx)` downloads (or full download for small videos), verifies, writes `segments.json`; `segment_for(clip) -> (Segment, offset)` |
| `cutter.py` | M2 | `compute_keep_intervals(words, fillers, audio_db, clip_range, cfg) -> list[Interval]`; `build_filter_script(intervals, seg_offset) -> str`; `cut_clip(seg_path, intervals, out_path)`; writes `cuts.json`, `words.json` |
| `face_track.py` | M2 | `load_detector()`; `sample_faces(video, every_s=2) -> list[FaceSample]`; `track_faces(video, fps) -> list[(t, cx)]` |
| `layout.py` | M2 | `detect_layout(samples, override) -> LayoutDecision`; `render_gameplay(...)`, `render_facecam(...)` (ffmpeg filter graphs); `render_talking_head(...)` (Python frame loop using `compositor` helpers); `smooth_path(xs, fps, crop_w)` |
| `captions.py` | M2 | `chunk_words(words) -> list[CaptionChunk]`; `write_ass(chunks, layout, emphasis, path)`; `write_srt(chunks, path)`; `validate_ass(path, duration)` |
| `audio_clean.py` | M2 | `clean_audio(cut_path, layout, out_wav)` |
| `compositor.py` | M3 | `class FrameReader`, `class FrameWriter` (ffmpeg pipes, NVENC), `render_with_effects(framed_path, edit_list, out_path, cancel)` |
| `final_render.py` | M2 | `render_final(clip_ctx) -> Path`: loudnorm 2-pass, ASS burn-in, NVENC (fallback libx264), then `qa.check_clip_file` |
| `__init__.py` stage entry | M2 | `run(ctx)` iterates clips by score: cut, layout, captions, audio; per-clip failure isolation |

## 10. `app/pipeline/s4_director/` (spec 06)

| File | M | API |
|---|---|---|
| `edit_schema.py` | M3 | `EditEvent`, `EditList` models; `validate_and_fix(edit_list, words, cfg, layout) -> (EditList, messages)` |
| `director.py` | M3 | `plan_with_gemini(ctx, clip) -> DirectorOut`; `fallback_director(clip, words, cfg) -> EditList`; `build_edit_list(director_out, located_boxes, ...)`; `run(ctx)` |
| `target_locator.py` | M3 | `locate(frame_path, description, gemini) -> LocatedBox|None`; `parse_box(raw, w, h)`; `verify_crop(...)` |
| `tracker.py` | M3 | `track_box(video, t0, dur, bbox) -> list[(t, Box)]` (CSRT with failure rules) |
| `apply_effects.py` | M3 | `render_effects(ctx, clip)`: if no visual events skip, else compositor |
| `effects/base.py` | M3 | `class Effect(Protocol)`: `render(frame, t_local, params, ctx) -> frame`; `REGISTRY` |
| `effects/zoom_punch.py` `hook_card.py` `arrow.py` `highlight_box.py` `emoji_pop.py` `part_label.py` `recap_line.py` `progress_bar.py` | M3 | one class each, exact visuals in 06 s10 |
| `effects/sfx.py` | M3 | `build_sfx_mix(events, duration, out_wav)`; synthesised assets from `scripts/make_sfx.py` |

## 11. `app/pipeline/s5_package/` (spec 07, 10)

| File | M | API |
|---|---|---|
| `credit.py` | M4 | `build_credit_block(source_info, clip, short=False) -> str` |
| `metadata.py` | M4 | `generate_metadata(ctx, clip) -> Metadata`; `validate_metadata`; `fallback_metadata`; `build_descriptions(...)` |
| `thumbnail_concept.py` | M4 | `make_concept(ctx, clip) -> ThumbConcept` |
| `thumbnail_generate.py` | M4 | `generate_art(concept, aspect, ctx) -> (PIL.Image, generator)` tiers gemini, sdxl, pillow; `ahash(img)`; `not_a_frame(img, sample_frames) -> bool` |
| `thumbnail_compose.py` | M4 | `compose_16x9(art, concept) -> Path`; `compose_9x16(...)`; auto-fit text, contrast box |
| `package.py` | M4 | `package_clip(ctx, clip) -> Path` writes folder + checklist; `run(ctx)` per clip, publishes `clip_update` |

## 12. `app/pipeline/orchestrator.py` (spec 02 s3, s4)

`STAGES: list[StageDef(name, weight, fn, artifact)]`; `class JobContext(settings, job, paths, db, gemini, publish, cancel_flag, options)` with helpers `artifact_ok(name)`, `progress(stage, fraction, message, clip_id=None)`, `check_cancel()`; `run_pipeline(ctx)`: resume logic (skip stage if artifact validates), per-clip loops for build/direct/package, error mapping, final status `review|failed|canceled`, SSE `done`.

## 13. `web/`

| File | M | Content |
|---|---|---|
| `index.html` | M1 | per 08 s2 with exact ids |
| `job.html` | M1 | per 08 s3, s4 |
| `css/style.css` | M1 | per 08 s7 |
| `js/api.js` | M1 | `getJSON`, `postJSON`, `patchJSON`, `openEvents(jobId, handlers)` with reconnect |
| `js/home.js` | M1 | URL validation regex, ack gating, options, submit, jobs table refresh |
| `js/job.js` | M1 | progress, summary, filters, clip cards, copy buttons, decisions |
| `js/editor.js` | M5 | modal editor per 08 s6 |

## 14. `scripts/`

`check_env.py` (M0; function `run_checks() -> list[Check]` reused by the API; CLI prints table, exit 1 on FAIL) · `update_ytdlp.py` (M0) · `download_models.py` (M0; `--fonts`, `--models`, verifies sizes, prints URLs) · `make_sfx.py` (M3) · `make_overlays.py` (M3; draws `arrow.png`) · `make_fixtures.py` (M1; synthetic video via ffmpeg lavfi, canned JSON) · `dev_smoke_test.py` (M1; runs a real job via API, runs QA checks) · `calibrate_scoring.py` (M4 per 09 s7).

## 15. `tests/`

`conftest.py` (fixtures: temp data dir, fake Gemini, fake yt-dlp, test client) and the exact test files named in `references/09` section 3. Fixtures in `tests/fixtures/` per 09 s2.

## 16. `assets/`

`fonts/` (Montserrat ExtraBold static, Anton, Noto Color Emoji), `sfx/` (generated), `overlays/` (arrow.png), `models/` (blaze_face_short_range.tflite, optional test face). Large binaries are gitignored except small overlays/sfx.

## 17. `docs/`

`FILE-MAP.md` (this), `SETUP-DOWNLOADS.md`, `SKILLS-TO-INSTALL.md`, `FLOWCHARTS.md`, `VERIFICATION-PROTOCOL.md`, `TRACEABILITY.md`, `PROGRESS.md`, `DECISIONS.md`, `spec-changes.md`, `INSTALLED-SKILLS.md`.

## 18. Runtime folders (created by the app, gitignored)

`data/app.db`, `data/logs/`, `data/cache/`, `data/work/<job_id>/...` (02 s2), `output/<slug>-<video_id>/<clip_folder>/` (07 s9).

## 19. Cross-file rules

1. A stage reads/writes artifacts only through `read_artifact`/`write_artifact`.
2. Stages never import from later stages.
3. Prompts are never inlined in code.
4. Every public function has a docstring (inputs, outputs, failure modes) and at least one test.
5. Every module is imported by something or exercised by a test (no orphans).
6. When a file's row here changes, update tests and callers in the same commit and note it in `PROGRESS.md`.
