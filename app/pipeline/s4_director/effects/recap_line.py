"""Recap line overlay: subtle contextual recap line for Part 2+ clips."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.core import paths
from app.pipeline.s4_director.effects.base import register_effect


def _get_font(size: int = 52) -> ImageFont.FreeTypeFont:
    font_path = paths.fonts_dir() / "Montserrat-ExtraBold.ttf"
    return ImageFont.truetype(str(font_path), size)


@register_effect("recap_line")
class RecapLineEffect:
    """Renders a centered context recap line with stroke and fade."""

    def render(
        self,
        frame: np.ndarray,
        t_local: float,
        dur: float,
        params: dict[str, Any],
        canvas_w: int = 1080,
        canvas_h: int = 1920,
    ) -> np.ndarray:
        text = str(params.get("text", "")).strip()
        if not text or dur <= 0.0:
            return frame

        # Fade in 0.2s, fade out 0.2s
        fade_in = 0.20
        fade_out = 0.20

        if t_local < fade_in:
            alpha_mult = min(1.0, t_local / fade_in)
        elif t_local > (dur - fade_out):
            alpha_mult = max(0.0, (dur - t_local) / fade_out)
        else:
            alpha_mult = 1.0

        if alpha_mult <= 0.01:
            return frame

        font = _get_font(52)
        bbox = font.getbbox(text)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        alpha_int = int(255 * alpha_mult)
        img = Image.new("RGBA", (text_w + 40, text_h + 30), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.text(
            (20 - bbox[0], 15 - bbox[1]),
            text,
            font=font,
            fill=(255, 255, 255, alpha_int),
            stroke_width=4,
            stroke_fill=(0, 0, 0, alpha_int),
        )

        dest_x = max(60, (canvas_w - (text_w + 40)) // 2)
        dest_y = 560

        base_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        base_pil.paste(img, (dest_x, dest_y), img)
        return cv2.cvtColor(np.array(base_pil), cv2.COLOR_RGB2BGR)
