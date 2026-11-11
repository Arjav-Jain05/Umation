"""local_llm.py: Local LLM client wrapping LocalModelManager for zero-cloud execution.

Replaces old Gemini client. Zero cloud AI calls, zero external API keys.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from PIL import Image, ImageDraw
from pydantic import BaseModel

from app.core.errors import BadModelOutput
from config.settings import Settings, get_settings
from llm.manager import LocalModelManager
from llm.ollama import OllamaProvider

logger = logging.getLogger("app.core.local_llm")
T = TypeVar("T", bound=BaseModel)


class LocalLLMClient:
    """Production local LLM client powered by Ollama and local model manager."""

    def __init__(self, settings: Settings | None = None, enable_cache: bool = True) -> None:
        self.settings = settings or get_settings()
        self.enable_cache = enable_cache
        self.provider = OllamaProvider(host=self.settings.ollama_host)
        self.manager = LocalModelManager(provider=self.provider)

    def generate_json(
        self,
        prompt: str,
        schema_model: type[T] | dict[str, Any],
        system_instruction: str | None = None,
        aspect: str | None = None,
        task: str = "clip_proposal",
        temperature: float | None = None,
        **kwargs: Any,
    ) -> T | dict[str, Any]:
        """Generate structured JSON adhering to the provided Pydantic schema."""
        logger.debug("LocalLLM generate_json task=%s prompt_len=%d", task, len(prompt))
        return self.manager.generate_json(
            task=task,
            prompt=prompt,
            schema_model=schema_model,
            system_instruction=system_instruction,
            temperature=temperature,
            **kwargs,
        )

    def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        task: str = "metadata",
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str:
        """Generate free-form text output from local model."""
        logger.debug("LocalLLM generate_text task=%s prompt_len=%d", task, len(prompt))
        return self.manager.generate_text(
            task=task,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            **kwargs,
        )

    def call_json(
        self,
        prompt: str,
        schema: type[T] | dict[str, Any] | None = None,
        schema_model: type[T] | dict[str, Any] | None = None,
        system_instruction: str | None = None,
        task: str = "clip_proposal",
        **kwargs: Any,
    ) -> T | dict[str, Any]:
        target = schema if schema is not None else schema_model
        return self.generate_json(
            prompt=prompt,
            schema_model=target,  # type: ignore
            system_instruction=system_instruction,
            task=task,
            **kwargs,
        )

    def call_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        task: str = "metadata",
        **kwargs: Any,
    ) -> str:
        return self.generate_text(
            prompt=prompt,
            system_instruction=system_instruction,
            task=task,
            **kwargs,
        )

    def generate_image(self, prompt: str, aspect: str = "16:9") -> Image.Image:
        """Generate thumbnail background using local procedural gradient canvas."""
        logger.info("Generating local procedural canvas thumbnail for prompt: %s (aspect %s)", prompt[:60], aspect)
        if aspect == "9:16":
            w, h = 1080, 1920
        else:
            w, h = 1280, 720

        img = Image.new("RGB", (w, h), color=(18, 18, 28))
        draw = ImageDraw.Draw(img)

        # Draw deep gaming gradient
        for y in range(h):
            ratio = y / float(h)
            r = int(24 * (1.0 - ratio) + 80 * ratio)
            g = int(14 * (1.0 - ratio) + 20 * ratio)
            b = int(45 * (1.0 - ratio) + 60 * ratio)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        return img


# Backward compatibility aliases for existing codebase callers
GeminiClient = LocalLLMClient


class FakeGeminiClient:
    """Mock LLM client for deterministic offline testing with canned responses."""

    def __init__(self, canned_response: Any = None) -> None:
        self.canned_response = canned_response
        self.calls: list[dict[str, Any]] = []

    def generate_json(
        self,
        prompt: str,
        schema_model: type[T],
        system_instruction: str | None = None,
        aspect: str | None = None,
        task: str = "clip_proposal",
        temperature: float | None = None,
        **kwargs: Any,
    ) -> T:
        self.calls.append({"prompt": prompt, "schema": schema_model, "system": system_instruction, "task": task})
        if self.canned_response is not None:
            if isinstance(self.canned_response, schema_model):
                return self.canned_response
            if isinstance(self.canned_response, dict):
                return schema_model.model_validate(self.canned_response)
        # Attempt default model instantiation
        try:
            return schema_model()
        except Exception as e:
            raise BadModelOutput("No canned response provided for FakeGeminiClient") from e

    def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        task: str = "metadata",
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str:
        self.calls.append({"prompt": prompt, "system": system_instruction, "task": task})
        if isinstance(self.canned_response, str):
            return self.canned_response
        return "Canned local LLM text response"

    def call_json(
        self,
        prompt: str,
        schema: type[T] | dict[str, Any] | None = None,
        schema_model: type[T] | dict[str, Any] | None = None,
        system_instruction: str | None = None,
        task: str = "clip_proposal",
        **kwargs: Any,
    ) -> T | dict[str, Any]:
        target = schema if schema is not None else schema_model
        return self.generate_json(
            prompt=prompt,
            schema_model=target,  # type: ignore
            system_instruction=system_instruction,
            task=task,
            **kwargs,
        )

    def call_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        task: str = "metadata",
        **kwargs: Any,
    ) -> str:
        return self.generate_text(
            prompt=prompt,
            system_instruction=system_instruction,
            task=task,
            **kwargs,
        )

    def generate_image(self, prompt: str, aspect: str = "16:9") -> Image.Image:
        w, h = (1080, 1920) if aspect == "9:16" else (1280, 720)
        return Image.new("RGB", (w, h), color=(30, 30, 45))


class TokenBucket:
    """Rate limiter token bucket maintained for backward compatibility."""

    def __init__(self, rpm: float = 60.0) -> None:
        self.capacity = float(rpm)
        self.tokens = float(rpm)

    def acquire(self) -> None:
        if self.tokens > 0:
            self.tokens -= 0.1


GeminiClient = LocalLLMClient
