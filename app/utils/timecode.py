"""Timecode formatting, parsing, and timeline remapping helpers."""

from __future__ import annotations

import re


def fmt_hms(seconds: float, force_hours: bool = False) -> str:
    """Format seconds into HH:MM:SS or MM:SS string."""
    total_sec = max(0, round(seconds))
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    if h > 0 or force_hours:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def fmt_ms(seconds: float) -> str:
    """Format seconds into MM:SS string."""
    total_sec = max(0, round(seconds))
    m = total_sec // 60
    s = total_sec % 60
    return f"{m:02d}:{s:02d}"


def parse_hms(text: str) -> float:
    """Parse time string (HH:MM:SS, MM:SS, or float seconds) into float seconds."""
    clean = text.strip()
    if not clean:
        return 0.0

    # Format HH:MM:SS[.fff] or MM:SS[.fff]
    if ":" in clean:
        parts = clean.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)

    # Bare seconds format
    match = re.match(r"^([\d.]+)", clean)
    if match:
        return float(match.group(1))
    return 0.0


class Remapper:
    """Remaps source timeline timestamps into clip timeline after interval cuts."""

    def __init__(self, keep_intervals: list[tuple[float, float]]) -> None:
        # Sort and filter valid intervals
        self.intervals = sorted(
            [(float(s), float(e)) for s, e in keep_intervals if e > s],
            key=lambda x: x[0],
        )
        self.total_duration = sum(e - s for s, e in self.intervals)

    def remap(self, t_source: float) -> float:
        """Convert a source timestamp into seconds on the cut-clip timeline."""
        if not self.intervals:
            return 0.0

        if t_source <= self.intervals[0][0]:
            return 0.0

        accumulated = 0.0
        for s, e in self.intervals:
            if t_source < s:
                # Inside a cut/removed gap before this interval
                return round(accumulated, 3)
            if s <= t_source <= e:
                # Inside this keep interval
                return round(accumulated + (t_source - s), 3)
            accumulated += (e - s)

        # Beyond last interval
        return round(self.total_duration, 3)
