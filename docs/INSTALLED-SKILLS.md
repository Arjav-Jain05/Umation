# INSTALLED-SKILLS

Record every skill considered (installed or rejected). Max 8 external skills installed. Always installed: `shorts-engine` (local, user-provided).

| Name | URL | Commit hash | License | Decision | Why | What I read | Date |
|---|---|---|---|---|---|---|---|
| `shorts-engine` | local | n/a | user's | installed | primary project spec | all (SKILL.md + refs 01-10) | 2026-11-10 |
| `fastapi` | `https://github.com/fastapi/fastapi` | `v0.162.2` | MIT | installed | Official first-party skill for FastAPI APIRouter, dependencies, SSE streaming (`EventSourceResponse`), Pydantic v2 integration, and static frontend serving | SKILL.md and all 7 reference files | 2026-11-10 |
| `ffmpeg` | `https://github.com/n0an/ffmpeg-skill` | `aec7706` | MIT | installed | Vetted recipes for ffmpeg/ffprobe: NVENC acceleration, filter_complex, loudness normalization, subtitles burn-in, audio crossfade, social-media cropping | SKILL.md and all 6 reference files | 2026-11-10 |
| `pytest` | `https://github.com/TerminalSkills/skills` | `4228905` | Apache-2.0 | installed | Python test best practices: fixtures, conftest.py, tmp_path, parametrize, exception assertions, FastAPI TestClient testing | entire SKILL.md | 2026-11-10 |
| `sqlite` | `https://github.com/TerminalSkills/skills` | `4228905` | Apache-2.0 | installed | SQLite in Python: WAL mode pragmas, transactions, parameterization, busy_timeout, row_factory | entire SKILL.md | 2026-11-10 |
| `ruff` | `https://github.com/TerminalSkills/skills` | `4228905` | Apache-2.0 | installed | Python linter/formatter config: pyproject.toml configuration, rule selection, line length 100 | entire SKILL.md | 2026-11-10 |
| `pydantic` | `https://github.com/TerminalSkills/skills` | `4228905` | Apache-2.0 | installed | Pydantic v2: ConfigDict, model_dump/model_dump_json, field_validator, discriminated unions for events/stages | entire SKILL.md | 2026-11-10 |
| `git-commit-pro` | `https://github.com/TerminalSkills/skills` | `4228905` | Apache-2.0 | installed | Conventional Commits analysis and message format matching Rule 30 `M<n>: <module>: <what>` | entire SKILL.md | 2026-11-10 |
| `gemini-api-dev` | `https://github.com/google-gemini/gemini-skills` | `7cfc690` | Apache-2.0 | installed | Official Google Gemini skill: `google-genai` SDK, structured JSON output with Pydantic schemas, streaming, image generation, vision coordinates | entire SKILL.md | 2026-11-10 |
| `browser-use/video-use` | `https://github.com/browser-use/video-use` | n/a | Unknown | rejected | Requires paid ElevenLabs API key, directly violating non-negotiable rule N1 (free only) | repository overview and dependencies | 2026-11-10 |
| `rightnow-ai/openfang` | `https://github.com/RightNow-AI/openfang` | n/a | Apache-2.0 | rejected | Includes automated social-media publishing (WhatsApp, Telegram) which violates non-negotiable rule N4 (no auto-uploading/posting) | clip-hand-skill documentation | 2026-11-10 |
| `GNSubrahmanyam/agentic-skills` | `https://github.com/GNSubrahmanyam/agentic-skills` | n/a | MIT | rejected | Contains over 100 rule files across 40 categories; excessive context bloat that degrades quality (Rule 20) | repository structure and manifest | 2026-11-10 |
| `iamzhihuix/happy-claude-skills` | `https://github.com/iamzhihuix/happy-claude-skills` | n/a | Unknown | rejected | Video processor includes arbitrary execution scripts that shell out without sandboxing; rejected in favor of pure-instruction ffmpeg skill | skill scripts and README | 2026-11-10 |
| `ofershap/fastapi-best-practices` | `https://github.com/ofershap/fastapi-best-practices` | n/a | MIT | rejected | Overlaps with official first-party `fastapi` skill from `tiangolo/fastapi` which is more comprehensive and directly matches installed FastAPI version | repository rules and examples | 2026-11-10 |
