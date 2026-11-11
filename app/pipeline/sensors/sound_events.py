"""Layer 1 Sound Event Detection: acoustic feature classification for explosions, gunshots, screams, laughter, tire squeals, and sirens."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

logger = logging.getLogger("app.pipeline.sensors.sound_events")

TARGET_EVENTS = [
    "explosion",
    "gunshot",
    "screaming",
    "laughter",
    "cheering",
    "tire_squeal",
    "siren",
]


@dataclass
class SoundEventItem:
    time_s: float
    event: str
    confidence: float


@dataclass
class SoundEventsProfile:
    duration_s: float
    events: list[SoundEventItem] = field(default_factory=list)
    per_second_scores: dict[int, float] = field(default_factory=dict)
    per_second_tags: dict[int, list[str]] = field(default_factory=dict)


def extract_sound_events(audio_path: Path | str) -> SoundEventsProfile:
    """Analyze audio track and detect key sound events across the video timeline."""
    path = Path(audio_path)
    if not path.is_file():
        return SoundEventsProfile(duration_s=0.0)

    try:
        data, samplerate = sf.read(str(path), dtype="float32")
    except Exception as exc:
        logger.warning(f"Failed to read audio in sound_events: {exc}")
        return SoundEventsProfile(duration_s=0.0)

    if data.ndim > 1:
        data = np.mean(data, axis=1)

    total_samples = len(data)
    duration_s = total_samples / float(samplerate)
    num_seconds = max(1, math.ceil(duration_s))

    step = int(samplerate)
    detected_events: list[SoundEventItem] = []
    per_second_scores: dict[int, float] = {}
    per_second_tags: dict[int, list[str]] = {}

    # Check for short-time frequency bands per 1-second interval
    for sec in range(num_seconds):
        s_idx = sec * step
        e_idx = min(total_samples, s_idx + step)
        if s_idx >= total_samples:
            break

        chunk = data[s_idx:e_idx]
        if len(chunk) < step // 2:
            continue

        rms = float(np.sqrt(np.mean(chunk ** 2)))
        if rms < 0.01:
            # Quiet background, no prominent events
            per_second_scores[sec] = 0.0
            continue

        # Zero crossing rate
        zcr = float(np.mean(np.abs(np.diff(np.signbit(chunk)))))

        # Simple FFT spectrum
        fft_vals = np.abs(np.fft.rfft(chunk))
        freqs = np.fft.rfftfreq(len(chunk), 1.0 / samplerate)

        total_energy = float(np.sum(fft_vals) + 1e-9)

        # Energy in bands
        # Low: 20-300 Hz (explosions, engines)
        # Mid: 300-2500 Hz (speech, laughter, applause)
        # High: 2500-6000 Hz (screaming, tire squeals, sirens, gunshots)
        low_band = float(np.sum(fft_vals[(freqs >= 20) & (freqs < 300)])) / total_energy
        mid_band = float(np.sum(fft_vals[(freqs >= 300) & (freqs < 2500)])) / total_energy
        high_band = float(np.sum(fft_vals[(freqs >= 2500) & (freqs < 6000)])) / total_energy

        sec_tags: list[str] = []
        confidence_accum = 0.0

        # Explosion: high low-band dominance + sudden amplitude
        if low_band > 0.45 and rms > 0.15:
            conf = min(0.95, low_band * 1.5)
            detected_events.append(SoundEventItem(time_s=float(sec), event="explosion", confidence=conf))
            sec_tags.append("explosion")
            confidence_accum = max(confidence_accum, conf)

        # Gunshot: high transient spike + high ZCR
        if high_band > 0.35 and zcr > 0.25 and rms > 0.18:
            conf = min(0.90, (high_band + zcr))
            detected_events.append(SoundEventItem(time_s=float(sec), event="gunshot", confidence=conf))
            sec_tags.append("gunshot")
            confidence_accum = max(confidence_accum, conf)

        # Screaming: high energy in 2-4 kHz + high overall volume
        if high_band > 0.30 and mid_band > 0.40 and rms > 0.20:
            conf = min(0.92, high_band * 2.0)
            detected_events.append(SoundEventItem(time_s=float(sec), event="screaming", confidence=conf))
            sec_tags.append("screaming")
            confidence_accum = max(confidence_accum, conf)

        # Laughter / cheering: mid-band dominance + modulation
        if mid_band > 0.65 and 0.05 < rms < 0.25:
            conf = min(0.85, mid_band * 1.1)
            detected_events.append(SoundEventItem(time_s=float(sec), event="laughter", confidence=conf))
            sec_tags.append("laughter")
            confidence_accum = max(confidence_accum, conf)

        # Tire squeal / siren: narrow high band
        if high_band > 0.50 and zcr > 0.30:
            conf = min(0.88, high_band * 1.4)
            tag = "tire_squeal" if zcr > 0.40 else "siren"
            detected_events.append(SoundEventItem(time_s=float(sec), event=tag, confidence=conf))
            sec_tags.append(tag)
            confidence_accum = max(confidence_accum, conf)

        if sec_tags:
            per_second_tags[sec] = sec_tags
            per_second_scores[sec] = round(confidence_accum * 100.0, 1)
        else:
            per_second_scores[sec] = round(rms * 100.0 * 0.5, 1)

    return SoundEventsProfile(
        duration_s=duration_s,
        events=detected_events,
        per_second_scores=per_second_scores,
        per_second_tags=per_second_tags,
    )


def score_sound_events_window(
    start_s: float,
    end_s: float,
    profile: SoundEventsProfile,
) -> tuple[float, list[str]]:
    """Score sound event presence in [start_s, end_s].

    Returns:
        (events_score_0_to_100, list_of_detected_event_names)
    """
    if not profile.per_second_scores:
        return 40.0, []

    s_sec = max(0, math.floor(start_s))
    e_sec = max(s_sec + 1, math.ceil(end_s))

    scores = [profile.per_second_scores.get(sec, 0.0) for sec in range(s_sec, e_sec)]
    tags: set[str] = set()
    for sec in range(s_sec, e_sec):
        for t in profile.per_second_tags.get(sec, []):
            tags.add(t)

    avg_score = sum(scores) / len(scores) if scores else 40.0
    max_score = max(scores) if scores else 40.0
    blended = (avg_score * 0.6) + (max_score * 0.4)

    # Boost score if multiple distinct high-interest events occurred
    if len(tags) >= 2:
        blended = min(100.0, blended + 10.0)

    return round(blended, 1), sorted(tags)
