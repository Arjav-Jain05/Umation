"""Highlight box overlay: pulsing yellow rounded boundary highlighting visual targets."""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

from app.pipeline.s4_director.effects.arrow import _interpolate_track
from app.pipeline.s4_director.effects.base import register_effect
from app.utils.easing import ease_out_back
from app.utils.geometry import Box, expand


@register_effect("highlight_box")
class HighlightBoxEffect:
    """Renders a pulsing yellow rounded rectangle outline around target coordinates."""

    def render(
        self,
        frame: np.ndarray,
        t_local: float,
        dur: float,
        params: dict[str, Any],
        canvas_w: int = 1080,
        canvas_h: int = 1920,
    ) -> np.ndarray:
        bbox = params.get("bbox")
        track = params.get("track")
        if track:
            interp = _interpolate_track(track, t_local)
            if interp:
                bbox = interp
        if not bbox or len(bbox) != 4 or dur <= 0.0:
            return frame

        bx1, by1, bx2, by2 = bbox
        base_box = Box(float(bx1), float(by1), float(bx2), float(by2))

        # Timing & Animation
        draw_in_dur = 0.20
        fade_dur = 0.20

        if t_local < draw_in_dur:
            scale = 0.85 + 0.15 * ease_out_back(t_local / draw_in_dur)
            alpha_fade = min(1.0, t_local / 0.05)
        elif t_local > (dur - fade_dur):
            scale = 1.0
            alpha_fade = max(0.0, (dur - t_local) / fade_dur)
        else:
            scale = 1.0
            alpha_fade = 1.0

        if alpha_fade <= 0.01:
            return frame

        # Pulse alpha 0.75 - 1.0 at 3 Hz
        pulse_alpha = 0.875 + 0.125 * math.sin(2.0 * math.pi * 3.0 * t_local)
        final_alpha = int(255 * pulse_alpha * alpha_fade)

        # Expand 10px beyond bbox
        exp_box = expand(base_box, pct=0.0)
        # Add 10px constant padding
        x1 = exp_box.x1 - 10.0
        y1 = exp_box.y1 - 10.0
        x2 = exp_box.x2 + 10.0
        y2 = exp_box.y2 + 10.0

        w = x2 - x1
        h = y2 - y1
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0

        # Scale from center
        sw = max(10.0, w * scale)
        sh = max(10.0, h * scale)
        sx1 = max(0, round(cx - (sw / 2.0)))
        sy1 = max(0, round(cy - (sh / 2.0)))
        sx2 = min(canvas_w - 1, round(cx + (sw / 2.0)))
        sy2 = min(canvas_h - 1, round(cy + (sh / 2.0)))

        if sx2 <= sx1 + 10 or sy2 <= sy1 + 10:
            return frame

        # Draw rounded rect on transparent layer
        overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rounded_rectangle(
            [(sx1, sy1), (sx2, sy2)],
            radius=18,
            outline=(255, 212, 0, final_alpha),
            width=6,
        )

        # Composite onto frame
        base_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        base_pil.paste(overlay, (0, 0), overlay)
        return cv2.cvtColor(np.array(base_pil), cv2.COLOR_RGB2BGR)
