"""CSRT object tracking for video overlay targets across time."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2

from app.utils.geometry import Box, clamp_box

logger = logging.getLogger("app.pipeline.s4_director.tracker")


def track_box(
    video_path: Path,
    t0: float,
    dur: float,
    bbox: list[int] | tuple[int, ...],
    fps: float = 30.0,
    static: bool = False,
) -> list[list[float]]:
    """Track bounding box across frames from t0 to t0+dur.

    Returns a list of [t_offset, x1, y1, x2, y2] sampled at 10 Hz.
    If static=True or tracker fails, freezes the last good box.
    """
    x1, y1, x2, y2 = bbox
    init_box = Box(float(x1), float(y1), float(x2), float(y2))
    orig_area = max(1.0, init_box.area)

    # If marked static, return steady trajectory
    if static:
        samples: list[list[float]] = []
        t = 0.0
        while t <= dur + 0.05:
            samples.append([round(t, 2), float(x1), float(y1), float(x2), float(y2)])
            t += 0.10
        return samples

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.warning("Could not open video %s for tracking; returning static box", video_path)
        return [[0.0, float(x1), float(y1), float(x2), float(y2)]]

    actual_fps = cap.get(cv2.CAP_PROP_FPS) or fps
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1080)
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1920)

    start_frame = max(0, round(t0 * actual_fps))
    total_frames = max(1, round(dur * actual_fps))
    end_frame = start_frame + total_frames

    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    ret, frame = cap.read()
    if not ret or frame is None:
        cap.release()
        return [[0.0, float(x1), float(y1), float(x2), float(y2)]]

    # Initialize TrackerCSRT
    tracker = cv2.TrackerCSRT_create()
    xywh = (round(init_box.x1), round(init_box.y1), round(init_box.w), round(init_box.h))
    tracker.init(frame, xywh)

    tracked_frames: list[tuple[float, Box]] = [(0.0, init_box)]
    curr_frame_idx = start_frame + 1
    last_good_box = init_box
    tracking_failed = False

    while curr_frame_idx <= end_frame:
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        t_offset = (curr_frame_idx - start_frame) / actual_fps

        if not tracking_failed:
            success, box_out = tracker.update(frame)
            if success:
                bx, by, bw, bh = box_out
                new_box = Box(float(bx), float(by), float(bx + bw), float(by + bh))
                clamped = clamp_box(new_box, w=frame_w, h=frame_h)

                # Check failure rules from 06 s8:
                # 1. Area changes by > 2.2x or < 1/2.2
                area_ratio = clamped.area / orig_area
                area_exploded = area_ratio > 2.2 or area_ratio < (1.0 / 2.2)

                # 2. Centre jumps > 25% of frame width in one frame
                center_jump = abs(clamped.center[0] - last_good_box.center[0]) > (0.25 * frame_w)

                if area_exploded or center_jump:
                    logger.info("Tracker diverged at frame %d (area_ratio=%.2f, jump=%.1fpx); freezing", curr_frame_idx, area_ratio, abs(clamped.center[0] - last_good_box.center[0]))
                    tracking_failed = True
                else:
                    last_good_box = clamped
            else:
                logger.info("Tracker lost target at frame %d; freezing", curr_frame_idx)
                tracking_failed = True

        tracked_frames.append((t_offset, last_good_box))
        curr_frame_idx += 1

    cap.release()

    # Subsample to 10 Hz
    step = max(1, round(actual_fps / 10.0))
    result: list[list[float]] = []
    for idx, (t_off, b) in enumerate(tracked_frames):
        if idx % step == 0 or idx == len(tracked_frames) - 1:
            ix1, iy1, ix2, iy2 = b.as_list()
            result.append([round(t_off, 2), float(ix1), float(iy1), float(ix2), float(iy2)])

    return result
