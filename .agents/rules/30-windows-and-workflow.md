---
trigger: always_on
---
# Rule 30: Windows, commands, git and coding workflow

## Environment
Windows 11, PowerShell, Python 3.12 virtual environment at `.venv`. Activate with `.\.venv\Scripts\Activate.ps1` before any Python command. RTX 4060 (8 GB VRAM), 16 GB RAM. On AC power for heavy runs.

## Commands
- Use PowerShell syntax (`;` not `&&` in older PowerShell, `$env:NAME`, backslashes or forward slashes in Python via `pathlib`).
- Python code: `subprocess.run([...list...], capture_output=True, text=True, encoding="utf-8", timeout=..., creationflags=subprocess.CREATE_NO_WINDOW)`. Never `shell=True`. Never build commands by string concatenation with user input (URLs, titles).
- ffmpeg on Windows: the `ass`/`subtitles` filter breaks with absolute paths containing `C:`. Run with `cwd` set to the working folder and use relative filenames; copy fonts to `fonts/` and pass `fontsdir=fonts`.
- Long commands (downloads, transcription, rendering): run in the background, poll every 15-30 s, show progress, set generous timeouts. If a command fails twice with the same error, stop and diagnose.
- Quote paths with spaces. Test with a folder name containing a space and a non-ASCII character once (M2).

## Git
- `git init` in M0; `.gitignore` first (`.env`, `data/`, `output/`, `.venv/`, `__pycache__/`, `*.mp4`, `*.wav`, `*.mkv`, `.pytest_cache/`).
- Commit after every verified unit: `M<n>: <module>: <what changed>`.
- Never commit secrets or media. Tag each passed gate: `git tag m0-pass` etc.

## Coding workflow
- One module at a time; run its tests before the next module.
- Follow `SKILL.md` section 6 coding standards: Python 3.12, type hints, Pydantic v2 for every JSON artifact, `pathlib`, `logging` (no `print` outside scripts), no module-level mutable state, atomic file writes (`*.tmp` then `os.replace`), time in float seconds rounded to 3 decimals.
- All paths via `app/core/paths.py`. All settings via `config/settings.py`. All prompts loaded from `prompts/*.md`. No hard-coded model names, keys, absolute paths.
- Keep functions short, name things as in `docs/FILE-MAP.md`. Do not rename public functions without updating FILE-MAP, tests and callers in the same change.
- No placeholder code. No commented-out code. No dead modules.

## Editing files
- Make small, reviewable edits. After editing, re-read the changed region.
- Never edit files inside `.agents/skills/shorts-engine/` (read-only spec).
- Keep `README.md` truthful: install, run, troubleshooting, privacy note.

## GPU and resources
- Whisper model loads only in the transcribe stage and is released after (`del model; gc.collect()`).
- One heavy job at a time (one worker thread). Check free disk before downloads (`MIN_FREE_GB`).
- Prevent sleep during jobs (`SetThreadExecutionState`).

## Reporting style to the user
Plain language, short paragraphs. Lead with failures and unverified items. Include command outputs as evidence. End with "Next step" and, at milestone gates, the question "Approve M<n> and continue?".
