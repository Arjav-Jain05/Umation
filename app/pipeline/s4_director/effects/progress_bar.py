"""Progress bar overlay: sleek yellow horizontal progress line indicating clip playback progress."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.pipeline.s4_director.effects.base import register_effect


@register_effect("progress_bar")
class ProgressBarEffect:
    """Renders a top progress track with yellow fill showing elapsed playback percentage."""

    def render(
        self,
        frame: np.ndarray,
        t_local: float,
        dur: float,
        params: dict[str, Any],
        canvas_w: int = 1080,
        canvas_h: int = 1920,
    ) -> np.ndarray:
        if dur <= 0.0:
            return frame

        y = 204
        height = 8

        # Track: rgba(255, 255, 255, 0.25) across full width
        track_roi = frame[y : y + height, 0:canvas_w]
        white_overlay = np.full_like(track_roi, 255)
        # Blend 25% white into background
        frame[y : y + height, 0:canvas_w] = cv2.addWeighted(track_roi, 0.75, white_overlay, 0.25, 0)

        # Fill: #FFD400 (BGR: 0, 212, 255) width = t / duration * 1080
        progress_frac = min(1.0, max(0.0, t_local / dur))
        fill_w = round(progress_frac * canvas_w)

        if fill_w > 0:
            # Solid BGR (0, 212, 255)
            frame[y : y + height, 0:fill_w] = (0, 212, 255)

        return frame
