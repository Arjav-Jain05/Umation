"""FFmpeg and FFprobe subprocess wrappers, hardware acceleration, and audio analysis."""

from __future__ import annotations

import contextlib
import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.errors import FfmpegFailed

logger = logging.getLogger("app.utils.ffmpeg")


@dataclass
class ProbeInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    vcodec: str | None = None
    acodec: str | None = None


def _get_creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _get_startupinfo() -> subprocess.STARTUPINFO | None:
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        return si
    return None


@lru_cache(maxsize=16)
def has_encoder(name: str) -> bool:
    """Check if ffmpeg binary supports a specific encoder."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return False
    try:
        res = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            creationflags=_get_creation_flags(),
            startupinfo=_get_startupinfo(),
        )
        return name in res.stdout
    except Exception as e:
        logger.debug("Failed checking encoder %s: %s", name, e)
        return False


def nvenc_args(cq: int = 19, preset: str = "p5") -> list[str]:
    """Return hardware NVENC encoding args or fallback to CPU libx264."""
    if has_encoder("h264_nvenc"):
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            preset,
            "-rc",
            "vbr",
            "-cq",
            str(cq),
            "-b:v",
            "0",
            "-pix_fmt",
            "yuv420p",
        ]
    logger.warning("h264_nvenc not available; falling back to libx264")
    return [
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        str(cq),
        "-pix_fmt",
        "yuv420p",
    ]


def run_ffmpeg(
    args: list[str],
    *,
    cwd: Path | str | None = None,
    timeout: int = 3600,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Execute ffmpeg command safely with timeout and stderr tail on failure."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg_bin, "-hide_banner", "-y"] + [str(a) for a in args]

    # Log truncated command
    cmd_str = " ".join(cmd)
    logger.debug("Running ffmpeg: %s", cmd_str[:500])

    try:
        res = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_get_creation_flags(),
            startupinfo=_get_startupinfo(),
        )
    except subprocess.TimeoutExpired as e:
        raise FfmpegFailed(
            f"FFmpeg command timed out after {timeout} seconds",
            hint="Try reducing input duration or video resolution",
        ) from e

    if check and res.returncode != 0:
        stderr_lines = res.stderr.strip().splitlines()
        tail = "\n".join(stderr_lines[-20:]) if stderr_lines else "No stderr output"
        logger.error("FFmpeg failed (code %d):\n%s", res.returncode, tail)
        raise FfmpegFailed(
            f"FFmpeg failed with exit code {res.returncode}:\n{tail}",
            hint="Check that input media files are valid and accessible",
        )

    return res


def probe(path: Path | str) -> ProbeInfo:
    """Probe media file and extract duration, dimensions, framerate, and codecs."""
    ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Media file not found for probe: {p}")

    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-show_streams",
        "-of",
        "json",
        str(p),
    ]

    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        creationflags=_get_creation_flags(),
        startupinfo=_get_startupinfo(),
    )
    if res.returncode != 0:
        raise FfmpegFailed(f"ffprobe failed on {p}: {res.stderr}")

    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    format_info = data.get("format", {})

    duration = float(format_info.get("duration", 0.0))
    width = 0
    height = 0
    fps = 30.0
    vcodec = None
    acodec = None
    has_audio = False

    for st in streams:
        codec_type = st.get("codec_type")
        if codec_type == "video" and width == 0:
            width = int(st.get("width", 0))
            height = int(st.get("height", 0))
            vcodec = st.get("codec_name")
            r_fps = st.get("r_frame_rate", "30/1")
            try:
                if "/" in r_fps:
                    num, den = r_fps.split("/")
                    fps = float(num) / float(den) if float(den) > 0 else 30.0
                else:
                    fps = float(r_fps)
            except Exception:
                fps = 30.0
            if duration == 0.0 and "duration" in st:
                with contextlib.suppress(Exception):
                    duration = float(st["duration"])

        elif codec_type == "audio":
            has_audio = True
            if acodec is None:
                acodec = st.get("codec_name")

    return ProbeInfo(
        duration=round(duration, 3),
        width=width,
        height=height,
        fps=round(fps, 3),
        has_audio=has_audio,
        vcodec=vcodec,
        acodec=acodec,
    )


def extract_frame(
    video: Path | str,
    t: float,
    out_path: Path | str,
    max_side: int | None = None,
) -> Path:
    """Extract a single video frame at timestamp t to an image file."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    args = ["-y", "-ss", str(max(0.0, t)), "-i", str(video), "-frames:v", "1", "-pix_fmt", "yuvj420p"]
    if max_side is not None and max_side > 0:
        vf = f"scale='min({max_side},iw)':'min({max_side},ih)':force_original_aspect_ratio=decrease"
        args.extend(["-vf", vf])
    args.extend(["-update", "1", str(out)])

    run_ffmpeg(args, check=True)
    return out


def loudnorm_measure(audio_path: Path | str) -> dict[str, Any]:
    """Measure EBU R128 loudness metrics using ffmpeg loudnorm filter."""
    cmd = [
        "-i",
        str(audio_path),
        "-af",
        "loudnorm=I=-14:TP=-1:print_format=json",
        "-f",
        "null",
        "-",
    ]
    res = run_ffmpeg(cmd, check=False)
    # Extract JSON block from stderr
    stderr = res.stderr
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.DOTALL)
    if not match:
        logger.warning("Could not parse loudnorm measurement JSON from stderr; using defaults")
        return {"input_i": "-24.0", "input_tp": "-1.0", "input_lra": "7.0", "input_thresh": "-34.0"}

    try:
        return json.loads(match.group(0))
    except Exception as e:
        logger.warning("Failed parsing loudnorm JSON block: %s", e)
        return {"input_i": "-24.0", "input_tp": "-1.0", "input_lra": "7.0", "input_thresh": "-34.0"}
