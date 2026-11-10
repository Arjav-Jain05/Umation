"""Unit tests for Stage 2 score blending (weights, penalties, weak-hook cap, topical boost)."""

from app.core.schemas import JudgedItem, JudgedScores, Signals
from app.pipeline.s2_select.blend import blend

DEFAULT_CFG = {
    "weights": {"llm": 0.65, "heat": 0.20, "audio": 0.15},
    "penalties": {
        "no_context": 15,
        "fixable_context": 4,
        "low_speech": 20,
        "long_clip": 5,
        "weak_hook_cap": 69,
    },
}


def test_blend_standard_weights():
    """Verify standard formula: 0.65*llm + 0.20*heat + 0.15*audio."""
    scores = JudgedScores(hook=8.0, payoff=8.0, clarity=8.0, emotion=8.0, novelty=8.0)
    judged = JudgedItem(
        cid="n01",
        start_sid=0,
        end_sid=5,
        hook_text="Check this out",
        s=0.0,
        e=30.0,
        scores=scores,
        llm_score=80.0,
        needs_context=False,
    )
    # Heat 70, audio 60, speech_ratio 0.8 (healthy), topical_hits 0
    signals = Signals(cid="n01", heat=70.0, audio=60.0, speech_ratio=0.8, topical_hits=0)

    # 0.65*80 + 0.20*70 + 0.15*60 = 52.0 + 14.0 + 9.0 = 75.0
    final = blend(judged, signals, DEFAULT_CFG, domain="general")
    assert final == 75.0


def test_blend_missing_heatmap_renormalization():
    """Verify missing heatmap renormalizes to 0.80*llm + 0.20*audio."""
    scores = JudgedScores(hook=8.0, payoff=8.0, clarity=8.0, emotion=8.0, novelty=8.0)
    judged = JudgedItem(
        cid="n01",
        start_sid=0,
        end_sid=5,
        hook_text="Check this out",
        s=0.0,
        e=30.0,
        scores=scores,
        llm_score=90.0,
        needs_context=False,
    )
    # Missing heat (None), audio 50
    signals = Signals(cid="n01", heat=None, audio=50.0, speech_ratio=0.8, topical_hits=0)

    # 0.80*90 + 0.20*50 = 72.0 + 10.0 = 82.0
    final = blend(judged, signals, DEFAULT_CFG, domain="general")
    assert final == 82.0


def test_blend_topical_boost():
    """Verify GTA 6 domain adds up to 5 points for topical hits."""
    scores = JudgedScores(hook=8.0, payoff=8.0, clarity=8.0, emotion=8.0, novelty=8.0)
    judged = JudgedItem(
        cid="n01",
        start_sid=0,
        end_sid=5,
        hook_text="Check this out",
        s=0.0,
        e=30.0,
        scores=scores,
        llm_score=80.0,
        needs_context=False,
    )
    # 2 topical hits -> 2 * 2.5 = 5.0 boost
    signals = Signals(cid="n01", heat=80.0, audio=80.0, speech_ratio=0.8, topical_hits=2)
    # Base = 80.0, Boost = 5.0 -> 85.0
    final = blend(judged, signals, DEFAULT_CFG, domain="gta6")
    assert final == 85.0


def test_blend_weak_hook_cap():
    """Verify hook score < 5.0 caps final score at 69 (cannot enter Tier A or B)."""
    # High scores everywhere except hook (< 5)
    scores = JudgedScores(hook=4.0, payoff=10.0, clarity=10.0, emotion=10.0, novelty=10.0)
    judged = JudgedItem(
        cid="n01",
        start_sid=0,
        end_sid=5,
        hook_text="Check this out",
        s=0.0,
        e=30.0,
        scores=scores,
        llm_score=95.0,
        needs_context=False,
    )
    signals = Signals(cid="n01", heat=95.0, audio=95.0, speech_ratio=0.8, topical_hits=0)

    # Without cap it would be ~95, but with hook < 5 it must cap at 69.0
    final = blend(judged, signals, DEFAULT_CFG, domain="general")
    assert final == 69.0


def test_blend_penalties():
    """Verify penalties for missing context, low speech, and long non-story clips."""
    scores = JudgedScores(hook=8.0, payoff=8.0, clarity=8.0, emotion=8.0, novelty=8.0)
    judged = JudgedItem(
        cid="n01",
        start_sid=0,
        end_sid=5,
        hook_text="Check this out",
        s=0.0,
        e=80.0,  # > 75s (-5 long clip penalty)
        scores=scores,
        llm_score=80.0,
        needs_context=True,
        context_fix=None,  # unfixable (-15 penalty)
        is_story=False,
    )
    # speech_ratio 0.20 (< 0.35 -> -20 penalty)
    signals = Signals(cid="n01", heat=80.0, audio=80.0, speech_ratio=0.20, topical_hits=0)

    # Base = 80.0. Penalties: -15 (context) -20 (low speech) -5 (long clip) = -40 -> 40.0
    final = blend(judged, signals, DEFAULT_CFG, domain="general")
    assert final == 40.0
