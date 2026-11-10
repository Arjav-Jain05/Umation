"""Zoom punch effect: quick dramatic punch-in and ease-back on emphasis moments."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.pipeline.s4_director.effects.base import register_effect
from app.utils.easing import ease_in_out, ease_out_cubic


@register_effect("zoom_punch")
class ZoomPunchEffect:
    """Punch-in zoom with cubic ease-in/ease-out around an anchor point."""

    def render(
        self,
        frame: np.ndarray,
        t_local: float,
        dur: float,
        params: dict[str, Any],
        canvas_w: int = 1080,
        canvas_h: int = 1920,
    ) -> np.ndarray:
        target_scale = float(params.get("scale", 1.12))
        if target_scale <= 1.001 or dur <= 0.0:
            return frame

        # Compute dynamic scale s
        attack_time = 0.12
        decay_time = 0.25

        if t_local < attack_time:
            frac = t_local / attack_time
            s = 1.0 + (target_scale - 1.0) * ease_out_cubic(frac)
        elif t_local > (dur - decay_time):
            frac = max(0.0, (dur - t_local) / decay_time)
            s = 1.0 + (target_scale - 1.0) * ease_in_out(frac)
        else:
            s = target_scale

        if s <= 1.005:
            return frame

        # Anchor resolution
        anchor = params.get("anchor", "center")
        if isinstance(anchor, (list, tuple)) and len(anchor) == 2:
            ax, ay = float(anchor[0]), float(anchor[1])
        elif anchor == "gameplay_center":
            ax, ay = canvas_w / 2.0, 864.0
        else:
            ax, ay = canvas_w / 2.0, canvas_h / 2.0

        # Calculate crop rectangle
        crop_w = round(canvas_w / s)
        crop_h = round(canvas_h / s)

        x1 = max(0, min(canvas_w - crop_w, round(ax - (crop_w / 2.0))))
        y1 = max(0, min(canvas_h - crop_h, round(ay - (crop_h / 2.0))))

        cropped = frame[y1 : y1 + crop_h, x1 : x1 + crop_w]
        return cv2.resize(cropped, (canvas_w, canvas_h), interpolation=cv2.INTER_CUBIC)
