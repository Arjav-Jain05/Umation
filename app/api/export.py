"""Clip packaging export API: streaming zip archive and folder open endpoint (07 s9)."""

from __future__ import annotations

import io
import logging
import os
import sys
import zipfile
from collections.abc import Generator
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core import paths
from app.core.models import get_clip

logger = logging.getLogger("app.api.export")
router = APIRouter(prefix="/api/clips", tags=["export"])


def _stream_folder_as_zip(folder_path: Path, chunk_size: int = 64 * 1024) -> Generator[bytes, None, None]:
    """Stream all files in folder_path as a zip archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(folder_path.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(folder_path)
                zf.write(file_path, arcname=str(arcname))

    buf.seek(0)
    while True:
        chunk = buf.read(chunk_size)
        if not chunk:
            break
        yield chunk


@router.get("/{job_id}/{clip_id}/zip")
def download_clip_zip(job_id: str, clip_id: str) -> StreamingResponse:
    """Stream a zip archive of the packaged clip folder."""
    clip = get_clip(job_id, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail=f"Clip {clip_id} not found in job {job_id}")

    folder_rel = clip.get("folder")
    if not folder_rel:
        raise HTTPException(status_code=400, detail="Clip has not been packaged yet")

    folder_path = (paths.output_dir() / folder_rel).resolve()
    # Guard against directory traversal
    try:
        folder_path.relative_to(paths.output_dir().resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid clip output folder") from None

    if not folder_path.is_dir():
        raise HTTPException(status_code=404, detail="Clip package folder does not exist on disk")

    filename = f"{clip_id}_package.zip"
    return StreamingResponse(
        _stream_folder_as_zip(folder_path),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{job_id}/{clip_id}/open-folder")
def open_clip_folder(job_id: str, clip_id: str) -> dict[str, bool]:
    """Open the clip package folder in Windows Explorer."""
    clip = get_clip(job_id, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail=f"Clip {clip_id} not found")

    folder_rel = clip.get("folder")
    if not folder_rel:
        raise HTTPException(status_code=400, detail="Clip is not packaged yet")

    folder_path = (paths.output_dir() / folder_rel).resolve()
    if not folder_path.is_dir():
        raise HTTPException(status_code=404, detail="Clip package folder does not exist")

    if sys.platform == "win32" and hasattr(os, "startfile"):
        try:
            os.startfile(str(folder_path))  # type: ignore[attr-defined]
            return {"ok": True}
        except Exception as e:
            logger.error("Failed opening folder %s: %s", folder_path, e)
            raise HTTPException(status_code=500, detail=f"Failed to open folder: {e}") from e

    return {"ok": False}
