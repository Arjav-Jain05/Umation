"""High-impact condensed text engine, auto-fitter, face-collision avoidance, and curiosity copy generator.

Implements Section 2.4 of Prompt v7:
- Anton OFL font rendering with fat black outline (8-14px) and drop shadow
- One keyword highlighted in vibrant accent color (yellow #FFE600 or red)
- Zero translucent boxes behind text
- Bounding-box auto-fit with >= 4% safe margins and strict face-box collision avoidance
- LLM / rule-based curiosity gap copy generation (shock, question, contrast, number, reaction)
"""

from __future__ import annotations

import logging
import re

from PIL import Image, ImageDraw, ImageFont

from app.core import paths

logger = logging.getLogger("app.pipeline.s5_package.text_engine")

ACCENT_COLORS = {
    "yellow": (255, 230, 0),
    "red": (255, 45, 45),
    "cyan": (0, 240, 255),
    "green": (57, 255, 20),
}


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load Anton-Regular.ttf with fallback to Montserrat-ExtraBold.ttf or default."""
    font_file = "Anton-Regular.ttf" if not bold else "Montserrat-ExtraBold.ttf"
    font_path = paths.fonts_dir() / font_file
    if font_path.is_file():
        try:
            return ImageFont.truetype(str(font_path), size=size)
        except Exception:
            pass
    fallback_path = paths.fonts_dir() / "Anton-Regular.ttf"
    if fallback_path.is_file():
        try:
            return ImageFont.truetype(str(fallback_path), size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def generate_curiosity_hooks(
    topic: str,
    transcript_summary: str = "",
    seed_hook: str = "",
) -> list[str]:
    """Generate 6 candidate curiosity-gap hooks conforming to Section 2.4 patterns."""
    topic_clean = topic.strip().upper()
    hooks: list[str] = []

    # Pattern 1: Shock word (IMPOSSIBLE, INSANE, NO WAY)
    if "LEBRON" in topic_clean or "LEBRON" in seed_hook.upper():
        hooks.append("NO WAY!")
    elif "EXPLOD" in topic_clean or "EXPLOD" in transcript_summary.upper():
        hooks.append("EXPLODED?!")
    elif "GTA" in topic_clean:
        hooks.append("INSANE LEAK!")
    else:
        hooks.append("IMPOSSIBLE?!")

    # Pattern 2: Question (HOW?!, REAL?, DID HE WIN?)
    if "PRO" in topic_clean or "PRO" in seed_hook.upper():
        hooks.append("DID HE WIN?!")
    elif "SHOT" in topic_clean or "SHOT" in seed_hook.upper():
        hooks.append("HOW DID HE?!")
    elif "DIE" in topic_clean or "DO OR DIE" in seed_hook.upper():
        hooks.append("WILL HE DIE?!")
    else:
        hooks.append("HOW IS THIS REAL?!")

    # Pattern 3: Contrast (PRO vs NOOB, LEBRON vs YOU)
    if "LEBRON" in topic_clean or "LEBRON" in seed_hook.upper():
        hooks.append("LEBRON VS YOU")
    elif "PRO" in topic_clean:
        hooks.append("PRO VS NOOB")
    elif "GORDON" in topic_clean:
        hooks.append("CHEF VS NOOB")
    else:
        hooks.append("BEST VS WORST")

    # Pattern 4: Number / stat (1 IN 1,000,000, $100,000)
    if "100" in topic_clean or "100" in seed_hook or "100" in transcript_summary:
        hooks.append("$100,000 SHOT!")
    elif "10" in topic_clean or "10" in seed_hook:
        hooks.append("10 SECONDS LEFT!")
    else:
        hooks.append("1 IN 1,000,000")

    # Pattern 5: Reaction ("HE DID WHAT?!", "NEVER AGAIN")
    if "SHOT" in topic_clean or "UNSEEN" in seed_hook.upper():
        hooks.append("HE DID WHAT?!")
    elif "EXPLOD" in topic_clean:
        hooks.append("ROOM EXPLODED!")
    else:
        hooks.append("NEVER SEEN BEFORE")

    # Pattern 6: High urgency ("DO OR DIE", "LAST CHANCE")
    if "DIE" in seed_hook.upper() or "DIE" in topic_clean:
        hooks.append("DO OR DIE!")
    else:
        hooks.append("LAST CHANCE!")

    # Clean and uppercase all
    cleaned: list[str] = []
    seen = set()
    for h in hooks:
        words = re.findall(r"[A-Za-z0-9$?!:]+", h.strip().upper())
        h_str = " ".join(words[:4])
        if h_str and h_str not in seen:
            seen.add(h_str)
            cleaned.append(h_str)

    return cleaned[:6]


def split_text_lines(text: str) -> list[str]:
    """Split text into 1 or 2 balanced lines."""
    words = text.strip().split()
    if len(words) <= 2:
        return [text.strip()]
    if len(words) == 3:
        # e.g. "LEBRON VS YOU" -> line 1: "LEBRON VS", line 2: "YOU" or "LEBRON", "VS YOU"
        return [f"{words[0]} {words[1]}", words[2]]
    # 4 words -> 2 words + 2 words
    mid = len(words) // 2
    return [" ".join(words[:mid]), " ".join(words[mid:])]


def measure_text_block(
    lines: list[str],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    stroke_width: int,
    line_spacing: int = 6,
) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    """Measure total width, height and line bboxes including stroke."""
    dummy_img = Image.new("RGBA", (10, 10))
    draw = ImageDraw.Draw(dummy_img)
    line_boxes: list[tuple[int, int, int, int]] = []
    max_w = 0
    total_h = 0

    for idx, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
        lw = bbox[2] - bbox[0]
        lh = bbox[3] - bbox[1]
        line_boxes.append((bbox[0], bbox[1], lw, lh))
        max_w = max(max_w, lw)
        total_h += lh
        if idx > 0:
            total_h += line_spacing

    return max_w, total_h, line_boxes


def auto_fit_text(
    lines: list[str],
    zone_box: tuple[int, int, int, int],
    canvas_size: tuple[int, int],
    face_box: tuple[int, int, int, int] | None = None,
    min_font_size: int = 54,
    start_font_size: int = 180,
) -> tuple[int, int, int, int, int, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    """Auto-fit font size so text fits in zone_box without colliding with face_box.

    Returns (x, y, total_w, total_h, font_size, font).
    """
    zx, zy, zw, zh = zone_box
    cw, ch = canvas_size
    is_vertical = ch > cw
    stroke_w = 12 if is_vertical else 10

    font_size = start_font_size
    font = _get_font(font_size)
    tw, th, _ = measure_text_block(lines, font, stroke_w)

    # Shrink font until it fits zone width and height
    while (tw > int(zw * 0.94) or th > int(zh * 0.92)) and font_size > min_font_size:
        font_size -= 4
        font = _get_font(font_size)
        tw, th, _ = measure_text_block(lines, font, stroke_w)

    # Center text horizontally in zone
    tx = zx + (zw - tw) // 2
    ty = zy + (zh - th) // 2

    # Check safe area margins (min 4%)
    margin_x = int(cw * 0.04)
    margin_y = int(ch * 0.04)
    tx = max(margin_x, min(tx, cw - margin_x - tw))
    ty = max(margin_y, min(ty, ch - margin_y - th))

    # Face collision avoidance
    if face_box is not None:
        fx, fy, fw, fh = face_box
        # Check overlap between (tx, ty, tw, th) and face_box
        overlap_x = max(0, min(tx + tw, fx + fw) - max(tx, fx))
        overlap_y = max(0, min(ty + th, fy + fh) - max(ty, fy))
        if overlap_x > 0 and overlap_y > 0:
            # Shift text away from face
            if fy > ch // 2:
                # Face is in lower half -> push text upward
                ty = max(margin_y, fy - th - 16)
            else:
                # Face is in upper half -> push text downward
                ty = min(ch - margin_y - th, fy + fh + 16)

    return tx, ty, tw, th, font_size, font


def render_styled_text(
    base_img: Image.Image,
    lines: list[str],
    pos: tuple[int, int],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    accent_keyword: str | None = None,
    accent_color: tuple[int, int, int] = (255, 230, 0),
    rotation_deg: float = 0.0,
    stroke_width: int = 12,
    shadow_offset: tuple[int, int] = (7, 7),
) -> tuple[int, int, int, int]:
    """Render high-contrast text directly with thick black outline and drop shadow.

    NO translucent box. Highlights accent_keyword in accent_color.
    Returns rendered bounding box (x, y, w, h).
    """
    tx, ty = pos
    tw, th, line_metrics = measure_text_block(lines, font, stroke_width)

    # Create temporary RGBA text canvas to support rotation and layer stacking
    pad = 40
    t_img = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    t_draw = ImageDraw.Draw(t_img)

    curr_y = pad
    # Identify keyword to color
    target_accent = accent_keyword.upper() if accent_keyword else ""

    for idx, line in enumerate(lines):
        lx = pad
        words = line.split()

        # Measure each word
        for widx, w in enumerate(words):
            w_str = w.upper()
            bbox = t_draw.textbbox((0, 0), w + " ", font=font, stroke_width=stroke_width)
            word_w = bbox[2] - bbox[0]

            # Choose fill color
            is_accent = False
            if target_accent and (target_accent in w_str or w_str in target_accent):
                is_accent = True
            elif not target_accent and widx == len(words) - 1:
                # Highlight last word by default if no keyword given
                is_accent = True

            fill_color = accent_color if is_accent else (255, 255, 255)

            # (1) Drop shadow (black stroke + fill shifted)
            sx, sy = shadow_offset
            t_draw.text(
                (lx + sx, curr_y + sy),
                w,
                font=font,
                fill=(0, 0, 0, 180),
                stroke_width=stroke_width + 2,
                stroke_fill=(0, 0, 0, 180),
            )

            # (2) Main word with thick black stroke
            t_draw.text(
                (lx, curr_y),
                w,
                font=font,
                fill=fill_color,
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0, 255),
            )

            lx += word_w

        curr_y += line_metrics[idx][3] + 6

    # Optional slight rotation (-3 to -5 deg)
    if abs(rotation_deg) > 0.5:
        t_img = t_img.rotate(rotation_deg, resample=Image.Resampling.BILINEAR, expand=True)

    # Paste onto base_img
    paste_x = tx - pad
    paste_y = ty - pad
    base_img.paste(t_img, (paste_x, paste_y), t_img)

    return (tx, ty, tw, th)
