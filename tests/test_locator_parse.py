"""Unit tests for Stage 4 target locator parse_box coordinate conversion and rejection rules."""


from app.pipeline.s4_director.target_locator import parse_box


def test_parse_box_valid_conversion():
    """Verify normalized 0-1000 coordinates convert accurately to 1080x1920 pixels."""
    # Centered box: ymin=300 (576px), xmin=300 (324px), ymax=600 (1152px), xmax=600 (648px)
    # Area: (648 - 324) * (1152 - 576) = 324 * 576 = 186,624 px (~9% of total canvas)
    raw = [300, 300, 600, 600]
    loc = parse_box(raw, w=1080, h=1920, confidence=0.85, label="car")

    assert loc is not None
    assert loc.confidence == 0.85
    assert loc.label == "car"
    assert loc.x1 == 324
    assert loc.y1 == 576
    assert loc.x2 == 648
    assert loc.y2 == 1152


def test_parse_box_confidence_floor():
    """Verify confidence < 0.6 is rejected."""
    raw = [300, 300, 600, 600]
    assert parse_box(raw, confidence=0.59) is None
    assert parse_box(raw, confidence=0.60) is not None


def test_parse_box_area_limits():
    """Verify boxes < 1.5% area or > 60% area are rejected."""
    # Tiny box: 10x10 normalized on 1000 -> 10.8 x 19.2 px = 207 px (~0.01% of frame)
    tiny_box = [450, 450, 460, 460]
    assert parse_box(tiny_box, confidence=0.90) is None

    # Massive box: 900x900 normalized -> 81% of frame
    massive_box = [50, 50, 950, 950]
    assert parse_box(massive_box, confidence=0.90) is None


def test_parse_box_safe_zone_rejection():
    """Verify boxes whose center lies outside safe zone are rejected."""
    # Center y at top margin: ymin=20, ymax=60 -> center y ~ 76 px (< 220 safe top)
    top_box = [20, 400, 60, 600]
    assert parse_box(top_box, confidence=0.90) is None

    # Center y at bottom margin: ymin=950, ymax=990 -> center y ~ 1862 px (> 1500 safe bottom)
    bottom_box = [950, 400, 990, 600]
    assert parse_box(bottom_box, confidence=0.90) is None
