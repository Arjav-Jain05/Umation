"""Background worker thread processing queued pipeline jobs sequentially."""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.db import get_conn
from app.core.models import update_job
from app.core.power import keep_awake
from app.pipeline.context import JobContext
from app.pipeline.orchestrator import run_pipeline
from config.settings import get_settings

logger = logging.getLogger("app.core.worker")


class Worker:
    """Sequential worker running in a dedicated background thread."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._current_cancel_event: threading.Event | None = None
        self._current_job_id: str | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start worker thread, resetting any stranded 'running' jobs to 'queued'."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            self._reset_stranded_jobs()
            self._stop_event.clear()
            self._wake_event.clear()

            self._thread = threading.Thread(target=self._run_loop, name="ShortsWorkerThread", daemon=True)
            self._thread.start()
            logger.info("Worker thread started successfully")

    def stop(self) -> None:
        """Signal worker thread to terminate and cancel any currently active job."""
        with self._lock:
            self._stop_event.set()
            self._wake_event.set()
            if self._current_cancel_event:
                self._current_cancel_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            logger.info("Worker thread stopped")

    def wake(self) -> None:
        """Notify worker that a new job has been queued."""
        self._wake_event.set()

    def cancel_job(self, job_id: str) -> bool:
        """Cancel the specified job if it is currently running or queued."""
        with self._lock:
            if self._current_job_id == job_id and self._current_cancel_event:
                self._current_cancel_event.set()
                return True

        # If job is still queued in DB, mark it canceled
        with get_conn() as conn:
            cur = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            if row and row["status"] == "queued":
                update_job(job_id, conn=conn, status="canceled", message="Canceled while queued")
                return True

        return False

    def _reset_stranded_jobs(self) -> None:
        """Reset running jobs back to queued on app startup for crash resume."""
        try:
            with get_conn() as conn:
                cur = conn.execute("SELECT id FROM jobs WHERE status = 'running'")
                stranded = cur.fetchall()
                for r in stranded:
                    logger.info("Resetting stranded running job %s to queued (resume)", r["id"])
                    update_job(r["id"], conn=conn, status="queued", message="Resumed after restart")
        except Exception as e:
            logger.warning("Could not reset stranded jobs: %s", e)

    def _fetch_next_job(self) -> dict[str, Any] | None:
        """Query database for oldest queued job."""
        try:
            with get_conn() as conn:
                cur = conn.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1")
                row = cur.fetchone()
                return dict(row) if row is not None else None
        except Exception as e:
            logger.warning("Error fetching next queued job: %s", e)
            return None

    def _run_loop(self) -> None:
        """Continuous execution loop processing jobs one by one."""
        settings = get_settings()

        while not self._stop_event.is_set():
            job = self._fetch_next_job()
            if job is None:
                # Wait for wake event or timeout
                self._wake_event.wait(timeout=2.0)
                self._wake_event.clear()
                continue

            job_id = job["id"]
            cancel_event = threading.Event()

            with self._lock:
                self._current_job_id = job_id
                self._current_cancel_event = cancel_event

            logger.info("Worker picked up job %s (URL: %s)", job_id, job["url"])

            try:
                ctx = JobContext(
                    job=job,
                    settings=settings,
                    cancel_event=cancel_event,
                )
                with keep_awake():
                    run_pipeline(ctx)
            except Exception as e:
                logger.exception("Unexpected error in worker execution for job %s: %s", job_id, e)
            finally:
                with self._lock:
                    self._current_job_id = None
                    self._current_cancel_event = None


worker = Worker()
