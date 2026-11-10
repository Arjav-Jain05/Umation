"""Tests for metadata generation and validation (07 s1-s4)."""

from __future__ import annotations

from app.core.schemas import Clip, SourceInfo
from app.pipeline.s5_package.metadata import (
    RawMetadataOut,
    TitleOption,
    _clean_title,
    fallback_metadata,
    validate_and_fix_metadata,
)


def make_test_source(**kwargs) -> SourceInfo:
    """Helper to construct valid SourceInfo with required fields."""
    defaults = {
        "video_id": "vid_123",
        "url": "https://www.youtube.com/watch?v=vid_123",
        "webpage_url": "https://www.youtube.com/watch?v=vid_123",
        "title": "GTA 6 Leak Analysis",
        "channel": "LeakHunter",
        "channel_url": "https://www.youtube.com/channel/UC123456789",
        "uploader": "LeakHunter",
        "upload_date": "20260101",
        "duration_s": 300.0,
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
        "hook_text": "Look at Vice City",
    }
    defaults.update(kwargs)
    return Clip(**defaults)


def test_clean_title_rules():
    # Length truncation at word boundary <= 70
    long_t = "This is an extremely long title that describes something amazing in the world of grand theft auto six leaks"
    cleaned = _clean_title(long_t, max_chars=70)
    assert len(cleaned) <= 70
    assert not cleaned.endswith(" ")
    assert not cleaned.endswith(".")

    # Excessive punctuation deduplication: at most one ! and at most one ?
    punct_t = "WHAT HAPPENED?!?!?! OMG!!!!!!"
    cleaned_punct = _clean_title(punct_t, max_chars=70)
    assert cleaned_punct.count("!") <= 1
    assert cleaned_punct.count("?") <= 1


def test_validate_and_fix_metadata_success():
    raw = RawMetadataOut(
        titles=[
            TitleOption(style="curiosity", text="Did Rockstar just reveal Vice City?"),
            TitleOption(style="direct", text="New GTA 6 map leak details"),
            TitleOption(style="bold", text="Best GTA 6 leak we have seen"),
        ],
        hook_line="Here is the newest GTA 6 leak explained.",
        context="A brand new leak highlights Vice City locations. It confirms previous rumors.",
        hashtags=["#GTA6", "#GamingNews", "#shorts", "#invalid tag with spaces", "#rockstar"],
        keywords=["gta 6 leak", "vice city map", "rockstar games"],
        instagram_caption="Huge GTA 6 news just dropped! #shorts",
        pinned_comment="Which location are you most excited to explore?",
    )
    source = make_test_source(
        video_id="vid_123",
        title="GTA 6 Leak Analysis",
        channel="LeakHunter",
    )
    clip = make_test_clip(id="c01", idx=0, start=10.0, end=45.0, topic="Map leak", hook_text="Look at Vice City")

    meta = validate_and_fix_metadata(raw, clip, source, domain="gta6")
    assert len(meta.titles) == 3
    assert len(meta.hashtags) <= 5
    for tag in meta.hashtags:
        assert tag.startswith("#")
        assert " " not in tag
        assert tag.islower()

    # Verify credit block exists in YouTube description
    assert "https://youtu.be/vid_123" in meta.description_youtube
    assert "Original video:" in meta.description_youtube
    assert len(meta.description_youtube) <= 5000
    assert len(meta.description_instagram) <= 2200


def test_fallback_metadata():
    source = make_test_source(video_id="vid_abc", title="Source Title", channel="Creator")
    clip = make_test_clip(id="c02", idx=1, start=5.0, end=35.0, duration=30.0, topic="Supercar physics", hook_text="The driving looks insane")

    fb = fallback_metadata(clip, source, domain="gta6")
    assert len(fb.titles) == 3
    assert "Supercar Physics" in fb.titles[1].text
    assert "#shorts" in fb.hashtags
    assert "#gta6" in fb.hashtags
    assert "https://youtu.be/vid_abc" in fb.description_youtube
