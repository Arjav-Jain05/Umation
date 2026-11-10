"""Part label badge overlay: solid yellow badge at top-left indicating multi-part series."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.core import paths
from app.pipeline.s4_director.effects.base import register_effect


def _get_font(size: int = 40) -> ImageFont.FreeTypeFont:
    font_path = paths.fonts_dir() / "Montserrat-ExtraBold.ttf"
    return ImageFont.truetype(str(font_path), size)


@register_effect("part_label")
class PartLabelEffect:
    """Renders a solid yellow rounded badge at top-left with black bold text."""

    def render(
        self,
        frame: np.ndarray,
        t_local: float,
        dur: float,
        params: dict[str, Any],
        canvas_w: int = 1080,
        canvas_h: int = 1920,
    ) -> np.ndarray:
        text = str(params.get("text", "PART 1/2")).strip().upper()
        if not text:
            return frame

        font = _get_font(40)
        bbox = font.getbbox(text)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        pad_x = 24
        chip_h = 64
        chip_w = text_w + (pad_x * 2)

        chip = Image.new("RGBA", (chip_w, chip_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(chip)

        # Background: rgba(255, 212, 0, 1) #FFD400 with radius 16
        draw.rounded_rectangle([(0, 0), (chip_w - 1, chip_h - 1)], radius=16, fill=(255, 212, 0, 255))

        # Text: black #000000 centered vertically
        tx = pad_x
        ty = (chip_h - text_h) // 2 - bbox[1]
        draw.text((tx, ty), text, font=font, fill=(0, 0, 0, 255))

        # Position at top-left: x=60, y=240
        base_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        base_pil.paste(chip, (60, 240), chip)
        return cv2.cvtColor(np.array(base_pil), cv2.COLOR_RGB2BGR)
