"""JobContext object passed to all pipeline stages with progress, artifacts, and cancellation."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core import paths
from app.core.db import get_conn
from app.core.errors import Canceled
from app.core.events import broadcaster
from app.core.gemini_client import GeminiClient
from app.core.models import update_job
from app.core.schemas import JobOptions, read_artifact, write_artifact
from config.settings import Settings, get_settings

logger = logging.getLogger("app.pipeline.context")
T = TypeVar("T", bound=BaseModel)


class JobContext:
    """Execution context encapsulating job state, artifacts, cancellation, and progress."""

    def __init__(
        self,
        job: dict[str, Any],
        settings: Settings | None = None,
        gemini: Any | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.job = job
        self.settings = settings or get_settings()
        self.job_id = str(job["id"])
        self.video_id = str(job.get("video_id") or "")
        self.gemini = gemini or GeminiClient(self.settings)
        self.cancel_event = cancel_event or threading.Event()

        # Parse options
        opts_raw = job.get("options_json") or "{}"
        if isinstance(opts_raw, str):
            import json

            opts_dict = json.loads(opts_raw)
        else:
            opts_dict = opts_raw
        self.options = JobOptions.model_validate(opts_dict)

        self.work_dir = paths.job_dir(self.job_id)
        self.db_path = self.settings.data_dir / "app.db"

    def check_cancel(self) -> None:
        """Raise Canceled if cancellation flag has been set."""
        if self.cancel_event.is_set():
            logger.info("Cancellation detected for job %s", self.job_id)
            raise Canceled(f"Job {self.job_id} was canceled by user")

    def progress(
        self,
        stage: str,
        fraction: float,
        message: str,
        clip_id: str | None = None,
    ) -> None:
        """Update job stage progress in database and publish SSE event."""
        self.check_cancel()
        pct = max(0.0, min(100.0, round(fraction * 100.0, 1)))
        logger.info("[%s] [%s] %.1f%% - %s", self.job_id, stage, pct, message)

        # Update DB
        with get_conn(self.db_path) as conn:
            update_job(
                self.job_id,
                conn=conn,
                status="running",
                stage=stage,
                progress=pct,
                message=message,
            )

        # Publish SSE event
        broadcaster.publish(
            self.job_id,
            "progress",
            {
                "job_id": self.job_id,
                "stage": stage,
                "progress": pct,
                "message": message,
                "clip_id": clip_id,
            },
        )

    def warning(self, message: str) -> None:
        """Log a warning and publish an SSE warning event."""
        logger.warning("[%s] %s", self.job_id, message)
        broadcaster.publish(self.job_id, "warning", {"message": message})

    def artifact_path(self, name: str) -> Path:
        """Resolve full filesystem path for a named artifact under job work directory."""
        return self.work_dir / name

    def artifact_ok(self, name: str, model_cls: type[BaseModel] | None = None) -> bool:
        """Check if an artifact exists and is non-empty / valid."""
        p = self.artifact_path(name)
        if not p.is_file() or p.stat().st_size == 0:
            return False
        if model_cls is not None:
            try:
                read_artifact(p, model_cls)
                return True
            except Exception:
                return False
        return True

    def read_artifact[M: BaseModel](self, name: str, model_cls: type[M]) -> M:
        """Read and validate a JSON artifact from the job work folder."""
        p = self.artifact_path(name)
        return read_artifact(p, model_cls)

    def write_artifact(self, name: str, obj: BaseModel | dict[str, Any] | list[Any]) -> Path:
        """Write an artifact atomically to the job work folder."""
        p = self.artifact_path(name)
        return write_artifact(p, obj)
