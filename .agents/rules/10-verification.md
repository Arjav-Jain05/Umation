---
trigger: always_on
---
# Rule 10: Verify everything. Cross-check. Prove it.

Full protocol: `docs/VERIFICATION-PROTOCOL.md`. This is the always-on summary.

## Three passes before anything is "done"
1. **Build pass**: implement against the spec section named in `docs/FILE-MAP.md`.
2. **Test pass**: tests from `.agents/skills/shorts-engine/references/09-quality-testing-evaluation.md` written and green (`pytest -q`), `ruff check .` clean, types sane.
3. **Reviewer pass**: re-open the spec text cold. For each sentence of the relevant spec section, find the line of code that satisfies it. Write the mapping in `docs/TRACEABILITY.md`. Then try to break it: empty input, huge input, Windows path with spaces and unicode, no GPU, Gemini 429, Gemini invalid JSON, cancel mid-run, restart mid-run.

## Evidence rules
- Evidence is pasted command output, test summary, file listing, or `ffprobe` output. "It should work" is never evidence.
- If you could not verify something, label it **UNVERIFIED** in your report and in `PROGRESS.md`. Do not hide it.
- If you made an assumption, it must be in `docs/DECISIONS.md` with date, question, choice, reason.

## Library and API verification
Before using any third-party call (yt-dlp options, google-genai methods, MediaPipe Tasks, faster-whisper arguments, OpenCV trackers, Pillow fonts, ffmpeg flags): check the installed version's real signature or docs (`python -c "import x; help(x.y)"`, `pip show x`, `ffmpeg -h filter=name`, official docs). If reality differs from the spec, make it work, and log the difference in DECISIONS.md. Never paste code from memory without running it.

## Numbers must be measured
Performance, loudness, sharpness, hit rates: measure with the commands in the spec and paste results. Never estimate.

## Cross-check checklist at every milestone gate
- Every requirement R1..R28 touched by this milestone has a TRACEABILITY row with a test and evidence.
- Every file in `docs/FILE-MAP.md` for this milestone exists, has no TODO/placeholder, and is imported or used somewhere (no dead files).
- `python scripts/check_env.py` run and pasted.
- Fresh-clone test: create a new virtual environment in a temp folder, install `requirements.txt`, run `pytest -q`. Paste result.
- A resume test (kill the server mid-job, restart, job resumes) when the milestone includes the orchestrator.
- README steps still match reality.

## When tests and spec disagree
The spec wins. If the spec looks wrong, do not silently change code: write the proposal in `docs/spec-changes.md`, tell the user, wait.

## Honest reporting
Report failures first. Say what is not working, what you tried, and what you need. Never present partial work as complete.
