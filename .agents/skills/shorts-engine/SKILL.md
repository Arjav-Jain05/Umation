---
name: shorts-engine
description: Complete build, run and maintenance spec for "shorts-engine", a free local Klap.app alternative. It turns a pasted YouTube link (video or finished livestream VOD) into every viral-worthy vertical short in it (variable clip count, Part 1/2/3 splits, face-aware 9:16 layouts, animated captions, AI-directed zooms/arrows/hook cards, generated thumbnails, titles, descriptions, tags and a mandatory credit block), built for the user's GTA 6 clipping channel. Use this skill whenever the user mentions shorts-engine, Klap, clipping or cutting clips from YouTube videos or livestreams, GTA 6 clips, viral shorts, a Whisper/yt-dlp/ffmpeg/Gemini pipeline, a FastAPI backend or localhost web UI for this project, or asks to build, continue, debug, test, run or extend ANY part of this project, even if they never name the skill.
---

# shorts-engine

You are building and maintaining a **local, free, Windows-friendly web app**. The user pastes one YouTube link into a page on `localhost`. The app does everything else and hands back a folder of finished, upload-ready shorts. **The user uploads manually. The app never uploads anything.**

This file is the contract. It is deliberately short enough to stay in context. **All details live in `references/`.** You must read the reference files named in section 8 before writing code for the matching stage. Do not work from memory of how such apps usually look.

---

## 0. How to use this skill

1. Read this entire file.
2. Read `references/01-environment-and-setup.md` and `references/02-architecture-and-data-contracts.md` fully. They apply to every milestone.
3. Find the current milestone in section 5. Read the references it lists. Do the work. Run its gate checks. Report. Wait for the user's go-ahead before the next milestone.
4. If the user asks for a change, find the owning reference file, change the spec there first (in the project's `docs/spec-changes.md`, not in this read-only skill), then change the code.

The skill folder is read-only reference. Project code lives in the workspace root. The skill is installed at `<workspace>/.agents/skills/shorts-engine/` (older Antigravity builds used `.agent/skills/`).

---

## 1. Mission and non-negotiables

**Goal:** a free tool at least as good as Klap.app at turning long videos into shorts, and better where possible, specialised for GTA 6 content. GTA 6 releases on 19 November 2026 (user's statement). YouTubers will post livestreams and videos. The user will clip them and give proper credit.

Non-negotiables. Violating any of these is a bug:

- N1. **Free only.** No paid API is required. Gemini free tier, local Whisper, local ffmpeg, local MediaPipe. Paid options may exist only as opt-in config, off by default.
- N2. **Runs on the user's laptop:** ASUS TUF F15, Windows, RTX 4060 8 GB VRAM, 16 GB RAM, 1 TB SSD. (The 8 GB iGPU memory is shared system RAM and is not usable for CUDA.)
- N3. **One link in, everything out.** After the paste the user does nothing until review.
- N4. **No uploading.** No YouTube API upload, no Instagram API, no browser automation to post. Export only.
- N5. **Variable clip count.** Never "top N". Every candidate above the quality bar becomes a clip (soft cap only as a safety net).
- N6. **Credit block in every description.** Original title, channel, channel URL, link with timestamp. No exceptions.
- N7. **Never claim legal certainty.** The app never says a clip "is fair use". It shows risk flags and the credit block. See `references/10-fair-use-credit-policy.md`.
- N8. **Public videos only.** No cookies, no logins, no private/members-only/age-gated bypass, no live streams still in progress.
- N9. **Thumbnails are generated artwork that references the topic. They are never a frame cut from the video.**
- N10. **Nothing is guessed.** See section 4.
- N11. **Everything resumable.** Every stage writes a validated JSON artifact. A crash or restart resumes from the last finished stage.
- N12. **Bind to 127.0.0.1 only.** The UI is private.

---

## 2. Requirement checklist

Every item must be demonstrably true at the end. Each has an owner file and a test.

| ID | Requirement | Owner reference |
|---|---|---|
| R1 | Basic web UI on localhost: paste link, press button | 08 |
| R2 | Live progress per stage in the UI | 02, 08 |
| R3 | Find **all** viral-worthy moments; count varies per video | 04 |
| R4 | Score blends transcript judgement + YouTube "most replayed" heatmap + audio energy | 04 |
| R5 | Hook quality judged; weak-opening clips cannot reach tier A | 04 |
| R6 | Clips must make sense standalone; otherwise fixed or rejected | 04 |
| R7 | Long stories split into Part 1/2/3 at cliffhangers | 04 |
| R8 | Fluid cuts: dead air and filler removed, audio crossfaded, no pops | 05 |
| R9 | Crisp output: 1080x1920, no blurry upscales, high bitrate | 05 |
| R10 | Layouts: talking head, gameplay stack, facecam + gameplay | 05 |
| R11 | Animated word-by-word captions in the safe zone | 05 |
| R12 | AI director: zoom punches, hook card, arrows/highlights on the right target, emoji, progress bar, part label, SFX | 06 |
| R13 | Arrows point at the correct thing (located by vision, verified, droppable) | 06 |
| R14 | Generated thumbnail referencing the clip topic, never a video frame | 07 |
| R15 | 3 title options, description, hashtags, tags/SEO keywords | 07 |
| R16 | Mandatory credit block | 07, 10 |
| R17 | Fair-use risk flags per clip | 10 |
| R18 | Review screen: preview, tier, edit text, approve/reject, copy buttons, download | 08 |
| R19 | Output folder per clip with everything needed to upload | 02, 07 |
| R20 | Handles 8-hour livestream VODs without filling the disk | 03 |
| R21 | Gemini free-tier rate limits, caching, retries | 02 |
| R22 | Windows power, GPU memory and disk-space safety | 01 |
| R23 | Results log (views per posted clip) feeding score calibration | 09 |
| R24 | Tests and measurable acceptance gates per milestone | 09 |
| R25 | Fast lane for release-week speed | 04, 09 |
| R26 | GTA 6 domain vocabulary and scoring boosts | 04 |
| R27 | Profanity masking in captions | 05 |
| R28 | Quality at least equal to Klap's feature set (parity list below) | 05, 06 |

**Klap parity list (must all exist by M4):** AI clip finding, per-clip virality score, auto reframe with face tracking, animated captions with emphasis colouring, hook text, title/description generation, filler-word removal, multiple clips per video, preview + download. **Beyond Klap:** replay-heatmap signal, Part splitting, vision-located arrows, generated thumbnails, credit blocks, risk flags, results-based calibration.

---

## 3. Environment facts (summary; details in 01)

- OS: Windows 11. Shell: PowerShell. Use `pathlib` and list-form `subprocess`, never `shell=True`.
- Python 3.12 (3.11 acceptable). Never 3.13 (MediaPipe wheels).
- ffmpeg: full build with NVENC (`winget install Gyan.FFmpeg`).
- GPU: Whisper on CUDA float16; ffmpeg NVENC encoding; nothing else needs the GPU except optional local SDXL.
- One heavy job at a time. One worker thread.
- Gemini via `google-genai`. Model names come from `.env`; never hard-code them (section 4, rule 6).

---

## 4. Operating protocol: how you avoid guessing

These rules are mandatory.

1. **Specified means follow exactly.** If a reference file gives a number, name, path, schema, prompt, formula or default, use it verbatim.
2. **Unspecified means decide minimally and record.** If something truly is not specified: pick the simplest option consistent with the spec, implement it, and append an entry to `docs/DECISIONS.md` (`date, milestone, question, choice, reason`). Do not ask the user unless the item is in section 11.
3. **Never invent an API.** Before using any third-party function (yt-dlp options, google-genai calls, MediaPipe Tasks, faster-whisper arguments, OpenCV trackers, Pillow font features), verify against the installed package: `python -c "import x; help(x.y)"`, `pip show`, `--help`, or the package docs. Library versions move. If reality differs from a reference file, trust reality, make it work, and log the difference in `docs/DECISIONS.md`.
4. **Never change a data contract silently.** Schemas in `02` are the contract between stages. If one must change, update `docs/spec-changes.md`, the Pydantic model, the validators and every consumer in the same change.
5. **No placeholder code.** No `TODO: implement`, no stubs that return fake data, except where a milestone explicitly says "stub in this milestone". Fake data must never reach a real job.
6. **No hard-coded model names, URLs of third-party endpoints, API keys or absolute paths.** Everything from `config/settings.py`, `.env` or `paths.py`.
7. **Fail loudly, recover gracefully.** Every external call has a timeout, a retry policy (where listed) and a typed error from `app/core/errors.py`. A failed clip must not fail the job. A failed job must show a human-readable reason in the UI.
8. **Test before claiming done.** A task is done only when its gate checks in section 5 pass and you have shown the command output.
9. **Small verified steps.** Implement one module, test it, then continue. Do not write 30 files and run nothing.
10. **Keep the user informed in plain language.** After each milestone: what works, what you ran, what failed, what you decided, what is next.

---

## 5. Milestones and gates

Do them in order. Do not start the next until the gate passes and the user agrees.

### M0: Scaffold and environment
- Create the full folder tree from `02` (empty modules allowed ONLY here).
- Implement `config/settings.py`, `.env.example`, `paths.py`, `db.py`, `models.py`, `schemas.py` (all Pydantic models from `02`), `errors.py`, `logging_setup.py`, `scripts/check_env.py`, `start.bat`, FastAPI skeleton with `/api/health` and `/api/system/check`, and a static `web/index.html` that loads.
- **Gate:** `python scripts/check_env.py` prints a PASS/FAIL table; `start.bat` opens the page; `pytest` runs (even with 0 real tests, config valid); `ruff check` clean.

### M1: Ingest, selection and plan (no video clips yet)
- Read `03` and `04`.
- Implement stages `source_check`, `audio_download`, `transcribe`, `tidy`, `nominate`, `refine`, `judge`, signals, `blend`, `planner`, `part_splitter`, `risk`.
- UI: paste box, fair-use acknowledgement, options, live progress, and a plan table (start-end, tier, score, hook text, risk).
- **Gate:** on a 10-20 min Creative Commons or user-owned video, the job completes; `plan.json` validates; at least one clip is nominated; every clip has start < end, 15 <= duration <= 90, a tier and a risk flag; killing the server mid-transcription and restarting resumes without re-downloading; all unit tests in `09` for M1 pass.

### M2: Build clips
- Read `05`.
- Implement section downloads, cutting, filler/dead-air removal, layout detection and rendering, captions (ASS + SRT), audio clean-up, final render.
- UI: clip cards with video preview.
- **Gate:** each planned clip produces `clip.mp4` at 1080x1920, H.264/AAC, loudness -14 LUFS (±1), captions inside the safe zone, no audio pops (verified by the check in `09`), no letterbox black bars, video duration within 0.15 s of audio duration. 30-minute source completes end-to-end in under 15 minutes on the target laptop.

### M3: AI director and effects
- Read `06`.
- Implement edit-list schema, director prompt, validator, deterministic fallback director, target locator, tracker, compositor and all effects.
- **Gate:** effect density rules hold on 10 sample clips; arrows land inside the target bbox on a labelled test set (>= 70% hit); with Gemini disabled the fallback director still produces a good clip; compositor renders a 45 s clip in under 3 minutes.

### M4: Packaging, thumbnails, feedback loop
- Read `07` and `10`.
- Implement metadata, credit block, thumbnail concept/generation/composition, package writer, zip export, results logging, calibration script.
- **Gate:** every packaged clip folder passes the checklist in `07` section 9; thumbnails exist in both sizes and contain no video frame (verified: perceptual hash differs from every sampled source frame by > threshold, see `09`); credit block present and links valid.

### M5: Review editor, polish, performance
- Read `08` (editor parts) and `09`.
- Trim handles, title/description editing, re-render, optional "second look", fast lane, cleanup tools, performance pass.
- **Gate:** all acceptance numbers in `09` met on the reference test set; README complete.

---

## 6. Coding standards (apply everywhere)

- Python 3.12, full type hints, `from __future__ import annotations`.
- Pydantic v2 for every JSON artifact and API body.
- `pathlib.Path` for all paths. Open text files with `encoding="utf-8"`.
- `logging` only (no `print` except scripts' user-facing tables). Log file `data/logs/app.log`, rotating 5 x 5 MB.
- Functions < 60 lines where reasonable; no module-level mutable state; dependency injection for the Gemini client and paths so tests can fake them.
- Time is **seconds as float**, rounded to 3 decimals when stored.
- Subprocess: list args, `check=False` then inspect return code, capture stderr, timeout always, `creationflags=subprocess.CREATE_NO_WINDOW` on Windows.
- Ruff for lint and format; pytest for tests; `httpx` + FastAPI `TestClient` for API tests.
- Write short docstrings stating inputs, outputs and failure modes.
- No global `sys.path` hacks. The package root is the workspace root; run with `python -m`.
- Never print or log API keys.

---

## 7. Fair use and safety (summary; full rules in 10)

- The user decides fair use. The app only informs: risk flags, credit block, commentary-ratio check, duration limits.
- Clips with almost no spoken commentary (just game footage) are high risk and cannot be tier A.
- Disclaimers do not create rights; never write "no copyright infringement intended" or "fair use" as a claim in descriptions. Write the factual credit and rights-ownership lines from `07`.
- Blocklisted channels (`config/source_policy.yaml`) are refused. Allowlisted channels are marked low risk.
- Never generate real people's likenesses, official logos or official key art in thumbnails.
- Only transcripts and a few still frames (arrow targets) are sent to Gemini. Say so in the README.

---

## 8. Reference index: what to read when

| File | Read before |
|---|---|
| `references/01-environment-and-setup.md` | M0, any install or environment issue |
| `references/02-architecture-and-data-contracts.md` | everything |
| `references/03-stage1-ingest.md` | M1 ingest, transcription, long VODs |
| `references/04-stage2-selection.md` | M1 selection, scoring, planning, parts |
| `references/05-stage3-build.md` | M2 |
| `references/06-stage4-director-effects.md` | M3 |
| `references/07-stage5-packaging-thumbnails.md` | M4 |
| `references/08-web-ui.md` | M1 UI, M2 UI, M5 editor |
| `references/09-quality-testing-evaluation.md` | every gate |
| `references/10-fair-use-credit-policy.md` | M1 risk, M4 credit, any legal question |

---

## 9. Documentation duties

Maintain in the project: `docs/PROGRESS.md` (milestone checkboxes + dates), `docs/DECISIONS.md`, `docs/spec-changes.md`, `README.md` (install, run, troubleshoot, privacy note). Update them in the same change as the code.

---

## 10. Quick triage table

| Symptom | First action |
|---|---|
| yt-dlp download or extraction error | `python scripts/update_ytdlp.py`; if it mentions a JavaScript runtime, install Deno (01 section 5) |
| Whisper CUDA / cuDNN DLL error | 01 section 4; fall back to `int8` on CPU with the `small` model and warn in UI |
| Gemini 429 | back off per 02 section 8; never loop without delay |
| ffmpeg `subtitles` filter fails on Windows | use relative paths with `cwd` (05 section 9) |
| Out of VRAM | unload Whisper after transcription; NVENC needs only a little |
| Disk low | abort job before download with the message in 01 section 8 |

---

## 11. When you MUST ask the user

Only these: the Gemini API key; confirming the Windows version if `check_env` cannot tell; approving a milestone; choosing between two options that `DECISIONS.md` marks "needs user"; anything destructive (deleting `output/`); and any legal judgement about a specific source. For everything else, decide per section 4 and move on.
