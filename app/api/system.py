"""System API endpoints: health, environment check, and open-folder."""

from __future__ import annotations

import os
import sys
from pathlib import Path

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
