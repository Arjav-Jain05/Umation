"""Speech density and domain glossary signal extraction."""

from __future__ import annotations

import re

from app.core.schemas import Word


def speech_ratio(words: list[Word], s: float, e: float) -> float:
    """Calculate the ratio of spoken speech time to total window duration."""
    dur = e - s
    if dur <= 0:
        return 0.0

    speech_dur = 0.0
    for w in words:
        overlap = max(0.0, min(e, w.e) - max(s, w.s))
        speech_dur += overlap

    ratio = min(1.0, speech_dur / dur)
    return round(ratio, 3)


def topical_hits(text: str, glossary_terms: list[str]) -> int:
    """Count unique domain glossary terms present in text (case-insensitive, whole-word)."""
    if not text or not glossary_terms:
        return 0

    hits = 0
    clean_text = text.lower()
    for term in glossary_terms:
        t_clean = term.strip().lower()
        if not t_clean:
            continue
        # Whole word match
        pattern = rf"\b{re.escape(t_clean)}\b"
        if re.search(pattern, clean_text):
            hits += 1

    return hits
