"""Emoji pop effect: animated expressive emoji icon with pop scale and float-up."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.core import paths
from app.pipeline.s4_director.effects.base import register_effect
from app.utils.easing import ease_out_back

logger = logging.getLogger("app.pipeline.s4_director.effects.emoji_pop")


@register_effect("emoji_pop")
class EmojiPopEffect:
    """Renders a color emoji sprite with pop-in, float-up and fade-out animation."""

    def __init__(self) -> None:
        self._font_cache: ImageFont.FreeTypeFont | None = None
        self._sprite_cache: dict[str, Image.Image] = {}

    def _get_fonts(self) -> list[ImageFont.FreeTypeFont]:
        fonts: list[ImageFont.FreeTypeFont] = []
        noto_path = paths.fonts_dir() / "NotoColorEmoji.ttf"
        if noto_path.is_file():
            with contextlib.suppress(Exception):
                fonts.append(ImageFont.truetype(str(noto_path), 109))

        # Windows system emoji font fallback
        win_emoji = Path("C:/Windows/Fonts/seguiemj.ttf")
        if win_emoji.is_file():
            with contextlib.suppress(Exception):
                fonts.append(ImageFont.truetype(str(win_emoji), 109))
        return fonts

    def _get_emoji_sprite(self, emoji_char: str) -> Image.Image | None:
        if emoji_char in self._sprite_cache:
            return self._sprite_cache[emoji_char]

        fonts = self._get_fonts()
        if not fonts:
            return None

        for font in fonts:
            try:
                # Render emoji onto transparent canvas
                img = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                draw.text((10, 10), emoji_char, font=font, embedded_color=True)
                if img.getbbox() is not None:
                    # Resize to target 200x200 px
                    scaled = img.resize((200, 200), resample=Image.Resampling.LANCZOS)
                    self._sprite_cache[emoji_char] = scaled
                    return scaled
            except Exception as e:
                logger.debug("Font failed to render emoji '%s': %s", emoji_char, e)

        logger.warning("No font could render emoji '%s'", emoji_char)
        return None

    def render(
        self,
        frame: np.ndarray,
        t_local: float,
        dur: float,
        params: dict[str, Any],
        canvas_w: int = 1080,
        canvas_h: int = 1920,
    ) -> np.ndarray:
        emoji_char = str(params.get("emoji", "🔥")).strip()
        if not emoji_char or dur <= 0.0:
            return frame

        sprite = self._get_emoji_sprite(emoji_char)
        if sprite is None:
            return frame

        # Timing & Animation
        pop_dur = 0.25
        fade_dur = 0.20

        if t_local < pop_dur:
            scale = ease_out_back(t_local / pop_dur, overshoot=1.15)
            alpha_mult = min(1.0, t_local / 0.05)
        elif t_local > (dur - fade_dur):
            scale = 1.0
            alpha_mult = max(0.0, (dur - t_local) / fade_dur)
        else:
            scale = 1.0
            alpha_mult = 1.0

        if alpha_mult <= 0.01 or scale <= 0.05:
            return frame

        # Float up 40px over duration
        float_y = (t_local / max(0.01, dur)) * 40.0

        base_x = float(params.get("x", 820))
        base_y = float(params.get("y", 700)) - float_y

        sw, sh = sprite.size
        curr_sprite = sprite

        if abs(scale - 1.0) > 0.02:
            nw = max(10, round(sw * scale))
            nh = max(10, round(sh * scale))
            curr_sprite = curr_sprite.resize((nw, nh), resample=Image.Resampling.BILINEAR)
            sw, sh = nw, nh

        if alpha_mult < 0.99:
            r, g, b_ch, a = curr_sprite.split()
            a = a.point(lambda p: int(p * alpha_mult))
            curr_sprite = Image.merge("RGBA", (r, g, b_ch, a))

        dest_x = max(60, min(canvas_w - sw - 60, round(base_x - (sw / 2.0))))
        dest_y = max(220, min(canvas_h - sh - 420, round(base_y - (sh / 2.0))))

        base_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        base_pil.paste(curr_sprite, (dest_x, dest_y), curr_sprite)
        return cv2.cvtColor(np.array(base_pil), cv2.COLOR_RGB2BGR)
