"""Pipeline orchestrator: stage execution, resumability, and error handling."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.core.db import get_conn
from app.core.errors import AppError, Canceled
from app.core.events import broadcaster
from app.core.models import get_job, update_job
from app.core.schemas import Plan
from app.pipeline.context import JobContext
from app.pipeline.s1_ingest import download as s1_download
from app.pipeline.s1_ingest import source_check as s1_source_check
from app.pipeline.s1_ingest import transcribe as s1_transcribe
from app.pipeline.s2_select import judge as s2_judge
from app.pipeline.s2_select import nominate as s2_nominate
from app.pipeline.s2_select import planner as s2_planner
from app.pipeline.s3_build import run as s3_build_run
from app.pipeline.s3_build import segments as s3_segments
from app.pipeline.s4_director import run as s4_director_run
from app.pipeline.s5_package import run as s5_package_run

logger = logging.getLogger("app.pipeline.orchestrator")


@dataclass
class StageDef:
    name: str
    weight: float
    fn: Callable[[JobContext], None]
    artifact: str


# Pipeline Stage definitions
STAGES: list[StageDef] = [
    StageDef("source_check", 0.02, s1_source_check.run, "source_info.json"),
    StageDef("audio_download", 0.05, s1_download.run, "audio.wav"),
    StageDef("transcribe", 0.18, s1_transcribe.run, "transcript.json"),
    StageDef("nominate", 0.07, s2_nominate.run, "candidates.json"),
    StageDef("judge", 0.07, s2_judge.run, "judged.json"),
    StageDef("plan", 0.04, s2_planner.run, "plan.json"),
    StageDef("segments", 0.10, s3_segments.run, "segments.json"),
    StageDef("build", 0.23, s3_build_run, "build_done.json"),
    StageDef("direct", 0.16, s4_director_run, "direct_done.json"),
    StageDef("package", 0.08, s5_package_run, "package_done.json"),
]


def run_pipeline(ctx: JobContext) -> None:
    """Execute the sequential pipeline stages with resume support and cancellation checks."""
    logger.info("[%s] Starting pipeline for URL: %s", ctx.job_id, ctx.job["url"])

    with get_conn(ctx.db_path) as conn:
        update_job(ctx.job_id, conn=conn, status="running", error=None)

    broadcaster.publish(
        ctx.job_id,
        "progress",
        {"job_id": ctx.job_id, "stage": "start", "progress": 0.0, "message": "Pipeline started"},
    )

    try:
        accumulated_progress = 0.0
        for stage in STAGES:
            ctx.check_cancel()

            logger.info("[%s] Beginning stage: %s (weight: %.0f%%)", ctx.job_id, stage.name, stage.weight * 100)

            # Check if stage artifact exists and validates (resumability)
            if ctx.artifact_ok(stage.artifact):
                logger.info("[%s] Artifact '%s' already exists and validates; resuming/skipping stage", ctx.job_id, stage.artifact)
                accumulated_progress += stage.weight
                ctx.progress(stage.name, accumulated_progress, f"Stage {stage.name} resumed from existing artifact")
            else:
                stage.fn(ctx)
                accumulated_progress += stage.weight
                ctx.progress(stage.name, accumulated_progress, f"Stage {stage.name} completed")

            broadcaster.publish(ctx.job_id, "stage_done", {"stage": stage.name})

        # Evaluate final planned clips
        plan = ctx.read_artifact("plan.json", Plan)
        total_clips = len(plan.clips)
        logger.info("[%s] Ingest and selection complete: %d clips planned", ctx.job_id, total_clips)

        final_msg = f"{total_clips} viral clips selected for review" if total_clips > 0 else "No moments passed the quality bar"

        with get_conn(ctx.db_path) as conn:
            update_job(
                ctx.job_id,
                conn=conn,
                status="review",
                stage="package",
                progress=100.0,
                message=final_msg,
            )

        broadcaster.publish(
            ctx.job_id,
            "done",
            {
                "clips_total": total_clips,
                "clips_ok": total_clips,
                "clips_failed": 0,
                "message": final_msg,
            },
        )

    except Canceled as e:
        logger.warning("[%s] Pipeline canceled by user: %s", ctx.job_id, e)
        with get_conn(ctx.db_path) as conn:
            update_job(
                ctx.job_id,
                conn=conn,
                status="canceled",
                error="canceled: Job was canceled by user",
                message="Job was canceled",
            )
        broadcaster.publish(ctx.job_id, "error", {"code": "canceled", "message": str(e)})

    except AppError as e:
        logger.error("[%s] Pipeline AppError in stage: %s", ctx.job_id, e)
        err_str = f"{e.code}: {e.message}"
        with get_conn(ctx.db_path) as conn:
            update_job(ctx.job_id, conn=conn, status="failed", error=err_str, message=e.message)
        broadcaster.publish(ctx.job_id, "error", {"code": e.code, "message": e.message, "hint": e.hint})

    except Exception as e:
        logger.exception("[%s] Unexpected pipeline failure: %s", ctx.job_id, e)
        err_str = f"unexpected_error: {e}"
        with get_conn(ctx.db_path) as conn:
            update_job(ctx.job_id, conn=conn, status="failed", error=err_str, message=str(e))
        broadcaster.publish(ctx.job_id, "error", {"code": "unexpected_error", "message": str(e)})


def resume_job(job_id: str) -> None:
    """Set job back to queued so worker resumes pipeline from existing artifacts."""
    with get_conn() as conn:
        job = get_job(job_id, conn=conn)
        if not job:
            return
        update_job(job_id, conn=conn, status="queued", error=None, message="Resuming job...")
