"""Audience-first signals parser (YouTube most replayed heatmap, timestamped comments, chat replay, chapters).

Implements Section 4 of the spec:
- Real human validation outranking AI models.
- Fail-soft principle: signals that are missing are marked missing (available=False), NEVER filled with 0.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("app.pipeline.s1_ingest.audience")

# Timestamp pattern in comment text: e.g. "03:45", "1:23:45", "0:50", "45s"
TIMESTAMP_RE = re.compile(
    r"(?:(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d))|(?:(\d+)\s*s(?:ec(?:onds?)?)?)\b",
    re.IGNORECASE,
)

HYPE_CHAT_KEYWORDS = {
    "clip it", "clip this", "pog", "poggers", "lol", "lmao", "omg", "wtf",
    "holy shit", "no way", "insane", "gg", "w", "sheesh", "clutch", "wasted",
}


def _parse_timestamp_seconds(match: re.Match[str]) -> float | None:
    """Convert regex match to seconds."""
    hours_str, mins_str, secs_str, seconds_only = match.groups()
    if seconds_only is not None:
        return float(seconds_only)
    try:
        hours = float(hours_str) if hours_str else 0.0
        mins = float(mins_str) if mins_str else 0.0
        secs = float(secs_str) if secs_str else 0.0
        return hours * 3600.0 + mins * 60.0 + secs
    except (ValueError, TypeError):
        return None


def parse_yt_heatmap(heatmap_raw: list[dict[str, Any]] | list[Any] | None) -> tuple[list[dict[str, float]], bool]:
    """Parse and normalize YouTube 'most replayed' heatmap to [0.0, 1.0]."""
    if not heatmap_raw:
        return [], False

    parsed: list[dict[str, float]] = []
    values: list[float] = []

    for pt in heatmap_raw:
        if isinstance(pt, dict):
            s = float(pt.get("start_time", 0.0))
            e = float(pt.get("end_time", s + 1.0))
            val = float(pt.get("value", 0.0))
        else:
            # HeatmapPoint schema object
            s = float(getattr(pt, "start_time", 0.0))
            e = float(getattr(pt, "end_time", s + 1.0))
            val = float(getattr(pt, "value", 0.0))
        parsed.append({"start_time": s, "end_time": e, "value": val})
        values.append(val)

    if not values:
        return [], False

    min_val = min(values)
    max_val = max(values)
    val_range = max_val - min_val

    # Normalize within video
    normalized: list[dict[str, float]] = []
    for pt in parsed:
        norm_val = (pt["value"] - min_val) / val_range if val_range > 1e-6 else 0.5
        normalized.append({
            "start_time": pt["start_time"],
            "end_time": pt["end_time"],
            "value": round(float(norm_val), 4),
        })

    return normalized, True


def parse_timestamped_comments(
    comments_raw: list[dict[str, Any]] | None,
    duration_s: float,
) -> tuple[dict[int, float], bool]:
    """Extract timestamps from comment text, weight by likes, and bucket into 10s bins."""
    if not comments_raw:
        return {}, False

    bin_scores: dict[int, float] = {}
    total_matches = 0
    max_bin = max(1, math.ceil(duration_s / 10.0)) if duration_s > 0 else 360

    for comment in comments_raw:
        text = str(comment.get("text", comment.get("comment", "")))
        if not text:
            continue
        likes = float(comment.get("like_count", comment.get("likes", 0)) or 0)
        weight = 1.0 + math.log1p(max(0.0, likes))

        for m in TIMESTAMP_RE.finditer(text):
            ts = _parse_timestamp_seconds(m)
            if ts is not None and (duration_s <= 0 or 0 <= ts <= duration_s):
                b = int(ts // 10)
                bin_scores[b] = bin_scores.get(b, 0.0) + weight
                total_matches += 1

    if not bin_scores or total_matches == 0:
        return {}, False

    # Normalize 10s bins to 0.0 - 1.0
    max_score = max(bin_scores.values())
    normalized_bins: dict[int, float] = {}
    for b, score in bin_scores.items():
        if b <= max_bin:
            normalized_bins[b] = round(score / max_score, 4)

    return normalized_bins, True


def parse_chat_replay(
    chat_messages: list[dict[str, Any]] | None,
    duration_s: float,
) -> tuple[dict[int, float], dict[int, list[str]], bool]:
    """Parse chat replay for message density spikes and hype keywords in 10s bins."""
    if not chat_messages:
        return {}, {}, False

    bin_counts: dict[int, int] = {}
    bin_hype_tags: dict[int, list[str]] = {}
    max_bin = max(1, math.ceil(duration_s / 10.0)) if duration_s > 0 else 360

    for msg in chat_messages:
        t = float(msg.get("offset_seconds", msg.get("timestamp_s", 0.0)))
        body = str(msg.get("message", msg.get("text", ""))).lower()
        if duration_s > 0 and (t < 0 or t > duration_s):
            continue

        b = int(t // 10)
        bin_counts[b] = bin_counts.get(b, 0) + 1

        for kw in HYPE_CHAT_KEYWORDS:
            if kw in body:
                if b not in bin_hype_tags:
                    bin_hype_tags[b] = []
                if kw not in bin_hype_tags[b]:
                    bin_hype_tags[b].append(kw)

    if not bin_counts:
        return {}, {}, False

    # Compute mean and standard deviation of message density
    counts = list(bin_counts.values())
    mean_count = sum(counts) / len(counts)
    std_count = math.sqrt(sum((c - mean_count) ** 2 for c in counts) / len(counts)) if len(counts) > 1 else 1.0
    max_count = max(counts)

    normalized_bins: dict[int, float] = {}
    for b, c in bin_counts.items():
        if b <= max_bin:
            # Scale combining peak density and z-score spike
            z = (c - mean_count) / max(1.0, std_count)
            base_norm = c / max_count
            spike_boost = 0.2 if z > 2.0 else 0.0
            normalized_bins[b] = round(min(1.0, base_norm + spike_boost), 4)

    return normalized_bins, bin_hype_tags, True


def parse_chapters(chapters_raw: list[dict[str, Any]] | list[Any] | None) -> tuple[list[dict[str, Any]], bool]:
    """Parse chapters as soft topic boundaries."""
    if not chapters_raw:
        return [], False

    parsed: list[dict[str, Any]] = []
    for ch in chapters_raw:
        if isinstance(ch, dict):
            title = str(ch.get("title", ""))
            s = float(ch.get("start_time", 0.0))
            e = float(ch.get("end_time", s))
        else:
            title = str(getattr(ch, "title", ""))
            s = float(getattr(ch, "start_time", 0.0))
            e = float(getattr(ch, "end_time", s))
        parsed.append({"title": title, "start_time": s, "end_time": e})

    return parsed, len(parsed) > 0


@dataclass
class AudienceSignalsData:
    """Aggregated audience signals across the whole video."""
    heatmap: list[dict[str, float]] = field(default_factory=list)
    has_heatmap: bool = False
    comments_bins: dict[int, float] = field(default_factory=dict)
    has_comments: bool = False
    chat_bins: dict[int, float] = field(default_factory=dict)
    chat_hype_tags: dict[int, list[str]] = field(default_factory=dict)
    has_chat: bool = False
    chapters: list[dict[str, Any]] = field(default_factory=list)
    has_chapters: bool = False

    @property
    def any_available(self) -> bool:
        return self.has_heatmap or self.has_comments or self.has_chat or self.has_chapters


def get_audience_score_for_window(
    start_s: float,
    end_s: float,
    audience: AudienceSignalsData,
) -> tuple[float | None, dict[str, Any]]:
    """Compute normalized audience score (0-100) and breakdown for a given time window.

    If no audience signals are available, returns (None, {"available": False}).
    """
    if not audience.any_available:
        return None, {"available": False}

    active_scores: list[float] = []
    breakdown: dict[str, Any] = {"available": True}

    # 1. Heatmap overlap
    if audience.has_heatmap and audience.heatmap:
        overlap_vals: list[float] = []
        for pt in audience.heatmap:
            if pt["end_time"] > start_s and pt["start_time"] < end_s:
                overlap_vals.append(pt["value"])
        if overlap_vals:
            heat_avg = sum(overlap_vals) / len(overlap_vals)
            heat_score = heat_avg * 100.0
            breakdown["heatmap"] = round(heat_score, 1)
            active_scores.append(heat_score)

    # 2. Timestamped comments in window (10s bins)
    if audience.has_comments and audience.comments_bins:
        b_start = int(start_s // 10)
        b_end = int(end_s // 10)
        bin_vals = [audience.comments_bins.get(b, 0.0) for b in range(b_start, b_end + 1)]
        if bin_vals:
            comm_score = max(bin_vals) * 100.0
            breakdown["comments"] = round(comm_score, 1)
            active_scores.append(comm_score)

    # 3. Chat replay in window (10s bins)
    if audience.has_chat and audience.chat_bins:
        b_start = int(start_s // 10)
        b_end = int(end_s // 10)
        chat_vals = [audience.chat_bins.get(b, 0.0) for b in range(b_start, b_end + 1)]
        hypes: list[str] = []
        for b in range(b_start, b_end + 1):
            hypes.extend(audience.chat_hype_tags.get(b, []))
        if chat_vals:
            chat_score = max(chat_vals) * 100.0
            breakdown["chat"] = round(chat_score, 1)
            breakdown["chat_hype"] = list(set(hypes))
            active_scores.append(chat_score)

    # 4. Chapters context
    if audience.has_chapters and audience.chapters:
        matching_ch = [
            ch["title"] for ch in audience.chapters
            if ch["end_time"] > start_s and ch["start_time"] < end_s
        ]
        if matching_ch:
            breakdown["chapters"] = matching_ch

    if not active_scores:
        return None, breakdown

    final_audience = sum(active_scores) / len(active_scores)
    return round(final_audience, 1), breakdown
