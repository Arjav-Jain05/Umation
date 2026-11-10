"""Tests for credit block builder (07 s5, 10)."""

from __future__ import annotations

from app.core.schemas import Clip, SourceInfo
from app.pipeline.s5_package.credit import build_credit_block


def make_test_source(**kwargs) -> SourceInfo:
    """Helper to construct valid SourceInfo with required fields."""
    defaults = {
        "video_id": "abc123xyz",
        "url": "https://www.youtube.com/watch?v=abc123xyz",
        "webpage_url": "https://www.youtube.com/watch?v=abc123xyz",
        "title": "GTA 6 Full Map Revealed",
        "channel": "RockstarInsider",
        "channel_url": "https://www.youtube.com/channel/UC123456789",
        "uploader": "RockstarInsider",
        "upload_date": "20260101",
        "duration_s": 1800.0,
        "live_status": "not_live",
        "width": 1920,
        "height": 1080,
        "fps": 60.0,
        "fetched_at": "2026-01-01T00:00:00Z",
    }
    defaults.update(kwargs)
    return SourceInfo(**defaults)


def make_test_clip(**kwargs) -> Clip:
    """Helper to construct valid Clip with required fields."""
    defaults = {
        "id": "c01",
        "idx": 0,
        "start": 10.0,
        "end": 45.0,
        "duration": 35.0,
        "tier": "A",
        "final_score": 85.0,
        "llm_score": 85.0,
        "topic": "Map leak",
        "hook_text": "Look at this island",
    }
    defaults.update(kwargs)
    return Clip(**defaults)


def test_credit_block_fields_and_links():
    source = make_test_source(
        video_id="abc123xyz",
        title="GTA 6 Full Map Revealed",
        uploader="RockstarInsider",
        channel="RockstarInsider",
        channel_id="UC123456789",
    )
    clip = make_test_clip(
        id="c01",
        idx=0,
        start=123.456,
        end=178.912,
        duration=55.456,
        topic="Map leak",
        hook_text="Look at this island",
    )

    credit_yt = build_credit_block(source, clip, short=False)
    assert 'Original video: "GTA 6 Full Map Revealed" by RockstarInsider' in credit_yt
    assert "https://youtu.be/abc123xyz?t=123" in credit_yt
    assert "Clip from 00:02:03 to 00:02:59 of the original." in credit_yt
    assert "All footage and rights belong to the original creator" in credit_yt

    # Short form for Instagram
    credit_ig = build_credit_block(source, clip, short=True)
    assert 'Credit: RockstarInsider - "GTA 6 Full Map Revealed"' in credit_ig
    assert "https://youtu.be/abc123xyz?t=123" in credit_ig


def test_credit_block_never_claims_fair_use():
    """Verify strictly that credit block never asserts fair use or no infringement (N6, N10)."""
    source = make_test_source(
        video_id="test_vid",
        title="Crazy Stunt",
        channel="GamerPro",
    )
    clip = make_test_clip(id="c02", idx=1, start=10.0, end=40.0, duration=30.0)

    for short in (False, True):
        text = build_credit_block(source, clip, short=short).lower()
        assert "fair use" not in text
        assert "no copyright infringement intended" not in text
        assert "infringement" not in text
        assert "fair-use" not in text


def test_credit_missing_channel_fallback():
    source = make_test_source(
        video_id="xyz999",
        title="Mystery Video",
        channel="",
        uploader="",
    )
    clip = make_test_clip(id="c03", idx=0, start=5.0, end=35.0, duration=30.0)

    block = build_credit_block(source, clip, short=False)
    assert "by the original creator" in block
    assert "https://youtu.be/xyz999?t=5" in block
