"""Unit tests for Stage 2 planner (thresholding, tiers, deduplication, soft cap, zero-clip result, ID assignment)."""

from pathlib import Path

from app.core.schemas import (
    JudgedItem,
    JudgedScores,
    Sentence,
    Signals,
    SourceInfo,
    Transcript,
)
from app.pipeline.s2_select.planner import plan_clips

DEFAULT_SCORING = {
    "thresholds": {"min_final": 60, "tier_a": 80, "tier_b": 70},
    "weights": {"llm": 0.65, "heat": 0.20, "audio": 0.15},
    "penalties": {
        "no_context": 15,
        "fixable_context": 4,
        "low_speech": 20,
        "long_clip": 5,
        "weak_hook_cap": 69,
    },
    "limits": {"max_clips_soft": 40},
}


VOCAB = [
    "apple", "banana", "cherry", "date", "elderberry", "fig", "grape", "honeydew",
    "iguana", "jaguar", "kangaroo", "leopard", "monkey", "newt", "ocelot", "penguin",
    "quail", "rabbit", "snake", "tiger", "urchin", "vulture", "walrus", "yak",
    "zebra", "airplane", "bicycle", "car", "dirigible", "engine", "ferry", "glider",
    "helicopter", "icebreaker", "jet", "kayak", "lorry", "motorcycle", "oceanliner",
    "parachute", "rocket", "submarine", "train", "unicycle", "van", "wagon",
    "yacht", "zeppelin", "acoustic", "bass", "cello", "drum", "flute", "guitar",
    "harp", "keyboard", "lute", "mandolin", "trumpet", "violin", "xylophone", "zither",
]


def _make_dummy_transcript() -> Transcript:
    sentences = []
    for i in range(100):
        # Pick 3 words from vocab
        words = [VOCAB[(i * 3 + k) % len(VOCAB)] for k in range(3)]
        text = " ".join(words)
        sentences.append(
            Sentence(id=i, s=float(i * 10), e=float(i * 10 + 9), text=text, w0=i * 3, w1=i * 3 + 2, wpm=100.0)
        )
    return Transcript(language="en", model="test", duration_s=1000.0, sentences=sentences, words=[])


def _make_source_info() -> SourceInfo:
    return SourceInfo.model_validate_json(
        Path("tests/fixtures/source_info_cc.json").read_text(encoding="utf-8")
    )


def test_planner_threshold_and_tiers():
    """Verify clips below min_final are dropped, and tiers A, B, C are assigned accurately."""
    transcript = _make_dummy_transcript()
    source_info = _make_source_info()

    # Cand 1: final = 85 -> Tier A
    # Cand 2: final = 75 -> Tier B
    # Cand 3: final = 65 -> Tier C
    # Cand 4: final = 50 -> Dropped (< 60)
    items = [
        JudgedItem(
            cid="n01", s=0.0, e=30.0, start_sid=0, end_sid=2, hook_text="A",
            scores=JudgedScores(hook=9.0, payoff=9.0), llm_score=85.0,
        ),
        JudgedItem(
            cid="n02", s=50.0, e=80.0, start_sid=5, end_sid=7, hook_text="B",
            scores=JudgedScores(hook=8.0, payoff=8.0), llm_score=75.0,
        ),
        JudgedItem(
            cid="n03", s=100.0, e=130.0, start_sid=10, end_sid=12, hook_text="C",
            scores=JudgedScores(hook=7.0, payoff=7.0), llm_score=65.0,
        ),
        JudgedItem(
            cid="n04", s=150.0, e=180.0, start_sid=15, end_sid=17, hook_text="D",
            scores=JudgedScores(hook=5.0, payoff=5.0), llm_score=50.0,
        ),
    ]

    sig_map = {
        "n01": Signals(cid="n01", heat=85.0, audio=85.0, speech_ratio=0.8),
        "n02": Signals(cid="n02", heat=75.0, audio=75.0, speech_ratio=0.8),
        "n03": Signals(cid="n03", heat=65.0, audio=65.0, speech_ratio=0.8),
        "n04": Signals(cid="n04", heat=50.0, audio=50.0, speech_ratio=0.8),
    }

    clips = plan_clips(
        items, sig_map, {}, source_info, transcript, DEFAULT_SCORING, domain="general"
    )

    assert len(clips) == 3
    assert clips[0].id == "c01"
    assert clips[0].tier == "A"
    assert clips[1].id == "c02"
    assert clips[1].tier == "B"
    assert clips[2].id == "c03"
    assert clips[2].tier == "C"


def test_planner_overlap_and_text_deduplication():
    """Verify overlapping clips (> 30% overlap) and similar text (token_set_ratio >= 85) are deduplicated."""
    transcript = _make_dummy_transcript()
    source_info = _make_source_info()

    # Two heavily overlapping clips: n01 (s=0, e=30, final=90), n02 (s=10, e=35, final=75)
    # n01 should win, n02 dropped
    items = [
        JudgedItem(
            cid="n01", s=0.0, e=30.0, start_sid=0, end_sid=2, hook_text="Higher",
            scores=JudgedScores(hook=9.0), llm_score=90.0,
        ),
        JudgedItem(
            cid="n02", s=10.0, e=35.0, start_sid=1, end_sid=3, hook_text="Lower",
            scores=JudgedScores(hook=8.0), llm_score=75.0,
        ),
    ]

    sig_map = {
        "n01": Signals(cid="n01", heat=90.0, audio=90.0, speech_ratio=0.8),
        "n02": Signals(cid="n02", heat=75.0, audio=75.0, speech_ratio=0.8),
    }

    clips = plan_clips(
        items, sig_map, {}, source_info, transcript, DEFAULT_SCORING, domain="general"
    )

    assert len(clips) == 1
    assert clips[0].final_score == 90.0


def test_planner_soft_cap():
    """Verify soft cap limits output to top 40 clips by final score."""
    transcript = _make_dummy_transcript()
    source_info = _make_source_info()

    items = []
    sig_map = {}
    for i in range(50):
        cid = f"n{i:02d}"
        s = float(i * 15)
        e = s + 14.0
        # Score increases with i: 61.0 to 85.5
        score = 61.0 + (i * 0.5)
        items.append(
            JudgedItem(
                cid=cid, s=s, e=e, start_sid=i, end_sid=i, hook_text=f"Clip {i}",
                scores=JudgedScores(hook=8.0), llm_score=score,
            )
        )
        sig_map[cid] = Signals(cid=cid, heat=score, audio=score, speech_ratio=0.8)

    clips = plan_clips(
        items, sig_map, {}, source_info, transcript, DEFAULT_SCORING, domain="general"
    )

    assert len(clips) == 40
    # Top 40 should have scores from lowest ~63.5 up to 85.5
    assert min(c.final_score for c in clips) >= 63.0


def test_planner_zero_clip_result():
    """Verify when all items fail threshold, planner returns empty list."""
    transcript = _make_dummy_transcript()
    source_info = _make_source_info()

    items = [
        JudgedItem(
            cid="n01", s=0.0, e=30.0, start_sid=0, end_sid=2, hook_text="Low",
            scores=JudgedScores(hook=3.0), llm_score=40.0,
        )
    ]
    sig_map = {"n01": Signals(cid="n01", heat=30.0, audio=30.0, speech_ratio=0.5)}

    clips = plan_clips(
        items, sig_map, {}, source_info, transcript, DEFAULT_SCORING, domain="general"
    )
    assert clips == []


def test_planner_sequential_id_assignment():
    """Verify clips sorted chronologically by start time receive c01, c02, ... IDs."""
    transcript = _make_dummy_transcript()
    source_info = _make_source_info()

    # Items provided out of order
    items = [
        JudgedItem(
            cid="n01", s=200.0, e=230.0, start_sid=20, end_sid=22, hook_text="Later",
            scores=JudgedScores(hook=9.0), llm_score=90.0,
        ),
        JudgedItem(
            cid="n02", s=50.0, e=80.0, start_sid=5, end_sid=7, hook_text="Earlier",
            scores=JudgedScores(hook=8.0), llm_score=85.0,
        ),
    ]

    sig_map = {
        "n01": Signals(cid="n01", heat=90.0, audio=90.0, speech_ratio=0.8),
        "n02": Signals(cid="n02", heat=85.0, audio=85.0, speech_ratio=0.8),
    }

    clips = plan_clips(
        items, sig_map, {}, source_info, transcript, DEFAULT_SCORING, domain="general"
    )

    assert len(clips) == 2
    assert clips[0].start == 50.0
    assert clips[0].id == "c01"
    assert clips[1].start == 200.0
    assert clips[1].id == "c02"
