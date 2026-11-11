"""Clips API endpoints: detail, approval toggle, timeline trim, edit list patch, re-render, and media streaming."""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core import paths
from app.core.db import get_conn
from app.core.gemini_client import GeminiClient
from app.core.models import get_clip, get_job, update_clip
from app.core.schemas import Clip, ClipOut, LayoutArtifact, WordsArtifact
from app.pipeline.context import JobContext
from app.pipeline.s3_build import captions, final_render
from app.pipeline.s4_director import apply_effects
from app.pipeline.s4_director.edit_schema import EditEvent, EditList, validate_and_fix
from app.pipeline.s5_package import package_clip
from config.settings import get_settings

logger = logging.getLogger("app.api.clips")
router = APIRouter(prefix="/api/clips", tags=["clips"])


class ClipPatch(BaseModel):
    decision: str | None = Field(default=None, description="approved | rejected | pending")
    title_choice: int | None = None
    title_override: str | None = None
    description_override: str | None = None
    start: float | None = None
    end: float | None = None


class EditListPatch(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)
    caption_emphasis: list[int] = Field(default_factory=list)


class RateRequest(BaseModel):
    rating: int = Field(description="1 for Good, 0 for Bad, -1 for Broken")


@router.post("/{job_id}/{clip_id}/rate")
def rate_clip(job_id: str, clip_id: str, body: RateRequest) -> dict[str, Any]:
    """Store human feedback rating (Good/Bad/Broken) for calibration."""
    with get_conn() as conn:
        c = get_clip(job_id, clip_id, conn=conn)
        if not c:
            raise HTTPException(status_code=404, detail="Clip not found")

    settings = get_settings()
    feedback_dir = settings.project_root / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    ratings_file = feedback_dir / "ratings.jsonl"

    record = {
        "job_id": job_id,
        "clip_id": clip_id,
        "rating": body.rating,
        "scores": {
            "hook": c.get("hook_score") or c.get("llm_score") or 50.0,
            "payoff": c.get("payoff_score") or c.get("llm_score") or 50.0,
            "audio": c.get("audio_energy") or 50.0,
            "heatmap": c.get("heatmap_score") or 50.0,
            "speech": (c.get("speech_ratio") or 0.8) * 100.0,
            "audience": 50.0,
            "audio_events": c.get("audio_energy") or 50.0,
            "emotion": 50.0,
            "text_hype": 50.0,
            "llm_consensus": c.get("llm_score") or 50.0,
            "critic": c.get("final_score") or 50.0,
            "rerank": c.get("final_score") or 50.0,
            "visual": 75.0,
            "agreement": 80.0,
        },
    }
    with open(ratings_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return {"ok": True, "job_id": job_id, "clip_id": clip_id, "rating": body.rating}


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
    """Update user decision, metadata overrides, or trim start/end boundaries for a clip."""
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

        cur_start = float(c["start"])
        cur_end = float(c["end"])

        if patch.start is not None:
            cur_start = float(patch.start)
            updates["start"] = cur_start
        if patch.end is not None:
            cur_end = float(patch.end)
            updates["end"] = cur_end

        if (patch.start is not None or patch.end is not None) and cur_end <= cur_start:
            raise HTTPException(status_code=422, detail="End time must be strictly greater than start time")

        if updates:
            update_clip(job_id, clip_id, conn=conn, **updates)

    return get_clip_detail(job_id, clip_id)


@router.get("/{job_id}/{clip_id}/words")
def get_clip_words(job_id: str, clip_id: str) -> dict[str, Any]:
    """Return words transcript for the clip."""
    words_file = paths.clip_dir(job_id, clip_id) / "words.json"
    if not words_file.is_file():
        raise HTTPException(status_code=404, detail="Words artifact not found for clip")
    try:
        return json.loads(words_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read words artifact: {e}") from e


@router.get("/{job_id}/{clip_id}/edit-list")
def get_clip_edit_list(job_id: str, clip_id: str) -> dict[str, Any]:
    """Return the current edit list for a clip."""
    edit_file = paths.clip_dir(job_id, clip_id) / "edit_list.json"
    if not edit_file.is_file():
        return {"schema_version": 1, "clip_id": clip_id, "events": [], "caption_emphasis": []}
    try:
        return json.loads(edit_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read edit list: {e}") from e


@router.patch("/{job_id}/{clip_id}/edit-list")
def patch_clip_edit_list(job_id: str, clip_id: str, body: EditListPatch) -> dict[str, Any]:
    """Update and re-validate effect events and caption emphasis for a clip."""
    clip_dir = paths.clip_dir(job_id, clip_id)
    if not clip_dir.is_dir():
        raise HTTPException(status_code=404, detail="Clip directory not found")

    dur = 60.0
    with get_conn() as conn:
        c = get_clip(job_id, clip_id, conn=conn)
        if c:
            dur = max(1.0, float(c["end"]) - float(c["start"]))

    normalized_events: list[EditEvent] = []
    for idx, e in enumerate(body.events):
        t_val = float(e.get("t", e.get("t0", 0.0)))
        dur_val = float(e.get("dur", e.get("t1", t_val + 1.0) - e.get("t0", t_val)))
        ev_id = str(e.get("id") or f"{e.get('type', 'ev')}_{idx}")
        normalized_events.append(
            EditEvent(
                id=ev_id,
                type=str(e.get("type", "zoom_punch")),
                t=t_val,
                dur=max(0.1, dur_val),
                params=dict(e.get("params") or {}),
            )
        )

    edit_list = EditList(
        schema_version=1,
        clip_id=clip_id,
        duration=dur,
        events=normalized_events,
        caption_emphasis=body.caption_emphasis,
    )

    words_file = clip_dir / "words.json"
    words_art = None
    if words_file.is_file():
        with contextlib.suppress(Exception):
            words_art = WordsArtifact.model_validate_json(words_file.read_text(encoding="utf-8"))

    layout_file = clip_dir / "layout.json"
    layout_str = "gameplay"
    if layout_file.is_file():
        with contextlib.suppress(Exception):
            lay_art = LayoutArtifact.model_validate_json(layout_file.read_text(encoding="utf-8"))
            layout_str = lay_art.layout

    words_list = words_art.words if words_art else []
    validated_list, _fixes = validate_and_fix(
        edit_list=edit_list,
        words=words_list,
        layout=layout_str,
    )

    out_file = clip_dir / "edit_list.json"
    out_file.write_text(validated_list.model_dump_json(indent=2), encoding="utf-8")

    return {"ok": True, "event_count": len(validated_list.events), "fixes": _fixes}


def _execute_rerender(job_id: str, clip_id: str) -> None:
    """Execute direct and package stages for single clip re-render."""
    settings = get_settings()
    job_row = get_job(job_id)
    if not job_row:
        logger.error("Job %s not found for re-render", job_id)
        return

    clip_row = get_clip(job_id, clip_id)
    if not clip_row:
        logger.error("Clip %s not found in job %s", clip_id, job_id)
        return

    clip_obj = Clip(
        id=clip_id,
        idx=clip_row["idx"],
        start=float(clip_row["start"]),
        end=float(clip_row["end"]),
        duration=round(float(clip_row["end"]) - float(clip_row["start"]), 3),
        tier=clip_row["tier"],
        final_score=float(clip_row["final_score"]),
        llm_score=float(clip_row.get("llm_score") or clip_row["final_score"]),
        risk=clip_row.get("risk", "low"),
        topic=clip_row.get("topic") or "Clip",
        hook_text=clip_row.get("hook_text") or "",
    )

    gemini = GeminiClient(settings)
    ctx = JobContext(job=job_row, settings=settings, gemini=gemini)
    clip_dir = paths.clip_dir(job_id, clip_id)

    try:
        logger.info("[%s] Starting re-render for clip %s", job_id, clip_id)
        update_clip(job_id, clip_id, status="rendering")

        # 1. Direct & Effects
        apply_effects.render_effects(ctx, clip_obj)

        # 2. Update captions ASS
        edit_file = clip_dir / "edit_list.json"
        words_file = clip_dir / "words.json"
        if edit_file.is_file() and words_file.is_file():
            ed_list = EditList.model_validate_json(edit_file.read_text(encoding="utf-8"))
            w_art = WordsArtifact.model_validate_json(words_file.read_text(encoding="utf-8"))
            chunks = captions.chunk_words(w_art.words)
            captions.write_ass(
                chunks,
                layout="gameplay",
                out_path=clip_dir / "captions.ass",
                mask_profanity_flag=True,
                emphasis_indices=ed_list.caption_emphasis,
            )

        # 3. Final render pass
        final_render.render_final(clip_dir=clip_dir, fps=30.0, has_captions=True)

        # 4. Package clip
        package_clip(ctx, clip_obj)

        update_clip(job_id, clip_id, status="packaged")
        logger.info("[%s] Re-render complete for clip %s", job_id, clip_id)
    except Exception as e:
        logger.error("[%s] Re-render failed for clip %s: %s", job_id, clip_id, e, exc_info=True)
        update_clip(job_id, clip_id, status="failed", error=str(e))


@router.post("/{job_id}/{clip_id}/rerender")
def post_rerender_clip(
    job_id: str,
    clip_id: str,
    background_tasks: BackgroundTasks,
) -> dict[str, bool]:
    """Request a single clip re-render (stages direct + package)."""
    with get_conn() as conn:
        c = get_clip(job_id, clip_id, conn=conn)
        if not c:
            raise HTTPException(status_code=404, detail="Clip not found")
        update_clip(job_id, clip_id, conn=conn, status="queued")

    background_tasks.add_task(_execute_rerender, job_id, clip_id)
    return {"ok": True}


@router.get("/{job_id}/{clip_id}/video")
def get_clip_video(job_id: str, clip_id: str) -> FileResponse:
    """Stream rendered vertical MP4 video for preview."""
    clip_file = paths.clip_dir(job_id, clip_id) / "clip.mp4"
    if not clip_file.is_file():
        clip_file = paths.clip_dir(job_id, clip_id) / "final.mp4"
    if not clip_file.is_file():
        raise HTTPException(status_code=404, detail="Clip video file not found")
    return FileResponse(clip_file, media_type="video/mp4")


@router.get("/{job_id}/{clip_id}/thumbnail")
def get_clip_thumbnail(job_id: str, clip_id: str) -> FileResponse:
    """Serve vertical thumbnail preview."""
    thumb_file = paths.clip_dir(job_id, clip_id) / "thumb_1080x1920.jpg"
    if not thumb_file.is_file():
        thumb_file = paths.clip_dir(job_id, clip_id) / "cover_9x16.jpg"
    if not thumb_file.is_file():
        raise HTTPException(status_code=404, detail="Clip thumbnail not found")
    return FileResponse(thumb_file, media_type="image/jpeg")
