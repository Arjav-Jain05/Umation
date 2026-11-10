"""Animation easing functions and linear interpolation helpers."""

from __future__ import annotations


def clamp01(x: float) -> float:
    """Clamp float to [0.0, 1.0]."""
    return max(0.0, min(1.0, float(x)))


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between a and b by factor t."""
    return a + (b - a) * t


def ease_out_cubic(x: float) -> float:
    """Cubic ease-out: starts fast, decelerates to stop."""
    u = clamp01(x)
    return 1.0 - (1.0 - u) ** 3


def ease_in_out(x: float) -> float:
    """Smoothstep cubic ease-in-out: starts slow, accelerates, decelerates."""
    u = clamp01(x)
    return 3.0 * (u**2) - 2.0 * (u**3)


def ease_out_back(x: float, overshoot: float = 1.4) -> float:
    """Back ease-out with overshoot bounce before settling at 1.0."""
    u = clamp01(x)
    c1 = overshoot
    c3 = c1 + 1.0
    return 1.0 + c3 * ((u - 1.0) ** 3) + c1 * ((u - 1.0) ** 2)
