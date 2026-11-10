"""Unit tests for YouTube URL validation and normalization."""

import pytest

from app.core.errors import InvalidUrl
from app.pipeline.s1_ingest.source_check import parse_youtube_url


def test_valid_youtube_urls():
    """Verify that all 4 supported YouTube URL forms are normalized to canonical watch URL."""
    expected = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    # 1. Standard watch URL
    assert parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == expected

    # 2. Watch URL with extra query params (timestamps, tracking, list)
    assert parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&feature=share") == expected

    # 3. Shortened youtu.be link
    assert parse_youtube_url("https://youtu.be/dQw4w9WgXcQ") == expected

    # 4. Finished livestream link
    assert parse_youtube_url("https://www.youtube.com/live/dQw4w9WgXcQ") == expected

    # 5. Mobile youtube link
    assert parse_youtube_url("https://m.youtube.com/watch?v=dQw4w9WgXcQ") == expected


def test_reject_invalid_urls():
    """Verify that playlists, channels, shorts, and invalid domains are rejected with InvalidUrl."""
    # YouTube Shorts (already vertical)
    with pytest.raises(InvalidUrl, match="Shorts"):
        parse_youtube_url("https://www.youtube.com/shorts/dQw4w9WgXcQ")

    # Playlist without specific video
    with pytest.raises(InvalidUrl, match="Playlists"):
        parse_youtube_url("https://www.youtube.com/playlist?list=PL123456789")

    # Channel URLs
    with pytest.raises(InvalidUrl, match="Channel"):
        parse_youtube_url("https://www.youtube.com/@RockstarGames")

    with pytest.raises(InvalidUrl, match="Channel"):
        parse_youtube_url("https://www.youtube.com/channel/UC1234567890abcdef")

    # Non-YouTube URL
    with pytest.raises(InvalidUrl, match="Invalid YouTube URL"):
        parse_youtube_url("https://vimeo.com/123456789")

    # Empty URL
    with pytest.raises(InvalidUrl, match="Empty URL"):
        parse_youtube_url("   ")

    # Malformed video ID (not 11 chars)
    with pytest.raises(InvalidUrl, match="Invalid YouTube URL"):
        parse_youtube_url("https://www.youtube.com/watch?v=too_short")
