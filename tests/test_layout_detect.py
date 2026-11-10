"""Unit tests for Stage 3 layout detection and classification thresholds."""

from app.pipeline.s3_build.face_track import FaceBox, FaceSample
from app.pipeline.s3_build.layout import detect_layout


def _make_samples(faces_per_sample: list[list[FaceBox]]) -> list[FaceSample]:
    return [FaceSample(t=float(idx * 2), faces=f_list) for idx, f_list in enumerate(faces_per_sample)]


def test_layout_detect_no_face_gameplay():
    """Verify samples with no faces or face presence < 40% classify as gameplay."""
    # 10 samples, all empty
    empty_samples = _make_samples([[] for _ in range(10)])
    res = detect_layout(empty_samples)
    assert res.layout == "gameplay"

    # 10 samples, only 3 have faces (30% < 40%)
    sporadic_samples = _make_samples(
        [[FaceBox(x=0.5, y=0.5, w=0.2, h=0.2, confidence=0.8)] if i < 3 else [] for i in range(10)]
    )
    res_sporadic = detect_layout(sporadic_samples)
    assert res_sporadic.layout == "gameplay"


def test_layout_detect_talking_head():
    """Verify large central face (area ratio >= 0.06, center inside [0.2, 0.8]) classifies as talking_head."""
    # Area ratio: 0.3 * 0.3 = 0.09 (>= 0.06), center: (0.5, 0.5)
    samples = _make_samples([
        [FaceBox(x=0.35, y=0.35, w=0.30, h=0.30, confidence=0.9)] for _ in range(12)
    ])
    res = detect_layout(samples)
    assert res.layout == "talking_head"
    assert res.confidence >= 0.90


def test_layout_detect_facecam():
    """Verify small stable corner face (area in [0.004, 0.06), in outer 30% border) classifies as facecam."""
    # Area ratio: 0.15 * 0.15 = 0.0225 (in [0.004, 0.06))
    # Top-right corner: x=0.80, y=0.10, cx = 0.875 (> 0.70)
    samples = _make_samples([
        [FaceBox(x=0.80, y=0.10, w=0.15, h=0.15, confidence=0.85)] for _ in range(12)
    ])
    res = detect_layout(samples)
    assert res.layout == "facecam"
    assert res.cam_rect is not None
    assert len(res.cam_rect) == 4
    rx, _ry, rw, _rh = res.cam_rect
    assert rx >= 0.70
    assert rw > 0.15


def test_layout_detect_override():
    """Verify manual override parameter forces specific layout."""
    samples = _make_samples([
        [FaceBox(x=0.35, y=0.35, w=0.30, h=0.30, confidence=0.9)] for _ in range(12)
    ])
    # Even though samples indicate talking_head, override to gameplay
    res = detect_layout(samples, override="gameplay")
    assert res.layout == "gameplay"
    assert res.confidence == 1.0
