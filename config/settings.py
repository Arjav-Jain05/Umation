"""Typed configuration settings loaded from .env.

Spec: docs/SPEC.md
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    """Application settings with validation."""

    # Local LLM / Ollama configuration
    ollama_host: str = Field(default="127.0.0.1:11434")
    weights_dir: Path = Field(default=Path("D:\\Open_Source_Weights"))
    llm_proposer_model_1: str = Field(default="qwen3.5:9b")
    llm_proposer_model_2: str = Field(default="gemma4:e4b")
    llm_critic_model: str = Field(default="gemma4:e4b")
    llm_rerank_models: str = Field(default="qwen3.5:9b,gemma4:e4b")
    llm_metadata_model: str = Field(default="gemma4:e4b")

    # Layer 0 Whisper
    whisper_model: str = Field(default="large-v3-turbo")
    whisper_device: Literal["cuda", "cpu"] = Field(default="cuda")
    whisper_compute: str = Field(default="float16")
    whisper_language: str = Field(default="auto")

    # Pipeline & Scoring
    clip_min_score: int = Field(default=65, ge=0, le=100)
    pipeline_preset: Literal["Fast", "Balanced", "Best"] = Field(default="Balanced")
    layer_sensors_enabled: bool = Field(default=True)
    layer_visual_enabled: bool = Field(default=True)
    layer_thumbnails_enabled: bool = Field(default=True)

    # Storage & Networking
    project_domain: str = Field(default="gta6")
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    output_dir: Path = Field(default=PROJECT_ROOT / "output")

    max_source_height: int = Field(default=1080, ge=360, le=2160)
    max_source_hours: int = Field(default=12, ge=1, le=24)
    min_free_gb: int = Field(default=30, ge=10)

    auto_update_ytdlp: bool = Field(default=True)
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000, ge=1024, le=65535)

    small_video_min: int = Field(default=40, ge=5)
    clean_after_days: int = Field(default=7, ge=1)
    max_clips_soft: int = Field(default=40, ge=1)
    local_image_fallback: bool = Field(default=True)

    # Legacy compatibility fields (empty defaults, no cloud calls)
    gemini_api_key: str = Field(default="")
    gemini_model_text: str = Field(default="qwen3.5:9b")
    gemini_model_image: str = Field(default="")
    gemini_rpm: int = Field(default=60)
    gemini_timeout_s: int = Field(default=120)

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @field_validator("data_dir", "output_dir", "weights_dir", mode="after")
    @classmethod
    def resolve_path(cls, v: Path) -> Path:
        if not v.is_absolute():
            v = (PROJECT_ROOT / v).resolve()
        return v

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> Settings:
        """Load settings from .env file and environment variables."""
        if env_path is None:
            env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)

        if not shutil.which("deno"):
            local_deno = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
            deno_candidates = list(local_deno.glob("**/deno.exe")) if local_deno.exists() else []
            if deno_candidates:
                os.environ["PATH"] = str(deno_candidates[0].parent) + ";" + os.environ.get("PATH", "")

        def get_bool(key: str, default: bool) -> bool:
            val = os.getenv(key)
            if val is None:
                return default
            return val.strip().lower() in ("true", "1", "yes", "on")

        def get_int(key: str, default: int) -> int:
            val = os.getenv(key)
            if val is None:
                return default
            try:
                return int(val.strip())
            except ValueError:
                return default

        preset_val = os.getenv("PIPELINE_PRESET", "Balanced").strip()
        if preset_val not in ("Fast", "Balanced", "Best"):
            preset_val = "Balanced"

        return cls(
            ollama_host=os.getenv("OLLAMA_HOST", "127.0.0.1:11434").strip(),
            weights_dir=Path(os.getenv("WEIGHTS_DIR", "D:\\Open_Source_Weights")),
            llm_proposer_model_1=os.getenv("LLM_PROPOSER_MODEL_1", "qwen3.5:9b").strip(),
            llm_proposer_model_2=os.getenv("LLM_PROPOSER_MODEL_2", "gemma4:e4b").strip(),
            llm_critic_model=os.getenv("LLM_CRITIC_MODEL", "gemma4:e4b").strip(),
            llm_rerank_models=os.getenv("LLM_RERANK_MODELS", "qwen3.5:9b,gemma4:e4b").strip(),
            llm_metadata_model=os.getenv("LLM_METADATA_MODEL", "gemma4:e4b").strip(),
            whisper_model=os.getenv("WHISPER_MODEL", "large-v3").strip(),
            whisper_device=os.getenv("WHISPER_DEVICE", "cuda").strip(),  # type: ignore
            whisper_compute=os.getenv("WHISPER_COMPUTE", "float16").strip(),
            whisper_language=os.getenv("WHISPER_LANGUAGE", "auto").strip(),
            clip_min_score=get_int("CLIP_MIN_SCORE", 65),
            pipeline_preset=preset_val,  # type: ignore
            layer_sensors_enabled=get_bool("LAYER_SENSORS_ENABLED", True),
            layer_visual_enabled=get_bool("LAYER_VISUAL_ENABLED", True),
            layer_thumbnails_enabled=get_bool("LAYER_THUMBNAILS_ENABLED", True),
            project_domain=os.getenv("PROJECT_DOMAIN", "gta6").strip(),
            data_dir=Path(os.getenv("DATA_DIR", "./data")),
            output_dir=Path(os.getenv("OUTPUT_DIR", "./output")),
            max_source_height=get_int("MAX_SOURCE_HEIGHT", 1080),
            max_source_hours=get_int("MAX_SOURCE_HOURS", 12),
            min_free_gb=get_int("MIN_FREE_GB", 30),
            auto_update_ytdlp=get_bool("AUTO_UPDATE_YTDLP", True),
            host=os.getenv("HOST", "127.0.0.1").strip(),
            port=get_int("PORT", 8000),
            small_video_min=get_int("SMALL_VIDEO_MIN", 40),
            clean_after_days=get_int("CLEAN_AFTER_DAYS", 7),
            max_clips_soft=get_int("MAX_CLIPS_SOFT", 40),
            local_image_fallback=get_bool("LOCAL_IMAGE_FALLBACK", True),
            gemini_api_key="",
            gemini_model_text=os.getenv("LLM_PROPOSER_MODEL_1", "qwen3.5:9b").strip(),
            gemini_model_image="",
            gemini_rpm=60,
            gemini_timeout_s=120,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton settings instance."""
    return Settings.from_env()
