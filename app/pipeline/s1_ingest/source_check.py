"""Stage 1: URL validation and source metadata inspection using yt-dlp."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from app.core.db import get_conn
from app.core.errors import (
    InvalidUrl,
    LiveNotFinished,
    SourceBlocked,
    SourceUnavailable,
    TooLong,
)
from app.core.models import update_job
from app.core.schemas import (
    Chapter,
    HeatmapPoint,
    SourceInfo,
    SourcePolicyMatch,
)
from app.pipeline.context import JobContext

logger = logging.getLogger("app.pipeline.s1_ingest.source_check")

# Allowed YouTube video ID pattern (exactly 11 characters)
VIDEO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def parse_youtube_url(url: str) -> str:
    """Validate and normalize a single YouTube video or finished livestream URL."""
    clean = url.strip()
    if not clean:
        raise InvalidUrl("Empty URL provided")

    # Reject unsupported platforms or paths
    if "youtube.com/shorts/" in clean or "youtu.be/shorts/" in clean:
        raise InvalidUrl("YouTube Shorts are already vertical and cannot be used as source")
    if "/playlist" in clean and "list=" in clean and "v=" not in clean:
        raise InvalidUrl("Playlists are not supported; paste a single video URL")
    if ("/channel/" in clean or "/c/" in clean or "/user/" in clean or "/@" in clean) and (
        "watch?v=" not in clean and "live/" not in clean
    ):
        raise InvalidUrl("Channel URLs are not supported; paste a single video URL")

    parsed = urlparse(clean)
    host = parsed.netloc.lower()

    video_id: str | None = None

    if host in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        if parsed.path == "/watch":
            qs = parse_qs(parsed.query)
            v_list = qs.get("v")
            if v_list and len(v_list[0]) == 11:
                video_id = v_list[0]
        elif parsed.path.startswith("/live/"):
            parts = parsed.path.split("/")
            if len(parts) >= 3 and len(parts[2]) == 11:
                video_id = parts[2]
    elif host == "youtu.be":
        cand = parsed.path.strip("/")
        if len(cand) == 11:
            video_id = cand

    if not video_id or not VIDEO_ID_PATTERN.match(video_id):
        raise InvalidUrl(
            f"Invalid YouTube URL: '{url}'. Only single video or livestream links are supported.",
            hint="Format: https://www.youtube.com/watch?v=... or https://youtu.be/...",
        )

    return f"https://www.youtube.com/watch?v={video_id}"


def _check_source_policy(
    channel_id: str,
    channel_name: str,
    policy_path: Path,
    is_cc: bool,
) -> SourcePolicyMatch:
    """Evaluate channel allow/block status against config/source_policy.yaml."""
    if not policy_path.exists():
        return SourcePolicyMatch(status="none")

    try:
        with open(policy_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("Failed to parse source policy: %s", e)
        return SourcePolicyMatch(status="none")

    c_name_lower = channel_name.strip().lower()

    # 1. Block list
    for entry in cfg.get("block", []):
        b_id = str(entry.get("channel_id") or "").strip()
        b_name = str(entry.get("name") or "").strip().lower()
        if (b_id and b_id == channel_id) or (b_name and b_name == c_name_lower):
            raise SourceBlocked(
                channel=channel_name,
                reason=entry.get("note") or "Channel listed in blocklist",
            )

    # 2. Allow list
    for entry in cfg.get("allow", []):
        a_id = str(entry.get("channel_id") or "").strip()
        a_name = str(entry.get("name") or "").strip().lower()
        if (a_id and a_id == channel_id) or (a_name and a_name == c_name_lower):
            return SourcePolicyMatch(status="allow", matched_rule=entry.get("note") or "allowlisted")

    # 3. Require CC
    if cfg.get("require_cc", False) and not is_cc:
        raise SourceBlocked(
            channel=channel_name,
            reason="Source policy requires Creative Commons license or allowlisted channel",
        )

    return SourcePolicyMatch(status="none")


def run(ctx: JobContext) -> None:
    """Execute Stage 1: source_check."""
    if ctx.artifact_ok("source_info.json", SourceInfo):
        logger.info("[%s] source_info.json already exists and validates; skipping source_check", ctx.job_id)
        return

    ctx.progress("source_check", 0.1, "Validating URL and fetching video metadata...")
    normalized_url = parse_youtube_url(ctx.job["url"])

    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "socket_timeout": 30,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(normalized_url, download=False)
    except Exception as e:
        err_str = str(e).lower()
        if "private" in err_str or "unavailable" in err_str or "deleted" in err_str or "404" in err_str:
            raise SourceUnavailable(
                f"Video is private, deleted, or unavailable: {e}",
            ) from e
        raise SourceUnavailable(f"Failed to fetch video information from YouTube: {e}") from e

    if not info:
        raise SourceUnavailable("yt-dlp returned no metadata for URL")

    # 1. Live stream checks
    live_status = info.get("live_status") or "not_live"
    if live_status in ("is_live", "is_upcoming"):
        raise LiveNotFinished("This livestream has not ended. Come back when it is a finished video.")
    if live_status == "post_live":
        raise LiveNotFinished("YouTube is still processing the livestream replay; try again later.")

    # 2. Duration checks
    duration_s = float(info.get("duration") or 0.0)
    max_duration = ctx.settings.max_source_hours * 3600
    if duration_s <= 0 or duration_s > max_duration:
        raise TooLong(duration_s=duration_s, max_hours=ctx.settings.max_source_hours)

    # 3. Channel and policy
    channel_id = str(info.get("channel_id") or "")
    channel = str(info.get("channel") or info.get("uploader") or "Unknown")
    license_str = info.get("license")
    is_cc = bool(license_str and "creative commons" in license_str.lower())

    policy_path = ctx.settings.project_root / "config" / "source_policy.yaml"
    policy_match = _check_source_policy(channel_id, channel, policy_path, is_cc)

    # 4. Heatmap
    heatmap_raw = info.get("heatmap") or []
    heatmap_points: list[HeatmapPoint] | None = None
    avg_seg: float | None = None
    if heatmap_raw:
        heatmap_points = [
            HeatmapPoint(
                start=float(pt.get("start_time", 0.0)),
                end=float(pt.get("end_time", 0.0)),
                value=float(pt.get("value", 0.0)),
            )
            for pt in heatmap_raw
        ]
        avg_seg = round(duration_s / max(1, len(heatmap_points)), 2)

    # 5. Best dimensions and framerate
    width = int(info.get("width") or 1920)
    height = int(info.get("height") or 1080)
    fps = float(info.get("fps") or 30.0)

    # 6. Chapters
    chapters_raw = info.get("chapters") or []
    chapters = [
        Chapter(
            start=float(ch.get("start_time", 0.0)),
            end=float(ch.get("end_time", 0.0)),
            title=str(ch.get("title", "")),
        )
        for ch in chapters_raw
    ]

    # 7. Warnings
    if not heatmap_points:
        ctx.warning("No replay heatmap data available for this video.")
    if not is_cc:
        ctx.warning("This video is not Creative Commons. Reusing it may lead to claims or takedowns.")
    if duration_s > 6 * 3600:
        ctx.warning(f"Long source video ({duration_s / 3600:.1f} hours). Ingest may take several minutes.")

    # Older video check for GTA 6 domain
    upload_date = str(info.get("upload_date") or "")
    if upload_date and len(upload_date) == 8 and ctx.settings.project_domain == "gta6":
        try:
            dt = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=UTC)
            now = datetime.now(UTC)
            if (now - dt).days > 7:
                ctx.warning("Older video: possible duplicate content already covered on social media.")
        except Exception:
            pass

    source_info = SourceInfo(
        video_id=info["id"],
        url=normalized_url,
        webpage_url=str(info.get("webpage_url") or normalized_url),
        title=str(info.get("title") or "Untitled"),
        channel=channel,
        channel_url=str(info.get("channel_url") or ""),
        uploader=str(info.get("uploader") or channel),
        upload_date=upload_date or "20260101",
        duration_s=round(duration_s, 3),
        live_status=live_status,
        license=license_str,
        width=width,
        height=height,
        fps=round(fps, 3),
        view_count=info.get("view_count"),
        like_count=info.get("like_count"),
        description_head=str(info.get("description") or "")[:600],
        chapters=chapters,
        heatmap=heatmap_points,
        heatmap_avg_seg_s=avg_seg,
        source_policy=policy_match,
        fetched_at=datetime.now(UTC).isoformat(),
    )

    ctx.write_artifact("source_info.json", source_info)

    # Update job DB row
    with get_conn(ctx.db_path) as conn:
        update_job(
            ctx.job_id,
            conn=conn,
            video_id=source_info.video_id,
            title=source_info.title,
            channel=source_info.channel,
        )

    ctx.progress("source_check", 1.0, f"Source metadata verified: '{source_info.title}' ({source_info.channel})")
