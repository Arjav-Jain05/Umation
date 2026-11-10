# 02. Architecture and data contracts

Contents: 1 Process model · 2 Final folder tree · 3 Pipeline and stage names · 4 Job state machine · 5 Database · 6 JSON artifacts · 7 API · 8 Gemini client rules · 9 Errors · 10 Conventions

## 1. Process model

- One Python process: FastAPI (uvicorn) serves the API and the static `web/` folder. A single **worker thread** (started at app startup) pulls queued jobs from SQLite and runs the pipeline. Only one job runs at a time.
- Progress goes to the browser by **Server-Sent Events** (`/api/jobs/{id}/events`). The worker publishes events to an in-memory broadcaster (`app/core/events.py`); on reconnect the endpoint first replays the latest state from the DB.
- Heavy work (Whisper, ffmpeg, compositor) runs in the worker thread or subprocesses. The API thread never blocks.
- The app binds to `127.0.0.1` only.

## 2. Final folder tree (project root = workspace root)

```
start.bat  README.md  requirements.txt  requirements-optional.txt  .env.example  .gitignore  pyproject.toml
config/
  settings.py            loads .env, exposes typed Settings
  scoring.yaml           weights, thresholds (04)
  layout.yaml            layout coordinates (05)
  effects.yaml           effect defaults and density rules (06)
  source_policy.yaml     allowlist/blocklist of channels (10)
  glossary_gta6.yaml     domain terms (04)
  profanity.yaml         words to mask in captions (05)
prompts/                 plain-text prompt files, loaded at runtime (never inline long prompts in code)
  nominate_candidates.md  judge_candidate.md  plan_parts.md  director_edit_list.md
  locate_target.md  metadata_text.md  thumbnail_concept.md
app/
  main.py                FastAPI app, mounts /web and /files
  api/        jobs.py  clips.py  export.py  results.py  system.py
  core/       db.py  models.py  schemas.py  worker.py  events.py  gemini_client.py
              paths.py  errors.py  power.py  cache.py
  pipeline/
    orchestrator.py
    s1_ingest/    source_check.py  download.py  transcribe.py  tidy_transcript.py
    s2_select/    chunker.py  nominate.py  refine.py  judge.py  signal_heatmap.py
                  signal_audio.py  signal_speech.py  blend.py  planner.py
                  part_splitter.py  risk.py
    s3_build/     segments.py  cutter.py  face_track.py  layout.py  captions.py
                  audio_clean.py  compositor.py  final_render.py
    s4_director/  director.py  edit_schema.py  target_locator.py  tracker.py
                  apply_effects.py  effects/{base,zoom_punch,hook_card,arrow,highlight_box,
                  emoji_pop,part_label,progress_bar,recap_line,sfx}.py
    s5_package/   metadata.py  credit.py  thumbnail_concept.py  thumbnail_generate.py
                  thumbnail_compose.py  package.py
  utils/        ffmpeg.py  timecode.py  text.py  logging_setup.py  geometry.py  easing.py
web/  index.html  job.html  css/style.css  js/{api.js,home.js,job.js,editor.js}
assets/  fonts/  sfx/  overlays/  models/
scripts/  check_env.py  update_ytdlp.py  download_models.py  make_sfx.py
          make_overlays.py  calibrate_scoring.py  dev_smoke_test.py
tests/  conftest.py  fixtures/  test_*.py
docs/  PROGRESS.md  DECISIONS.md  spec-changes.md
data/   (runtime, gitignored)   app.db  logs/  cache/  work/<job_id>/
output/ (runtime, gitignored)   <video-slug>/<clip-folder>/
```
Per-job work folder:
```
data/work/<job_id>/
  source_info.json  audio.wav  transcript.json  chunks.json  candidates.json
  judged.json  signals.json  plan.json  segments.json
  segments/seg_01.mkv ...
  clips/<clip_id>/  words.json  cut.mkv  layout.json  framed.mp4  audio_clean.wav
                    captions.ass  captions.srt  edit_list.json  fx.mp4  metadata.json
                    thumb_*.jpg  clip.mp4
```

## 3. Pipeline and stage names

`orchestrator.py` runs stages in this order. Each stage has a name used in DB, SSE and UI, a progress weight, and an output artifact. A stage is skipped if its artifact exists and validates (resume).

| # | stage | weight % | artifact |
|---|---|---|---|
| 1 | `source_check` | 2 | `source_info.json` |
| 2 | `audio_download` | 6 | `audio.wav` |
| 3 | `transcribe` | 25 | `transcript.json` |
| 4 | `nominate` | 10 | `candidates.json` |
| 5 | `judge` | 10 | `judged.json` |
| 6 | `plan` | 4 | `signals.json`, `plan.json` |
| 7 | `segments` | 12 | `segments.json` + files |
| 8 | `build` (per clip) | 15 | `framed.mp4` etc. |
| 9 | `direct` (per clip) | 8 | `edit_list.json`, `fx.mp4` |
| 10 | `package` (per clip) | 8 | `clip.mp4`, metadata, thumbnails, output folder |

Per-clip stages 8-10 run for each planned clip in score order (tier A first). A clip failure marks that clip `failed` with a reason and continues.

## 4. Job state machine

`queued -> running -> (review | failed | canceled)`. `review` means all clips finished (some may be failed); the user can then approve/reject. `running` has a `stage` and a `progress` 0..100. Cancel sets a flag checked between stages and inside long loops; the worker stops cleanly and leaves artifacts. On app restart, any job left `running` becomes `queued` (resume).

## 5. Database (SQLite, WAL mode, file `data/app.db`)

```sql
CREATE TABLE jobs(
  id TEXT PRIMARY KEY, url TEXT NOT NULL, video_id TEXT, title TEXT, channel TEXT,
  status TEXT NOT NULL, stage TEXT, progress REAL DEFAULT 0, message TEXT,
  options_json TEXT NOT NULL, ack_fair_use INTEGER NOT NULL, ack_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT);
CREATE TABLE clips(
  job_id TEXT NOT NULL, id TEXT NOT NULL, idx INTEGER NOT NULL,
  parent_id TEXT, part_index INTEGER, part_total INTEGER,
  start REAL NOT NULL, end REAL NOT NULL, tier TEXT NOT NULL, final_score REAL NOT NULL,
  risk TEXT NOT NULL, status TEXT NOT NULL, decision TEXT NOT NULL DEFAULT 'pending',
  title_choice INTEGER DEFAULT 0, title_override TEXT, description_override TEXT,
  folder TEXT, error TEXT, PRIMARY KEY(job_id,id));
CREATE TABLE results(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, clip_id TEXT NOT NULL,
  platform TEXT NOT NULL, url TEXT, views INTEGER, likes INTEGER, logged_at TEXT NOT NULL);
CREATE TABLE cache(key TEXT PRIMARY KEY, value TEXT NOT NULL, created_at TEXT NOT NULL);
```
`clips.status`: `planned | building | built | directing | directed | packaging | packaged | failed`. `risk`: `low | medium | high`. `tier`: `A | B | C`. `decision`: `pending | approved | rejected`.
IDs: `job_id = YYYYMMDD-HHMMSS-<video_id>`; `clip_id = c01, c02...`; Part clips `c04p1, c04p2` with `parent_id = c04`.

## 6. JSON artifacts (Pydantic models in `app/core/schemas.py`)

All times: seconds on the **source video timeline** unless the field name ends `_clip` (seconds from clip start after cuts). Round to 3 decimals. Every artifact has `"schema_version": 1`.

**SourceInfo** (`source_info.json`): `video_id, url, webpage_url, title, channel, channel_url, uploader, upload_date (YYYYMMDD), duration_s, live_status, license (string|null), width, height, fps, view_count, like_count, description_head (first 600 chars), chapters [{start,end,title}], heatmap [{start,end,value}]|null, heatmap_avg_seg_s|null, source_policy {status: allow|block|none, matched_rule|null}, fetched_at`.

**Transcript** (`transcript.json`): `language, model, duration_s, words [{i, w, s, e, p}]` (`p` = probability), `sentences [{id, s, e, text, w0, w1, wpm}]` (`w0..w1` inclusive word indices), `fillers [i,...]`.

**Chunks** (`chunks.json`): `[{id, s, e, sentence_ids [first,last]}]`.

**Candidates** (`candidates.json`): `[{cid, chunk_id, start_sid, end_sid, hook_sid, s, e, reason, llm_hint_score}]` after nomination and merge.

**Judged** (`judged.json`): `[{cid, s, e, start_sid, end_sid, hook_text, scores{hook,payoff,clarity,emotion,novelty,shareability,pace} (0-10 floats), needs_context(bool), context_fix(string|null), is_story(bool), topic, entities[], content_flags[], reasons{...}, llm_score(0-100), runs(int)}]`.

**Signals** (`signals.json`): per cid `{heat(0-100|null), audio(0-100), speech_ratio(0-1), burst_count, topical_hits}`.

**Plan** (`plan.json`): `{job_id, generated_at, weights, thresholds, clips [Clip...]}` with
`Clip = {id, parent_id, part_index, part_total, start, end, duration, tier, final_score, llm_score, heat, audio, speech_ratio, hook_text, topic, risk, risk_flags [string], needs_context, context_fix, recap_line|null}`.

**Segments** (`segments.json`): `[{id, s, e, path, clip_ids [...]}]` (merged download ranges). Mapping rule: a clip reads from the segment containing `[clip.start - pad, clip.end + pad]`; offset = clip.start - segment.s.

**Words (per clip)** (`words.json`): words with times converted to the **clip timeline after cuts**: `[{w, s_clip, e_clip, emphasis(bool)}]`.

**EditList** (`edit_list.json`) in `06`. **Metadata** (`metadata.json`) in `07`.

## 7. API (all JSON; errors `{ "error": {"code": "...", "message": "..."} }`)

| Method + path | Body / result |
|---|---|
| `GET /api/health` | `{ok:true, version}` |
| `GET /api/system/check` | list of checks (01 section 7) |
| `POST /api/jobs` | body `{url, ack_fair_use:true, options:{min_tier:"C", max_clip_s:60, layout:"auto", effects:true, second_look:false, fast_mode:false, max_height:1080}}` -> `201 {job_id}`. 422 if `ack_fair_use` is not true, URL is not a single YouTube video, or source policy blocks it. |
| `GET /api/jobs` | list newest first |
| `GET /api/jobs/{id}` | job row + `stages [{name,status,progress}]` + clip counts |
| `GET /api/jobs/{id}/events` | SSE |
| `POST /api/jobs/{id}/cancel` | `{ok}` |
| `POST /api/jobs/{id}/cleanup` | deletes work files, keeps output |
| `POST /api/jobs/{id}/resume` | sets a paused/queued-by-quota job back to `queued` (also used to re-plan with a lower `min_tier` when body `{min_tier}` is given; re-planning reuses `judged.json` and makes no Gemini calls) |
| `PATCH /api/clips/{job_id}/{clip_id}/edit-list` | body `{events:[...], caption_emphasis:[...]}`; validated by `validate_and_fix` (06); requires a rerender of stages direct+package |
| `GET /api/jobs/{id}/clips` | list of clip rows + plan fields + `paths` (preview URL, thumbnail URL) |
| `GET /api/clips/{job_id}/{clip_id}` | full clip detail incl. metadata and edit_list |
| `PATCH /api/clips/{job_id}/{clip_id}` | `{decision?, title_choice?, title_override?, description_override?, start?, end?}`; changing start/end sets status to `planned` and requires rerender |
| `POST /api/clips/{job_id}/{clip_id}/rerender` | re-runs build+direct+package for this clip |
| `POST /api/clips/{job_id}/{clip_id}/results` | `{platform:"youtube|instagram|tiktok", url?, views?, likes?}` |
| `GET /api/clips/{job_id}/{clip_id}/zip` | streams the clip folder zip |
| `POST /api/system/open-folder` | `{path}` must resolve inside `OUTPUT_DIR`; calls `os.startfile` |
Static: `/web/*` (the UI), `/files/output/*` (read-only output folder).

**SSE events** (`event:` name + JSON `data:`): `progress {job_id, stage, progress, message, clip_id|null}`, `stage_done {stage}`, `clip_update {clip_id, status}`, `warning {message}`, `error {code, message}`, `done {clips_total, clips_ok, clips_failed}`. Send a comment heartbeat every 15 s.

## 8. Gemini client rules (`app/core/gemini_client.py`)

- Single class `GeminiClient` wrapping `google-genai`. Methods: `generate_json(prompt, schema_model, *, temperature, cache_key|None, images=None)`, `generate_text(...)`, `generate_image(prompt, aspect)`.
- **Rate limit:** token bucket at `GEMINI_RPM` (default 8). Block until a token is free.
- **Retries:** on 429/500/503/timeouts, exponential backoff 2, 4, 8, 16, 32 s with jitter, max 5 attempts, honouring any `retry-after`. After exhausting, raise `GeminiUnavailable`. Daily-quota errors raise `GeminiQuotaExceeded`; the job pauses stage-by-stage and shows "Gemini daily quota reached; resume later" (job status `queued` with message, not failed).
- **JSON mode:** request JSON output with a schema (structured output). Validate with Pydantic. If invalid, retry once with the validation error appended ("Your previous output failed validation: ..."). If still invalid, raise `BadModelOutput`.
- **Cache:** key = sha256(model + prompt + images hash + temperature + schema name). Store in the `cache` table. Reads are free; this makes resumes and re-runs cost nothing.
- **Temperature:** nominate 0.4, judge 0.2, director 0.4, metadata 0.7, thumbnail concept 0.8.
- Never send API keys in logs. Log token counts when available.

## 9. Errors (`app/core/errors.py`)

Base `AppError(code, message, hint=None)`. Subclasses: `InvalidUrl`, `SourceBlocked`, `SourceUnavailable`, `LiveNotFinished`, `TooLong`, `DiskSpace`, `DownloadFailed`, `TranscribeFailed`, `GeminiUnavailable`, `GeminiQuotaExceeded`, `BadModelOutput`, `FfmpegFailed`, `NoCandidates`, `Canceled`. The API converts them to the error JSON; the worker stores `code: message` in `jobs.error`.

## 10. Conventions

- All filesystem paths come from `paths.py` functions (`job_dir(job_id)`, `clip_dir(job_id, clip_id)`, `output_clip_dir(...)`). No string-concatenated paths.
- Slug: lowercase, ASCII, hyphens, max 60 chars, from the video title.
- Output folder name: `output/<slug>-<video_id>/<clip_id>_<tier>[_part<k>of<n>]/`.
- Atomic writes: write to `*.tmp` then `os.replace`.
- Every stage function signature: `run(ctx: JobContext) -> None`, where `JobContext` holds settings, paths, db handle, gemini client, event publisher, cancel flag and the options. Stages read and write artifacts only through `ctx` helpers that validate against the schemas.
