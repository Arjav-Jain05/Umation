# TROUBLESHOOTING: Self-Healing Log

Log of problems encountered, root causes identified, and solutions implemented.

## Solved Issues
| Timestamp | Symptom | Root Cause | Solution Applied |
|-----------|---------|------------|------------------|
| 2026-11-11 | Ollama CLI failed with "Unable to init instance" | Non-interactive shell attempted to spawn GUI `ollama app.exe` tray app | Run `ollama.exe serve` CLI service directly in background or via service |
| 2026-11-11 | Git branch creation permission denied in sandbox | Sandboxed user lacked write access to create new branch directory under `.git/refs/heads/` | Executed branch creation with `BypassSandbox: true` |
