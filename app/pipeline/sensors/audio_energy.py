"""Layer 1 Acoustic Sensor: RMS loudness, baseline z-scores, peak bursts, and silence-to-explosion payoff shapes."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

logger = logging.getLogger("app.pipeline.sensors.audio_energy")


@dataclass
class AudioEnergyProfile:
    """Per-second loudness and energy statistics for the entire audio file."""
    duration_s: float
    per_second_rms: np.ndarray  # shape: (num_seconds,)
    per_second_z: np.ndarray  # shape: (num_seconds,)
    mean_rms: float
    std_rms: float
    silence_explosion_indices: list[int] = field(default_factory=list)


def extract_audio_energy(audio_path: Path | str) -> AudioEnergyProfile:
    """Analyze 16 kHz audio file and compute per-second RMS, z-scores, and explosion patterns."""
    path = Path(audio_path)
    if not path.is_file():
        logger.warning(f"Audio file not found: {path}; returning empty energy profile")
        return AudioEnergyProfile(
            duration_s=0.0,
            per_second_rms=np.array([], dtype=np.float32),
            per_second_z=np.array([], dtype=np.float32),
            mean_rms=0.0,
            std_rms=1.0,
        )

    try:
        data, samplerate = sf.read(str(path), dtype="float32")
    except Exception as exc:
        logger.warning(f"Failed to read audio with soundfile: {exc}; returning flat profile")
        return AudioEnergyProfile(
            duration_s=0.0,
            per_second_rms=np.array([], dtype=np.float32),
            per_second_z=np.array([], dtype=np.float32),
            mean_rms=0.0,
            std_rms=1.0,
        )

    if data.ndim > 1:
        data = np.mean(data, axis=1)

    total_samples = len(data)
    duration_s = total_samples / float(samplerate)
    num_seconds = max(1, math.ceil(duration_s))

    # Compute RMS per 1.0s window
    rms_values = np.zeros(num_seconds, dtype=np.float32)
    step = int(samplerate)

    for i in range(num_seconds):
        s_idx = i * step
        e_idx = min(total_samples, s_idx + step)
        if s_idx < total_samples:
            chunk = data[s_idx:e_idx]
            rms = np.sqrt(np.mean(chunk ** 2) + 1e-9)
            rms_values[i] = rms

    mean_rms = float(np.mean(rms_values)) if len(rms_values) > 0 else 0.0
    std_rms = float(np.std(rms_values)) if len(rms_values) > 0 else 1.0
    if std_rms < 1e-6:
        std_rms = 1.0

    z_values = (rms_values - mean_rms) / std_rms

    # Detect silence-to-explosion payoff shapes:
    # Quiet period followed immediately by high burst
    max_rms = float(np.max(rms_values)) if len(rms_values) > 0 else 1.0
    silence_explosions: list[int] = []
    for i in range(1, num_seconds):
        prev_quiet = (rms_values[i - 1] < 0.25 * max_rms) or (z_values[i - 1] < -0.4)
        curr_spike = (z_values[i] >= 1.8) or (
            rms_values[i] >= 0.40 * max_rms and rms_values[i] >= 3.0 * max(1e-4, rms_values[i - 1])
        )
        if prev_quiet and curr_spike:
            silence_explosions.append(i)

    return AudioEnergyProfile(
        duration_s=duration_s,
        per_second_rms=rms_values,
        per_second_z=z_values,
        mean_rms=mean_rms,
        std_rms=std_rms,
        silence_explosion_indices=silence_explosions,
    )


def score_audio_window(
    start_s: float,
    end_s: float,
    profile: AudioEnergyProfile,
) -> tuple[float, int, bool]:
    """Score audio energy for [start_s, end_s].

    Returns:
        (audio_score_0_to_100, burst_count, is_silence_explosion)
    """
    if len(profile.per_second_rms) == 0:
        return 50.0, 0, False

    s_sec = max(0, math.floor(start_s))
    e_sec = min(len(profile.per_second_rms), math.ceil(end_s))
    if s_sec >= e_sec:
        e_sec = s_sec + 1

    window_rms = profile.per_second_rms[s_sec:e_sec]
    window_z = profile.per_second_z[s_sec:e_sec]

    if len(window_rms) == 0:
        return 50.0, 0, False

    avg_z = float(np.mean(window_z))
    max_z = float(np.max(window_z))
    bursts = int(np.sum((window_z >= 1.0) | (window_rms >= profile.mean_rms + 0.5 * profile.std_rms)))

    # Base score scaled from z-scores: z=0 -> 50, z=2 -> 80, z=3+ -> 95-100
    base_score = 50.0 + (avg_z * 15.0) + (max_z * 5.0)
    score = min(100.0, max(0.0, base_score))

    # Check silence-to-explosion shape inside window
    has_silence_explosion = any(s_sec <= idx < e_sec for idx in profile.silence_explosion_indices)
    if has_silence_explosion:
        score = min(100.0, score + 10.0)

    return round(score, 1), bursts, has_silence_explosion
