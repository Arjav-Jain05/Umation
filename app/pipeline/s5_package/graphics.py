"""Procedural vector graphics kit for MrBeast-style thumbnails.

Provides hand-drawn attention circles, directional arrows, 'VS' badges,
starbursts, and energy accents drawn in code without external raster assets.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.core import paths


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load Anton or fallback font at size."""
    font_path = paths.fonts_dir() / "Anton-Regular.ttf"
    if font_path.is_file():
        try:
            return ImageFont.truetype(str(font_path), size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def draw_attention_circle(
    img: Image.Image,
    center: tuple[int, int],
    radius: int,
    color: tuple[int, int, int] = (255, 30, 30),
    stroke_width: int = 12,
    jitter: float = 3.5,
) -> None:
    """Draw an authentic hand-drawn, slightly irregular thick attention circle."""
    draw = ImageDraw.Draw(img, "RGBA")
    cx, cy = center
    num_points = 36
    points = []

    # Generate points with slight radial jitter for organic hand-drawn feel
    np.random.seed(int(cx * 17 + cy * 31 + radius) % 10000)
    for i in range(num_points + 1):
        angle = (2 * math.pi * i) / num_points
        # Slight elliptical and jitter variations
        r_jitter = radius + np.sin(angle * 3) * jitter + np.random.uniform(-jitter, jitter)
        px = cx + int(r_jitter * math.cos(angle))
        py = cy + int(r_jitter * 0.92 * math.sin(angle))  # slightly oval
        points.append((px, py))

    # Outer dark shadow for contrast
    shadow_color = (0, 0, 0, 160)
    for i in range(len(points) - 1):
        p1 = (points[i][0] + 4, points[i][1] + 4)
        p2 = (points[i + 1][0] + 4, points[i + 1][1] + 4)
        draw.line([p1, p2], fill=shadow_color, width=stroke_width + 4)

    # Main red stroke
    rgba_color = (color[0], color[1], color[2], 240)
    for i in range(len(points) - 1):
        draw.line([points[i], points[i + 1]], fill=rgba_color, width=stroke_width)


def draw_attention_arrow(
    img: Image.Image,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int] = (255, 30, 30),
    shaft_width: int = 16,
    head_size: int = 42,
) -> None:
    """Draw a thick, dynamic pointer arrow from start towards end (focal subject)."""
    draw = ImageDraw.Draw(img, "RGBA")
    x1, y1 = start
    x2, y2 = end

    dx = x2 - x1
    dy = y2 - y1
    dist = math.hypot(dx, dy)
    if dist < 10:
        return

    angle = math.atan2(dy, dx)

    # Calculate arrowhead base point
    base_x = x2 - head_size * math.cos(angle)
    base_y = y2 - head_size * math.sin(angle)

    # Perpendicular vector for arrowhead wings
    perp_angle1 = angle + math.pi * 0.78
    perp_angle2 = angle - math.pi * 0.78

    wing1 = (x2 + head_size * math.cos(perp_angle1), y2 + head_size * math.sin(perp_angle1))
    wing2 = (x2 + head_size * math.cos(perp_angle2), y2 + head_size * math.sin(perp_angle2))

    # Shadow
    s_offset = 5
    shadow_fill = (0, 0, 0, 180)
    draw.line([(x1 + s_offset, y1 + s_offset), (base_x + s_offset, base_y + s_offset)], fill=shadow_fill, width=shaft_width + 4)
    draw.polygon([
        (x2 + s_offset, y2 + s_offset),
        (wing1[0] + s_offset, wing1[1] + s_offset),
        (wing2[0] + s_offset, wing2[1] + s_offset),
    ], fill=shadow_fill)

    # Main arrow
    arrow_fill = (color[0], color[1], color[2], 255)
    draw.line([(x1, y1), (base_x, base_y)], fill=arrow_fill, width=shaft_width)
    draw.polygon([(x2, y2), wing1, wing2], fill=arrow_fill)

    # White highlight stroke on arrow head
    draw.line([wing1, (x2, y2), wing2], fill=(255, 255, 255, 220), width=3)


def draw_vs_badge(
    img: Image.Image,
    center: tuple[int, int],
    size: int = 140,
) -> None:
    """Draw a high-energy metallic/glowing 'VS' badge for versus-split thumbnails."""
    draw = ImageDraw.Draw(img, "RGBA")
    cx, cy = center
    r = size // 2

    # Outer glow
    for glow in range(4, 0, -1):
        gr = r + glow * 8
        alpha = int(45 / glow)
        draw.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], fill=(255, 230, 0, alpha))

    # Outer dark hexagon or circle border
    draw.ellipse([cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6], fill=(15, 15, 20, 255))

    # Red-to-orange badge body
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(235, 30, 30, 255))
    # Inner gold ring
    draw.ellipse([cx - r + 8, cy - r + 8, cx + r - 8, cy + r - 8], outline=(255, 230, 0, 255), width=4)

    # Render "VS" text
    font_size = int(size * 0.58)
    font = _get_font(font_size)
    bbox = draw.textbbox((0, 0), "VS", font=font, stroke_width=6)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = cx - tw // 2
    ty = cy - th // 2 - 4

    # Text shadow + stroke
    draw.text((tx + 3, ty + 3), "VS", font=font, fill=(0, 0, 0, 220), stroke_width=6, stroke_fill=(0, 0, 0, 255))
    draw.text((tx, ty), "VS", font=font, fill=(255, 255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0, 255))


def draw_shock_badge(
    img: Image.Image,
    top_left: tuple[int, int],
    text: str = "?!",
    size: int = 110,
) -> None:
    """Draw a dramatic yellow/red starburst shock badge with '?!' or '100%'."""
    draw = ImageDraw.Draw(img, "RGBA")
    x, y = top_left
    cx = x + size // 2
    cy = y + size // 2
    r_outer = size // 2
    r_inner = int(r_outer * 0.65)
    points = []

    num_spikes = 12
    for i in range(num_spikes * 2):
        r = r_outer if i % 2 == 0 else r_inner
        ang = (math.pi * i) / num_spikes
        points.append((cx + int(r * math.cos(ang)), cy + int(r * math.sin(ang))))

    # Drop shadow
    shadow_pts = [(p[0] + 5, p[1] + 5) for p in points]
    draw.polygon(shadow_pts, fill=(0, 0, 0, 160))
    # Main badge
    draw.polygon(points, fill=(255, 230, 0, 255), outline=(0, 0, 0, 255))

    font_size = int(size * 0.48)
    font = _get_font(font_size)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=4)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = cx - tw // 2
    ty = cy - th // 2 - 2
    draw.text((tx, ty), text, font=font, fill=(220, 20, 20, 255), stroke_width=4, stroke_fill=(0, 0, 0, 255))
