"""Synthesize sound effects (whoosh, pop, ding) at 48 kHz mono using NumPy."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def synthesize_whoosh(sample_rate: int = 48000) -> np.ndarray:
    """Generate 0.35s band-limited noise with rising then falling filter envelope."""
    dur = 0.35
    num_samples = int(dur * sample_rate)
    t = np.linspace(0, dur, num_samples, endpoint=False)

    # White noise base
    rng = np.random.default_rng(42)
    noise = rng.uniform(-1.0, 1.0, num_samples)

    # Rising then falling envelope: sin^2 curve
    envelope = np.sin(np.pi * (t / dur)) ** 2

    # Smooth the noise with a moving average filter to simulate band-limiting
    window_size = int(0.002 * sample_rate)  # 2ms smoothing
    window = np.ones(window_size) / window_size
    smoothed = np.convolve(noise, window, mode="same")

    signal = smoothed * envelope
    # Normalize peak to 0.8
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak * 0.8
    return signal


def synthesize_pop(sample_rate: int = 48000) -> np.ndarray:
    """Generate 80ms sine sweep 700 -> 300 Hz with fast exponential decay."""
    dur = 0.08
    num_samples = int(dur * sample_rate)
    t = np.linspace(0, dur, num_samples, endpoint=False)

    # Frequency sweep 700 to 300 Hz
    f_start = 700.0
    f_end = 300.0
    freqs = np.linspace(f_start, f_end, num_samples)
    phase = 2 * np.pi * np.cumsum(freqs) / sample_rate

    # Fast decay envelope
    envelope = np.exp(-t * 40.0)
    signal = np.sin(phase) * envelope

    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak * 0.8
    return signal


def synthesize_ding(sample_rate: int = 48000) -> np.ndarray:
    """Generate 0.45s 880 Hz + 1760 Hz partial tone with exponential decay."""
    dur = 0.45
    num_samples = int(dur * sample_rate)
    t = np.linspace(0, dur, num_samples, endpoint=False)

    # Fundamental 880 Hz + overtone 1760 Hz
    tone1 = np.sin(2 * np.pi * 880.0 * t)
    tone2 = 0.5 * np.sin(2 * np.pi * 1760.0 * t)
    signal = tone1 + tone2

    # Exponential decay
    envelope = np.exp(-t * 8.0)
    signal = signal * envelope

    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak * 0.8
    return signal


def save_wav(path: Path, samples: np.ndarray, sample_rate: int = 48000) -> None:
    """Save 1D float array [-1, 1] as 16-bit PCM WAV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    int_samples = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int_samples.tobytes())


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    sfx_dir = root / "assets" / "sfx"
    sfx_dir.mkdir(parents=True, exist_ok=True)

    whoosh_path = sfx_dir / "whoosh.wav"
    pop_path = sfx_dir / "pop.wav"
    ding_path = sfx_dir / "ding.wav"

    save_wav(whoosh_path, synthesize_whoosh())
    save_wav(pop_path, synthesize_pop())
    save_wav(ding_path, synthesize_ding())

    print(f"Generated whoosh.wav ({whoosh_path.stat().st_size} bytes)")
    print(f"Generated pop.wav ({pop_path.stat().st_size} bytes)")
    print(f"Generated ding.wav ({ding_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
