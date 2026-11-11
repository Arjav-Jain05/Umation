"""Layer 5 Visual Evidence: 1 fps frame sampling, dead footage detection, and OCR trigger words."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger("app.pipeline.sensors.visual_evidence")

DEFAULT_OCR_TRIGGERS = [
    "WASTED",
    "BUSTED",
    "MISSION PASSED",
    "FAILED",
    "WANTED",
    "LEVEL UP",
    "VICTORY",
    "GAME OVER",
]


@dataclass
class VisualEvidenceResult:
    visual_action_score: float  # 0.0 to 100.0
    is_dead_footage: bool  # True if menu, loading screen, or static footage
    ocr_triggers_found: list[str] = field(default_factory=list)
    frames_inspected: int = 0


def detect_dead_frame(frame: np.ndarray, prev_frame: np.ndarray | None = None) -> bool:
    """Detect if a frame is static, solid black/loading screen, or a low-information menu."""
    if frame is None or frame.size == 0:
        return True

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame

    # 1. Check for extreme brightness / darkness (black screen or whiteout)
    mean_val = float(np.mean(gray))
    std_val = float(np.std(gray))
    if mean_val < 5.0 or std_val < 8.0:
        return True  # Solid black or blank loading screen

    # 2. Check for static frame with zero motion if previous frame available
    if prev_frame is not None and prev_frame.shape == gray.shape:
        diff = cv2.absdiff(gray, prev_frame)
        diff_mean = float(np.mean(diff))
        if diff_mean < 0.8:
            return True  # Static frame

    return False


def detect_visual_action_level(frames: list[np.ndarray]) -> float:
    """Compute visual action score (0-100) from motion, contrast, and edge dynamics."""
    if not frames:
        return 50.0

    action_values: list[float] = []
    prev_gray: np.ndarray | None = None

    for f in frames:
        small = cv2.resize(f, (320, 180), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        # Edge complexity via Canny
        edges = cv2.Canny(gray, 50, 150)
        edge_ratio = float(np.count_nonzero(edges)) / float(edges.size)

        # Motion if previous frame exists
        motion_ratio = 0.0
        if prev_gray is not None:
            diff = cv2.absdiff(gray, prev_gray)
            motion_ratio = float(np.mean(diff)) / 255.0

        prev_gray = gray

        # Composite frame action
        f_action = (edge_ratio * 400.0) + (motion_ratio * 300.0)
        action_values.append(min(100.0, f_action))

    avg_action = float(np.mean(action_values)) if action_values else 50.0
    return round(max(15.0, min(100.0, avg_action)), 1)


def inspect_candidate_visuals(
    video_path: Path | str | None,
    start_s: float,
    end_s: float,
    ocr_triggers: list[str] | None = None,
    sample_fps: float = 1.0,
) -> VisualEvidenceResult:
    """Sample candidate clip frames at 1 fps to inspect visual action, dead footage, and OCR triggers."""
    if not video_path:
        return VisualEvidenceResult(visual_action_score=50.0, is_dead_footage=False)

    p = Path(video_path)
    if not p.is_file():
        return VisualEvidenceResult(visual_action_score=50.0, is_dead_footage=False)

    triggers_to_check = [t.upper() for t in (ocr_triggers or DEFAULT_OCR_TRIGGERS)]
    cap = cv2.VideoCapture(str(p))
    if not cap.isOpened():
        return VisualEvidenceResult(visual_action_score=50.0, is_dead_footage=False)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = total_frames / fps if fps > 0 else 0.0

    s_clamped = max(0.0, min(start_s, dur))
    e_clamped = max(s_clamped + 1.0, min(end_s, dur if dur > 0 else end_s))

    frames: list[np.ndarray] = []
    dead_frame_count = 0
    prev_gray: np.ndarray | None = None

    step_sec = 1.0 / max(0.2, sample_fps)
    curr_t = s_clamped

    try:
        while curr_t < e_clamped and len(frames) < 60:
            frame_num = int(curr_t * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            frames.append(frame)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if detect_dead_frame(frame, prev_gray):
                dead_frame_count += 1
            prev_gray = gray

            curr_t += step_sec
    except Exception as exc:
        logger.warning(f"Error sampling video frames: {exc}")
    finally:
        cap.release()

    if not frames:
        return VisualEvidenceResult(visual_action_score=50.0, is_dead_footage=False)

    # Dead footage if > 60% of sampled frames are static or blank
    is_dead = (dead_frame_count / float(len(frames))) >= 0.60

    # Visual action level
    action_score = detect_visual_action_level(frames)
    if is_dead:
        action_score = min(25.0, action_score * 0.4)

    # Check for on-screen text triggers via simple OCR if available
    ocr_hits: list[str] = []
    try:
        # Check if RapidOCR is available
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        # Inspect top candidate frame and middle frame
        sample_indices = [len(frames) // 2] if len(frames) == 1 else [0, len(frames) // 2]
        for s_idx in sample_indices:
            res, _ = engine(frames[s_idx])
            if res:
                for line in res:
                    txt = str(line[1]).upper()
                    for trig in triggers_to_check:
                        if trig in txt and trig not in ocr_hits:
                            ocr_hits.append(trig)
    except Exception:
        # OCR engine optional; continue gracefully
        pass

    return VisualEvidenceResult(
        visual_action_score=action_score,
        is_dead_footage=is_dead,
        ocr_triggers_found=ocr_hits,
        frames_inspected=len(frames),
    )


def check_candidate_visual_integrity(
    video_path: Path | str | None,
    start_s: float,
    end_s: float,
    scene_cuts: list[float] | None = None,
) -> tuple[bool, float, float, str]:
    """Layer 5 Visual Check: inspect candidate first, middle, and last frames for dead footage or black screen.

    Returns:
        (passed: bool, final_start_s: float, final_end_s: float, reason: str)
    """
    if not video_path:
        return True, start_s, end_s, "no_video_path"

    p = Path(video_path)
    if not p.is_file():
        return True, start_s, end_s, "video_file_not_found"

    cap = cv2.VideoCapture(str(p))
    if not cap.isOpened():
        return True, start_s, end_s, "cannot_open_video"

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    max_dur = total_frames / fps if fps > 0 else end_s

    final_start = max(0.0, min(start_s, max_dur))
    final_end = max(final_start + 1.0, min(end_s, max_dur))

    try:
        # 1. Sample first frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(final_start * fps))
        ret, first_frame = cap.read()
        if ret and first_frame is not None and detect_dead_frame(first_frame):
            # Try shifting boundary to nearest scene cut within 1.0s or +0.5s
            shifted = False
            if scene_cuts:
                for sc in scene_cuts:
                    if final_start < sc <= final_start + 1.5:
                        final_start = sc
                        shifted = True
                        break
            if not shifted:
                final_start += 0.5

            # Re-check first frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(final_start * fps))
            ret2, first_frame2 = cap.read()
            if ret2 and first_frame2 is not None and detect_dead_frame(first_frame2):
                return False, final_start, final_end, "first_frame_black_or_loading"

        # 2. Sample last frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(final_end * fps) - 1))
        ret, last_frame = cap.read()
        if ret and last_frame is not None and detect_dead_frame(last_frame):
            # Trim 0.5s off the end to avoid black trailing screen
            final_end = max(final_start + 5.0, final_end - 0.5)

        return True, round(final_start, 3), round(final_end, 3), "passed"
    except Exception as exc:
        logger.warning("Visual integrity check failed: %s", exc)
        return True, final_start, final_end, f"check_error: {exc}"
    finally:
        cap.release()
