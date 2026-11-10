"""Unit tests for Stage 3 cutter (keep-interval calculation, 25% cap, gap rules, filter script)."""

from unittest.mock import patch

from app.core.schemas import Word
from app.pipeline.s3_build.cutter import build_filter_script, compute_keep_intervals


def test_cutter_filler_word_removal():
    """Verify filler words are removed with -0.03s/+0.03s padding."""
    words = [
        Word(i=0, w="Let's", s=10.0, e=10.5, p=0.9),
        Word(i=1, w="um", s=11.0, e=11.4, p=0.9),  # filler to remove: 10.97 to 11.43
        Word(i=2, w="drive", s=12.0, e=12.5, p=0.9),
    ]

    intervals = compute_keep_intervals(
        clip_start=10.0,
        clip_end=15.0,
        words=words,
        fillers=[1],
        hook_end=10.0,
    )

    # Should have 2 intervals: [10.0, 10.97] and [11.43, 15.0]
    assert len(intervals) == 2
    assert intervals[0][0] == 10.0
    assert abs(intervals[0][1] - 10.97) < 0.01
    assert abs(intervals[1][0] - 11.43) < 0.01
    assert intervals[1][1] == 15.0


def test_cutter_quiet_vs_loud_gap():
    """Verify quiet dead-air gaps (> 0.60s, < -35 dBFS) are shortened, while loud gaps are untouched."""
    words = [
        Word(i=0, w="First", s=10.0, e=11.0, p=0.9),
        # Gap 1: 11.0 to 12.0 (1.0s gap) -> Quiet (-50 dBFS) -> middle removed
        Word(i=1, w="Second", s=12.0, e=13.0, p=0.9),
        # Gap 2: 13.0 to 14.5 (1.5s gap) -> Loud (-20 dBFS, game action) -> untouched
        Word(i=2, w="Third", s=14.5, e=15.5, p=0.9),
    ]

    def mock_db(audio_path, s, e):
        if s >= 11.0 and e <= 12.0:
            return -50.0  # Quiet
        return -20.0  # Loud game audio

    with patch("app.pipeline.s3_build.cutter._measure_gap_db", side_effect=mock_db):
        intervals = compute_keep_intervals(
            clip_start=10.0,
            clip_end=16.0,
            words=words,
            fillers=[],
            hook_end=10.0,
        )

    # Gap 1 (11.0 to 12.0) had removal: 11.09 to 11.91 (middle 0.82s removed)
    # Gap 2 (13.0 to 14.5) was kept untouched
    assert len(intervals) == 2
    assert abs(intervals[0][1] - 11.09) < 0.01
    assert abs(intervals[1][0] - 11.91) < 0.01
    assert intervals[1][1] == 16.0


def test_cutter_25_percent_cap():
    """Verify total removed duration never exceeds 25% of clip duration."""
    # Clip duration: 10s -> max removable is 2.5s
    # Create multiple large gaps totaling 5.0s
    words = [
        Word(i=0, w="A", s=0.0, e=1.0, p=0.9),
        Word(i=1, w="B", s=3.0, e=4.0, p=0.9),  # 2.0s gap
        Word(i=2, w="C", s=6.0, e=7.0, p=0.9),  # 2.0s gap
        Word(i=3, w="D", s=9.0, e=10.0, p=0.9),  # 2.0s gap
    ]

    with patch("app.pipeline.s3_build.cutter._measure_gap_db", return_value=-60.0):
        intervals = compute_keep_intervals(
            clip_start=0.0,
            clip_end=10.0,
            words=words,
            fillers=[],
            hook_end=0.0,
            max_removal_pct=0.25,
        )

    total_kept = sum(e - s for s, e in intervals)
    total_removed = 10.0 - total_kept
    assert total_removed <= 2.501  # Within 25% cap


def test_cutter_build_filter_script():
    """Verify filter_complex_script generation with trim, afade, and concat."""
    intervals = [(10.0, 15.0), (16.0, 20.0)]
    seg_start = 5.0  # Segment starts at 5.0s

    script = build_filter_script(intervals, seg_start=seg_start)

    # Relative to seg_start 5.0:
    # Interval 1: 5.0 to 10.0
    # Interval 2: 11.0 to 15.0
    assert "[0:v]trim=start=5.000:end=10.000,setpts=PTS-STARTPTS[v0];" in script
    assert "[0:a]atrim=start=5.000:end=10.000,asetpts=PTS-STARTPTS,afade=" in script
    assert "[0:v]trim=start=11.000:end=15.000,setpts=PTS-STARTPTS[v1];" in script
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" in script
