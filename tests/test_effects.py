"""Unit tests for overlay effects (renders onto blank frame, verifies non-identical modification)."""

import numpy as np
import pytest

from app.pipeline.s4_director.effects.base import REGISTRY


@pytest.fixture
def blank_frame() -> np.ndarray:
    """Create a blank black 1080x1920 BGR frame."""
    return np.zeros((1920, 1080, 3), dtype=np.uint8)


def test_zoom_punch_effect(blank_frame: np.ndarray):
    """Verify zoom_punch modifies frame without crashing."""
    # Put a white rectangle in the center of the frame so zoom changes pixels
    blank_frame[800:1000, 400:600] = 255
    orig = blank_frame.copy()

    eff = REGISTRY["zoom_punch"]
    out = eff.render(
        frame=blank_frame,
        t_local=0.5,
        dur=1.0,
        params={"scale": 1.15, "anchor": "center"},
        canvas_w=1080,
        canvas_h=1920,
    )
    assert out.shape == (1920, 1080, 3)
    assert not np.array_equal(out, orig)


def test_hook_card_effect(blank_frame: np.ndarray):
    """Verify hook_card renders text card onto frame."""
    orig = blank_frame.copy()
    eff = REGISTRY["hook_card"]
    out = eff.render(
        frame=blank_frame,
        t_local=1.0,
        dur=2.4,
        params={"text": "INSANE GTA 6 LEAK"},
        canvas_w=1080,
        canvas_h=1920,
    )
    assert out.shape == (1920, 1080, 3)
    assert not np.array_equal(out, orig)
    # Check pixels around y=380 are modified
    assert np.any(out[350:450, 400:680] > 0)


def test_arrow_effect(blank_frame: np.ndarray):
    """Verify arrow sprite renders pointing to bbox."""
    orig = blank_frame.copy()
    eff = REGISTRY["arrow"]
    out = eff.render(
        frame=blank_frame,
        t_local=0.8,
        dur=2.0,
        params={"bbox": [400, 700, 680, 980]},
        canvas_w=1080,
        canvas_h=1920,
    )
    assert out.shape == (1920, 1080, 3)
    assert not np.array_equal(out, orig)


def test_highlight_box_effect(blank_frame: np.ndarray):
    """Verify highlight_box draws pulsing yellow rounded rectangle."""
    orig = blank_frame.copy()
    eff = REGISTRY["highlight_box"]
    out = eff.render(
        frame=blank_frame,
        t_local=0.5,
        dur=1.5,
        params={"bbox": [300, 600, 700, 1000]},
        canvas_w=1080,
        canvas_h=1920,
    )
    assert out.shape == (1920, 1080, 3)
    assert not np.array_equal(out, orig)
    # Check yellow color (BGR: 0, 212, 255) appears
    assert np.any(out[:, :, 0] == 0) and np.any(out[:, :, 1] > 180) and np.any(out[:, :, 2] > 200)


def test_emoji_pop_effect(blank_frame: np.ndarray):
    """Verify emoji_pop renders emoji."""
    orig = blank_frame.copy()
    eff = REGISTRY["emoji_pop"]
    out = eff.render(
        frame=blank_frame,
        t_local=0.5,
        dur=1.0,
        params={"emoji": "🔥", "x": 820, "y": 700},
        canvas_w=1080,
        canvas_h=1920,
    )
    assert out.shape == (1920, 1080, 3)
    assert not np.array_equal(out, orig)


def test_part_label_effect(blank_frame: np.ndarray):
    """Verify part_label draws yellow chip at top-left."""
    orig = blank_frame.copy()
    eff = REGISTRY["part_label"]
    out = eff.render(
        frame=blank_frame,
        t_local=0.5,
        dur=10.0,
        params={"text": "PART 1/3"},
        canvas_w=1080,
        canvas_h=1920,
    )
    assert out.shape == (1920, 1080, 3)
    assert not np.array_equal(out, orig)
    # Check chip position at x=60, y=240
    assert np.any(out[240:304, 60:200, 1] > 200)  # Yellow green channel


def test_recap_line_effect(blank_frame: np.ndarray):
    """Verify recap_line renders text."""
    orig = blank_frame.copy()
    eff = REGISTRY["recap_line"]
    out = eff.render(
        frame=blank_frame,
        t_local=0.5,
        dur=2.0,
        params={"text": "Previously: The secret heist"},
        canvas_w=1080,
        canvas_h=1920,
    )
    assert out.shape == (1920, 1080, 3)
    assert not np.array_equal(out, orig)


def test_progress_bar_effect(blank_frame: np.ndarray):
    """Verify progress_bar renders full width track with yellow fill at y=204."""
    orig = blank_frame.copy()
    eff = REGISTRY["progress_bar"]
    # 50% through duration: fill should extend to x=540
    out = eff.render(
        frame=blank_frame,
        t_local=5.0,
        dur=10.0,
        params={},
        canvas_w=1080,
        canvas_h=1920,
    )
    assert out.shape == (1920, 1080, 3)
    assert not np.array_equal(out, orig)
    # Check y=204: x=100 has yellow fill (BGR: 0, 212, 255)
    assert out[206, 100, 0] == 0
    assert out[206, 100, 1] == 212
    assert out[206, 100, 2] == 255
    # Check x=800 has track white overlay
    assert out[206, 800, 0] > 0
