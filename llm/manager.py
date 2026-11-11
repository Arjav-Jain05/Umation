"""manager.py: Hardened LocalModelManager with task fallback chains, OOM handling, and schema repair."""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel

from app.core.errors import AllLocalModelsFailed, BadModelOutput
from llm.ollama import OllamaProvider
from llm.provider import LLMProvider

logger = logging.getLogger("llm.manager")

T = TypeVar("T", bound=BaseModel)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "models.yaml"


class LocalModelManager:
    """Manages local model inference with fallback chains, retries, and schema validation."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        config_path: Path | None = None,
    ) -> None:
        self.provider = provider or OllamaProvider()
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.chains = self._load_chains()
        self.call_history: list[dict[str, Any]] = []

    def _load_chains(self) -> dict[str, list[dict[str, Any]]]:
        if self.config_path.exists():
            try:
                with open(self.config_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    return data.get("chains", {})
            except Exception as exc:
                logger.warning("Failed to parse %s: %s; using hardcoded defaults", self.config_path, exc)

        return {
            "clip_proposal": [
                {"model": "qwen3.5:9b", "num_ctx": 4096, "temperature": 0.2, "think": False},
                {"model": "gemma4:e4b", "num_ctx": 4096, "temperature": 0.2, "think": False},
                {"model": "qwen2.5:7b", "num_ctx": 4096, "temperature": 0.2, "think": False},
                {"model": "qwen3.5:4b", "num_ctx": 4096, "temperature": 0.2, "think": False},
            ],
            "critic": [
                {"model": "qwen3.5:9b", "num_ctx": 4096, "temperature": 0.3, "think": True},
                {"model": "gemma4:e4b", "num_ctx": 4096, "temperature": 0.3, "think": True},
            ],
            "arc_stitching": [
                {"model": "qwen3.5:9b", "num_ctx": 4096, "temperature": 0.2, "think": False},
            ],
            "metadata": [
                {"model": "qwen3.5:9b", "num_ctx": 4096, "temperature": 0.3, "think": False},
            ],
            "title_judge": [
                {"model": "qwen3.5:9b", "num_ctx": 4096, "temperature": 0.2, "think": False},
            ],
            "thumbnail_prompt": [
                {"model": "qwen3.5:9b", "num_ctx": 4096, "temperature": 0.4, "think": False},
            ],
        }

    def _get_chain_for_task(self, task: str) -> list[dict[str, Any]]:
        chain = self.chains.get(task, [])
        if not chain:
            # Fallback to single primary model
            return [{"model": "qwen3.5:9b", "num_ctx": 4096, "temperature": 0.2, "think": False}]
        return chain

    def generate_json(
        self,
        task: str,
        prompt: str,
        schema_model: type[T] | dict[str, Any],
        system_instruction: str | None = None,
        max_tokens: int = 1500,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> T | dict[str, Any]:
        """Execute JSON generation through the task's model chain with repair retries."""
        # Convert schema_model to JSON schema dict if Pydantic model
        is_pydantic = isinstance(schema_model, type) and issubclass(schema_model, BaseModel)
        schema_dict = schema_model.model_json_schema() if is_pydantic else schema_model  # type: ignore

        full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
        chain = self._get_chain_for_task(task)
        errors: list[str] = []

        for step in chain:
            model = step.get("model", "qwen3.5:9b")
            num_ctx = step.get("num_ctx", 4096)
            temp = temperature if temperature is not None else step.get("temperature", 0.2)
            think = step.get("think", False)

            # Retry loop for connection / repair
            for attempt in range(2):
                try:
                    t0 = time.monotonic()
                    raw_dict = self.provider.generate_json(
                        task=task,
                        prompt=full_prompt,
                        schema=schema_dict,
                        max_tokens=max_tokens,
                        model=model,
                        temperature=temp,
                        think=think,
                        num_ctx=num_ctx,
                        keep_alive=0,
                    )
                    latency = time.monotonic() - t0

                    # Validate against Pydantic schema if provided
                    if is_pydantic:
                        parsed_obj = schema_model.model_validate(raw_dict)  # type: ignore
                        self.call_history.append({
                            "task": task,
                            "model": model,
                            "latency_s": latency,
                            "success": True,
                        })
                        return parsed_obj
                    else:
                        self.call_history.append({
                            "task": task,
                            "model": model,
                            "latency_s": latency,
                            "success": True,
                        })
                        return raw_dict

                except (ValueError, BadModelOutput) as parse_err:
                    logger.warning("JSON parse/schema error on %s (attempt %d): %s", model, attempt + 1, parse_err)
                    if attempt == 0:
                        # Schema repair retry with error feedback
                        full_prompt = (
                            f"{full_prompt}\n\n"
                            f"[ERROR: Your previous JSON output was invalid: {parse_err}. "
                            f"Output ONLY valid JSON matching the exact schema without extra commentary.]"
                        )
                        continue
                    errors.append(f"{model}: {parse_err}")

                except (MemoryError, RuntimeError) as oom_err:
                    if isinstance(oom_err, MemoryError) or "out of memory" in str(oom_err).lower():
                        logger.warning("CUDA OOM / memory error on %s: %s. Unloading and reducing context.", model, oom_err)
                        self.provider.unload_model(model)
                        if num_ctx > 2048:
                            num_ctx = 2048
                            continue
                        errors.append(f"{model} OOM: {oom_err}")
                        break
                    else:
                        logger.warning("Model %s failed on task %s: %s", model, task, oom_err)
                        if attempt == 1:
                            errors.append(f"{model}: {oom_err}")

                except Exception as exc:
                    logger.warning("Model %s failed on task %s: %s", model, task, exc)
                    # Small backoff before retry or next model
                    time.sleep(0.5 + random.uniform(0.1, 0.4))
                    if attempt == 1:
                        errors.append(f"{model}: {exc}")

        raise AllLocalModelsFailed(
            f"All local models in chain failed for task '{task}'. Errors: {'; '.join(errors)}"
        )

    def generate_text(
        self,
        task: str,
        prompt: str,
        system_instruction: str | None = None,
        max_tokens: int = 1000,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str:
        """Execute text generation through task's fallback chain."""
        full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
        chain = self._get_chain_for_task(task)
        errors: list[str] = []

        for step in chain:
            model = step.get("model", "qwen3.5:9b")
            num_ctx = step.get("num_ctx", 4096)
            temp = temperature if temperature is not None else step.get("temperature", 0.3)
            think = step.get("think", False)

            try:
                t0 = time.monotonic()
                text = self.provider.generate_text(
                    task=task,
                    prompt=full_prompt,
                    max_tokens=max_tokens,
                    model=model,
                    temperature=temp,
                    think=think,
                    num_ctx=num_ctx,
                    keep_alive=0,
                )
                latency = time.monotonic() - t0
                self.call_history.append({
                    "task": task,
                    "model": model,
                    "latency_s": latency,
                    "success": True,
                })
                return text
            except Exception as exc:
                logger.warning("Model %s text gen failed on task %s: %s", model, task, exc)
                errors.append(f"{model}: {exc}")

        raise AllLocalModelsFailed(
            f"All local models in chain failed for task '{task}'. Errors: {'; '.join(errors)}"
        )

    def unload_all(self) -> None:
        """Unload all models."""
        for task_steps in self.chains.values():
            if isinstance(task_steps, list):
                for step in task_steps:
                    model = step.get("model")
                    if model:
                        self.provider.unload_model(model)
