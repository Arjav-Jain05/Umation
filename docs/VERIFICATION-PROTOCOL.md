# VERIFICATION-PROTOCOL

Purpose: nothing is "done" until it is proven. The agent may take as long as needed. This file defines how to prove work at four levels: unit, stage, milestone, project. Always-on summary: `.agents/rules/10-verification.md`.

## 1. Evidence standard

Acceptable evidence: pasted terminal output (tests, commands), file listings with sizes, `ffprobe` JSON, screenshots described with exact observations, DB rows, log lines with timestamps.
Not acceptable: "should work", "looks right", reading your own code and agreeing with it.
Label anything not proven as **UNVERIFIED** and say what is needed to verify it.

## 2. Unit level (every function/module)

1. State acceptance criteria copied from the spec sentence(s).
2. Tests: happy path, boundary values, invalid input, failure mode. Names per `references/09` section 3.
3. `pytest -q path/to/test_file.py` green, then full `pytest -q` green.
4. `ruff check .` clean.
5. Docstring present (inputs, outputs, failure modes).
6. Library calls verified against the installed version (paste `help()` excerpt or `--help` line in your notes when a call is non-obvious).

## 3. Stage level (each pipeline stage)

1. Run the stage on fixtures (synthetic) and on one real short public video (Creative Commons or user-owned).
2. Validate the artifact with its Pydantic model (`read_artifact`). Paste a short excerpt.
3. Resume test: delete only that stage's artifact, rerun, confirm only that stage reruns; corrupt the artifact (truncate), confirm it is recomputed, not crashed.
4. Cancel test: cancel mid-stage; confirm clean stop and resumable state.
5. Failure injection: fake Gemini 429 then success; fake invalid JSON; no GPU (force CPU fallback); disk-full simulation (set `MIN_FREE_GB` huge) - confirm the specified error text.
6. Timing: measure and compare with the budgets in `references/09` section 5.

## 4. Milestone level (gate)

Run this checklist and paste the output:
1. `git status` clean, last commit message follows the convention, `git tag m<n>-pass`.
2. `python scripts/check_env.py` table.
3. Fresh environment test: new venv in a temp folder, `pip install -r requirements.txt`, `pytest -q`.
4. Every FILE-MAP row for this milestone exists; grep for `TODO|FIXME|pass  # |NotImplemented` returns nothing.
5. Every requirement row touched has evidence in `docs/TRACEABILITY.md`.
6. The milestone gate in `SKILL.md` section 5 is satisfied item by item (each item: command + result).
7. README steps executed literally by a "new user" pass: follow only the README, no prior knowledge; note anything missing.
8. A second-opinion review: re-read the milestone's spec sections and list differences between spec and implementation. If there are none, say so explicitly; if any, fix or log.
Then stop and ask the user to approve.

## 5. Project level (Phase 4 final audit)

1. TRACEABILITY complete: all R1-R28 have file, test and evidence.
2. Smoke test: `python scripts/dev_smoke_test.py <public CC or user-owned video URL>` on a 20-40 minute video; QA table printed; paste it.
3. Long-video test: a 3+ hour public video or a synthetic 3-hour audio/transcript fixture to prove chunking, memory and disk behaviour (no whole-video loads, no disk blow-up).
4. Security review: server binds 127.0.0.1; static serving cannot read outside `output/` (try `/files/output/..%2f..%2f.env`); `open-folder` rejects paths outside `OUTPUT_DIR`; API key never in logs (grep logs); no `shell=True` (grep); URL input injection (a URL containing `&`, quotes, spaces) cannot alter commands.
5. Privacy check: confirm what is sent to Gemini (transcript text, a few frames) matches README.
6. Performance table (measured): transcription speed, selection time, per-clip build time, compositor fps, total for 30 min and 60 min sources.
7. Quality sampling: build 5 real clips and inspect: captions timing and position, layout, audio levels, pops, sharpness, thumbnails not a frame, credit block correct, titles sensible. Describe findings honestly.
8. Report remaining limitations and recommended next improvements.

## 6. Cross-check techniques

- **Spec-to-code mapping:** for each numbered rule in the spec, grep the code for the constant/behaviour and list `rule -> file:line`.
- **Constants audit:** every number in the spec (thresholds, pixel positions, durations) appears in config or code exactly once; no silent differences.
- **Schema round trip:** every artifact model: write, read, compare equal.
- **Idempotence:** running a stage twice yields identical artifacts (except timestamps) when cached Gemini responses are used.
- **Differential check:** compute loudness/duration/resolution independently with `ffprobe` and `ffmpeg ebur128` and compare with the app's own QA report.
- **Mutation sanity:** temporarily break a rule (for example set the safe-zone wrong) and confirm a test fails; revert.
- **Reviewer role-play:** write "How could this break?" with at least three concrete scenarios per module and test them.
- **Fresh-eyes read:** before reporting, re-read the user's original requirement (R-list in SKILL.md section 2) and confirm nothing was dropped.

## 7. Reporting template

```
Milestone/Module: ...
Skills used: ...
What works (evidence): ...
What failed or is unverified: ...
Decisions made (see DECISIONS.md): ...
Spec differences found: ...
Next step: ...
Question for user: ...
```
