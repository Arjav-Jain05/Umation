"""Face tracking exponential smoothing, dead zones, and velocity clamps."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SmoothedTrajectory:
    xs: list[float]  # Smoothed center-x values per frame (normalized [0, 1])


def smooth_face_trajectory(
    target_xs: list[float | None],
    fps: float = 30.0,
    crop_w: float = 0.5625,  # 9/16 normalized width in 16:9 frame
) -> list[float]:
    """Smooth face detection center-x coordinates with dead zone, velocity clamp, and lost-face hold."""
    n_frames = len(target_xs)
    if n_frames == 0:
        return []

    # Valid targets for baseline median
    valid_targets = [x for x in target_xs if x is not None]
    default_center = float(np.median(valid_targets)) if valid_targets else 0.5

    # 30 fps scaling: alpha = 0.15 * (30.0 / fps)
    alpha = max(0.01, min(0.5, 0.15 * (30.0 / max(1.0, fps))))
    dead_zone = 0.04 * crop_w
    max_vel_per_frame = (0.5 * crop_w) / max(1.0, fps)

    lost_hold_frames = int(1.5 * fps)
    lost_ease_frames = int(1.0 * fps)

    smoothed: list[float] = []
    current_x = default_center
    lost_count = 0
    hold_pos = default_center

    for x_target in target_xs:
        if x_target is None:
            lost_count += 1
            if lost_count <= lost_hold_frames:
                # Hold last known position
                target = hold_pos
            elif lost_count <= (lost_hold_frames + lost_ease_frames):
                # Ease towards median position
                frac = (lost_count - lost_hold_frames) / max(1, lost_ease_frames)
                target = hold_pos + frac * (default_center - hold_pos)
            else:
                target = default_center
        else:
            lost_count = 0
            target = x_target
            hold_pos = target

        # 1. Dead zone: ignore tiny movements
        diff = target - current_x
        if abs(diff) < dead_zone:
            target = current_x

        # 2. Exponential smoothing
        step = alpha * (target - current_x)

        # 3. Velocity limit clamp
        if abs(step) > max_vel_per_frame:
            step = max_vel_per_frame if step > 0 else -max_vel_per_frame

        current_x += step

        # Clamp crop center so 9:16 window stays inside [0, 1] frame
        half_w = crop_w / 2.0
        clamped_x = max(half_w, min(1.0 - half_w, current_x))
        smoothed.append(round(clamped_x, 4))

    return smoothed
