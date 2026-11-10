"""Bounding box geometry, intersection over union, clipping, and safe zone checking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Box:
    """Axis-aligned bounding box defined by [x1, y1, x2, y2]."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def w(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def h(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.w / 2.0, self.y1 + self.h / 2.0)

    def as_list(self) -> list[int]:
        return [round(self.x1), round(self.y1), round(self.x2), round(self.y2)]

    def as_floats(self) -> list[float]:
        return [self.x1, self.y1, self.x2, self.y2]


def iou(a: Box, b: Box) -> float:
    """Calculate Intersection over Union (IoU) between two bounding boxes."""
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)

    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter_area = iw * ih

    union_area = a.area + b.area - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def clamp_box(box: Box, w: int = 1080, h: int = 1920) -> Box:
    """Clamp box coordinates inside frame canvas [0, 0, w, h]."""
    x1 = max(0.0, min(float(w), box.x1))
    y1 = max(0.0, min(float(h), box.y1))
    x2 = max(x1, min(float(w), box.x2))
    y2 = max(y1, min(float(h), box.y2))
    return Box(x1=x1, y1=y1, x2=x2, y2=y2)


def expand(box: Box, pct: float) -> Box:
    """Expand box outward by percentage (e.g. 0.15 = 15% padding on all sides)."""
    dx = box.w * pct
    dy = box.h * pct
    return Box(
        x1=box.x1 - dx,
        y1=box.y1 - dy,
        x2=box.x2 + dx,
        y2=box.y2 + dy,
    )


def in_safe_zone(box: Box, layout_cfg: dict[str, Any] | None = None) -> bool:
    """Check if box center or majority falls inside 9:16 safe zones.

    Canvas: 1080x1920.
    Standard safe zone margins:
    - Top >= 220
    - Bottom <= 1500 (1920 - 420)
    - Left >= 60
    - Right <= 920 (1080 - 160)
    """
    safe_top = 220.0
    safe_bot = 1500.0
    safe_left = 60.0
    safe_right = 920.0

    if layout_cfg and "safe_zone" in layout_cfg:
        sz = layout_cfg["safe_zone"]
        safe_top = float(sz.get("top", safe_top))
        safe_bot = 1920.0 - float(sz.get("bottom", 420.0))
        safe_left = float(sz.get("sides", safe_left))
        right_pad = float(sz.get("sides", 60.0)) + float(sz.get("right_extra", 100.0))
        safe_right = 1080.0 - right_pad

    cx, cy = box.center
    return safe_left <= cx <= safe_right and safe_top <= cy <= safe_bot
