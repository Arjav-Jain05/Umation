"""Unit tests for Stage 3 face-tracking smoothing (dead zone, velocity limits, lost face behavior)."""

from app.pipeline.s3_build.smoothing import smooth_face_trajectory


def test_smoothing_dead_zone():
    """Verify tiny movements (< 0.04 * crop_w) are ignored by the dead zone."""
    crop_w = 0.5625
    _dead_zone = 0.04 * crop_w  # ~0.0225

    # Center starts at 0.50, then tiny jitter +0.01 (< 0.0225)
    targets = [0.50] * 30 + [0.51] * 10
    smoothed = smooth_face_trajectory(targets, fps=30.0, crop_w=crop_w)

    # All frames should remain at 0.50 due to dead zone
    assert smoothed[29] == 0.50
    assert smoothed[35] == 0.50


def test_smoothing_velocity_limit():
    """Verify sudden position jumps are clamped to max velocity of 0.5 * crop_w per second."""
    crop_w = 0.5625
    fps = 30.0
    max_step = (0.5 * crop_w) / fps  # ~0.009375 per frame

    # Sudden jump from 0.40 to 0.70 at frame 5
    targets = [0.40] * 5 + [0.70] * 10
    smoothed = smooth_face_trajectory(targets, fps=fps, crop_w=crop_w)

    # Check step between frame 5 and 6
    step = abs(smoothed[6] - smoothed[5])
    assert step <= (max_step + 0.001)


def test_smoothing_face_lost_hold_and_ease():
    """Verify lost face holds last position for 1.5s then eases to median over 1.0s."""
    crop_w = 0.5625
    fps = 30.0
    # 30 frames (1s) at 0.60, then face lost (None) for 90 frames (3s)
    targets: list[float | None] = [0.60] * 30 + [None] * 90
    smoothed = smooth_face_trajectory(targets, fps=fps, crop_w=crop_w)

    # 1. During first 1.5s (45 frames) after loss (frames 30 to 74), position holds at ~0.60
    assert abs(smoothed[35] - 0.60) < 0.01
    assert abs(smoothed[65] - 0.60) < 0.01

    # 2. After 1.5s hold (at 2.5s = 75 frames after loss -> frame 105), it should have eased towards median (0.60)
    assert abs(smoothed[-1] - 0.60) < 0.02
