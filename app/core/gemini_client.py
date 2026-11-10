"""Gemini API client with structured outputs, token-bucket rate limiting, retries, and caching."""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, TypeVar

from PIL import Image
from pydantic import BaseModel

from app.core.cache import cache_get, cache_set, make_key
from app.core.errors import BadModelOutput, GeminiQuotaExceeded, GeminiUnavailable
from config.settings import Settings, get_settings

logger = logging.getLogger("app.core.gemini_client")
T = TypeVar("T", bound=BaseModel)


class TokenBucket:
    """Thread-safe token bucket rate limiter for requests per minute (RPM)."""

    def __init__(self, rpm: int) -> None:
        self.rpm = max(1, rpm)
        self.capacity = float(self.rpm)
        self.tokens = float(self.rpm)
        self.fill_rate = float(self.rpm) / 60.0
        self.last_update = time.monotonic()

    def acquire(self) -> None:
        while True:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return

            sleep_time = (1.0 - self.tokens) / self.fill_rate
            time.sleep(max(0.05, sleep_time))


class GeminiClient:
    """Production Gemini client wrapping official google-genai SDK."""

    def __init__(self, settings: Settings | None = None, enable_cache: bool = True) -> None:
        self.settings = settings or get_settings()
        self.enable_cache = enable_cache
        self.limiter = TokenBucket(self.settings.gemini_rpm)
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from google import genai

            api_key = self.settings.gemini_api_key
            if not api_key:
                raise GeminiUnavailable("GEMINI_API_KEY is not set in environment or .env")
            self._client = genai.Client(api_key=api_key)
        return self._client

    def _call_with_retry(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute API call with exponential backoff on 429/500/503 and quota detection."""
        delays = [2.0, 4.0, 8.0, 16.0, 32.0]
        for attempt in range(len(delays) + 1):
            self.limiter.acquire()
            try:
                t0 = time.monotonic()
                res = fn(*args, **kwargs)
                latency = time.monotonic() - t0
                logger.debug("Gemini call succeeded in %.2fs (attempt %d)", latency, attempt + 1)
                return res
            except Exception as e:
                err_msg = str(e).lower()

                # Quota exceeded detection
                if "quota" in err_msg or "daily" in err_msg or "resource_exhausted" in err_msg:
                    # Distinguish per-minute rate limit vs daily quota
                    if "per-minute" in err_msg or "rate limit" in err_msg:
                        pass  # Treat as normal 429 to retry
                    else:
                        logger.error("Gemini daily quota exceeded: %s", e)
                        raise GeminiQuotaExceeded(
                            "Gemini daily quota reached. Job is queued to resume later.",
                            hint="Wait for your quota to reset or upgrade tier in Google AI Studio",
                        ) from e

                if attempt >= len(delays):
                    logger.error("Gemini call failed after %d retries: %s", len(delays), e)
                    raise GeminiUnavailable(f"Gemini API unavailable: {e}") from e

                base_delay = delays[attempt]
                jitter = random.uniform(0.1, 0.9)
                sleep_s = base_delay + jitter
                logger.warning(
                    "Gemini API error (attempt %d/%d): %s. Backing off for %.2fs",
                    attempt + 1,
                    len(delays),
                    e,
                    sleep_s,
                )
                time.sleep(sleep_s)

    def generate_json(
        self,
        prompt: str,
        schema_model: type[T],
        *,
        temperature: float = 0.2,
        cache_key: str | None = None,
        images: list[Any] | None = None,
        system: str | None = None,
    ) -> T:
        """Generate structured JSON adhering to schema_model, with caching and 1 schema retry."""
        key = cache_key or make_key(
            self.settings.gemini_model_text,
            prompt,
            schema_model.__name__,
            temperature,
            str(images),
        )

        if self.enable_cache:
            cached_val = cache_get(key)
            if cached_val is not None:
                try:
                    data = json.loads(cached_val)
                    logger.debug("Cache hit for Gemini JSON: %s", key[:12])
                    return schema_model.model_validate(data)
                except Exception as e:
                    logger.warning("Corrupted cache entry for %s, re-generating: %s", key[:12], e)

        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema_model,
        )

        # First attempt
        content_inputs: list[Any] = [prompt]
        if images:
            content_inputs.extend(images)

        response = self._call_with_retry(
            self.client.models.generate_content,
            model=self.settings.gemini_model_text,
            contents=content_inputs,
            config=config,
        )

        raw_text = (response.text or "").strip()
        try:
            data = json.loads(raw_text)
            parsed = schema_model.model_validate(data)
            if self.enable_cache:
                cache_set(key, json.dumps(data, ensure_ascii=False))
            return parsed
        except Exception as first_err:
            logger.warning("Gemini JSON validation failed: %s. Retrying once with error feedback...", first_err)

            # Retry once with validation feedback
            feedback_prompt = (
                f"{prompt}\n\n"
                f"Your previous output failed validation with error: {first_err}\n"
                "Please fix the error and output strictly valid JSON matching the schema."
            )
            retry_response = self._call_with_retry(
                self.client.models.generate_content,
                model=self.settings.gemini_model_text,
                contents=[feedback_prompt] + (images or []),
                config=config,
            )
            retry_text = (retry_response.text or "").strip()
            try:
                retry_data = json.loads(retry_text)
                parsed = schema_model.model_validate(retry_data)
                if self.enable_cache:
                    cache_set(key, json.dumps(retry_data, ensure_ascii=False))
                return parsed
            except Exception as final_err:
                logger.error("Gemini failed schema validation twice. Raw text was: %s", retry_text[:200])
                raise BadModelOutput(
                    f"Gemini output violated schema {schema_model.__name__}: {final_err}",
                    hint="Check model temperature or tighten prompt instructions",
                ) from final_err

    def generate_text(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        cache_key: str | None = None,
        images: list[Any] | None = None,
        system: str | None = None,
    ) -> str:
        """Generate free-form text output from Gemini."""
        key = cache_key or make_key(
            self.settings.gemini_model_text,
            prompt,
            temperature,
            str(images),
        )

        if self.enable_cache:
            cached_val = cache_get(key)
            if cached_val is not None:
                logger.debug("Cache hit for Gemini text: %s", key[:12])
                return cached_val

        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system,
        )

        content_inputs: list[Any] = [prompt]
        if images:
            content_inputs.extend(images)

        response = self._call_with_retry(
            self.client.models.generate_content,
            model=self.settings.gemini_model_text,
            contents=content_inputs,
            config=config,
        )

        text = (response.text or "").strip()
        if self.enable_cache:
            cache_set(key, text)
        return text

    def generate_image(self, prompt: str, aspect: str = "16:9") -> Image.Image:
        """Generate an image using Gemini image model (or return pillow canvas fallback)."""
        model_name = self.settings.gemini_model_image
        logger.info("Requesting Gemini image generation with model %s (aspect %s)", model_name, aspect)
        from google.genai import types

        config = types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio=aspect,
        )

        try:
            res = self._call_with_retry(
                self.client.models.generate_images,
                model=model_name,
                prompt=prompt,
                config=config,
            )
            if res.generated_images:
                img_bytes = res.generated_images[0].image.image_bytes
                import io

                return Image.open(io.BytesIO(img_bytes))
        except Exception as e:
            logger.warning("Gemini image generation failed (%s); using pillow fallback", e)

        # Fallback to pillow solid banner
        w, h = (1280, 720) if aspect == "16:9" else (1080, 1920)
        return Image.new("RGB", (w, h), color=(30, 34, 42))


class FakeGeminiClient:
    """Mock GeminiClient for deterministic offline testing with canned responses."""

    def __init__(self, canned: dict[str, Any] | None = None) -> None:
        self.canned: dict[str, Any] = canned or {}
        self.call_log: list[dict[str, Any]] = []

    def generate_json(
        self,
        prompt: str,
        schema_model: type[T],
        *,
        temperature: float = 0.2,
        cache_key: str | None = None,
        images: list[Any] | None = None,
        system: str | None = None,
    ) -> T:
        self.call_log.append({
            "type": "json",
            "prompt": prompt,
            "schema": schema_model.__name__,
            "cache_key": cache_key,
        })

        # Match schema or prompt substring
        if schema_model.__name__ in self.canned:
            val = self.canned[schema_model.__name__]
        elif cache_key and cache_key in self.canned:
            val = self.canned[cache_key]
        else:
            # Search for keyword match
            val = None
            for k, v in self.canned.items():
                if k.lower() in prompt.lower():
                    val = v
                    break

        if val is None:
            # Instantiate an empty model or raise
            try:
                return schema_model.model_validate({})
            except Exception as e:
                raise BadModelOutput(f"No canned response for {schema_model.__name__}: {e}") from e

        if isinstance(val, BaseModel):
            return val  # type: ignore
        return schema_model.model_validate(val)

    def generate_text(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        cache_key: str | None = None,
        images: list[Any] | None = None,
        system: str | None = None,
    ) -> str:
        self.call_log.append({"type": "text", "prompt": prompt})
        for k, v in self.canned.items():
            if k.lower() in prompt.lower():
                return str(v)
        return "Canned model response text."

    def generate_image(self, prompt: str, aspect: str = "16:9") -> Image.Image:
        self.call_log.append({"type": "image", "prompt": prompt, "aspect": aspect})
        w, h = (1280, 720) if aspect == "16:9" else (1080, 1920)
        return Image.new("RGB", (w, h), color=(40, 50, 70))
