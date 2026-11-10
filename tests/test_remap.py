"""Unit tests for timecode Remapper on boundaries and cut regions."""

from app.utils.timecode import Remapper


def test_remap_single_interval():
    """Verify remapping within a single interval."""
    # Interval: [10.0, 30.0], duration = 20.0s
    remapper = Remapper([(10.0, 30.0)])
    assert remapper.total_duration == 20.0

    # Before start -> 0.0
    assert remapper.remap(5.0) == 0.0
    assert remapper.remap(10.0) == 0.0

    # Inside interval
    assert remapper.remap(15.0) == 5.0
    assert remapper.remap(25.5) == 15.5
    assert remapper.remap(30.0) == 20.0

    # Beyond end -> total_duration
    assert remapper.remap(35.0) == 20.0


def test_remap_multiple_intervals_and_removed_regions():
    """Verify remapping with cut gaps maps removed regions to the boundary."""
    # Interval 1: [10.0, 20.0] (10s)
    # Gap: [20.0, 25.0] (5s removed)
    # Interval 2: [25.0, 35.0] (10s)
    # Total duration = 20.0s
    intervals = [(10.0, 20.0), (25.0, 35.0)]
    remapper = Remapper(intervals)
    assert remapper.total_duration == 20.0

    # Inside interval 1
    assert remapper.remap(12.0) == 2.0
    assert remapper.remap(20.0) == 10.0

    # Inside removed gap [20.0, 25.0]: must return clip time at gap boundary (10.0)
    assert remapper.remap(21.0) == 10.0
    assert remapper.remap(23.5) == 10.0
    assert remapper.remap(24.9) == 10.0

    # Start of interval 2
    assert remapper.remap(25.0) == 10.0
    # Inside interval 2
    assert remapper.remap(27.0) == 12.0
    assert remapper.remap(35.0) == 20.0

    # Beyond end
    assert remapper.remap(40.0) == 20.0
