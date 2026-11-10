"""Base Protocol and registry for video overlay effect renderers."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np


class Effect(Protocol):
    """Protocol implemented by every overlay effect renderer."""

    def render(
        self,
        frame: np.ndarray,
        t_local: float,
        dur: float,
        params: dict[str, Any],
        canvas_w: int = 1080,
        canvas_h: int = 1920,
    ) -> np.ndarray:
        """Render effect onto the given BGR frame and return the modified frame."""
        ...


REGISTRY: dict[str, Effect] = {}


def register_effect(name: str):
    def decorator(cls):
        REGISTRY[name] = cls()
        return cls

    return decorator
