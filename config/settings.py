"""Typed configuration settings loaded from .env.

Spec: references/01-environment-and-setup.md section 6.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    """Application settings with validation."""

    gemini_api_key: str = Field(default="")
    gemini_model_text: str = Field(default="gemini-2.5-flash")
    gemini_model_image: str = Field(default="gemini-2.5-flash-image")
    gemini_rpm: int = Field(default=8, ge=1, le=60)
    gemini_timeout_s: int = Field(default=120, ge=10)

    whisper_model: str = Field(default="large-v3")
    whisper_device: Literal["cuda", "cpu"] = Field(default="cuda")
    whisper_compute: str = Field(default="float16")
    whisper_language: str = Field(default="auto")

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
    local_image_fallback: bool = Field(default=False)

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @field_validator("data_dir", "output_dir", mode="after")
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

        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            gemini_model_text=os.getenv("GEMINI_MODEL_TEXT", "gemini-2.5-flash").strip(),
            gemini_model_image=os.getenv("GEMINI_MODEL_IMAGE", "gemini-2.5-flash-image").strip(),
            gemini_rpm=get_int("GEMINI_RPM", 8),
            gemini_timeout_s=get_int("GEMINI_TIMEOUT_S", 120),
            whisper_model=os.getenv("WHISPER_MODEL", "large-v3").strip(),
            whisper_device=os.getenv("WHISPER_DEVICE", "cuda").strip(),  # type: ignore
            whisper_compute=os.getenv("WHISPER_COMPUTE", "float16").strip(),
            whisper_language=os.getenv("WHISPER_LANGUAGE", "auto").strip(),
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
            local_image_fallback=get_bool("LOCAL_IMAGE_FALLBACK", False),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton settings instance."""
    return Settings.from_env()
