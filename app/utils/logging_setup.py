"""Logging setup with rotating file handler and contextual LoggerAdapter."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from typing import Any

from config.settings import Settings, get_settings


class ContextAdapter(logging.LoggerAdapter):
    """Logger adapter that prepends [job:...] [clip:...] context if present."""

    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        prefix_parts = []
        job = self.extra.get("job") if self.extra else None
        clip = self.extra.get("clip") if self.extra else None
        if job:
            prefix_parts.append(f"[job:{job}]")
        if clip:
            prefix_parts.append(f"[clip:{clip}]")
        if prefix_parts:
            return f"{' '.join(prefix_parts)} {msg}", kwargs
        return msg, kwargs


def setup_logging(settings: Settings | None = None) -> None:
    """Configure root logger with console and rotating file handlers."""
    cfg = settings or get_settings()
    log_dir = cfg.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if root_logger.handlers:
        root_logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 5 x 5MB Rotating File Handler
    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Silence noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(
    name: str,
    job: str | None = None,
    clip: str | None = None,
) -> logging.Logger | logging.LoggerAdapter:
    """Return a logger or ContextAdapter with optional job and clip identifiers."""
    logger = logging.getLogger(name)
    if job or clip:
        return ContextAdapter(logger, {"job": job, "clip": clip})
    return logger
