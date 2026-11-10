"""Unit tests for Stage 2 refine_candidate boundary clean-up."""

from app.core.schemas import Candidate, Sentence
from app.pipeline.s2_select.refine import refine_candidate


def test_refine_hook_and_tail_trim():
    """Verify weak filler lead-ins and subscribe wrap-ups are trimmed."""
    sentences = [
        # sid 0: filler lead-in (< 4 words and starts with "so")
        Sentence(id=0, s=10.0, e=11.5, text="So yeah.", w0=0, w1=1, wpm=80.0),
        # sid 1: hook sentence
        Sentence(id=1, s=12.0, e=25.0, text="The secret bunker was finally discovered!", w0=2, w1=7, wpm=120.0),
        # sid 2: payoff sentence
        Sentence(id=2, s=25.5, e=35.0, text="Inside we found the military jet.", w0=8, w1=13, wpm=120.0),
        # sid 3: tail sentence (starts with "subscribe")
        Sentence(id=3, s=35.5, e=38.0, text="Subscribe for more GTA leaks!", w0=14, w1=18, wpm=120.0),
    ]

    cand = Candidate(
        cid="n01",
        chunk_id="ch01",
        start_sid=0,
        end_sid=3,
        hook_sid=1,
        s=10.0,
        e=38.0,
        reason="Secret bunker",
        llm_hint_score=80.0,
    )

    res = refine_candidate(cand, sentences, max_clip_s=60, is_story=False)
    assert res is not None
    refined, is_story = res

    # sid 0 should be trimmed (hook trim), sid 3 trimmed (tail trim)
    assert refined.start_sid == 1
    assert refined.end_sid == 2
    assert not is_story


def test_refine_padding():
    """Verify -0.15s start and +0.35s end padding with boundary constraints."""
    sentences = [
        Sentence(id=0, s=10.0, e=11.9, text="Previous sentence.", w0=0, w1=2, wpm=100.0),
        Sentence(id=1, s=12.0, e=30.0, text="Main clip action happening here.", w0=3, w1=7, wpm=100.0),
        Sentence(id=2, s=30.2, e=40.0, text="Next sentence.", w0=8, w1=10, wpm=100.0),
    ]

    cand = Candidate(
        cid="n01",
        chunk_id="ch01",
        start_sid=1,
        end_sid=1,
        hook_sid=1,
        s=12.0,
        e=30.0,
        reason="Action",
        llm_hint_score=75.0,
    )

    res = refine_candidate(cand, sentences, max_clip_s=60, is_story=False)
    assert res is not None
    refined, _ = res

    # s_padded: 12.0 - 0.15 = 11.85, but bounded by prev_end (11.90) -> 11.90
    assert refined.s == 11.9
    # e_padded: 30.0 + 0.35 = 30.35, but bounded by next_start (30.20) -> 30.20
    assert refined.e == 30.2


def test_refine_length_fit_and_story_split():
    """Verify length-fit trims start up to hook_sid, and marks story when still exceeding max_clip_s."""
    # Sentences totaling 80s: sid 0 (25s), sid 1 hook (30s), sid 2 (25s)
    sentences = [
        Sentence(id=0, s=0.0, e=25.0, text="Long backstory explanation.", w0=0, w1=5, wpm=100.0),
        Sentence(id=1, s=25.5, e=55.0, text="Major plot twist occurs right here!", w0=6, w1=11, wpm=100.0),
        Sentence(id=2, s=55.5, e=80.0, text="Conclusion of the epic scene.", w0=12, w1=16, wpm=100.0),
    ]

    # Candidate spans all 80s, hook_sid is 1. Max clip is 60s.
    cand = Candidate(
        cid="n01",
        chunk_id="ch01",
        start_sid=0,
        end_sid=2,
        hook_sid=1,
        s=0.0,
        e=80.0,
        reason="Epic scene",
        llm_hint_score=90.0,
    )

    # 1. Trimming sid 0 drops 25s, leaving 25.5 to 80.0 (~55s <= 60s)
    res = refine_candidate(cand, sentences, max_clip_s=60, is_story=False)
    assert res is not None
    refined, is_story = res
    assert refined.start_sid == 1
    assert not is_story

    # 2. When hook is sid 0, trimming cannot occur, so story_flag becomes True
    cand_hook_start = Candidate(
        cid="n02",
        chunk_id="ch01",
        start_sid=0,
        end_sid=2,
        hook_sid=0,
        s=0.0,
        e=80.0,
        reason="Epic scene",
        llm_hint_score=90.0,
    )
    res2 = refine_candidate(cand_hook_start, sentences, max_clip_s=60, is_story=False)
    assert res2 is not None
    _refined2, is_story2 = res2
    assert is_story2 is True


def test_refine_min_duration_discard():
    """Verify candidates shorter than 15s that cannot be extended are discarded (return None)."""
    sentences = [
        # 5 seconds duration
        Sentence(id=0, s=10.0, e=15.0, text="Short isolated moment.", w0=0, w1=3, wpm=100.0),
    ]
    cand = Candidate(
        cid="n01",
        chunk_id="ch01",
        start_sid=0,
        end_sid=0,
        hook_sid=0,
        s=10.0,
        e=15.0,
        reason="Short",
        llm_hint_score=70.0,
    )
    res = refine_candidate(cand, sentences, max_clip_s=60, is_story=False)
    assert res is None
