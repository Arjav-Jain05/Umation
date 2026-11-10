"""Unit tests for Stage 4 edit list schema, snapping, and density rule enforcement."""


from app.pipeline.s4_director.edit_schema import EditEvent, EditList, validate_and_fix


def test_edit_schema_unknown_event_dropped():
    """Verify unknown event types are dropped by validator."""
    events = [
        EditEvent(id="e01", type="unknown_glitch", t=2.0, dur=1.0, params={}),
        EditEvent(id="e02", type="zoom_punch", t=4.0, dur=0.9, params={"scale": 1.12}),
    ]
    edit_list = EditList(clip_id="c01", duration=30.0, events=events)
    fixed, msgs = validate_and_fix(edit_list)

    assert len(fixed.events) == 1
    assert fixed.events[0].id == "e02"
    assert any("unknown_glitch" in m for m in msgs)


def test_edit_schema_word_snapping():
    """Verify zoom_punch and emoji_pop snap to nearest word start within 0.25s."""
    words = [
        {"start": 3.12, "end": 3.45, "word": "hello"},
        {"start": 10.05, "end": 10.40, "word": "world"},
    ]
    events = [
        # 3.20 is within 0.08s of 3.12 -> snaps to 3.12
        EditEvent(id="e01", type="zoom_punch", t=3.20, dur=0.9, params={"scale": 1.12}),
        # 15.00 is > 0.25s from any word -> stays at 15.00
        EditEvent(id="e02", type="emoji_pop", t=15.00, dur=0.9, params={"emoji": "🔥"}),
    ]
    edit_list = EditList(clip_id="c01", duration=30.0, events=events)
    fixed, _msgs = validate_and_fix(edit_list, words=words)

    assert fixed.events[0].t == 3.12
    assert fixed.events[1].t == 15.00


def test_edit_schema_density_and_gap_rules():
    """Verify density rules: min gaps, max counts, and highlight_box requiring arrow."""
    cfg = {
        "max_events_per_second": 0.4,
        "zoom_punch": {"min_gap_s": 4.0, "max_per_clip": 6, "scale": [1.06, 1.18], "dur": [0.6, 1.2]},
        "arrow": {"min_gap_s": 3.0, "max_per_clip": 4, "min_confidence": 0.6, "dur": [1.2, 2.5]},
        "highlight_box": {"only_with_arrow": True},
        "hook_card": {"t_max": 0.3, "dur": [1.8, 2.8], "max_words": 8},
    }

    events = [
        # Two hook cards: duplicate should be dropped
        EditEvent(id="h01", type="hook_card", t=0.0, dur=2.4, params={"text": "FIRST HOOK"}),
        EditEvent(id="h02", type="hook_card", t=0.1, dur=2.4, params={"text": "SECOND HOOK"}),
        # Two zoom punches too close (gap 1.5s < 4.0s) -> second dropped
        EditEvent(id="z01", type="zoom_punch", t=5.0, dur=0.9, params={"scale": 1.12}),
        EditEvent(id="z02", type="zoom_punch", t=6.5, dur=0.9, params={"scale": 1.12}),
        # Arrow with low confidence (< 0.6) -> dropped
        EditEvent(id="a01", type="arrow", t=12.0, dur=1.8, params={"confidence": 0.45}),
        # Arrow with good confidence -> kept
        EditEvent(id="a02", type="arrow", t=16.0, dur=1.8, params={"confidence": 0.85}),
        # Highlight box near a02 (t=16.0) -> kept
        EditEvent(id="hb01", type="highlight_box", t=16.0, dur=1.8, params={}),
        # Highlight box orphaned (t=22.0, no arrow) -> dropped
        EditEvent(id="hb02", type="highlight_box", t=22.0, dur=1.8, params={}),
    ]

    edit_list = EditList(clip_id="c01", duration=30.0, events=events)
    fixed, _msgs = validate_and_fix(edit_list, cfg=cfg)

    types = [e.type for e in fixed.events]
    assert types.count("hook_card") == 1
    assert types.count("zoom_punch") == 1
    assert types.count("arrow") == 1
    assert types.count("highlight_box") == 1


def test_edit_schema_caption_emphasis_cap():
    """Verify caption_emphasis indices are capped at 8."""
    edit_list = EditList(
        clip_id="c01",
        duration=30.0,
        caption_emphasis=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        events=[],
    )
    fixed, _msgs = validate_and_fix(edit_list)
    assert len(fixed.caption_emphasis) == 8
    assert fixed.caption_emphasis == [1, 2, 3, 4, 5, 6, 7, 8]
