"""Layer 6 Fusion: Multi-signal viral quality scoring with dynamic weight redistribution.

Implements the specification formula:
quality = w_aud*audience + w_ev*audio_events + w_emo*emotion + w_hype*text_hype +
          w_llm*llm_consensus + w_crit*critic + w_rank*rerank + w_vis*visual +
          w_agree*agreement + w_pers*personal_ranker

Dynamic weight redistribution:
If audience signals or any optional layer is missing (None), its weight is
dynamically redistributed among remaining active signals so active weights sum to 1.0.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("app.pipeline.s2_select.fusion")

DEFAULT_WEIGHTS = {
    "audience": 0.18,
    "audio_events": 0.12,
    "emotion": 0.10,
    "text_hype": 0.05,
    "llm_consensus": 0.12,
    "critic": 0.13,
    "rerank": 0.15,
    "visual": 0.08,
    "agreement": 0.04,
    "personal_ranker": 0.0,
}


def calculate_fusion_score(
    signals_input: dict[str, float | None],
    base_weights: dict[str, float] | None = None,
    penalties: dict[str, float] | None = None,
    topical_hits: int = 0,
    needs_context: bool = False,
    context_fix: bool = False,
    speech_ratio: float = 1.0,
    duration_s: float = 30.0,
    is_story: bool = False,
    hook_score: float = 8.0,
) -> tuple[float, str, dict[str, Any]]:
    """Compute composite viral quality score (0-100), tier, and full audit breakdown.

    Returns:
        (final_score, tier, breakdown_dict)
    """
    weights_spec = dict(DEFAULT_WEIGHTS)
    if base_weights:
        weights_spec.update(base_weights)

    # 1. Identify active signals (non-None)
    active_keys: list[str] = []
    for k, val in signals_input.items():
        if val is not None and k in weights_spec and weights_spec[k] > 0:
            active_keys.append(k)

    if not active_keys:
        # Fallback if no signals provided
        return 50.0, "B", {"error": "no active signals"}

    # 2. Dynamic weight redistribution
    total_active_weight = sum(weights_spec[k] for k in active_keys)
    normalized_weights: dict[str, float] = {}
    for k in active_keys:
        normalized_weights[k] = round(weights_spec[k] / total_active_weight, 4)

    # 3. Weighted sum of active signals
    composite = 0.0
    for k in active_keys:
        val = float(signals_input[k] or 0.0)
        composite += normalized_weights[k] * val

    # 4. Topical boost (up to 5 points)
    if topical_hits > 0:
        composite += min(5.0, 2.5 * topical_hits)

    # 5. Penalties
    pen_cfg = penalties or {
        "no_context": 15.0,
        "fixable_context": 4.0,
        "low_speech": 20.0,
        "long_clip": 5.0,
        "weak_hook_cap": 69.0,
    }

    if needs_context:
        if context_fix:
            composite -= float(pen_cfg.get("fixable_context", 4.0))
        else:
            composite -= float(pen_cfg.get("no_context", 15.0))

    if speech_ratio < 0.35:
        composite -= float(pen_cfg.get("low_speech", 20.0))

    if duration_s > 75.0 and not is_story:
        composite -= float(pen_cfg.get("long_clip", 5.0))

    if hook_score < 5.0:
        cap = float(pen_cfg.get("weak_hook_cap", 69.0))
        composite = min(composite, cap)

    final_score = round(max(0.0, min(100.0, composite)), 1)

    # 6. Tier assignment per spec (S: 85+, A: 70-84, B: 55-69, C: below 55)
    if final_score >= 85.0:
        tier = "S"
    elif final_score >= 70.0:
        tier = "A"
    elif final_score >= 55.0:
        tier = "B"
    else:
        tier = "C"

    # 7. Audit breakdown
    breakdown = {
        "final_score": final_score,
        "tier": tier,
        "raw_signals": {k: signals_input.get(k) for k in weights_spec},
        "active_weights": normalized_weights,
        "topical_hits": topical_hits,
        "penalties_applied": {
            "needs_context": needs_context,
            "context_fix": context_fix,
            "low_speech": speech_ratio < 0.35,
            "long_clip": duration_s > 75.0 and not is_story,
            "weak_hook": hook_score < 5.0,
        },
    }

    return final_score, tier, breakdown
