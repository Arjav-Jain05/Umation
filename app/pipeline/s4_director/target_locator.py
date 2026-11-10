"""Vision-based target locator for pointers and arrows via Gemini multimodal."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from app.core import paths
from app.utils.ffmpeg import run_ffmpeg
from app.utils.geometry import Box, clamp_box, expand, in_safe_zone

logger = logging.getLogger("app.pipeline.s4_director.target_locator")


@dataclass(frozen=True)
class LocatedBox:
    """Bounding box in pixel coordinates on the 1080x1920 canvas."""

    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    label: str | None = None

    @property
    def box(self) -> Box:
        return Box(float(self.x1), float(self.y1), float(self.x2), float(self.y2))

    @property
    def as_list(self) -> list[int]:
        return [self.x1, self.y1, self.x2, self.y2]


def parse_box(
    raw_box_2d: list[int | float] | tuple[int | float, ...],
    w: int = 1080,
    h: int = 1920,
    confidence: float = 1.0,
    label: str | None = None,
) -> LocatedBox | None:
    """Convert normalized [ymin, xmin, ymax, xmax] (0-1000 scale) to pixel coordinates.

    Applies strict rejection rules from 06 s7:
    - Must have 4 values.
    - Confidence must be >= 0.6.
    - Area must be between 1.5% and 60% of the frame canvas.
    - Box must not lie fully outside the safe zone.
    """
    if confidence < 0.6:
        logger.info("Target rejected: confidence %.2f < 0.6", confidence)
        return None

    if not raw_box_2d or len(raw_box_2d) != 4:
        logger.info("Target rejected: invalid box_2d length %s", raw_box_2d)
        return None

    ymin, xmin, ymax, xmax = [float(v) for v in raw_box_2d]

    # Convert 0-1000 scale to pixel coordinates
    x1 = round((xmin / 1000.0) * w)
    y1 = round((ymin / 1000.0) * h)
    x2 = round((xmax / 1000.0) * w)
    y2 = round((ymax / 1000.0) * h)

    # Clamp to canvas
    c_box = clamp_box(Box(float(x1), float(y1), float(x2), float(y2)), w=w, h=h)
    ix1, iy1, ix2, iy2 = c_box.as_list()

    box_area = c_box.area
    total_area = float(w * h)
    area_pct = box_area / max(1.0, total_area)

    # Area rules: between 1.5% (0.015) and 60% (0.60)
    if area_pct < 0.015:
        logger.info("Target rejected: area %.3f < 1.5%% of frame", area_pct)
        return None
    if area_pct > 0.60:
        logger.info("Target rejected: area %.3f > 60%% of frame", area_pct)
        return None

    # Safe zone rule: box center must lie in safe zone
    if not in_safe_zone(c_box):
        logger.info("Target rejected: box center outside safe zone (%s)", c_box.center)
        return None

    return LocatedBox(x1=ix1, y1=iy1, x2=ix2, y2=iy2, confidence=confidence, label=label)


def extract_frame(video_path: Path, t: float, out_jpeg: Path) -> Path:
    """Extract a single frame at time t, scaled to max side 1280."""
    out_jpeg.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "-ss", f"{max(0.0, t):.3f}",
        "-i", str(video_path),
        "-vframes", "1",
        "-vf", "scale='if(gt(iw,ih),min(1280,iw),-2)':'if(gt(ih,iw),min(1280,ih),-2)'",
        "-q:v", "2",
        "-y",
        str(out_jpeg),
    ]
    run_ffmpeg(cmd, check=True)
    return out_jpeg


def verify_crop(
    frame_path: Path,
    box: LocatedBox,
    target_description: str,
    gemini_client: Any,
) -> bool:
    """Verification pass: crop box (+15% padding) and confirm target presence."""
    try:
        with Image.open(frame_path) as img:
            w, h = img.size
            # Scale box from 1080x1920 to actual frame size if different
            sx = w / 1080.0
            sy = h / 1920.0
            scaled_box = Box(box.x1 * sx, box.y1 * sy, box.x2 * sx, box.y2 * sy)
            exp = expand(scaled_box, pct=0.15)
            c = clamp_box(exp, w=w, h=h)

            crop_img = img.crop((c.x1, c.y1, c.x2, c.y2))
            crop_path = frame_path.with_name(f"{frame_path.stem}_crop.jpg")
            crop_img.save(crop_path, format="JPEG", quality=85)

        prompt_template = (paths.prompts_dir() / "verify_target.md").read_text(encoding="utf-8")
        prompt = prompt_template.replace("{{target_description}}", target_description)

        res_text = gemini_client.call_with_image(prompt, crop_path)
        # Parse JSON
        m = re.search(r"\{.*\}", res_text, re.DOTALL)
        if not m:
            return False
        data = json.loads(m.group(0))
        return bool(data.get("shows_target") and float(data.get("confidence", 0.0)) >= 0.6)
    except Exception as e:
        logger.warning("Target crop verification failed with error: %s", e)
        return False


def locate(
    frame_path: Path,
    target_description: str,
    gemini_client: Any,
    fast_mode: bool = False,
) -> LocatedBox | None:
    """Locate object described in target_description on the given video frame."""
    prompt_template = (paths.prompts_dir() / "locate_target.md").read_text(encoding="utf-8")
    prompt = prompt_template.replace("{{target_description}}", target_description)

    try:
        res_text = gemini_client.call_with_image(prompt, frame_path)
        m = re.search(r"\{.*\}", res_text, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(0))
        if not data.get("found"):
            return None

        box_2d = data.get("box_2d")
        conf = float(data.get("confidence", 0.0))
        label = data.get("label")

        loc_box = parse_box(box_2d, w=1080, h=1920, confidence=conf, label=label)
        if not loc_box:
            return None

        # Verification pass (unless fast_mode)
        if not fast_mode:
            ok = verify_crop(frame_path, loc_box, target_description, gemini_client)
            if not ok:
                logger.info("Target failed verification pass for '%s'", target_description)
                return None

        return loc_box
    except Exception as e:
        logger.warning("Gemini target location failed for '%s': %s", target_description, e)
        return None
