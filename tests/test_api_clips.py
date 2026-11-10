"""Unit tests for /api/clips endpoints (detail, patch approval, rerender)."""

from fastapi.testclient import TestClient

from app.core.db import get_conn
from app.core.models import create_job, upsert_clip


def test_clip_detail_404_when_missing(client: TestClient):
    """Verify GET /api/clips/{job_id}/{clip_id} returns 404 for unknown clip."""
    res = client.get("/api/clips/unknown_job/c99")
    assert res.status_code == 404


def test_clip_patch_and_approval(client: TestClient):
    """Verify PATCH /api/clips/{job_id}/{clip_id} updates decision and title overrides."""
    job_id = "test_job_clips"
    with get_conn() as conn:
        create_job(job_id=job_id, url="https://youtube.com/watch?v=123", video_id="123", options={}, ack_fair_use=True, conn=conn)
        upsert_clip(
            {
                "job_id": job_id,
                "id": "c01",
                "idx": 1,
                "start": 10.0,
                "end": 30.0,
                "tier": "A",
                "final_score": 85.0,
                "risk": "low",
                "status": "built",
            },
            conn=conn,
        )

    # 1. Invalid decision -> 422
    bad_res = client.patch(f"/api/clips/{job_id}/c01", json={"decision": "invalid_choice"})
    assert bad_res.status_code == 422

    # 2. Valid approve patch
    patch_res = client.patch(
        f"/api/clips/{job_id}/c01",
        json={"decision": "approved", "title_override": "Custom Title Override"},
    )
    assert patch_res.status_code == 200
    data = patch_res.json()
    assert data["decision"] == "approved"
    assert data["title_override"] == "Custom Title Override"

    # 3. Verify GET returns updated data
    get_res = client.get(f"/api/clips/{job_id}/c01")
    assert get_res.status_code == 200
    assert get_res.json()["decision"] == "approved"


def test_clip_rerender(client: TestClient):
    """Verify POST /api/clips/{job_id}/{clip_id}/rerender sets status to queued."""
    job_id = "test_job_rerender"
    with get_conn() as conn:
        create_job(job_id=job_id, url="https://youtube.com/watch?v=123", video_id="123", options={}, ack_fair_use=True, conn=conn)
        upsert_clip(
            {
                "job_id": job_id,
                "id": "c01",
                "idx": 1,
                "start": 10.0,
                "end": 30.0,
                "tier": "A",
                "final_score": 85.0,
                "risk": "low",
                "status": "built",
            },
            conn=conn,
        )

    res = client.post(f"/api/clips/{job_id}/c01/rerender")
    assert res.status_code == 200
    assert res.json()["ok"] is True

    # Status should now be queued
    get_res = client.get(f"/api/clips/{job_id}/c01")
    assert get_res.json()["status"] == "queued"
