# DECISIONS

Every time the spec did not specify something, or reality differed from the spec, add a row. Mark "needs user" if the user must choose.

| Date | Milestone | Question | Choice | Reason | Needs user? |
|---|---|---|---|---|---|
| 2026-11-10 | pre | FILE-MAP adds `prompts/verify_target.md` as a separate prompt file for the arrow-verification pass (06 s7 step 4) | add file | keeps prompts out of code | no |
| 2026-11-10 | Phase 1 | Direct download URL for `Montserrat-ExtraBold.ttf` static build | `https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-ExtraBold.ttf` | Author's official repo static build (Google Fonts repo only houses variable font) | no |
| 2026-11-10 | Phase 1 | Direct download URL for `NotoColorEmoji.ttf` | `https://github.com/google/fonts/raw/main/ofl/notocoloremoji/NotoColorEmoji-Regular.ttf` | Upstream official Google Fonts repository build (noto-emoji repo uses Git LFS which 404s on raw URLs) | no |
| 2026-11-10 | M0 | `Settings.from_env()` dotenv override flag | `load_dotenv(override=False)` | Ensures environment variables set by test fixtures/monkeypatch take precedence over default `.env` | no |
| 2026-11-10 | M0 | `output_clip_dir` part argument signature | `part: tuple[int, int] | None = None` | Conforms to FILE-MAP.md row 48 signature while supporting part index/total | no |
| 2026-11-10 | M0 | `check_port_free` behavior during API request | `in_process: bool = False` | Allows `GET /api/system/check` to report PASS when called from inside the active server process | no |
| 2026-11-10 | M0 | `app/core/models.py` transaction handling | Use SQLite autocommit for single queries and let `transaction()` manage explicit transactions | Avoids `cannot commit - no transaction is active` OperationalError with autocommit mode | no |
| 2026-11-10 | M1 | `tests/test_api_jobs.py` offline execution | Autouse fixture patches `worker.wake` | Prevents background thread from attempting real YouTube metadata fetches during unit testing per 09 s1 offline mandate | no |
| 2026-11-10 | M1 | Synthetic sentence diversity for rapidfuzz testing | Use distinct vocabulary pool across sentences | Ensures `rapidfuzz.token_set_ratio` measures actual textual diversity without false-positive deduplication | no |
| 2026-11-10 | M2 | Subtitle filter path on Windows | Run ffmpeg with `cwd=clip_dir`, copy fonts to local `fonts/`, pass relative `ass=captions.ass:fontsdir=fonts` | Avoids ffmpeg filter graph colon syntax error with Windows drive letters (e.g. `C:`) | no |
| 2026-11-10 | M2 | Background worker lifecycle in automated tests | Autouse fixture patches `Worker.start` and `Worker.stop` in `conftest.py` | Prevents background thread from picking up queued test jobs and executing live yt-dlp/Whisper pipelines during test suite runs | no |
| 2026-11-10 | M3 | Windows Emoji Font Fallback in Pillow | If FreeType COLRv1 table in `NotoColorEmoji.ttf` cannot render colored bitmaps in Windows Pillow wheels, fallback to `C:/Windows/Fonts/seguiemj.ttf` | Windows native Segoe UI Emoji supports full embedded color bitmap rendering via Pillow without external dependencies | no |
