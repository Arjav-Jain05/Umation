"""provider.py: Abstract LLMProvider interface for local model execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Abstract interface for local LLM inference engines."""

    @abstractmethod
    def generate_json(
        self,
        task: str,
        prompt: str,
        schema: dict[str, Any],
        max_tokens: int = 1000,
        model: str | None = None,
        temperature: float = 0.2,
        think: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate schema-valid JSON for a given task."""
        pass

    @abstractmethod
    def generate_text(
        self,
        task: str,
        prompt: str,
        max_tokens: int = 1000,
        model: str | None = None,
        temperature: float = 0.3,
        think: bool = False,
        **kwargs: Any,
    ) -> str:
        """Generate text output for a given task."""
        pass

    @abstractmethod
    def unload_model(self, model: str) -> None:
        """Explicitly unload model from VRAM."""
        pass
