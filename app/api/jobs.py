"""Jobs API endpoints: creation, status, Server-Sent Events, cancellation, resume, and cleanup."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core import paths
from app.core.db import get_conn
from app.core.errors import InvalidUrl
from app.core.events import broadcaster
from app.core.models import (
    create_job,
    get_job,
    list_candidates,
    list_clips,
    list_jobs,
    update_candidate_selection,
    update_job,
)
from app.core.schemas import ClipOut, JobCreate, JobOptions, JobOut, StageProgress
from app.core.worker import worker
from app.pipeline.s1_ingest.source_check import parse_youtube_url

logger = logging.getLogger("app.api.jobs")
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _extract_video_id(canonical_url: str) -> str:
    parsed = urlparse(canonical_url)
    qs = parse_qs(parsed.query)
    v_list = qs.get("v")
    if v_list and v_list[0]:
        return v_list[0]
    return "video"


@router.post("", status_code=status.HTTP_201_CREATED)
def post_job(payload: JobCreate) -> dict[str, str]:
    """Create a new clipping job and queue it for sequential execution."""
    if not payload.ack_fair_use:
        raise HTTPException(
            status_code=422,
            detail="You must acknowledge the fair use policy to proceed",
        )

    try:
        canonical_url = parse_youtube_url(payload.url)
    except InvalidUrl as e:
        raise HTTPException(status_code=422, detail=e.message) from e

    video_id = _extract_video_id(canonical_url)
    now_str = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    job_id = f"{now_str}-{video_id}"

    with get_conn() as conn:
        create_job(
            job_id=job_id,
            url=canonical_url,
            video_id=video_id,
            options=payload.options.model_dump(),
            ack_fair_use=True,
            status="queued",
            conn=conn,
        )

    # Wake background worker
    worker.wake()
    logger.info("Created and queued job %s for %s", job_id, canonical_url)
    return {"job_id": job_id}


@router.get("", response_model=list[JobOut])
def get_jobs_list(limit: int = Query(default=50, ge=1, le=100)) -> list[JobOut]:
    """List recent clipping jobs ordered newest first."""
    with get_conn() as conn:
        raw_jobs = list_jobs(limit=limit, conn=conn)
        out: list[JobOut] = []
        for j in raw_jobs:
            opts = json.loads(j["options_json"]) if isinstance(j["options_json"], str) else j["options_json"]
            clips = list_clips(j["id"], conn=conn)
            clips_ok = len([c for c in clips if c["status"] != "failed"])
            clips_failed = len([c for c in clips if c["status"] == "failed"])

            out.append(
                JobOut(
                    id=j["id"],
                    url=j["url"],
                    video_id=j.get("video_id"),
                    title=j.get("title"),
                    channel=j.get("channel"),
                    status=j["status"],
                    stage=j.get("stage"),
                    progress=float(j.get("progress") or 0.0),
                    message=j.get("message"),
                    options=JobOptions.model_validate(opts),
                    ack_fair_use=bool(j.get("ack_fair_use")),
                    ack_at=j.get("ack_at"),
                    created_at=j["created_at"],
                    updated_at=j["updated_at"],
                    error=j.get("error"),
                    clips_total=len(clips),
                    clips_ok=clips_ok,
                    clips_failed=clips_failed,
                )
            )
        return out


@router.get("/{job_id}", response_model=JobOut)
def get_job_detail(job_id: str) -> JobOut:
    """Fetch details and current progress for a single job."""
    with get_conn() as conn:
        j = get_job(job_id, conn=conn)
        if not j:
            raise HTTPException(status_code=404, detail="Job not found")

        opts = json.loads(j["options_json"]) if isinstance(j["options_json"], str) else j["options_json"]
        clips = list_clips(job_id, conn=conn)
        clips_ok = len([c for c in clips if c["status"] != "failed"])
        clips_failed = len([c for c in clips if c["status"] == "failed"])

        stages = [
            StageProgress(name="source_check", status="done" if j.get("progress", 0) > 5 else "pending"),
            StageProgress(name="audio_download", status="done" if j.get("progress", 0) > 20 else "pending"),
            StageProgress(name="transcribe", status="done" if j.get("progress", 0) > 65 else "pending"),
            StageProgress(name="nominate", status="done" if j.get("progress", 0) > 80 else "pending"),
            StageProgress(name="judge", status="done" if j.get("progress", 0) > 95 else "pending"),
            StageProgress(name="plan", status="done" if j.get("progress", 0) >= 100 else "pending"),
        ]

        return JobOut(
            id=j["id"],
            url=j["url"],
            video_id=j.get("video_id"),
            title=j.get("title"),
            channel=j.get("channel"),
            status=j["status"],
            stage=j.get("stage"),
            progress=float(j.get("progress") or 0.0),
            message=j.get("message"),
            options=JobOptions.model_validate(opts),
            ack_fair_use=bool(j.get("ack_fair_use")),
            ack_at=j.get("ack_at"),
            created_at=j["created_at"],
            updated_at=j["updated_at"],
            error=j.get("error"),
            stages=stages,
            clips_total=len(clips),
            clips_ok=clips_ok,
            clips_failed=clips_failed,
        )


@router.get("/{job_id}/events")
async def get_job_events(job_id: str, request: Request) -> StreamingResponse:
    """Server-Sent Events (SSE) stream reporting real-time job progress with 15s heartbeats."""
    with get_conn() as conn:
        j = get_job(job_id, conn=conn)
        if not j:
            raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        # Initial replay event
        with get_conn() as conn:
            initial_job = get_job(job_id, conn=conn)

        if initial_job:
            init_data = json.dumps({
                "job_id": job_id,
                "status": initial_job["status"],
                "stage": initial_job.get("stage"),
                "progress": float(initial_job.get("progress") or 0.0),
                "message": initial_job.get("message"),
            })
            yield f"event: progress\ndata: {init_data}\n\n"

        # Stream broadcaster events
        sub_gen = broadcaster.subscribe(job_id)
        while True:
            if await request.is_disconnected():
                break

            try:
                # Wait for next event with 15-second heartbeat timeout
                event_item = await asyncio.wait_for(sub_gen.__anext__(), timeout=15.0)
                e_name = event_item.get("event", "message")
                e_data = event_item.get("data", "")
                if not isinstance(e_data, str):
                    e_data = json.dumps(e_data)
                yield f"event: {e_name}\ndata: {e_data}\n\n"
            except TimeoutError:
                # Send comment heartbeat to keep connection alive
                yield ": heartbeat\n\n"
            except (asyncio.CancelledError, StopAsyncIteration):
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{job_id}/cancel")
def post_cancel_job(job_id: str) -> dict[str, bool]:
    """Request cancellation of an active or queued job."""
    with get_conn() as conn:
        j = get_job(job_id, conn=conn)
        if not j:
            raise HTTPException(status_code=404, detail="Job not found")

    canceled = worker.cancel_job(job_id)
    return {"ok": canceled or True}


class ResumeRequest(BaseModel):
    min_tier: str | None = Field(default=None, description="Optional lower min_tier to re-plan without Gemini calls")


@router.post("/{job_id}/resume")
def post_resume_job(job_id: str, body: ResumeRequest | None = None) -> dict[str, bool]:
    """Resume a paused or failed job, optionally re-planning with a lower tier bar."""
    with get_conn() as conn:
        j = get_job(job_id, conn=conn)
        if not j:
            raise HTTPException(status_code=404, detail="Job not found")

        opts = json.loads(j["options_json"]) if isinstance(j["options_json"], str) else j["options_json"]

        # If min_tier override is provided, update options
        if body and body.min_tier:
            opts["min_tier"] = body.min_tier
            # Clear plan.json artifact to trigger re-planning from judged.json
            plan_path = paths.job_dir(job_id) / "plan.json"
            if plan_path.exists():
                plan_path.unlink()

        update_job(job_id, conn=conn, options=opts, status="queued", error=None, message="Resumed")

    worker.wake()
    return {"ok": True}


@router.post("/{job_id}/cleanup")
def post_cleanup_job(job_id: str) -> dict[str, bool]:
    """Delete intermediate working files (audio, segments) for job, keeping finished outputs."""
    j_dir = paths.job_dir(job_id)
    if not j_dir.exists():
        return {"ok": True}

    audio_wav = j_dir / "audio.wav"
    if audio_wav.exists():
        audio_wav.unlink()

    asr_chunks = j_dir / "asr_chunks"
    if asr_chunks.exists():
        shutil.rmtree(asr_chunks, ignore_errors=True)

    segments_dir = j_dir / "segments"
    if segments_dir.exists():
        shutil.rmtree(segments_dir, ignore_errors=True)

    return {"ok": True}


@router.get("/{job_id}/clips", response_model=list[ClipOut])
def get_job_clips(job_id: str) -> list[ClipOut]:
    """List all planned/packaged clips for a given job."""
    with get_conn() as conn:
        clips = list_clips(job_id, conn=conn)
        out: list[ClipOut] = []
        for c in clips:
            video_url = f"/files/output/{c['folder']}/clip.mp4" if c.get("folder") else None
            thumb_url = f"/files/output/{c['folder']}/thumb_16x9.jpg" if c.get("folder") else None

            out.append(
                ClipOut(
                    job_id=c["job_id"],
                    id=c["id"],
                    idx=c["idx"],
                    parent_id=c.get("parent_id"),
                    part_index=c.get("part_index"),
                    part_total=c.get("part_total"),
                    start=float(c["start"]),
                    end=float(c["end"]),
                    tier=c["tier"],
                    final_score=float(c["final_score"]),
                    risk=c["risk"],
                    status=c["status"],
                    decision=c.get("decision", "pending"),
                    title_choice=int(c.get("title_choice") or 0),
                    title_override=c.get("title_override"),
                    description_override=c.get("description_override"),
                    folder=c.get("folder"),
                    error=c.get("error"),
                    video_url=video_url,
                    thumb_url=thumb_url,
                )
            )
        return out


class RenderRequest(BaseModel):
    threshold: float = Field(default=65.0, ge=0.0, le=100.0)
    mode: str = Field(default="absolute", description="absolute | relative")
    pins: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)


def compute_suggested_threshold(scores: list[float]) -> float:
    """Compute suggested quality threshold using Otsu's method or largest gap."""
    if not scores:
        return 65.0
    if len(scores) < 3:
        return round(float(scores[0]), 1)

    s_sorted = sorted(scores)
    # Check largest gap in the 35-80 range
    max_gap = -1.0
    gap_thresh = 65.0
    for i in range(len(s_sorted) - 1):
        gap = s_sorted[i + 1] - s_sorted[i]
        mid = (s_sorted[i + 1] + s_sorted[i]) / 2.0
        if 35.0 <= mid <= 80.0 and gap > max_gap:
            max_gap = gap
            gap_thresh = round(s_sorted[i + 1], 1)

    if max_gap >= 5.0:
        return gap_thresh

    # Otsu-like variance maximization
    total = len(s_sorted)
    current_max = 0.0
    best_t = 65.0
    for t in range(35, 85, 5):
        w0 = sum(1 for s in s_sorted if s < t) / total
        w1 = 1.0 - w0
        if w0 == 0 or w1 == 0:
            continue
        mean0 = sum(s for s in s_sorted if s < t) / (w0 * total)
        mean1 = sum(s for s in s_sorted if s >= t) / (w1 * total)
        variance_between = w0 * w1 * ((mean0 - mean1) ** 2)
        if variance_between > current_max:
            current_max = variance_between
            best_t = float(t)

    return best_t


def compute_score_histogram(scores: list[float], bin_size: int = 10) -> list[dict[str, Any]]:
    """Compute score histogram bins with tier categorization."""
    bins = []
    for low in range(0, 100, bin_size):
        high = low + bin_size
        count = sum(1 for s in scores if (low <= s < high or (high == 100 and s == 100)))
        tier = "S" if low >= 85 else ("A" if low >= 70 else ("B" if low >= 55 else "C"))
        bins.append({
            "range": f"{low}-{high}",
            "low": low,
            "high": high,
            "count": count,
            "tier": tier,
        })
    return bins


@router.get("/{job_id}/candidates")
def get_job_candidates(job_id: str) -> dict[str, Any]:
    """Retrieve all candidates stored in SQLite with full score breakdowns and histogram."""
    candidates = list_candidates(job_id)
    # If no candidates in DB, attempt fallback to job plan.json
    if not candidates:
        plan_path = paths.job_dir(job_id) / "plan.json"
        if plan_path.is_file():
            try:
                from app.core.schemas import Plan
                plan = Plan.model_validate_json(plan_path.read_text(encoding="utf-8"))
                for c in plan.clips:
                    candidates.append({
                        "job_id": job_id,
                        "id": c.id,
                        "start_s": c.start,
                        "end_s": c.end,
                        "hook_text": c.hook_text,
                        "topic": c.topic,
                        "llm_score": c.llm_score,
                        "audio_score": c.audio,
                        "heat_score": c.heat,
                        "final_score": c.final_score,
                        "tier": c.tier,
                        "scores": {"llm": c.llm_score, "audio": c.audio, "heat": c.heat},
                        "selected": 1,
                        "pinned": 0,
                        "excluded": 0,
                    })
            except Exception as e:
                logger.warning("Could not read plan.json for candidates: %s", e)

    scores = [float(c["final_score"]) for c in candidates]
    suggested = compute_suggested_threshold(scores)
    histogram = compute_score_histogram(scores)

    return {
        "job_id": job_id,
        "total_candidates": len(candidates),
        "suggested_threshold": suggested,
        "histogram": histogram,
        "candidates": candidates,
    }


@router.post("/{job_id}/render")
def post_render_job(job_id: str, req: RenderRequest) -> dict[str, Any]:
    """Filter candidates by threshold, pins, excludes, and execute selective rendering."""
    candidates = list_candidates(job_id)
    if not candidates:
        raise HTTPException(status_code=404, detail="No candidates found for this job")

    pin_set = set(req.pins)
    ex_set = set(req.excludes)

    selected_ids: list[str] = []
    if req.mode == "relative":
        # Keep top X% of candidates sorted by score
        candidates_sorted = sorted(candidates, key=lambda c: float(c["final_score"]), reverse=True)
        pct = max(0.05, min(1.0, req.threshold / 100.0))
        target_count = max(1, int(len(candidates_sorted) * pct))
        for idx, c in enumerate(candidates_sorted):
            cid = c["id"]
            if cid in ex_set:
                is_sel = False
            elif cid in pin_set or idx < target_count:
                is_sel = True
            else:
                is_sel = False
            if is_sel:
                selected_ids.append(cid)
            update_candidate_selection(job_id, cid, selected=is_sel, pinned=(cid in pin_set), excluded=(cid in ex_set))
    else:
        # Absolute mode: score >= threshold
        for c in candidates:
            cid = c["id"]
            score = float(c["final_score"])
            if cid in ex_set:
                is_sel = False
            elif cid in pin_set or score >= req.threshold:
                is_sel = True
            else:
                is_sel = False
            if is_sel:
                selected_ids.append(cid)
            update_candidate_selection(job_id, cid, selected=is_sel, pinned=(cid in pin_set), excluded=(cid in ex_set))

    # Update job options in DB with new quality threshold
    with get_conn() as conn:
        job = get_job(job_id, conn=conn)
        if job:
            opts = json.loads(job["options_json"]) if isinstance(job["options_json"], str) else job["options_json"]
            opts["quality_threshold"] = req.threshold
            opts["threshold_mode"] = req.mode
            update_job(job_id, conn=conn, options=opts)

    logger.info("Render selection for job %s: %d / %d candidates selected", job_id, len(selected_ids), len(candidates))
    return {
        "ok": True,
        "job_id": job_id,
        "selected_count": len(selected_ids),
        "selected_ids": selected_ids,
        "threshold": req.threshold,
        "mode": req.mode,
    }
