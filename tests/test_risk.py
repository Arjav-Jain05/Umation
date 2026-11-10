"""Unit tests for Stage 2 fair-use risk assessment and Tier A capping."""

from pathlib import Path

from app.core.schemas import (
    JudgedItem,
    JudgedScores,
    Sentence,
    Signals,
    SourceInfo,
    SourcePolicyMatch,
    Transcript,
)
from app.pipeline.s2_select.planner import plan_clips
from app.pipeline.s2_select.risk import assess


def _base_source_info(is_cc: bool = True, allowlisted: bool = False) -> SourceInfo:
    info = SourceInfo.model_validate_json(
        Path("tests/fixtures/source_info_cc.json").read_text(encoding="utf-8")
    )
    if not is_cc:
        info.license = "Standard YouTube License"
    if allowlisted:
        info.source_policy = SourcePolicyMatch(status="allow", matched_rule="Trusted creator")
    else:
        info.source_policy = SourcePolicyMatch(status="none")
    return info


def test_risk_commentary_levels():
    """Verify speech ratio thresholds: < 0.35 is high risk, < 0.50 is medium risk."""
    source_info = _base_source_info(is_cc=True)

    # Low commentary: 0.40 -> medium risk, flag 'low_commentary'
    level, flags = assess(duration_s=40.0, speech_ratio=0.40, source_info=source_info)
    assert level == "medium"
    assert "low_commentary" in flags

    # No commentary: 0.20 -> high risk, flag 'no_commentary'
    level_high, flags_high = assess(duration_s=40.0, speech_ratio=0.20, source_info=source_info)
    assert level_high == "high"
    assert "no_commentary" in flags_high


def test_risk_license_and_duration():
    """Verify non-CC source and duration > 75s add medium risk flags."""
    source_non_cc = _base_source_info(is_cc=False, allowlisted=False)

    level, flags = assess(duration_s=40.0, speech_ratio=0.80, source_info=source_non_cc)
    assert level == "medium"
    assert "non_cc_source" in flags

    # CC source but long clip (> 75s)
    source_cc = _base_source_info(is_cc=True)
    level_long, flags_long = assess(duration_s=80.0, speech_ratio=0.80, source_info=source_cc)
    assert level_long == "medium"
    assert "long_clip" in flags_long


def test_risk_allowlisted_discount():
    """Verify allowlisted source reduces risk rank (medium becomes low)."""
    # Non-CC would be medium, but allowlisted drops it to low
    source_allow = _base_source_info(is_cc=False, allowlisted=True)
    level, flags = assess(duration_s=40.0, speech_ratio=0.80, source_info=source_allow)
    assert level == "low"
    assert "allowlisted" in flags


def test_risk_high_risk_cannot_be_tier_a():
    """Verify a clip with high risk (e.g. no commentary) is capped at 79.0 and cannot be Tier A."""
    source_info = _base_source_info(is_cc=True)
    sentences = [
        Sentence(id=0, s=0.0, e=29.0, text="Action scene without commentary", w0=0, w1=3, wpm=100.0)
    ]
    transcript = Transcript(language="en", model="test", duration_s=100.0, sentences=sentences, words=[])

    item = JudgedItem(
        cid="n01",
        s=0.0,
        e=29.0,
        start_sid=0,
        end_sid=0,
        hook_text="Action",
        scores=JudgedScores(hook=9.5, payoff=9.5),
        llm_score=95.0,
    )
    # Speech ratio 0.20 triggers no_commentary -> high risk
    sig_map = {"n01": Signals(cid="n01", heat=95.0, audio=95.0, speech_ratio=0.20)}

    scoring_cfg = {
        "thresholds": {"min_final": 60, "tier_a": 80, "tier_b": 70},
        "weights": {"llm": 0.65, "heat": 0.20, "audio": 0.15},
        "penalties": {"low_speech": 0},  # isolate risk cap
        "limits": {"max_clips_soft": 40},
    }

    clips = plan_clips(
        [item], sig_map, {}, source_info, transcript, scoring_cfg, domain="general"
    )

    assert len(clips) == 1
    clip = clips[0]
    assert clip.risk == "high"
    # Even though raw score was 95, high risk capped it to 79.0
    assert clip.final_score <= 79.0
    assert clip.tier == "B"
    assert clip.tier != "A"
