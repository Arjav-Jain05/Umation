"""Layer 1 Prosodic & Voice Emotion Sensor: speech rate (WPM), exclamation density, and hype lexicon matching."""

from __future__ import annotations

import logging
from typing import Any

from rapidfuzz import fuzz

logger = logging.getLogger("app.pipeline.sensors.voice_emotion")

DEFAULT_HYPE_LEXICON = [
    "holy shit", "no way", "insane", "oh my god", "what the hell",
    "what the fuck", "let's go", "unbelievable", "crazy", "huge",
    "watch this", "clip it", "wasted", "busted", "headshot", "clutch",
    "pog", "sheesh", "omg", "wtf", "lmao",
]


def compute_window_wpm(words: list[Any], start_s: float, end_s: float) -> float:
    """Calculate speaking pace in Words Per Minute (WPM) for a given window."""
    duration_s = end_s - start_s
    if duration_s <= 0.5:
        return 0.0

    count = 0
    for w in words:
        w_start = float(getattr(w, "s", getattr(w, "start", 0.0)))
        w_end = float(getattr(w, "e", getattr(w, "end", w_start + 0.1)))
        if w_end > start_s and w_start < end_s:
            count += 1

    duration_min = duration_s / 60.0
    return count / duration_min


def match_hype_lexicon(text: str, custom_hype_words: list[str] | None = None) -> list[str]:
    """Find occurrences of hype phrases in text using fuzzy matching and regex substring search."""
    if not text:
        return []

    words_to_check = custom_hype_words if custom_hype_words else DEFAULT_HYPE_LEXICON
    clean_text = text.lower()
    matches: list[str] = []

    for hw in words_to_check:
        hw_clean = hw.lower().strip()
        if not hw_clean:
            continue
        # Direct substring
        if hw_clean in clean_text or (len(hw_clean.split()) > 1 and fuzz.partial_ratio(hw_clean, clean_text) >= 88):
            matches.append(hw_clean)

    return list(set(matches))


def score_voice_emotion(
    start_s: float,
    end_s: float,
    words: list[Any],
    sentences: list[Any],
    custom_hype_words: list[str] | None = None,
) -> tuple[float, float, list[str]]:
    """Score speech emotion and text hype for window [start_s, end_s].

    Returns:
        (emotion_score_0_to_100, text_hype_score_0_to_100, matched_hype_words)
    """
    duration = end_s - start_s
    if duration <= 1.0:
        return 50.0, 50.0, []

    # 1. Speaking pace
    wpm = compute_window_wpm(words, start_s, end_s)

    # Base emotion score from pace: 140 WPM baseline -> 50; 200+ WPM -> 80+
    if wpm <= 50:
        pace_score = 40.0
    elif wpm <= 140:
        pace_score = 50.0 + (wpm - 50) * 0.15
    elif wpm <= 220:
        pace_score = 63.5 + (wpm - 140) * 0.35
    else:
        # Very fast excited delivery
        pace_score = min(95.0, 91.5 + (wpm - 220) * 0.1)

    # 2. Text extraction for sentences overlapping window
    overlap_texts: list[str] = []
    exclamation_count = 0
    question_count = 0

    for s in sentences:
        s_start = float(getattr(s, "start", getattr(s, "s", 0.0)))
        s_end = float(getattr(s, "end", getattr(s, "e", s_start + 1.0)))
        if s_end > start_s and s_start < end_s:
            t = str(getattr(s, "text", ""))
            overlap_texts.append(t)
            exclamation_count += t.count("!")
            question_count += t.count("?")

    combined_text = " ".join(overlap_texts)
    matched_hypes = match_hype_lexicon(combined_text, custom_hype_words)

    # Exclamation & question density
    punct_boost = min(15.0, exclamation_count * 5.0 + question_count * 2.5)

    emotion_score = min(100.0, pace_score + punct_boost)

    # 3. Text hype score
    # Baseline 45; each hype hit adds 12-15 points
    hype_score = 45.0 + min(45.0, len(matched_hypes) * 14.0)
    if exclamation_count > 0:
        hype_score = min(100.0, hype_score + 10.0)

    return round(emotion_score, 1), round(hype_score, 1), matched_hypes
