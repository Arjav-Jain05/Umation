"""Unit tests for Stage 1 tidy_transcript (sentence splitting, filler detection, wpm)."""

from pathlib import Path

from app.core.schemas import Word
from app.pipeline.s1_ingest.tidy_transcript import (
    _compute_wpm,
    build_sentences,
    detect_fillers,
    write_debug_txt,
)


def test_filler_detection():
    """Verify standard hesitation fillers are identified by index."""
    words = [
        Word(i=0, w="Hello", s=0.0, e=0.5, p=0.99),
        Word(i=1, w="um,", s=0.6, e=0.8, p=0.95),
        Word(i=2, w="welcome", s=0.9, e=1.2, p=0.98),
        Word(i=3, w="uh", s=1.3, e=1.5, p=0.90),
        Word(i=4, w="to", s=1.6, e=1.7, p=0.99),
        Word(i=5, w="Vice", s=1.8, e=2.1, p=0.99),
        Word(i=6, w="City.", s=2.2, e=2.6, p=0.99),
    ]
    fillers = detect_fillers(words)
    assert fillers == [1, 3]


def test_wpm_calculation():
    """Verify WPM computation over a duration."""
    # 10 words in 3.0 seconds -> (10 / 3) * 60 = 200.0 wpm
    wpm = _compute_wpm(10, 0.0, 3.0)
    assert wpm == 200.0

    # Near-zero duration uses minimum floor of 0.2s
    wpm_min = _compute_wpm(2, 0.0, 0.05)
    assert wpm_min == 600.0


def test_sentence_splitting_punctuation_and_pause():
    """Verify sentences split on punctuation with next capital and on silence gaps > 0.80s."""
    words = [
        # Sentence 1: Ends with period, next starts capital
        Word(i=0, w="This", s=0.0, e=0.3, p=0.9),
        Word(i=1, w="is", s=0.35, e=0.5, p=0.9),
        Word(i=2, w="first.", s=0.55, e=0.9, p=0.9),
        # Next starts capital, has 3 words so not merged by step 3
        Word(i=3, w="Second", s=1.0, e=1.3, p=0.9),
        Word(i=4, w="part", s=1.35, e=1.6, p=0.9),
        Word(i=5, w="here.", s=1.65, e=1.9, p=0.9),
        # Gap > 0.8s without punctuation: 1.9 to 2.8 is 0.9s gap
        Word(i=6, w="third", s=2.8, e=3.0, p=0.9),
        Word(i=7, w="segment", s=3.05, e=3.3, p=0.9),
        Word(i=8, w="now.", s=3.35, e=3.6, p=0.9),
    ]

    sentences = build_sentences(words)
    assert len(sentences) == 3
    assert sentences[0].text == "This is first."
    assert sentences[1].text == "Second part here."
    assert sentences[2].text == "third segment now."
    assert sentences[0].w0 == 0
    assert sentences[0].w1 == 2
    assert sentences[1].w0 == 3
    assert sentences[1].w1 == 5
    assert sentences[2].w0 == 6
    assert sentences[2].w1 == 8


def test_sentence_splitting_long_sentence():
    """Verify sentences exceeding 30 words are split at a comma or mid-point gap."""
    words = []
    t = 0.0
    for idx in range(40):
        # Insert a comma at index 20
        w_str = f"word{idx}," if idx == 20 else f"word{idx}"
        words.append(Word(i=idx, w=w_str, s=round(t, 2), e=round(t + 0.2, 2), p=0.9))
        t += 0.25

    sentences = build_sentences(words)
    assert len(sentences) >= 2
    for s in sentences:
        assert (s.w1 - s.w0 + 1) <= 30


def test_sentence_merging_short_gap():
    """Verify very short sentences (< 3 words) merge into previous if gap < 0.5s."""
    words = [
        Word(i=0, w="We", s=0.0, e=0.2, p=0.9),
        Word(i=1, w="are", s=0.25, e=0.4, p=0.9),
        Word(i=2, w="ready.", s=0.45, e=0.8, p=0.9),
        # 2 words, gap is 0.9 - 0.8 = 0.1s (< 0.5s)
        Word(i=3, w="Let's", s=0.9, e=1.1, p=0.9),
        Word(i=4, w="go.", s=1.15, e=1.4, p=0.9),
    ]
    sentences = build_sentences(words)
    assert len(sentences) == 1
    assert sentences[0].text == "We are ready. Let's go."


def test_write_debug_txt(tmp_path: Path):
    """Verify formatting of debug transcript file."""
    words = [
        Word(i=0, w="Look", s=0.0, e=0.3, p=0.9),
        Word(i=1, w="there.", s=0.35, e=0.7, p=0.9),
    ]
    sentences = build_sentences(words)
    out_file = tmp_path / "debug" / "transcript.txt"
    write_debug_txt(sentences, out_file)

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "[00:00:00] sid=000 Look there." in content
