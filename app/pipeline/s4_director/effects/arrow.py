"""Arrow pointer overlay: animated directional pointing arrow referencing key targets."""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.core import paths
from app.pipeline.s4_director.effects.base import register_effect
from app.utils.easing import ease_out_back


def _interpolate_track(track: list[list[float]], t_local: float) -> list[float] | None:
    if not track:
        return None
    # Track items are [t_offset, x1, y1, x2, y2]
    if t_local <= track[0][0]:
        return track[0][1:5]
    if t_local >= track[-1][0]:
        return track[-1][1:5]

    for i in range(len(track) - 1):
        t1, b1 = track[i][0], track[i][1:5]
        t2, b2 = track[i + 1][0], track[i + 1][1:5]
        if t1 <= t_local <= t2:
            dt = max(0.0001, t2 - t1)
            frac = (t_local - t1) / dt
            return [b1[k] + (b2[k] - b1[k]) * frac for k in range(4)]
    return track[-1][1:5]


@register_effect("arrow")
class ArrowEffect:
    """Renders a high-visibility animated yellow pointing arrow with bobbing and tracking."""

    def __init__(self) -> None:
        self._sprite_cache: dict[int, Image.Image] = {}

    def _get_arrow_sprite(self) -> Image.Image:
        arrow_path = paths.project_root() / "assets" / "overlays" / "arrow.png"
        if not arrow_path.is_file():
            # If not yet generated, create fallback
            from scripts.make_overlays import generate_arrow_sprite
            generate_arrow_sprite(arrow_path)
        return Image.open(arrow_path).convert("RGBA")

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
        b_cx = (bx1 + bx2) / 2.0
        b_cy = (by1 + by2) / 2.0

        # Safe zone bounds
        safe_l, safe_r = 60.0, 920.0
        safe_t, safe_b = 220.0, 1500.0

        # Measure free space on each side
        spaces = [
            ("left", bx1 - safe_l),
            ("top", by1 - safe_t),
            ("right", safe_r - bx2),
            ("bottom", safe_b - by2),
        ]
        # Sort descending by free space (tie order preserved: left, top, right, bottom)
        spaces.sort(key=lambda s: s[1], reverse=True)
        best_side = spaces[0][0]

        # Timing & Animation
        pop_dur = 0.25
        fade_dur = 0.20

        if t_local < pop_dur:
            scale = 0.70 + 0.30 * ease_out_back(t_local / pop_dur)
            alpha_mult = min(1.0, t_local / 0.05)
        elif t_local > (dur - fade_dur):
            scale = 1.0
            alpha_mult = max(0.0, (dur - t_local) / fade_dur)
        else:
            scale = 1.0
            alpha_mult = 1.0

        if alpha_mult <= 0.01:
            return frame

        # Bobbing +-8px along axis at 2 Hz
        bob = 8.0 * math.sin(2.0 * math.pi * 2.0 * t_local)

        # Base sprite points right (tip on the right, tail on the left)
        # Dimensions: 220 x 130
        sprite = self._get_arrow_sprite()
        sw, sh = sprite.size  # 220, 130
        tip_offset_x = 210  # Tip is near right edge
        tip_offset_y = 65

        gap = 14.0

        # Determine rotation and tip anchor
        # angle is counter-clockwise for PIL rotate:
        # 0 deg = points right (places on left)
        # 270 deg = points down (places on top)
        # 180 deg = points left (places on right)
        # 90 deg = points up (places on bottom)
        if best_side == "left":
            rot_deg = 0
            tip_target_x = bx1 - gap - bob
            tip_target_y = b_cy
            tip_local = (tip_offset_x, tip_offset_y)
        elif best_side == "top":
            rot_deg = 270
            tip_target_x = b_cx
            tip_target_y = by1 - gap - bob
            tip_local = (sh - tip_offset_y, tip_offset_x)
        elif best_side == "right":
            rot_deg = 180
            tip_target_x = bx2 + gap + bob
            tip_target_y = b_cy
            tip_local = (sw - tip_offset_x, sh - tip_offset_y)
        else:  # bottom
            rot_deg = 90
            tip_target_x = b_cx
            tip_target_y = by2 + gap + bob
            tip_local = (tip_offset_y, sw - tip_offset_x)

        rotated = sprite.rotate(rot_deg, expand=True, resample=Image.Resampling.BILINEAR)
        rw, rh = rotated.size

        # Apply scaling
        if abs(scale - 1.0) > 0.01:
            fw = max(10, int(rw * scale))
            fh = max(10, int(rh * scale))
            rotated = rotated.resize((fw, fh), resample=Image.Resampling.BILINEAR)
            rw, rh = fw, fh
            tip_local = (int(tip_local[0] * scale), int(tip_local[1] * scale))

        # Apply fade-out alpha
        if alpha_mult < 0.99:
            r, g, b_ch, a = rotated.split()
            a = a.point(lambda p: int(p * alpha_mult))
            rotated = Image.merge("RGBA", (r, g, b_ch, a))

        # Place tip at target
        place_x = round(tip_target_x - tip_local[0])
        place_y = round(tip_target_y - tip_local[1])

        # Alpha composite on frame
        base_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        base_pil.paste(rotated, (place_x, place_y), rotated)
        return cv2.cvtColor(np.array(base_pil), cv2.COLOR_RGB2BGR)
