"""Layer 1 Visual Motion & Scene Cut Sensor: 2 fps frame difference motion energy and histogram scene cut detection."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger("app.pipeline.sensors.scene_motion")


@dataclass
class MotionProfile:
    duration_s: float
    per_second_motion: np.ndarray  # shape: (num_seconds,)
    scene_cuts: list[float] = field(default_factory=list)


def extract_video_motion(video_path: Path | str | None, max_sample_fps: float = 2.0) -> MotionProfile:
    """Sample video at 2 fps and compute motion energy track and scene cuts."""
    if not video_path:
        return MotionProfile(duration_s=0.0, per_second_motion=np.array([], dtype=np.float32))

    p = Path(video_path)
    if not p.is_file():
        logger.info(f"Video file {p} not available for motion sensor; returning empty profile")
        return MotionProfile(duration_s=0.0, per_second_motion=np.array([], dtype=np.float32))

    cap = cv2.VideoCapture(str(p))
    if not cap.isOpened():
        logger.warning(f"Failed to open video file {p} with cv2")
        return MotionProfile(duration_s=0.0, per_second_motion=np.array([], dtype=np.float32))

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_s = total_frames / fps if fps > 0 else 0.0
    num_seconds = max(1, math.ceil(duration_s))

    frame_interval = max(1, round(fps / max_sample_fps))

    prev_gray: np.ndarray | None = None
    prev_hist: np.ndarray | None = None

    sec_diff_accum: dict[int, list[float]] = {}
    scene_cuts: list[float] = []

    frame_idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_interval == 0:
                t_s = frame_idx / fps
                sec = math.floor(t_s)

                # Resize to 320x180 for ultra fast processing
                small = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

                # Compute histogram for scene cut detection
                hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
                cv2.normalize(hist, hist)

                if prev_gray is not None and prev_hist is not None:
                    # Mean absolute frame difference
                    diff = cv2.absdiff(gray, prev_gray)
                    mean_diff = float(np.mean(diff)) / 255.0

                    if sec not in sec_diff_accum:
                        sec_diff_accum[sec] = []
                    sec_diff_accum[sec].append(mean_diff)

                    # Histogram correlation: < 0.55 indicates sudden scene transition
                    hist_corr = float(cv2.compareHist(hist, prev_hist, cv2.HISTCMP_CORREL))
                    if hist_corr < 0.55 or mean_diff > 0.38:
                        scene_cuts.append(round(t_s, 2))

                prev_gray = gray
                prev_hist = hist

            frame_idx += 1
    except Exception as exc:
        logger.warning(f"Error during video motion extraction: {exc}")
    finally:
        cap.release()

    per_second_motion = np.zeros(num_seconds, dtype=np.float32)
    for sec, diffs in sec_diff_accum.items():
        if sec < num_seconds and diffs:
            per_second_motion[sec] = float(np.mean(diffs))

    # Normalize motion energy to 0.0 - 1.0 within video
    max_m = float(np.max(per_second_motion)) if len(per_second_motion) > 0 else 1.0
    if max_m > 1e-6:
        per_second_motion = per_second_motion / max_m

    return MotionProfile(
        duration_s=duration_s,
        per_second_motion=per_second_motion,
        scene_cuts=scene_cuts,
    )


def score_motion_window(
    start_s: float,
    end_s: float,
    profile: MotionProfile,
) -> tuple[float, int]:
    """Score motion energy and count scene cuts in [start_s, end_s].

    Returns:
        (motion_score_0_to_100, scene_cuts_count)
    """
    if len(profile.per_second_motion) == 0:
        return 50.0, 0

    s_sec = max(0, math.floor(start_s))
    e_sec = min(len(profile.per_second_motion), math.ceil(end_s))
    if s_sec >= e_sec:
        e_sec = s_sec + 1

    window_motion = profile.per_second_motion[s_sec:e_sec]
    if len(window_motion) == 0:
        return 50.0, 0

    avg_m = float(np.mean(window_motion))
    max_m = float(np.max(window_motion))
    motion_score = (avg_m * 70.0) + (max_m * 30.0)

    # Count scene cuts in window
    cuts_in_window = [c for c in profile.scene_cuts if start_s <= c <= end_s]

    return round(min(100.0, max(0.0, motion_score * 100.0)), 1), len(cuts_in_window)
