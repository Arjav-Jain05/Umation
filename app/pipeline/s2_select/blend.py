"""Blended viral score calculation combining LLM rubric, heatmap, and audio signals."""

from __future__ import annotations

from typing import Any

from app.core.schemas import JudgedItem, Signals


def blend(
    judged: JudgedItem,
    signals: Signals,
    scoring_cfg: dict[str, Any],
    domain: str = "gta6",
    heat_coarse_override: bool = False,
) -> float:
    """Calculate composite final viral potential score (0-100) per spec 04 section 7."""
    weights = scoring_cfg.get("weights", {"llm": 0.65, "heat": 0.20, "audio": 0.15})
    w_llm = float(weights.get("llm", 0.65))
    w_heat = float(weights.get("heat", 0.20))
    w_audio = float(weights.get("audio", 0.15))

    # Renormalize weights if heatmap is missing or coarse
    if signals.heat is None:
        w_llm = 0.80
        w_audio = 0.20
        w_heat = 0.0
    elif heat_coarse_override:
        w_heat = 0.05
        # Renormalize w_llm and w_audio to sum to 0.95 preserving their ratio
        ratio = w_llm / (w_llm + w_audio + 1e-6)
        w_llm = ratio * 0.95
        w_audio = (1.0 - ratio) * 0.95

    heat_val = signals.heat if signals.heat is not None else 0.0
    final = (w_llm * judged.llm_score) + (w_heat * heat_val) + (w_audio * signals.audio)

    # Topical boost (up to 5 points) for GTA 6
    if domain == "gta6":
        final += min(5.0, 2.5 * signals.topical_hits)

    # Penalties
    penalties = scoring_cfg.get(
        "penalties",
        {
            "no_context": 15,
            "fixable_context": 4,
            "low_speech": 20,
            "long_clip": 5,
            "weak_hook_cap": 69,
        },
    )

    if judged.needs_context:
        if judged.context_fix:
            final -= float(penalties.get("fixable_context", 4))
        else:
            final -= float(penalties.get("no_context", 15))

    if signals.speech_ratio < 0.35:
        final -= float(penalties.get("low_speech", 20))

    duration = judged.e - judged.s
    if duration > 75.0 and not judged.is_story:
        final -= float(penalties.get("long_clip", 5))

    # Weak hook cap: cannot reach Tier A or B
    if judged.scores.hook < 5.0:
        cap = float(penalties.get("weak_hook_cap", 69))
        final = min(final, cap)

    return round(max(0.0, min(100.0, final)), 1)
