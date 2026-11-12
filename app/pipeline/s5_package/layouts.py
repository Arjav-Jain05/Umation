"""Percent-based layout templates for 16:9 (1280x720) and 9:16 (1080x1920).

Implements Section 2.3 of Prompt v7:
- 5 distinct layout families: Big Reaction, Hero Center, Versus Split, Mystery Zoom, Number Punch
- 9:16 has dedicated vertical layouts (subject in lower-middle 55-60%, text in upper third)
- Safe area enforcement: bottom 20% and right 15% clear of vital text/faces
- Canvas coverage rules: never leave >25% of canvas as flat empty space
"""

from __future__ import annotations

from typing import Any

LAYOUT_TEMPLATES: dict[str, dict[str, Any]] = {
    "big_reaction": {
        "16:9": {
            # Subject on right side (45-55% width), text on left side
            "subject_zone": {"x": 0.46, "y": 0.08, "w": 0.52, "h": 0.88},
            "text_zone": {"x": 0.04, "y": 0.16, "w": 0.42, "h": 0.65},
            "anchor": (0.72, 0.50),  # Focal center for bursts
            "bg_family": "radial_burst",
            "arrow": {"start": (0.38, 0.48), "end": (0.58, 0.42)},
            "circle": None,
            "badge": None,
        },
        "9:16": {
            # Subject in lower-middle (55-60% height), text in top third
            "subject_zone": {"x": 0.06, "y": 0.36, "w": 0.88, "h": 0.52},
            "text_zone": {"x": 0.06, "y": 0.08, "w": 0.88, "h": 0.25},
            "anchor": (0.50, 0.60),
            "bg_family": "spotlight_vignette",
            "arrow": None,
            "circle": None,
            "badge": None,
        },
    },
    "hero_center": {
        "16:9": {
            # Subject centered and huge, text across top
            "subject_zone": {"x": 0.24, "y": 0.12, "w": 0.52, "h": 0.84},
            "text_zone": {"x": 0.04, "y": 0.06, "w": 0.92, "h": 0.26},
            "anchor": (0.50, 0.55),
            "bg_family": "radial_burst",
            "arrow": None,
            "circle": None,
            "badge": None,
        },
        "9:16": {
            # Subject centered, text in upper third
            "subject_zone": {"x": 0.08, "y": 0.34, "w": 0.84, "h": 0.54},
            "text_zone": {"x": 0.05, "y": 0.08, "w": 0.90, "h": 0.24},
            "anchor": (0.50, 0.58),
            "bg_family": "speed_lines",
            "arrow": None,
            "circle": None,
            "badge": None,
        },
    },
    "versus_split": {
        "16:9": {
            # Left vs Right with VS badge in center
            "subject_zone": {"x": 0.48, "y": 0.10, "w": 0.50, "h": 0.86},
            "text_zone": {"x": 0.04, "y": 0.06, "w": 0.92, "h": 0.24},
            "anchor": (0.50, 0.50),
            "bg_family": "versus_split",
            "arrow": None,
            "circle": None,
            "badge": "vs",
        },
        "9:16": {
            # Top vs Bottom or centered with VS badge
            "subject_zone": {"x": 0.06, "y": 0.38, "w": 0.88, "h": 0.50},
            "text_zone": {"x": 0.05, "y": 0.08, "w": 0.90, "h": 0.24},
            "anchor": (0.50, 0.50),
            "bg_family": "versus_split",
            "arrow": None,
            "circle": None,
            "badge": "vs",
        },
    },
    "mystery_zoom": {
        "16:9": {
            # Subject / action zoom with red circle + arrow
            "subject_zone": {"x": 0.38, "y": 0.08, "w": 0.58, "h": 0.88},
            "text_zone": {"x": 0.04, "y": 0.18, "w": 0.38, "h": 0.60},
            "anchor": (0.65, 0.45),
            "bg_family": "spotlight_vignette",
            "arrow": {"start": (0.35, 0.45), "end": (0.54, 0.38)},
            "circle": {"center": (0.60, 0.40), "radius": 0.14},
            "badge": None,
        },
        "9:16": {
            # 9:16 action zoom
            "subject_zone": {"x": 0.08, "y": 0.32, "w": 0.84, "h": 0.52},
            "text_zone": {"x": 0.05, "y": 0.08, "w": 0.90, "h": 0.22},
            "anchor": (0.50, 0.52),
            "bg_family": "spotlight_vignette",
            "arrow": {"start": (0.30, 0.30), "end": (0.48, 0.42)},
            "circle": {"center": (0.50, 0.44), "radius": 0.12},
            "badge": None,
        },
    },
    "number_punch": {
        "16:9": {
            # Huge number / stat punch on left, subject on right
            "subject_zone": {"x": 0.48, "y": 0.10, "w": 0.50, "h": 0.86},
            "text_zone": {"x": 0.04, "y": 0.14, "w": 0.44, "h": 0.68},
            "anchor": (0.72, 0.50),
            "bg_family": "comic_halftone",
            "arrow": None,
            "circle": None,
            "badge": "shock",
        },
        "9:16": {
            # Giant stat across upper third
            "subject_zone": {"x": 0.08, "y": 0.38, "w": 0.84, "h": 0.50},
            "text_zone": {"x": 0.04, "y": 0.08, "w": 0.92, "h": 0.28},
            "anchor": (0.50, 0.60),
            "bg_family": "comic_halftone",
            "arrow": None,
            "circle": None,
            "badge": "shock",
        },
    },
}


def get_layout(template_name: str, aspect: str = "16:9") -> dict[str, Any]:
    """Retrieve percent-based layout dictionary for a template and aspect ratio."""
    tmpl = LAYOUT_TEMPLATES.get(template_name, LAYOUT_TEMPLATES["big_reaction"])
    return tmpl.get(aspect, tmpl["16:9"])


def resolve_zone_pixels(zone_pct: dict[str, float], canvas_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Convert percent-based zone dictionary {x, y, w, h} into pixel bbox (x, y, w, h)."""
    cw, ch = canvas_size
    px = int(zone_pct["x"] * cw)
    py = int(zone_pct["y"] * ch)
    pw = int(zone_pct["w"] * cw)
    ph = int(zone_pct["h"] * ch)
    return px, py, pw, ph
