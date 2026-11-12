"""Thumbnail composition: multi-template layout, pop-out subject, graphics kit, and text rendering.

Replaces Section 7 (Task D) with the MrBeast-style clickbait thumbnail compositor:
- Percent-based layouts for 16:9 (1280x720) and 9:16 (1080x1920)
- 8 procedural backgrounds with dynamic complementary palette
- Pop-out subject treatment: thick outline + outer glow + soft drop shadow
- Vector attention graphics: hand-drawn red circles, arrows, VS badges, shock badges
- Giant condensed typography with thick black stroke and drop shadow (NO translucent boxes)
- Hard quality gate verification via RapidOCR and layout metrics
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from app.pipeline.s5_package import backgrounds, graphics, layouts, quality_gate, text_engine
from app.pipeline.s5_package.thumbnail_concept import ThumbConcept

logger = logging.getLogger("app.pipeline.s5_package.thumbnail_compose")


def compose_thumbnail(
    subject_rgba: Image.Image,
    hook_text: str,
    aspect: str,
    out_path: Path,
    template_name: str = "big_reaction",
    palette: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]] | None = None,
    source_frame: Image.Image | None = None,
    face_box: tuple[int, int, int, int] | None = None,
    accent_keyword: str | None = None,
) -> tuple[Path, quality_gate.HardCheckReport]:
    """Compose a complete MrBeast-style thumbnail adhering to Section 2.3 and Section 2.4."""
    canvas_size = (1280, 720) if aspect == "16:9" else (1080, 1920)
    cw, ch = canvas_size
    is_vertical = ch > cw

    # 1. Palette: if not provided, extract from subject dominant hue
    if palette is None:
        dominant_hue = backgrounds.extract_dominant_hue(subject_rgba)
        palette = backgrounds.generate_palette(dominant_hue, mode="split_complementary")

    _c1, _c2, accent_color = palette

    # 2. Layout template
    tmpl = layouts.get_layout(template_name, aspect)
    sz_px = layouts.resolve_zone_pixels(tmpl["subject_zone"], canvas_size)
    tz_px = layouts.resolve_zone_pixels(tmpl["text_zone"], canvas_size)
    anchor_px = (int(tmpl["anchor"][0] * cw), int(tmpl["anchor"][1] * ch))

    # 3. Create procedural background
    bg_family = tmpl.get("bg_family", "radial_burst")
    base_bg = backgrounds.create_background(
        bg_family,
        canvas_size,
        anchor_px,
        palette,
        source_frame=source_frame,
    ).convert("RGBA")

    # 4. Subject Pop-out treatment (outline + colored glow + drop shadow)
    # Target height: 50-60% of canvas height
    target_height_ratio = 0.56 if not is_vertical else 0.52
    treated_subj, pad_offset = subject_extractor_popout(
        subject_rgba,
        canvas_size,
        target_height_ratio=target_height_ratio,
        outline_color=(255, 255, 255),
        glow_color=accent_color,
    )

    # Position subject within subject_zone
    target_subj_h = int(ch * target_height_ratio)
    scale = target_subj_h / float(max(1, subject_rgba.size[1]))
    target_subj_w = int(subject_rgba.size[0] * scale)

    if not is_vertical:
        # 16:9: align subject inside zone
        subj_x = sz_px[0] + (sz_px[2] - target_subj_w) // 2 - pad_offset[0]
        subj_y = sz_px[1] + (sz_px[3] - target_subj_h) // 2 - pad_offset[1]
    else:
        # 9:16: center subject horizontally in lower-middle zone
        subj_x = (cw - target_subj_w) // 2 - pad_offset[0]
        subj_y = sz_px[1] + (sz_px[3] - target_subj_h) // 2 - pad_offset[1]

    # Bound coordinates inside safe limits
    subj_x = max(-pad_offset[0] // 2, min(subj_x, cw - target_subj_w + pad_offset[0] // 2))
    subj_y = max(-pad_offset[1] // 2, min(subj_y, ch - target_subj_h + pad_offset[1] // 2))

    base_bg.paste(treated_subj, (subj_x, subj_y), treated_subj)
    comp_subj_bbox = (subj_x + pad_offset[0], subj_y + pad_offset[1], target_subj_w, target_subj_h)

    # 5. Attention Graphics (at most one per thumbnail per Section 2)
    badge_type = tmpl.get("badge")
    if badge_type == "vs":
        badge_cx = cw // 2
        badge_cy = ch // 2 if not is_vertical else int(ch * 0.46)
        graphics.draw_vs_badge(base_bg, (badge_cx, badge_cy), size=130 if not is_vertical else 150)
    elif badge_type == "shock":
        bx = int(cw * 0.05)
        by = int(ch * 0.05) if not is_vertical else int(ch * 0.04)
        graphics.draw_shock_badge(base_bg, (bx, by), text="?!", size=115)
    elif tmpl.get("arrow") is not None:
        arr_info = tmpl["arrow"]
        p_start = (int(arr_info["start"][0] * cw), int(arr_info["start"][1] * ch))
        p_end = (int(arr_info["end"][0] * cw), int(arr_info["end"][1] * ch))
        graphics.draw_attention_arrow(base_bg, p_start, p_end, color=(255, 35, 35))
    elif tmpl.get("circle") is not None:
        circ_info = tmpl["circle"]
        circ_c = (int(circ_info["center"][0] * cw), int(circ_info["center"][1] * ch))
        circ_r = int(circ_info["radius"] * min(cw, ch))
        graphics.draw_attention_circle(base_bg, circ_c, circ_r, color=(255, 35, 35))

    # 6. Text Engine: Auto-fit text & render with thick stroke + drop shadow (NO BOX)
    lines = text_engine.split_text_lines(hook_text)
    start_font_size = 145 if not is_vertical else 165
    tx, ty, _tw, _th, _fsize, font = text_engine.auto_fit_text(
        lines=lines,
        zone_box=tz_px,
        canvas_size=canvas_size,
        face_box=face_box,
        start_font_size=start_font_size,
    )

    # Keyword accent determination
    if not accent_keyword and lines:
        words = lines[0].split()
        if words:
            accent_keyword = words[0]

    stroke_w = 12 if is_vertical else 10
    text_bbox = text_engine.render_styled_text(
        base_img=base_bg,
        lines=lines,
        pos=(tx, ty),
        font=font,
        accent_keyword=accent_keyword,
        accent_color=(255, 230, 0),
        rotation_deg=-3.0 if not is_vertical else 0.0,
        stroke_width=stroke_w,
    )

    # 7. Convert and save JPEG quality 90
    final_rgb = base_bg.convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final_rgb.save(out_path, format="JPEG", quality=90, optimize=True)

    if out_path.stat().st_size > 2 * 1024 * 1024:
        final_rgb.save(out_path, format="JPEG", quality=80, optimize=True)

    # 8. Run Quality Gate evaluation
    report = quality_gate.evaluate_thumbnail(
        out_path,
        expected_text=hook_text,
        subject_bbox=comp_subj_bbox,
        face_box=face_box,
        text_bbox=text_bbox,
    )

    return out_path, report


def subject_extractor_popout(
    subject_rgba: Image.Image,
    canvas_size: tuple[int, int],
    target_height_ratio: float = 0.54,
    outline_color: tuple[int, int, int] = (255, 255, 255),
    glow_color: tuple[int, int, int] = (255, 230, 0),
) -> tuple[Image.Image, tuple[int, int]]:
    """Helper wrapping apply_popout_treatment from subject_extractor."""
    from app.pipeline.s5_package import subject_extractor
    return subject_extractor.apply_popout_treatment(
        subject_rgba,
        canvas_size,
        target_height_ratio=target_height_ratio,
        outline_color=outline_color,
        glow_color=glow_color,
    )


def compose_16x9(
    art: Image.Image,
    concept: ThumbConcept,
    out_path: Path,
    subject_rgba: Image.Image | None = None,
    source_frame: Image.Image | None = None,
    face_box: tuple[int, int, int, int] | None = None,
    template_name: str = "big_reaction",
) -> Path:
    """Compose YouTube 16:9 thumbnail (1280x720)."""
    text = concept.text.strip().upper() if hasattr(concept, "text") else "VIRAL MOMENT"
    subj = subject_rgba if subject_rgba is not None else art
    path, _ = compose_thumbnail(
        subject_rgba=subj,
        hook_text=text,
        aspect="16:9",
        out_path=out_path,
        template_name=template_name,
        source_frame=source_frame,
        face_box=face_box,
    )
    return path


def compose_9x16(
    art: Image.Image,
    concept: ThumbConcept,
    out_path: Path,
    subject_rgba: Image.Image | None = None,
    source_frame: Image.Image | None = None,
    face_box: tuple[int, int, int, int] | None = None,
    template_name: str = "big_reaction",
) -> Path:
    """Compose vertical 9:16 Shorts cover (1080x1920) with dedicated vertical layout."""
    text = concept.text.strip().upper() if hasattr(concept, "text") else "VIRAL MOMENT"
    subj = subject_rgba if subject_rgba is not None else art
    path, _ = compose_thumbnail(
        subject_rgba=subj,
        hook_text=text,
        aspect="9:16",
        out_path=out_path,
        template_name=template_name,
        source_frame=source_frame,
        face_box=face_box,
    )
    return path


def verify_thumbnail_ocr(thumb_img: Image.Image | Path, expected_text: str) -> tuple[bool, str]:
    """160px preview RapidOCR readability verification."""
    ok, msg, _ = quality_gate.verify_ocr_160px(thumb_img, expected_text)
    return ok, msg
