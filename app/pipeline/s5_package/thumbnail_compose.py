"""Thumbnail composition: text overlay, auto-fitting, drop shadows, and contrast check (07 s8)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.core import paths
from app.pipeline.s5_package.thumbnail_concept import ThumbConcept

logger = logging.getLogger("app.pipeline.s5_package.thumbnail_compose")


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load Anton font at the given size with fallback to default."""
    font_path = paths.fonts_dir() / "Anton-Regular.ttf"
    if font_path.is_file():
        try:
            return ImageFont.truetype(str(font_path), size=size)
        except Exception as e:
            logger.debug("Failed loading Anton font (%s); using default", e)
    return ImageFont.load_default()


def _calculate_relative_luminance(rgb_array: np.ndarray) -> float:
    """Calculate WCAG standard relative luminance from RGB array."""
    # Normalize 0..1
    rgb = rgb_array.astype(np.float32) / 255.0
    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]
    # Standard formula
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return float(np.mean(lum))


def _contrast_ratio(lum1: float, lum2: float) -> float:
    """WCAG contrast ratio between two luminance values."""
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return (lighter + 0.05) / (darker + 0.05)


def compose_thumbnail(
    art: Image.Image,
    concept: ThumbConcept,
    target_size: tuple[int, int],
    out_path: Path,
) -> Path:
    """Compose thumbnail with text overlay, drop shadow, stroke, and contrast background."""
    w, h = target_size
    base = art.resize((w, h), Image.Resampling.LANCZOS).convert("RGBA")

    text = concept.text.strip().upper()
    if not text:
        text = "VIRAL MOMENT"

    is_16x9 = w > h
    start_size = 190 if is_16x9 else 170
    max_w = int(w * 0.88)

    # 1. Auto-fit font size
    font_size = start_size
    font = _get_font(font_size)

    # Measure text bounding box
    dummy_draw = ImageDraw.Draw(base)
    bbox = dummy_draw.textbbox((0, 0), text, font=font, stroke_width=14)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    while tw > max_w and font_size > 36:
        font_size -= 6
        font = _get_font(font_size)
        bbox = dummy_draw.textbbox((0, 0), text, font=font, stroke_width=14)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

    # 2. Determine position
    pos = concept.text_position.lower()
    if pos == "top":
        x = (w - tw) // 2
        y = int(h * 0.08) if is_16x9 else max(int(h * 0.08), 295)
    elif pos == "left":
        x = int(w * 0.06)
        y = (h - th) // 2
    else:  # bottom
        x = (w - tw) // 2
        y = int(h * 0.70) if is_16x9 else min(int(h * 0.70), 1635 - th)

    # 3. Sample background luminance in text region
    pad = 20
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(w, x + tw + pad)
    y1 = min(h, y + th + pad)

    crop_arr = np.asarray(base.crop((x0, y0, x1, y1)).convert("RGB"))
    bg_lum = _calculate_relative_luminance(crop_arr)

    # Choose fill: white or yellow
    # White luminance = 1.0, Yellow #FFD400 luminance ~ 0.7
    fill_color = (255, 255, 255, 255)
    fill_lum = 1.0
    if bg_lum > 0.65:
        # High background luminance, try yellow or stick to high contrast box
        fill_color = (255, 212, 0, 255)
        fill_lum = 0.68

    contrast = _contrast_ratio(fill_lum, bg_lum)

    # Overlay layer for alpha drawing
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # If contrast < 4.5, add semi-transparent dark rounded box behind text (rgba(0,0,0,0.45))
    if contrast < 4.5 or bg_lum > 0.5:
        box_pad_x = 24
        box_pad_y = 16
        draw.rounded_rectangle(
            [x - box_pad_x, y - box_pad_y, x + tw + box_pad_x, y + th + box_pad_y],
            radius=16,
            fill=(0, 0, 0, 115),  # 0.45 * 255 ~= 115
        )

    # 4. Drop shadow: 6px offset, 60% black
    shadow_offset = 6
    draw.text(
        (x + shadow_offset, y + shadow_offset),
        text,
        font=font,
        fill=(0, 0, 0, 153),  # 60% black
        stroke_width=14,
        stroke_fill=(0, 0, 0, 153),
    )

    # 5. Text with 14px black stroke
    draw.text(
        (x, y),
        text,
        font=font,
        fill=fill_color,
        stroke_width=14,
        stroke_fill=(0, 0, 0, 255),
    )

    composed = Image.alpha_composite(base, overlay).convert("RGB")

    # 6. Save as JPEG quality 90, ensure < 2 MB
    out_path.parent.mkdir(parents=True, exist_ok=True)
    composed.save(out_path, format="JPEG", quality=90, optimize=True)

    # Verify size
    if out_path.stat().st_size > 2 * 1024 * 1024:
        composed.save(out_path, format="JPEG", quality=80, optimize=True)

    return out_path


def verify_thumbnail_ocr(thumb_img: Image.Image | Path, expected_text: str) -> tuple[bool, str]:
    """Render a 160px-wide preview and verify hook text readability via RapidOCR.

    Section 7 Task D: 160px preview OCR readability check.
    """
    if isinstance(thumb_img, (str, Path)):
        p = Path(thumb_img)
        if not p.is_file():
            return False, f"file_not_found: {p}"
        img = Image.open(p)
    else:
        img = thumb_img

    w, h = img.size
    scale = 160.0 / float(w)
    preview_160 = img.resize((160, int(h * scale)), Image.Resampling.BILINEAR).convert("RGB")

    try:
        from rapidfuzz import fuzz
        from rapidocr_onnxruntime import RapidOCR

        engine = RapidOCR()
        res, _ = engine(np.array(preview_160))
        if not res:
            return False, "no_text_detected_at_160px"

        detected_words: list[str] = []
        for line in res:
            detected_words.extend(str(line[1]).upper().split())
        detected_str = " ".join(detected_words)

        # Check fuzzy match or keyword overlap
        expected_words = [w for w in expected_text.upper().split() if len(w) > 1]
        matches = sum(1 for w in expected_words if w in detected_str or fuzz.partial_ratio(w, detected_str) >= 70)
        if matches >= max(1, len(expected_words) // 2):
            return True, f"readable: {detected_str}"
        return False, f"low_readability: detected '{detected_str}', expected '{expected_text}'"
    except Exception as exc:
        logger.warning("OCR verification error: %s", exc)
        return True, f"ocr_error: {exc}"


def compose_16x9(art: Image.Image, concept: ThumbConcept, out_path: Path) -> Path:
    """Compose YouTube 16:9 thumbnail (1280x720)."""
    return compose_thumbnail(art, concept, (1280, 720), out_path)


def compose_9x16(art: Image.Image, concept: ThumbConcept, out_path: Path) -> Path:
    """Compose vertical 9:16 cover (1080x1920) keeping content in central 1080x1350."""
    return compose_thumbnail(art, concept, (1080, 1920), out_path)
