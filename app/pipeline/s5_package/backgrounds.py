"""Procedural background families and palette engine for MrBeast-style thumbnails.

Generates 8 procedural background families (zero GPU, deterministic, never blank)
with dynamic complementary color theory based on subject hue.
"""

from __future__ import annotations

import colorsys
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def extract_dominant_hue(img: Image.Image) -> float:
    """Extract dominant hue (0.0 to 1.0) of subject from non-transparent pixels."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    arr = np.asarray(img)
    alpha = arr[:, :, 3]
    mask = alpha > 40
    if not np.any(mask):
        return 0.08  # Default warm orange hue

    rgb_pixels = arr[mask][:, :3]
    # Sample up to 1000 pixels for fast execution
    if len(rgb_pixels) > 1000:
        indices = np.random.choice(len(rgb_pixels), 1000, replace=False)
        rgb_pixels = rgb_pixels[indices]

    hues = []
    for r, g, b in rgb_pixels:
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        if s > 0.15 and v > 0.15:  # ignore near-grey/black
            hues.append(h)

    if not hues:
        return 0.08
    return float(np.median(hues))


def generate_palette(dominant_hue: float, mode: str = "complementary") -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """Compute high-contrast complementary color trio (bg_primary, bg_secondary, accent)."""
    # Complementary hue is 180 deg offset (0.5 in 0..1 scale)
    if mode == "split_complementary":
        bg_h1 = (dominant_hue + 0.42) % 1.0
        bg_h2 = (dominant_hue + 0.58) % 1.0
    else:
        bg_h1 = (dominant_hue + 0.50) % 1.0
        bg_h2 = (dominant_hue + 0.55) % 1.0

    # Subject is bright; background should be deep and saturated
    rgb1 = colorsys.hsv_to_rgb(bg_h1, 0.88, 0.28)
    rgb2 = colorsys.hsv_to_rgb(bg_h2, 0.95, 0.45)

    # Accent color (high brightness yellow #FFE600 or bright cyan/orange)
    accent_h = (dominant_hue + 0.15) % 1.0
    accent_rgb = colorsys.hsv_to_rgb(accent_h, 0.95, 0.98)

    c1 = (int(rgb1[0] * 255), int(rgb1[1] * 255), int(rgb1[2] * 255))
    c2 = (int(rgb2[0] * 255), int(rgb2[1] * 255), int(rgb2[2] * 255))
    accent = (int(accent_rgb[0] * 255), int(accent_rgb[1] * 255), int(accent_rgb[2] * 255))
    return c1, c2, accent


def render_radial_burst(
    size: tuple[int, int],
    center: tuple[int, int],
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
    num_rays: int = 24,
) -> Image.Image:
    """Radial sunburst rays expanding from focal anchor with alternating colors."""
    w, h = size
    img = Image.new("RGB", (w, h), c1)
    draw = ImageDraw.Draw(img)
    cx, cy = center
    max_r = int(math.hypot(max(cx, w - cx), max(cy, h - cy)) * 1.2)

    for i in range(num_rays):
        if i % 2 == 1:
            continue
        a1 = (2 * math.pi * i) / num_rays
        a2 = (2 * math.pi * (i + 1)) / num_rays
        p1 = (cx + int(max_r * math.cos(a1)), cy + int(max_r * math.sin(a1)))
        p2 = (cx + int(max_r * math.cos(a2)), cy + int(max_r * math.sin(a2)))
        draw.polygon([(cx, cy), p1, p2], fill=c2)

    # Subtle center gradient overlay to soften anchor
    vignette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    vdraw = ImageDraw.Draw(vignette)
    for r in range(min(w, h) // 3, 0, -20):
        alpha = int(70 * (1.0 - r / (min(w, h) / 3)))
        vdraw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(c2[0], c2[1], c2[2], alpha))

    img = Image.alpha_composite(img.convert("RGBA"), vignette).convert("RGB")
    return img


def render_diagonal_split(
    size: tuple[int, int],
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
) -> Image.Image:
    """Angled high-contrast two-color split with lighting gradient and energy streaks."""
    w, h = size
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        frac = y / max(1, h)
        factor = 0.8 + 0.4 * frac
        for ch in range(3):
            arr[y, :, ch] = np.clip(int(c1[ch] * factor), 0, 255)

    img = Image.fromarray(arr, "RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    # Diagonal cut from 65% top to 35% bottom
    x_top = int(w * 0.65)
    x_bot = int(w * 0.35)
    draw.polygon([(x_top, 0), (w, 0), (w, h), (x_bot, h)], fill=(c2[0], c2[1], c2[2], 240))

    # Energy streaks across diagonal
    for offset in range(-200, 200, 45):
        draw.line([(x_top + offset, 0), (x_bot + offset, h)], fill=(255, 255, 255, 30), width=4)

    # Seam glow
    draw.line([(x_top, 0), (x_bot, h)], fill=(0, 0, 0, 255), width=12)
    draw.line([(x_top, 0), (x_bot, h)], fill=(255, 230, 0, 220), width=4)
    return img


def render_spotlight_vignette(
    size: tuple[int, int],
    center: tuple[int, int],
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
) -> Image.Image:
    """Deep dark radial vignette with central glowing spotlight and energy light rays."""
    w, h = size
    cx, cy = center
    y, x = np.ogrid[:h, :w]
    dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    max_d = math.hypot(max(cx, w - cx), max(cy, h - cy))
    factor = np.clip(dist / max_d, 0.0, 1.0)

    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for ch in range(3):
        col = c2[ch] * (1.0 - factor * 0.85) + c1[ch] * (factor * 0.85)
        arr[:, :, ch] = np.clip(col, 0, 255).astype(np.uint8)

    img = Image.fromarray(arr, "RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    # Subtle radiating light rays from center
    num_rays = 20
    np.random.seed(int(cx * 11 + cy * 19) % 3000)
    for i in range(num_rays):
        ang = (2 * math.pi * i) / num_rays
        p_end = (cx + int(max_d * math.cos(ang)), cy + int(max_d * math.sin(ang)))
        alpha = int(np.random.uniform(25, 60))
        draw.line([(cx, cy), p_end], fill=(255, 255, 255, alpha), width=3)

    # Concentric soft rings
    for r in range(int(min(w, h) * 0.2), int(max_d), int(min(w, h) * 0.15)):
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(c2[0], c2[1], c2[2], 35), width=2)

    return img


def render_comic_halftone(
    size: tuple[int, int],
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
) -> Image.Image:
    """Pop-art comic book dot grid over saturated gradient."""
    w, h = size
    base = render_diagonal_split(size, c1, c2)
    draw = ImageDraw.Draw(base, "RGBA")

    spacing = 36
    for y in range(0, h, spacing):
        for x in range(0, w, spacing):
            r = int(4 + 6 * (x / w))
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(0, 0, 0, 75))

    return base


def render_neon_glow(
    size: tuple[int, int],
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
) -> Image.Image:
    """Cyber dual-hue neon gradient with horizontal light streak accents."""
    w, h = size
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        ratio = y / max(1, h)
        for ch in range(3):
            arr[y, :, ch] = int(c1[ch] * (1.0 - ratio) + c2[ch] * ratio)
    img = Image.fromarray(arr, "RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    # Glowing neon streaks
    for streak_y in [int(h * 0.28), int(h * 0.72)]:
        draw.line([(0, streak_y), (w, streak_y)], fill=(c2[0], c2[1], c2[2], 180), width=6)
        draw.line([(0, streak_y), (w, streak_y)], fill=(255, 255, 255, 220), width=2)

    return img


def render_versus_split(
    size: tuple[int, int],
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
    is_vertical: bool = False,
) -> Image.Image:
    """High-contrast Versus split with diagonal energy streaks, gradient lighting, and center seam."""
    w, h = size
    arr = np.zeros((h, w, 3), dtype=np.uint8)

    if not is_vertical:
        mid_x = w // 2
        # Left half: vertical gradient with lighting
        for y in range(h):
            frac = y / max(1, h)
            factor = 0.75 + 0.5 * (1.0 - frac)
            for ch in range(3):
                arr[y, :mid_x, ch] = np.clip(int(c1[ch] * factor), 0, 255)
                arr[y, mid_x:, ch] = np.clip(int(c2[ch] * factor), 0, 255)
        img = Image.fromarray(arr, "RGB")
        draw = ImageDraw.Draw(img, "RGBA")

        # Dynamic diagonal energy lines on both sides
        for i in range(0, mid_x, 40):
            draw.line([(i, 0), (i + 120, h)], fill=(255, 255, 255, 35), width=3)
        for i in range(mid_x, w, 40):
            draw.line([(i, 0), (i - 120, h)], fill=(255, 255, 255, 35), width=3)

        # Center seam divider with glow
        draw.line([(mid_x, 0), (mid_x, h)], fill=(0, 0, 0, 255), width=16)
        draw.line([(mid_x, 0), (mid_x, h)], fill=(255, 230, 0, 255), width=4)
    else:
        mid_y = int(h * 0.48)
        for y in range(h):
            factor = 0.7 + 0.6 * (y / max(1, h))
            target_c = c1 if y < mid_y else c2
            for ch in range(3):
                arr[y, :, ch] = np.clip(int(target_c[ch] * factor), 0, 255)
        img = Image.fromarray(arr, "RGB")
        draw = ImageDraw.Draw(img, "RGBA")

        for i in range(0, w, 50):
            draw.line([(i, 0), (i + 80, mid_y)], fill=(255, 255, 255, 30), width=3)
            draw.line([(i, mid_y), (i - 80, h)], fill=(255, 255, 255, 30), width=3)

        draw.line([(0, mid_y), (w, mid_y)], fill=(0, 0, 0, 255), width=16)
        draw.line([(0, mid_y), (w, mid_y)], fill=(255, 230, 0, 255), width=4)

    return img


def render_blurred_zoom(
    size: tuple[int, int],
    source_frame: Image.Image,
    tint_color: tuple[int, int, int],
) -> Image.Image:
    """Heavily blurred zoom of source video frame, darkened and color-tinted."""
    w, h = size
    # Zoom in by 1.35x into center
    sw, sh = source_frame.size
    crop_w = int(sw / 1.35)
    crop_h = int(sh / 1.35)
    x0 = (sw - crop_w) // 2
    y0 = (sh - crop_h) // 2
    zoomed = source_frame.crop((x0, y0, x0 + crop_w, y0 + crop_h)).resize((w, h), Image.Resampling.BILINEAR)

    # Heavy blur
    blurred = zoomed.filter(ImageFilter.GaussianBlur(radius=36))

    # Darken and tint
    arr = np.asarray(blurred).astype(np.float32)
    # Darken (-35%)
    arr = arr * 0.65
    # Tint towards tint_color
    tint_weight = 0.28
    for ch in range(3):
        arr[:, :, ch] = arr[:, :, ch] * (1.0 - tint_weight) + tint_color[ch] * tint_weight

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def render_speed_lines(
    size: tuple[int, int],
    center: tuple[int, int],
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
) -> Image.Image:
    """Manga / anime high-speed energy lines converging toward focal subject."""
    w, h = size
    img = Image.new("RGB", (w, h), c1)
    draw = ImageDraw.Draw(img, "RGBA")
    cx, cy = center

    num_lines = 48
    max_r = int(math.hypot(max(cx, w - cx), max(cy, h - cy)))
    inner_r = int(min(w, h) * 0.22)

    np.random.seed(int(cx * 13 + cy * 7) % 5000)
    for i in range(num_lines):
        ang = (2 * math.pi * i) / num_lines + np.random.uniform(-0.04, 0.04)
        start_r = inner_r + np.random.uniform(10, 60)
        p1 = (cx + int(start_r * math.cos(ang)), cy + int(start_r * math.sin(ang)))
        p2 = (cx + int(max_r * math.cos(ang)), cy + int(max_r * math.sin(ang)))
        line_w = int(np.random.choice([2, 3, 5, 8]))
        alpha = int(np.random.uniform(90, 220))
        draw.line([p1, p2], fill=(c2[0], c2[1], c2[2], alpha), width=line_w)

    return img


def create_background(
    family: str,
    size: tuple[int, int],
    anchor: tuple[int, int],
    palette: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]],
    source_frame: Image.Image | None = None,
) -> Image.Image:
    """Dispatch procedural background generation based on family name."""
    c1, c2, _accent = palette
    is_vertical = size[1] > size[0]

    fam = family.lower()
    if fam == "radial_burst":
        return render_radial_burst(size, anchor, c1, c2)
    elif fam == "diagonal_split":
        return render_diagonal_split(size, c1, c2)
    elif fam == "spotlight_vignette":
        return render_spotlight_vignette(size, anchor, c1, c2)
    elif fam == "comic_halftone":
        return render_comic_halftone(size, c1, c2)
    elif fam == "neon_glow":
        return render_neon_glow(size, c1, c2)
    elif fam == "versus_split":
        return render_versus_split(size, c1, c2, is_vertical=is_vertical)
    elif fam == "blurred_zoom" and source_frame is not None:
        return render_blurred_zoom(size, source_frame, c1)
    elif fam == "speed_lines":
        return render_speed_lines(size, anchor, c1, c2)
    else:
        # Fallback to high-contrast radial burst
        return render_radial_burst(size, anchor, c1, c2)
