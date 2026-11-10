"""Unit tests for Stage 3 segments planning and segment_for matching."""

from app.core.schemas import Clip
from app.pipeline.s3_build.segments import plan_segments, segment_for


def test_plan_segments_small_video_full_segment():
    """Verify videos <= 40 minutes (2400s) produce a single full-duration segment."""
    clips = [
        Clip(id="c01", start=10.0, end=40.0, duration=30.0, tier="A", final_score=85.0, llm_score=85.0, hook_text="A", topic="T"),
        Clip(id="c02", start=100.0, end=130.0, duration=30.0, tier="B", final_score=75.0, llm_score=75.0, hook_text="B", topic="T"),
    ]
    # 30-minute video (1800s <= 2400s)
    segments = plan_segments(clips, source_duration=1800.0, small_video_min=40)

    assert len(segments) == 1
    assert segments[0].id == "seg01"
    assert segments[0].s == 0.0
    assert segments[0].e == 1800.0
    assert segments[0].clip_ids == ["c01", "c02"]


def test_plan_segments_large_video_merging():
    """Verify long videos (> 40 min) expand clips ±6s and merge gaps < 20s."""
    # 2-hour video (7200s)
    # Clip 1: [100.0, 130.0] -> expanded range [94.0, 136.0]
    # Clip 2: [145.0, 175.0] -> expanded range [139.0, 181.0]
    # Gap between 136.0 and 139.0 is 3.0s (< 20s) -> Merged into [94.0, 181.0]
    # Clip 3: [1000.0, 1030.0] -> expanded range [994.0, 1036.0] -> Separate segment
    clips = [
        Clip(id="c01", start=100.0, end=130.0, duration=30.0, tier="A", final_score=85.0, llm_score=85.0, hook_text="A", topic="T"),
        Clip(id="c02", start=145.0, end=175.0, duration=30.0, tier="A", final_score=80.0, llm_score=80.0, hook_text="B", topic="T"),
        Clip(id="c03", start=1000.0, end=1030.0, duration=30.0, tier="B", final_score=70.0, llm_score=70.0, hook_text="C", topic="T"),
    ]

    segments = plan_segments(clips, source_duration=7200.0, small_video_min=40)

    assert len(segments) == 2
    seg1 = segments[0]
    assert seg1.id == "seg01"
    assert seg1.s == 94.0
    assert seg1.e == 181.0
    assert seg1.clip_ids == ["c01", "c02"]

    seg2 = segments[1]
    assert seg2.id == "seg02"
    assert seg2.s == 994.0
    assert seg2.e == 1036.0
    assert seg2.clip_ids == ["c03"]


def test_segment_for_matching_and_offset():
    """Verify segment_for matches correct segment and computes relative offset."""
    clips = [
        Clip(id="c01", start=100.0, end=130.0, duration=30.0, tier="A", final_score=85.0, llm_score=85.0, hook_text="A", topic="T"),
        Clip(id="c02", start=1000.0, end=1030.0, duration=30.0, tier="B", final_score=70.0, llm_score=70.0, hook_text="C", topic="T"),
    ]
    segments = plan_segments(clips, source_duration=7200.0, small_video_min=40)

    # For clip 1: start=100.0, seg01 start=94.0 -> offset = 6.0s
    seg, offset = segment_for(clips[0], segments)
    assert seg.id == "seg01"
    assert offset == 6.0

    # For clip 2: start=1000.0, seg02 start=994.0 -> offset = 6.0s
    seg2, offset2 = segment_for(clips[1], segments)
    assert seg2.id == "seg02"
    assert offset2 == 6.0
