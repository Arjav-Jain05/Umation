"""Tests for export zip streaming and results logging APIs (07 s9, 09 s7)."""

from __future__ import annotations

import io
import uuid
import zipfile

from fastapi.testclient import TestClient

from app.core import paths
from app.core.db import get_conn
from app.core.models import create_job, upsert_clip
from app.main import app


def test_api_export_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "output_dir", lambda: tmp_path / "output")

    client = TestClient(app)
    job_id = f"job_exp_{uuid.uuid4().hex[:8]}"
    clip_id = "c01"

    # Set up DB job and clip
    with get_conn() as conn:
        create_job(job_id=job_id, url="https://www.youtube.com/watch?v=exp12345678", options={}, ack_fair_use=True, conn=conn)

        # Create physical package folder
        folder_rel = "exp-slug-exp12345678/c01_A"
        pkg_dir = tmp_path / "output" / folder_rel
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "clip.mp4").write_bytes(b"dummy video")
        (pkg_dir / "metadata.txt").write_text("dummy metadata", encoding="utf-8")

        upsert_clip({
            "job_id": job_id,
            "id": clip_id,
            "idx": 0,
            "start": 0.0,
            "end": 30.0,
            "tier": "A",
            "final_score": 85.0,
            "risk": "low",
            "status": "packaged",
            "folder": folder_rel,
        }, conn=conn)

    # Call GET /api/clips/{job_id}/{clip_id}/zip
    res = client.get(f"/api/clips/{job_id}/{clip_id}/zip")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"

    # Verify zip content
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    namelist = zf.namelist()
    assert "clip.mp4" in namelist
    assert "metadata.txt" in namelist
    assert zf.read("metadata.txt").decode("utf-8") == "dummy metadata"


def test_api_results_logging_and_summary():
    client = TestClient(app)
    job_id = f"job_res_{uuid.uuid4().hex[:8]}"
    clip_id = "c01"

    with get_conn() as conn:
        create_job(job_id=job_id, url="https://www.youtube.com/watch?v=res12345678", options={}, ack_fair_use=True, conn=conn)
        upsert_clip({
            "job_id": job_id,
            "id": clip_id,
            "idx": 0,
            "start": 0.0,
            "end": 30.0,
            "tier": "A",
            "final_score": 89.5,
            "risk": "low",
            "status": "packaged",
        }, conn=conn)

    # Post result
    post_res = client.post(
        f"/api/clips/{job_id}/{clip_id}/results",
        json={
            "platform": "youtube_shorts",
            "url": "https://youtube.com/shorts/xyz",
            "views": 15420,
            "likes": 890,
        },
    )
    assert post_res.status_code == 200
    assert post_res.json()["ok"] is True

    # Get summary
    sum_res = client.get("/api/results/summary")
    assert sum_res.status_code == 200
    data = sum_res.json()
    assert data["total_logged"] >= 1
    assert "youtube_shorts" in data["by_platform"]
    assert data["by_platform"]["youtube_shorts"]["total_views"] >= 15420
