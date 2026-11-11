"""Layer 1 Topic Boundary Segmentation and Candidate Deduplication."""

from __future__ import annotations

import logging
from typing import Any

from rapidfuzz import fuzz

logger = logging.getLogger("app.pipeline.sensors.topic_segmenter")


def detect_topic_boundaries(sentences: list[Any], window_size: int = 3) -> list[float]:
    """Find timestamps of topical shift points where sentence similarity drops."""
    if len(sentences) < window_size * 2:
        return []

    boundaries: list[float] = []

    for i in range(window_size, len(sentences) - window_size):
        # Window before
        w_before = " ".join([str(getattr(s, "text", "")) for s in sentences[i - window_size : i]])
        # Window after
        w_after = " ".join([str(getattr(s, "text", "")) for s in sentences[i : i + window_size]])

        if not w_before or not w_after:
            continue

        sim = fuzz.token_set_ratio(w_before, w_after)
        # Similarity drop below 40 indicates topic shift
        if sim < 40:
            t = float(getattr(sentences[i], "start", getattr(sentences[i], "s", 0.0)))
            boundaries.append(round(t, 2))

    return boundaries


def compute_candidate_overlap(
    start_a: float,
    end_a: float,
    text_a: str,
    start_b: float,
    end_b: float,
    text_b: str,
) -> tuple[float, float, bool]:
    """Calculate time overlap ratio and text similarity between two candidates.

    Returns:
        (time_overlap_ratio, text_similarity_0_to_100, is_agreement)
    """
    len_a = max(0.1, end_a - start_a)
    len_b = max(0.1, end_b - start_b)

    overlap_start = max(start_a, start_b)
    overlap_end = min(end_a, end_b)
    overlap_duration = max(0.0, overlap_end - overlap_start)

    # Time overlap relative to shorter candidate
    time_ratio = overlap_duration / min(len_a, len_b)

    # Text similarity
    text_sim = float(fuzz.token_set_ratio(text_a, text_b)) if text_a and text_b else 0.0

    # Agreement if > 50% time overlap or very high text similarity (> 85%)
    is_agreement = (time_ratio >= 0.50) or (time_ratio >= 0.30 and text_sim >= 85.0)

    return round(time_ratio, 3), round(text_sim, 1), is_agreement
