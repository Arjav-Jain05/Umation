"""Audio energy and volume burst signal extraction (laughter, hype, and tension)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import soundfile as sf

logger = logging.getLogger("app.pipeline.s2_select.signal_audio")


def frame_db(audio_path: Path, frame_s: float = 0.5) -> np.ndarray:
    """Compute RMS energy in dBFS (floor -80) for 0.5s audio blocks."""
    if not audio_path.exists():
        return np.array([], dtype=np.float32)

    db_values: list[float] = []
    with sf.SoundFile(str(audio_path)) as f:
        sr = f.samplerate
        block_len = round(frame_s * sr)

        while f.tell() < len(f):
            block = f.read(block_len, dtype="float32")
            if len(block) == 0:
                break
            rms = np.sqrt(np.mean(block**2) + 1e-12)
            db = 20.0 * np.log10(max(1e-4, float(rms)))
            db_values.append(max(-80.0, db))

    return np.array(db_values, dtype=np.float32)


def compute_baseline_z(db: np.ndarray, window_radius_frames: int = 600) -> np.ndarray:
    """Compute local z-score per frame using rolling median and Median Absolute Deviation (MAD)."""
    n = len(db)
    if n == 0:
        return np.array([], dtype=np.float32)

    z = np.zeros(n, dtype=np.float32)
    for i in range(n):
        w_start = max(0, i - window_radius_frames)
        w_end = min(n, i + window_radius_frames + 1)
        sub = db[w_start:w_end]
        med = float(np.median(sub))
        mad = float(np.median(np.abs(sub - med)))
        scale = 1.4826 * mad + 1e-3
        z[i] = (db[i] - med) / scale

    return z


def audio_score(
    window: tuple[float, float],
    z_scores: np.ndarray,
    frame_s: float = 0.5,
) -> tuple[float, int]:
    """Calculate audio signal score (0-100) and burst count for candidate window."""
    w_start, w_end = window
    dur = max(1.0, w_end - w_start)

    f_start = int(max(0, np.floor(w_start / frame_s)))
    f_end = int(min(len(z_scores), np.ceil(w_end / frame_s)))

    if f_start >= f_end or len(z_scores) == 0:
        return 0.0, 0

    sub_z = z_scores[f_start:f_end]
    bursts = int(np.sum(sub_z > 2.0))
    burst_density = bursts / (dur / 10.0)

    # Energy: mean of top 20% z values
    top_k = max(1, int(len(sub_z) * 0.20))
    sorted_z = np.sort(sub_z)
    energy = float(np.mean(sorted_z[-top_k:]))

    energy_norm = max(0.0, min(1.0, energy / 3.0))
    density_norm = max(0.0, min(1.0, burst_density / 3.0))

    score = 100.0 * (0.6 * energy_norm + 0.4 * density_norm)
    return round(float(score), 1), bursts
