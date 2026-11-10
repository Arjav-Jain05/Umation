"""Results logging and performance analytics API (09 s7)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.models import add_result, get_clip, list_results

logger = logging.getLogger("app.api.results")
router = APIRouter(prefix="/api", tags=["results"])


class ResultCreate(BaseModel):
    platform: str
    url: str | None = None
    views: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)


class ResultSummaryOut(BaseModel):
    total_logged: int
    top_clips: list[dict[str, Any]]
    by_platform: dict[str, dict[str, int]]


@router.post("/clips/{job_id}/{clip_id}/results")
def log_clip_result(job_id: str, clip_id: str, body: ResultCreate) -> dict[str, Any]:
    """Store performance metrics (views, likes, link) for a posted clip."""
    clip = get_clip(job_id, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail=f"Clip {clip_id} not found")

    res_id = add_result(
        job_id=job_id,
        clip_id=clip_id,
        platform=body.platform,
        url=body.url,
        views=body.views,
        likes=body.likes,
    )
    return {"ok": True, "result_id": res_id}


@router.get("/results/summary")
def get_results_summary() -> dict[str, Any]:
    """Return aggregated performance summary and top clips by views."""
    all_results = list_results()

    # Aggregate by platform
    by_platform: dict[str, dict[str, int]] = {}
    for r in all_results:
        plat = r.get("platform", "other")
        if plat not in by_platform:
            by_platform[plat] = {"count": 0, "total_views": 0, "total_likes": 0}
        by_platform[plat]["count"] += 1
        by_platform[plat]["total_views"] += int(r.get("views") or 0)
        by_platform[plat]["total_likes"] += int(r.get("likes") or 0)

    # Sort by views descending
    sorted_results = sorted(all_results, key=lambda x: int(x.get("views") or 0), reverse=True)
    top_clips = sorted_results[:10]

    return {
        "total_logged": len(all_results),
        "top_clips": top_clips,
        "by_platform": by_platform,
    }
