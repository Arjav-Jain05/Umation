"""Mandatory credit block builder for YouTube descriptions and Instagram captions (N6)."""

from __future__ import annotations

import math
from typing import Any

from app.core.schemas import Clip, SourceInfo
from app.utils.timecode import fmt_hms


def _resolve_channel_name(source: SourceInfo | dict[str, Any]) -> tuple[str, bool]:
    """Extract channel name with fallback to uploader; returns (channel_name, is_missing)."""
    channel = getattr(source, "channel", None) if isinstance(source, SourceInfo) else source.get("channel")
    if channel and str(channel).strip():
        return str(channel).strip(), False

    uploader = getattr(source, "uploader", None) if isinstance(source, SourceInfo) else source.get("uploader")
    if uploader and str(uploader).strip():
        return str(uploader).strip(), False

    return "the original creator", True


def _resolve_channel_url(source: SourceInfo | dict[str, Any]) -> str:
    """Resolve full canonical channel link."""
    channel_url = getattr(source, "channel_url", None) if isinstance(source, SourceInfo) else source.get("channel_url")
    if channel_url and str(channel_url).strip():
        return str(channel_url).strip()

    channel_id = getattr(source, "channel_id", None) if isinstance(source, SourceInfo) else source.get("channel_id")
    if channel_id and str(channel_id).strip():
        return f"https://www.youtube.com/channel/{str(channel_id).strip()}"

    channel_name = getattr(source, "channel", None) if isinstance(source, SourceInfo) else source.get("channel")
    if channel_name and str(channel_name).strip().startswith("@"):
        return f"https://www.youtube.com/{str(channel_name).strip()}"

    return "https://www.youtube.com"


def build_credit_block(
    source_info: SourceInfo | dict[str, Any],
    clip: Clip | dict[str, Any],
    short: bool = False,
) -> str:
    """Generate mandatory factual credit block verbatim according to 07 s5.

    Guaranteed never to contain legal claims such as 'fair use' or 'no infringement intended'.
    """
    title = source_info.title if isinstance(source_info, SourceInfo) else source_info.get("title", "Video")
    video_id = source_info.video_id if isinstance(source_info, SourceInfo) else source_info.get("video_id", "")

    clip_start = float(clip.start if isinstance(clip, Clip) else clip.get("start", 0.0))
    clip_end = float(clip.end if isinstance(clip, Clip) else clip.get("end", 0.0))

    start_seconds_int = math.floor(max(0.0, clip_start))
    channel_name, _ = _resolve_channel_name(source_info)
    channel_url = _resolve_channel_url(source_info)

    start_hms = fmt_hms(clip_start, force_hours=True)
    end_hms = fmt_hms(clip_end, force_hours=True)

    if short:
        # Instagram compact form
        return (
            f'Credit: {channel_name} - "{title}"\n'
            f"Full video: https://youtu.be/{video_id}?t={start_seconds_int}"
        )

    # YouTube full form
    return (
        f'Original video: "{title}" by {channel_name}\n'
        f"Channel: {channel_url}\n"
        f"Full video: https://youtu.be/{video_id}?t={start_seconds_int}\n"
        f"Clip from {start_hms} to {end_hms} of the original.\n"
        f"All footage and rights belong to the original creator and to the game's publisher/owners."
    )
