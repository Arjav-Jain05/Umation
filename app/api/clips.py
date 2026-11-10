"""Clips API endpoints: detail, approval toggle, re-render, and media streaming."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core import paths
from app.core.db import get_conn
from app.core.models import get_clip, update_clip
from app.core.schemas import ClipOut

logger = logging.getLogger("app.api.clips")
router = APIRouter(prefix="/api/clips", tags=["clips"])


class ClipPatch(BaseModel):
    decision: str | None = Field(default=None, description="approved | rejected | pending")
    title_choice: int | None = None
    title_override: str | None = None
    description_override: str | None = None


@router.get("/{job_id}/{clip_id}", response_model=ClipOut)
def get_clip_detail(job_id: str, clip_id: str) -> ClipOut:
    """Retrieve full details for a single short-form clip."""
    with get_conn() as conn:
        c = get_clip(job_id, clip_id, conn=conn)
        if not c:
            raise HTTPException(status_code=404, detail="Clip not found")

    clip_file = paths.clip_dir(job_id, clip_id) / "clip.mp4"
    thumb_file = paths.clip_dir(job_id, clip_id) / "thumb_1080x1920.jpg"

    video_url = f"/api/clips/{job_id}/{clip_id}/video" if clip_file.is_file() else None
    thumb_url = f"/api/clips/{job_id}/{clip_id}/thumbnail" if thumb_file.is_file() else None

    return ClipOut(
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
        title_choice=c.get("title_choice", 0),
        title_override=c.get("title_override"),
        description_override=c.get("description_override"),
        folder=c.get("folder"),
        error=c.get("error"),
        video_url=video_url,
        thumb_url=thumb_url,
    )


@router.patch("/{job_id}/{clip_id}", response_model=ClipOut)
def patch_clip_detail(job_id: str, clip_id: str, patch: ClipPatch) -> ClipOut:
    """Update user decision (approve/reject) or metadata overrides for a clip."""
    with get_conn() as conn:
        c = get_clip(job_id, clip_id, conn=conn)
        if not c:
            raise HTTPException(status_code=404, detail="Clip not found")

        updates: dict[str, Any] = {}
        if patch.decision is not None:
            if patch.decision not in ("approved", "rejected", "pending"):
                raise HTTPException(status_code=422, detail="Invalid decision. Must be approved, rejected, or pending")
            updates["decision"] = patch.decision

        if patch.title_choice is not None:
            updates["title_choice"] = patch.title_choice
        if patch.title_override is not None:
            updates["title_override"] = patch.title_override
        if patch.description_override is not None:
            updates["description_override"] = patch.description_override

        if updates:
            update_clip(job_id, clip_id, conn=conn, **updates)

    return get_clip_detail(job_id, clip_id)


@router.get("/{job_id}/{clip_id}/video")
def get_clip_video(job_id: str, clip_id: str) -> FileResponse:
    """Stream rendered vertical MP4 video for preview."""
    clip_file = paths.clip_dir(job_id, clip_id) / "clip.mp4"
    if not clip_file.is_file():
        raise HTTPException(status_code=404, detail="Clip video file not found")
    return FileResponse(clip_file, media_type="video/mp4")


@router.get("/{job_id}/{clip_id}/thumbnail")
def get_clip_thumbnail(job_id: str, clip_id: str) -> FileResponse:
    """Serve vertical thumbnail preview."""
    thumb_file = paths.clip_dir(job_id, clip_id) / "thumb_1080x1920.jpg"
    if not thumb_file.is_file():
        raise HTTPException(status_code=404, detail="Clip thumbnail not found")
    return FileResponse(thumb_file, media_type="image/jpeg")


@router.post("/{job_id}/{clip_id}/rerender")
def post_rerender_clip(job_id: str, clip_id: str) -> dict[str, bool]:
    """Request a single clip re-render."""
    with get_conn() as conn:
        c = get_clip(job_id, clip_id, conn=conn)
        if not c:
            raise HTTPException(status_code=404, detail="Clip not found")
        update_clip(job_id, clip_id, conn=conn, status="queued")

    # Invalidate existing clip.mp4
    clip_file = paths.clip_dir(job_id, clip_id) / "clip.mp4"
    if clip_file.is_file():
        clip_file.unlink()

    return {"ok": True}
