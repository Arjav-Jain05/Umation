# CHANGES: Layered Local-Only Pipeline Upgrade

This file documents every decision, modification, default choice, and replaced component during the upgrade to the v4 local-only layered pipeline.

## Initial Setup (Phase 0)
- **Branch**: `feature/final-local-layered` created from master.
- **Spec**: Copied `ANTIGRAVITY_PROMPT_FINAL_v4.md` to `docs/SPEC.md`.
- **Checklist**: Created `docs/CHECKLIST.md` tracking all requirements by phase.
- **Weights directory**: `D:\Open_Source_Weights` confirmed with >170 GB free space.
- **Execution model**: Phased, autonomous loop with automated selftests per phase.
