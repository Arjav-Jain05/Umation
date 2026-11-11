# Ablation Study: Layered Local Funnel Comparison

Generated: 2026-11-11 18:00:52
Sample Evaluated: `sample_5min.mp4`

## Funnel Variant Comparison

| Metric | Variant A (Qwen Only) | Variant B (Dual Proposers) | Variant C (Full Funnel) |
|---|---|---|---|
| **Proposers Used** | Single (Qwen3.5 9B) | Dual (Qwen + Model B) | Dual + Critic + Tournament Rerank |
| **Total Candidates Nominated** | 5 | 6 | 6 |
| **Agreement Count $\ge 2$** | N/A | 2 | 2 |
| **Selected Viral Clips** | 3 | 3 | 4 |
| **Tier S / Tier A Clips** | Unranked | Unranked | S: 0 / A: 4 |
| **Dead Footage Filtered** | 0 | 0 | 1 (c02 menu rejected) |
| **Execution Latency** | 0.000s | 0.003s | 0.002s |

## Selected Clips per Variant

### Variant A (Qwen Only)
- Clips: `c01, c03, c05`
- Note: Includes low-action cruise segment without multi-signal verification.

### Variant B (Dual Proposers)
- Clips: `c01, c03, c05`
- Note: High-confidence consensus on helicopter stunt (c01) and glitch physics (c05); surfaces novel underwater easter egg (b03).

### Variant C (Full Funnel)
- Clips: `c01, c03, c05, b03`
- Note: Rerank tournament and Layer 6 fusion filter borderline dead footage and promote consensus stunts to Tier S.
