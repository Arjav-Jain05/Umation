"""Hook card overlay: viral opening text card with animated pop-in and fade-out."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.core import paths
from app.pipeline.s4_director.effects.base import register_effect
from app.utils.easing import ease_out_back


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    font_path = paths.fonts_dir() / "Anton-Regular.ttf"
    if not font_path.is_file():
        font_path = paths.fonts_dir() / "Montserrat-ExtraBold.ttf"
    return ImageFont.truetype(str(font_path), size)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    curr = words[0]
    for w in words[1:]:
        test_line = f"{curr} {w}"
        bbox = font.getbbox(test_line)
        line_w = bbox[2] - bbox[0]
        if line_w <= max_width:
            curr = test_line
        else:
            lines.append(curr)
            curr = w
    lines.append(curr)
    return lines


@register_effect("hook_card")
class HookCardEffect:
    """Renders a rounded translucent hook card with Anton bold uppercase text."""

    def render(
        self,
        frame: np.ndarray,
        t_local: float,
        dur: float,
        params: dict[str, Any],
        canvas_w: int = 1080,
        canvas_h: int = 1920,
    ) -> np.ndarray:
        raw_text = str(params.get("text", "")).strip().upper()
        if not raw_text or dur <= 0.0:
            return frame

        # Timing & Animation
        pop_dur = 0.18
        fade_dur = 0.20

        if t_local < pop_dur:
            scale = 0.85 + 0.15 * ease_out_back(t_local / pop_dur)
            alpha_mult = min(1.0, t_local / 0.05)
        elif t_local > (dur - fade_dur):
            scale = 1.0
            alpha_mult = max(0.0, (dur - t_local) / fade_dur)
        else:
            scale = 1.0
            alpha_mult = 1.0

        if alpha_mult <= 0.01:
            return frame

        # Text size & line layout
        font_size = 96
        max_card_w = 960
        pad_x = 40
        pad_y = 30
        content_max_w = max_card_w - (pad_x * 2)

        font = _get_font(font_size)
        lines = _wrap_text(raw_text, font, content_max_w)
        while len(lines) > 2 and font_size > 64:
            font_size -= 8
            font = _get_font(font_size)
            lines = _wrap_text(raw_text, font, content_max_w)

        # Measure text box
        line_height = int(font_size * 1.05)
        text_h = len(lines) * line_height
        text_w = max([font.getbbox(lt)[2] - font.getbbox(lt)[0] for lt in lines]) if lines else 200

        card_w = min(max_card_w, text_w + (pad_x * 2))
        card_h = text_h + (pad_y * 2)

        # Draw card to RGBA sprite
        card_img = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(card_img)

        # Background rounded rect: rgba(0,0,0,0.62) fill, white 3px border at 25% alpha
        bg_alpha = int(255 * 0.62 * alpha_mult)
        border_alpha = int(255 * 0.25 * alpha_mult)
        draw.rounded_rectangle(
            [(0, 0), (card_w - 1, card_h - 1)],
            radius=28,
            fill=(0, 0, 0, bg_alpha),
            outline=(255, 255, 255, border_alpha),
            width=3,
        )

        # Draw lines centered
        curr_y = pad_y
        for line_text in lines:
            lb = font.getbbox(line_text)
            lw = lb[2] - lb[0]
            lx = (card_w - lw) // 2
            text_alpha = int(255 * alpha_mult)
            draw.text(
                (lx, curr_y),
                line_text,
                font=font,
                fill=(255, 255, 255, text_alpha),
                stroke_width=4,
                stroke_fill=(0, 0, 0, text_alpha),
            )
            curr_y += line_height

        # Scale animation transform
        if abs(scale - 1.0) > 0.01:
            sw = max(10, int(card_w * scale))
            sh = max(10, int(card_h * scale))
            card_img = card_img.resize((sw, sh), resample=Image.Resampling.BILINEAR)
            card_w, card_h = sw, sh

        # Composite onto frame at y ~ 380
        center_x = canvas_w // 2
        center_y = 380

        dest_x = max(0, center_x - (card_w // 2))
        dest_y = max(0, center_y - (card_h // 2))

        # Alpha composite Pillow image on numpy BGR frame
        base_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        base_pil.paste(card_img, (dest_x, dest_y), card_img)
        return cv2.cvtColor(np.array(base_pil), cv2.COLOR_RGB2BGR)
