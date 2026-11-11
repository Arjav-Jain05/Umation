# Reference Projects

Analysis of referenced projects for architectural ideas, techniques, and license compliance.

| Project | License | Architectural Concept Borrowed | Code Copied? | Notes |
|---------|---------|--------------------------------|--------------|-------|
| `JayWebtech/autoshorts` | MIT | 7 caption style presets (modern box, yellow outline, minimal shadow, cyan, yellow box, green, red/gaming), responsive font scaling, absolute PTS alignment | No (clean reimplementation) | Key insight: prevent seek offset caption drift with absolute PTS. |
| `ColinGPT9/clips-studio` | AGPL-3.0 | Signal normalization within video, event timeline in LLM prompt, head-to-head rerank, 0-100 score without hard clip count | **NO (AGPL - ideas only)** | Small LLM pairwise rerank is far more robust than absolute scoring. |
| `JeremySNR/clip-forge` | MIT | Hook-build-payoff micro story structure, ending review, auto punch-in zooms, LR-ASD active-speaker ONNX | No | Useful for boundary review and smart zooms. |
| `mutonby/openshorts` | MIT | Auditable score breakdowns, face tracking | No | Basis for transparency in fusion score. |
