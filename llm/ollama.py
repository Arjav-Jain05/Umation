"""ollama.py: Ollama implementation of LLMProvider with structured schema support."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

from llm.provider import LLMProvider

logger = logging.getLogger("llm.ollama")


class OllamaProvider(LLMProvider):
    """Local Ollama client wrapping localhost:11434 HTTP API."""

    def __init__(self, host: str | None = None) -> None:
        raw_host = host or os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
        if not raw_host.startswith("http://") and not raw_host.startswith("https://"):
            self.host = f"http://{raw_host}"
        else:
            self.host = raw_host

    def _post(self, endpoint: str, payload: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
        url = f"{self.host}{endpoint}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ConnectionRefusedError) or "[WinError 10061]" in str(exc):
                raise ConnectionError(
                    f"Cannot reach Ollama at {self.host}. Is Ollama running? Start with: 'ollama serve'"
                ) from exc
            raise

    def generate_json(
        self,
        task: str,
        prompt: str,
        schema: dict[str, Any],
        max_tokens: int = 1000,
        model: str | None = None,
        temperature: float = 0.2,
        think: bool = False,
        num_ctx: int = 4096,
        keep_alive: int | str = "5m",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate structured JSON adhering to the provided JSON schema."""
        model_name = model or os.environ.get("LLM_PROPOSER_MODEL_1", "qwen3.5:9b")
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "format": schema,
            "stream": False,
            "think": think,
            "keep_alive": keep_alive,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": num_ctx,
            },
        }

        t0 = time.monotonic()
        data = self._post("/api/chat", payload, timeout=180.0)
        latency = time.monotonic() - t0

        msg = data.get("message", {})
        content = msg.get("content", "").strip()
        eval_count = data.get("eval_count", 0)
        eval_duration_ns = data.get("eval_duration", 1)
        tokens_per_sec = (eval_count / (eval_duration_ns / 1e9)) if eval_duration_ns > 0 else 0.0

        logger.debug(
            "Ollama JSON task=%s model=%s tokens=%d speed=%.1ft/s latency=%.2fs",
            task,
            model_name,
            eval_count,
            tokens_per_sec,
            latency,
        )

        if not content:
            raise ValueError(f"Ollama returned empty content for task '{task}' (model: {model_name})")

        try:
            parsed = json.loads(content)
            return parsed
        except json.JSONDecodeError as exc:
            # Check for markdown code fence
            if "```json" in content:
                extracted = content.split("```json")[-1].split("```")[0].strip()
                try:
                    return json.loads(extracted)
                except Exception:
                    pass
            elif "```" in content:
                extracted = content.split("```")[-1].split("```")[0].strip()
                try:
                    return json.loads(extracted)
                except Exception:
                    pass
            raise ValueError(f"Failed to decode JSON from model {model_name}: {exc}\nRaw output: {content}") from exc

    def generate_text(
        self,
        task: str,
        prompt: str,
        max_tokens: int = 1000,
        model: str | None = None,
        temperature: float = 0.3,
        think: bool = False,
        num_ctx: int = 4096,
        keep_alive: int | str = "5m",
        **kwargs: Any,
    ) -> str:
        """Generate free-form text output."""
        model_name = model or os.environ.get("LLM_PROPOSER_MODEL_1", "qwen3.5:9b")
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": think,
            "keep_alive": keep_alive,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": num_ctx,
            },
        }

        t0 = time.monotonic()
        data = self._post("/api/chat", payload, timeout=180.0)
        latency = time.monotonic() - t0

        msg = data.get("message", {})
        content = msg.get("content", "").strip()
        eval_count = data.get("eval_count", 0)
        eval_duration_ns = data.get("eval_duration", 1)
        tokens_per_sec = (eval_count / (eval_duration_ns / 1e9)) if eval_duration_ns > 0 else 0.0

        logger.debug(
            "Ollama text task=%s model=%s tokens=%d speed=%.1ft/s latency=%.2fs",
            task,
            model_name,
            eval_count,
            tokens_per_sec,
            latency,
        )
        return content

    def unload_model(self, model: str) -> None:
        """Unload model from GPU memory immediately."""
        try:
            self._post("/api/generate", {"model": model, "keep_alive": 0}, timeout=5.0)
            logger.info("Unloaded Ollama model: %s", model)
        except Exception as exc:
            logger.debug("Failed to unload %s: %s", model, exc)
