"""YouTube replay heatmap signal analysis."""

from __future__ import annotations

import statistics

from app.core.schemas import HeatmapPoint


def heat_score(
    window: tuple[float, float],
    heatmap: list[HeatmapPoint] | None,
    avg_seg: float | None = None,
) -> tuple[float | None, bool]:
    """Calculate normalized heat score (0-100) and whether coarse heatmap weight override applies."""
    if not heatmap:
        return None, False

    # Check if heatmap segments are too coarse (> 90s)
    coarse_override = bool(avg_seg is not None and avg_seg > 90.0)

    all_vals = [pt.value for pt in heatmap]
    if not all_vals:
        return None, False

    median_v = statistics.median(all_vals)
    max_v = max(all_vals)

    w_start, w_end = window
    total_overlap_s = 0.0
    weighted_sum = 0.0

    for pt in heatmap:
        # Compute overlap with window [w_start, w_end]
        overlap_s = max(0.0, min(w_end, pt.end) - max(w_start, pt.start))
        if overlap_s > 0.0:
            total_overlap_s += overlap_s
            weighted_sum += pt.value * overlap_s

    if total_overlap_s <= 0.0:
        return 0.0, coarse_override

    m = weighted_sum / total_overlap_s
    denom = max_v - median_v + 1e-6

    normalized = max(0.0, min(1.0, (m - median_v) / denom))
    return round(normalized * 100.0, 1), coarse_override
