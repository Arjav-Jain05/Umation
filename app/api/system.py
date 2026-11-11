"""System API endpoints: health, environment check, and open-folder."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.settings import get_settings
from scripts.check_env import run_checks

router = APIRouter(prefix="/api", tags=["system"])


class HealthResponse(BaseModel):
    ok: bool = True
    version: str = "1.0.0"


class OpenFolderRequest(BaseModel):
    path: str


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Return application health and version."""
    return HealthResponse(ok=True, version="1.0.0")


@router.get("/system/check")
def get_system_check() -> list[dict]:
    """Run environment and dependency checks, returning results as JSON."""
    settings = get_settings()
    results = run_checks(root_dir=settings.project_root, in_process=True)
    return [r.to_dict() for r in results]


@router.post("/system/open-folder")
def open_folder(req: OpenFolderRequest) -> dict[str, bool]:
    """Open a folder in Windows File Explorer, restricted to output_dir."""
    settings = get_settings()
    output_dir = settings.output_dir.resolve()
    target_path = Path(req.path).resolve()

    # Guard: must be inside or equal to output_dir
    try:
        target_path.relative_to(output_dir)
    except ValueError as err:
        raise HTTPException(
            status_code=400,
            detail="Forbidden: path must resolve inside output_dir",
        ) from err

    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Path does not exist")

    if sys.platform == "win32" and hasattr(os, "startfile") and not os.environ.get("PYTEST_CURRENT_TEST"):
        os.startfile(str(target_path))  # type: ignore[attr-defined]
    return {"ok": True}


@router.post("/system/calibrate")
def calibrate_weights() -> dict[str, Any]:
    """Tune scoring fusion weights from user feedback labels using logistic regression / ranker."""
    from scripts.train_ranker import train_ranker

    settings = get_settings()
    feedback_file = settings.project_root / "feedback" / "ratings.jsonl"

    res = train_ranker(ratings_path=feedback_file)

    weights_before = {
        "hook": 0.25,
        "payoff": 0.20,
        "audio": 0.15,
        "heatmap": 0.20,
        "speech": 0.20,
    }
    imp = res.get("feature_importance", {})
    weights_after = {
        "hook": round(float(imp.get("llm_consensus", 0.28)), 3),
        "payoff": round(float(imp.get("critic", 0.24)), 3),
        "audio": round(float(imp.get("audio_events", 0.16)), 3),
        "heatmap": round(float(imp.get("audience", 0.18)), 3),
        "speech": round(float(imp.get("emotion", 0.14)), 3),
    }
    total = sum(weights_after.values())
    if total > 0:
        weights_after = {k: round(v / total, 3) for k, v in weights_after.items()}

    return {
        "ok": True,
        "samples": res.get("dataset_size", 10),
        "weights_before": weights_before,
        "weights_after": weights_after,
    }

