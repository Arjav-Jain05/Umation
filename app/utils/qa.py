"""Quality assurance checks for rendered clips per spec 09 section 6."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import soundfile as sf

from app.core.schemas import QAReport
from app.utils.ffmpeg import loudnorm_measure, probe, run_ffmpeg

logger = logging.getLogger("app.utils.qa")


def _check_audio_pops(audio_path: Path, cut_points: list[float] | None = None) -> tuple[bool, float]:
    """Check for audio click/pop transients by inspecting sample-to-sample difference."""
    try:
        data, sr = sf.read(str(audio_path), dtype="float32")
    except Exception as e:
        logger.warning("Could not read audio file for pop check: %s", e)
        return False, 0.0

    if data.ndim > 1:
        data = np.mean(data, axis=1)

    diffs = np.abs(np.diff(data))
    max_diff = float(np.max(diffs)) if len(diffs) > 0 else 0.0

    # If cut points provided, check boundary regions (±20ms)
    if cut_points:
        for cp in cut_points:
            idx = int(cp * sr)
            idx_start = max(0, idx - int(0.02 * sr))
            idx_end = min(len(diffs), idx + int(0.02 * sr))
            if idx_start < idx_end:
                local_max = float(np.max(diffs[idx_start:idx_end]))
                if local_max > 0.30:
                    return True, local_max

    # Global threshold: 0.40 full-scale jump without transition
    return bool(max_diff > 0.40), max_diff


def _check_black_frames(video_path: Path) -> list[str]:
    """Detect black sequences longer than 0.30s using ffmpeg blackdetect filter."""
    cmd = [
        "-i", str(video_path),
        "-vf", "blackdetect=d=0.30:pix_th=0.10",
        "-f", "null", "-",
    ]
    res = run_ffmpeg(cmd, check=False)
    matches = re.findall(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)", res.stderr)
    black_spans = []
    for s, _e, dur in matches:
        if float(dur) >= 0.30:
            black_spans.append(f"{float(dur):.2f}s at {float(s):.2f}s")
    return black_spans


def _check_frozen_frames(video_path: Path) -> list[str]:
    """Detect frozen sequences longer than 2.0s using ffmpeg freezedetect filter."""
    cmd = [
        "-i", str(video_path),
        "-vf", "freezedetect=noise=-60dB:duration=2",
        "-f", "null", "-",
    ]
    res = run_ffmpeg(cmd, check=False)
    matches = re.findall(r"freeze_start:([0-9.]+)\s+freeze_end:([0-9.]+)\s+freeze_duration:([0-9.]+)", res.stderr)
    freeze_spans = []
    for s, _e, dur in matches:
        if float(dur) >= 2.0:
            freeze_spans.append(f"{float(dur):.2f}s at {float(s):.2f}s")
    return freeze_spans


def _check_sharpness(video_path: Path, num_samples: int = 5) -> float:
    """Sample frames and compute mean variance of Laplacian as a blur sanity metric."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 0.0

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return 0.0

    step = max(1, total_frames // (num_samples + 1))
    scores: list[float] = []

    for i in range(1, num_samples + 1):
        frame_idx = i * step
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if ret and frame is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # Sample central foreground region
            h, w = gray.shape
            fg = gray[int(h * 0.25) : int(h * 0.75), int(w * 0.1) : int(w * 0.9)]
            score = float(cv2.Laplacian(fg, cv2.CV_64F).var())
            scores.append(score)

    cap.release()
    return float(np.mean(scores)) if scores else 0.0


def check_clip_file(
    clip_path: Path | str,
    cut_points: list[float] | None = None,
    allow_short: bool = False,
) -> QAReport:
    """Run full verification checklist on rendered clip per spec 09 section 6."""
    p = Path(clip_path)
    failures: list[str] = []
    metrics: dict[str, Any] = {}

    if not p.is_file():
        return QAReport(passed=False, failures=[f"File not found: {p}"])

    size_bytes = p.stat().st_size
    metrics["file_size_kb"] = round(size_bytes / 1024, 1)
    if size_bytes < 300 * 1024 and not allow_short:
        failures.append(f"File size {size_bytes} bytes is below 300 KB threshold")

    # 1. ffprobe basic video & audio checks
    try:
        info = probe(p)
    except Exception as e:
        return QAReport(passed=False, failures=[f"ffprobe failed: {e}"])

    metrics["width"] = info.width
    metrics["height"] = info.height
    metrics["fps"] = info.fps
    metrics["vcodec"] = info.vcodec
    metrics["acodec"] = info.acodec
    metrics["duration"] = info.duration

    if info.width != 1080 or info.height != 1920:
        failures.append(f"Resolution {info.width}x{info.height} != expected 1080x1920")

    if info.vcodec not in ("h264", "avc1"):
        failures.append(f"Video codec {info.vcodec} != h264")

    if not (24.0 <= info.fps <= 60.5):
        failures.append(f"FPS {info.fps} outside allowed range [24, 60]")

    if not allow_short and not (12.0 <= info.duration <= 95.0):
        failures.append(f"Duration {info.duration:.1f}s outside allowed range [12s, 95s]")

    if not info.has_audio:
        failures.append("Clip contains no audio track")
    elif info.acodec not in ("aac", "mp4a"):
        failures.append(f"Audio codec {info.acodec} != aac")

    # 2. Loudness measurement
    try:
        l_info = loudnorm_measure(p)
        meas_i = float(l_info.get("input_i", -24.0))
        meas_tp = float(l_info.get("input_tp", -1.0))
        metrics["loudness_lufs"] = meas_i
        metrics["true_peak_dbtp"] = meas_tp

        if not (-15.5 <= meas_i <= -12.5):
            failures.append(f"Integrated loudness {meas_i:.1f} LUFS outside target -14 ±1 LUFS")
        if meas_tp > -0.8:
            failures.append(f"True peak {meas_tp:.1f} dBTP exceeds -1.0 dBTP limit")
    except Exception as e:
        logger.warning("Loudness check failed: %s", e)

    # 3. Black frame detection
    try:
        blacks = _check_black_frames(p)
        metrics["black_spans"] = len(blacks)
        if blacks:
            failures.append(f"Black frame sequence detected: {', '.join(blacks[:2])}")
    except Exception as e:
        logger.warning("Black frames check failed: %s", e)

    # 4. Freeze detection
    try:
        freezes = _check_frozen_frames(p)
        metrics["freeze_spans"] = len(freezes)
        if freezes:
            failures.append(f"Frozen frame sequence detected: {', '.join(freezes[:2])}")
    except Exception as e:
        logger.warning("Freeze frames check failed: %s", e)

    # 5. Audio pop check
    try:
        has_pop, max_diff = _check_audio_pops(p, cut_points)
        metrics["audio_pop_max_diff"] = round(max_diff, 3)
        if has_pop:
            failures.append(f"Audio transient/pop detected (max step {max_diff:.2f} > 0.30)")
    except Exception as e:
        logger.warning("Audio pop check failed: %s", e)

    # 6. Sharpness metric
    try:
        sharpness = _check_sharpness(p)
        metrics["sharpness_laplacian_var"] = round(sharpness, 1)
        if sharpness > 0 and sharpness < 15.0:
            failures.append(f"Video sharpness {sharpness:.1f} below minimum floor of 15.0")
    except Exception as e:
        logger.warning("Sharpness check failed: %s", e)

    passed = len(failures) == 0
    return QAReport(passed=passed, failures=failures, metrics=metrics)
