"""Stage 3: Audio cleanup, light compression, and layout-aware speech denoising."""

from __future__ import annotations

import logging
from pathlib import Path

from app.utils.ffmpeg import run_ffmpeg

logger = logging.getLogger("app.pipeline.s3_build.audio_clean")


def clean_audio(
    cut_video_or_audio: Path,
    layout: str,
    out_wav: Path,
) -> Path:
    """Produce clean 48 kHz stereo audio_clean.wav with optional talking_head denoise and compression."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    af_filters: list[str] = []

    # Optional speech denoise only for talking_head (never for gameplay, which harms game audio)
    if layout == "talking_head":
        af_filters.append("afftdn=nf=-25")

    # Light compression
    af_filters.append("acompressor=threshold=-18dB:ratio=3:attack=5:release=80")

    af_chain = ",".join(af_filters)

    args = [
        "-i", str(cut_video_or_audio),
        "-vn",
        "-af", af_chain,
        "-c:a", "pcm_s16le",
        "-ar", "48000",
        "-ac", "2",
        str(out_wav),
    ]

    run_ffmpeg(args, check=True)
    return out_wav
