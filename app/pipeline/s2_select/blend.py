"""Blended viral score calculation combining LLM rubric, heatmap, and audio signals."""

from __future__ import annotations

from typing import Any

from app.core.schemas import JudgedItem, Signals
from app.pipeline.s2_select.fusion import calculate_fusion_score


def blend(
    judged: JudgedItem,
    signals: Signals,
    scoring_cfg: dict[str, Any],
    domain: str = "general",
    heat_coarse_override: bool = False,
) -> float:
    """Calculate composite final viral potential score (0-100) per spec 04 section 7."""
    # Check if rich layered signals from Layer 1 sensors or audience parser are present
    has_layered_signals = (
        getattr(signals, "audience_available", False)
        or getattr(signals, "audio_events_score", 0.0) > 0.0
        or getattr(signals, "emotion_score", 0.0) > 0.0
        or getattr(signals, "text_hype_score", 0.0) > 0.0
    )

    if has_layered_signals:
        aud_val = signals.audience_score if getattr(signals, "audience_available", False) else signals.heat
        signals_input = {
            "audience": aud_val,
            "audio_events": getattr(signals, "audio_events_score", signals.audio),
            "emotion": getattr(signals, "emotion_score", 50.0),
            "text_hype": getattr(signals, "text_hype_score", 50.0),
            "llm_consensus": judged.llm_score,
            "critic": getattr(judged, "critic_score", judged.llm_score),
            "rerank": getattr(judged, "rerank_score", judged.llm_score),
            "visual": getattr(signals, "motion_score", 50.0),
            "agreement": 80.0 if getattr(signals, "hot_zone_overlap", False) else 50.0,
            "personal_ranker": None,
        }
        hook_val = float(getattr(judged.scores, "hook", 8.0))
        final, _, _ = calculate_fusion_score(
            signals_input,
            penalties=scoring_cfg.get("penalties"),
            topical_hits=signals.topical_hits if signals.topical_hits else 0,
            needs_context=judged.needs_context,
            context_fix=bool(judged.context_fix),
            speech_ratio=signals.speech_ratio,
            duration_s=judged.e - judged.s,
            is_story=judged.is_story,
            hook_score=hook_val,
        )
        return final

    # Legacy 3-signal blend
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

    # Topical boost (up to 5 points)
    if getattr(signals, "topical_hits", 0) > 0:
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
