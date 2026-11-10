"""Unit tests for Stage 2 part_splitter (multi-part story splitting, child IDs, durations, recaps)."""

from unittest.mock import MagicMock

from app.core.schemas import Clip, Sentence
from app.pipeline.s2_select.part_splitter import PartSplitOut, StoryPartRaw, split_story


def test_part_splitter_valid_multpart():
    """Verify long story is split into sequential child clips with c01p1 IDs and recap lines."""
    # 8 sentences: total 80s (0s to 80s)
    sentences = [
        Sentence(id=i, s=float(i * 10), e=float(i * 10 + 9), text=f"Sentence {i}", w0=i * 4, w1=i * 4 + 3, wpm=100.0)
        for i in range(8)
    ]

    parent_clip = Clip(
        id="c01",
        start=0.0,
        end=79.0,
        duration=79.0,
        tier="A",
        final_score=85.0,
        llm_score=85.0,
        hook_text="Parent Hook",
        topic="Heist",
        risk="low",
        risk_flags=[],
    )

    mock_gemini = MagicMock()
    # 2 parts: part 1 (sids 0-3, 0s to 39s), part 2 (sids 4-7, 40s to 79s)
    mock_gemini.generate_json.return_value = PartSplitOut(
        parts=[
            StoryPartRaw(part_index=1, start_sid=0, end_sid=3, hook_text="Part 1 Hook"),
            StoryPartRaw(part_index=2, start_sid=4, end_sid=7, hook_text="Part 2 Hook", recap_line="Previously on the heist..."),
        ]
    )

    parts = split_story(parent_clip, sentences, mock_gemini, max_parts=3)
    assert len(parts) == 2

    # Part 1 checks
    p1 = parts[0]
    assert p1.id == "c01p1"
    assert p1.parent_id == "c01"
    assert p1.part_index == 1
    assert p1.part_total == 2
    assert p1.start == 0.0
    assert p1.end == 39.0
    assert p1.duration == 39.0
    assert p1.recap_line is None

    # Part 2 checks
    p2 = parts[1]
    assert p2.id == "c01p2"
    assert p2.parent_id == "c01"
    assert p2.part_index == 2
    assert p2.part_total == 2
    assert p2.start == 40.0
    assert p2.end == 79.0
    assert p2.duration == 39.0
    assert p2.recap_line == "Previously on the heist..."


def test_part_splitter_fallback_on_invalid_or_error():
    """Verify invalid boundaries or Gemini exceptions fallback cleanly to returning single parent clip."""
    sentences = [
        Sentence(id=i, s=float(i * 10), e=float(i * 10 + 9), text=f"Sentence {i}", w0=i * 4, w1=i * 4 + 3, wpm=100.0)
        for i in range(8)
    ]

    parent_clip = Clip(
        id="c01",
        start=0.0,
        end=79.0,
        duration=79.0,
        tier="A",
        final_score=85.0,
        llm_score=85.0,
        hook_text="Parent Hook",
        topic="Heist",
        risk="low",
        risk_flags=[],
    )

    mock_gemini = MagicMock()

    # 1. Gemini raises exception
    mock_gemini.generate_json.side_effect = RuntimeError("API failed")
    fallback1 = split_story(parent_clip, sentences, mock_gemini)
    assert len(fallback1) == 1
    assert fallback1[0].id == "c01"

    # 2. Overlapping / invalid boundaries (part 2 starts before part 1 ends)
    mock_gemini.side_effect = None
    mock_gemini.generate_json.return_value = PartSplitOut(
        parts=[
            StoryPartRaw(part_index=1, start_sid=0, end_sid=5),
            StoryPartRaw(part_index=2, start_sid=3, end_sid=7),  # overlaps with sid 3-5
        ]
    )
    fallback2 = split_story(parent_clip, sentences, mock_gemini)
    assert len(fallback2) == 1
    assert fallback2[0].id == "c01"
