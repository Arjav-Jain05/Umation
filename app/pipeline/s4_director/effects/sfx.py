"""Sound effects synthesis, placement, and timeline audio mixing."""

from __future__ import annotations

import logging
import wave
from pathlib import Path

import numpy as np

from app.core import paths
from app.pipeline.s4_director.edit_schema import EditEvent

logger = logging.getLogger("app.pipeline.s4_director.effects.sfx")


def _read_wav_floats(wav_path: Path) -> tuple[np.ndarray, int]:
    """Read a 16-bit PCM WAV file into a normalized float array [-1.0, 1.0]."""
    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return data, sr


def build_sfx_mix(
    events: list[EditEvent],
    duration: float,
    out_wav: Path,
    sample_rate: int = 48000,
) -> Path:
    """Build a complete sfx_mix.wav timeline placing each sfx event at its timestamp."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    num_samples = max(sample_rate, round(duration * sample_rate))
    timeline = np.zeros(num_samples, dtype=np.float32)

    sfx_dir = paths.project_root() / "assets" / "sfx"
    sfx_events = [e for e in events if e.type == "sfx"]

    for ev in sfx_events:
        name = ev.params.get("name", "whoosh")
        sfx_file = sfx_dir / f"{name}.wav"
        if not sfx_file.is_file():
            # If sfx is missing, generate on the fly
            from scripts.make_sfx import main as generate_sfx
            generate_sfx()

        if not sfx_file.is_file():
            # Fall back to standard sounds if specific sound is missing (e.g. arrow -> whoosh)
            fallback = sfx_dir / "whoosh.wav" if (sfx_dir / "whoosh.wav").is_file() else (sfx_dir / "pop.wav")
            if fallback.is_file():
                sfx_file = fallback
            else:
                logger.warning("SFX asset %s not found; skipping", sfx_file)
                continue

        try:
            samples, _sr = _read_wav_floats(sfx_file)
            gain_db = float(ev.params.get("gain_db", -12.0))
            linear_gain = 10.0 ** (gain_db / 20.0)
            scaled = samples * linear_gain

            start_idx = max(0, round(ev.t * sample_rate))
            end_idx = min(num_samples, start_idx + len(scaled))
            copy_len = end_idx - start_idx
            if copy_len > 0:
                timeline[start_idx:end_idx] += scaled[:copy_len]
        except Exception as e:
            logger.warning("Failed to mix sfx event %s (%s): %s", ev.id, name, e)

    # Master limiter: limit to -1.0 dBFS (~0.8912)
    max_peak = np.max(np.abs(timeline))
    limit_floor = 10.0 ** (-1.0 / 20.0)  # ~0.89125
    if max_peak > limit_floor:
        timeline = timeline * (limit_floor / max_peak)

    # Write 16-bit PCM WAV
    int_samples = (np.clip(timeline, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int_samples.tobytes())

    return out_wav
