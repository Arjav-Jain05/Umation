"""Unit and API integration tests for /api/jobs endpoints."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def prevent_worker_wake(monkeypatch: pytest.MonkeyPatch):
    """Prevent background worker from executing jobs against live YouTube during API tests."""
    monkeypatch.setattr("app.api.jobs.worker.wake", lambda: None)


def test_post_job_unacknowledged_fair_use_rejected(client: TestClient):
    """Verify POST /api/jobs without fair use acknowledgment returns 422."""
    res = client.post(
        "/api/jobs",
        json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "ack_fair_use": False,
        },
    )
    assert res.status_code == 422
    assert "fair use policy" in res.text


def test_post_job_acknowledged_creates_job(client: TestClient):
    """Verify POST /api/jobs with fair use acknowledgment returns 201 and job_id."""
    res = client.post(
        "/api/jobs",
        json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "ack_fair_use": True,
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert "job_id" in data
    assert "dQw4w9WgXcQ" in data["job_id"]


def test_jobs_listing_and_detail(client: TestClient):
    """Verify GET /api/jobs lists jobs and GET /api/jobs/{id} returns job details."""
    # Create a job
    res = client.post(
        "/api/jobs",
        json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "ack_fair_use": True,
        },
    )
    job_id = res.json()["job_id"]

    # List jobs
    res_list = client.get("/api/jobs")
    assert res_list.status_code == 200
    jobs = res_list.json()
    assert any(j["id"] == job_id for j in jobs)

    # Get single job
    res_single = client.get(f"/api/jobs/{job_id}")
    assert res_single.status_code == 200
    job_data = res_single.json()
    assert job_data["id"] == job_id
    assert job_data["status"] == "queued"


def test_job_cancel(client: TestClient):
    """Verify POST /api/jobs/{id}/cancel cancels a queued job."""
    res = client.post(
        "/api/jobs",
        json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "ack_fair_use": True,
        },
    )
    job_id = res.json()["job_id"]

    cancel_res = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["ok"] is True


def test_review_ui_mount(client: TestClient):
    """Verify /review static mount serves the review & calibration HTML interface."""
    res = client.get("/review/index.html")
    assert res.status_code == 200
    assert "Shorts Engine - Clip Review & Calibration" in res.text
    assert "Calibrate Scoring Weights" in res.text


def test_rate_clip_and_calibrate_endpoint(client: TestClient):
    """Verify rating clips and running logistic regression calibration endpoint."""
    # 1. Create job and insert mock clip
    from app.core.models import upsert_clip

    res = client.post(
        "/api/jobs",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "ack_fair_use": True},
    )
    job_id = res.json()["job_id"]

    clip_dict = {
        "job_id": job_id,
        "id": "c01",
        "idx": 0,
        "start": 10.0,
        "end": 35.0,
        "tier": "A",
        "final_score": 85.0,
        "risk": "low",
        "status": "planned",
    }
    upsert_clip(clip_dict)

    # 2. Rate clip as Good (1)
    rate_res = client.post(f"/api/clips/{job_id}/c01/rate", json={"rating": 1})
    assert rate_res.status_code == 200
    assert rate_res.json()["ok"] is True
    assert rate_res.json()["rating"] == 1

    # 3. Test calibration endpoint
    calib_res = client.post("/api/system/calibrate")
    assert calib_res.status_code == 200
    data = calib_res.json()
    assert data["ok"] is True
    assert "weights_before" in data
    assert "weights_after" in data
    assert len(data["weights_after"]) > 0


