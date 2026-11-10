"""Unit tests for /api/clips endpoints (detail, patch approval, trim, edit-list, rerender)."""

import json

from fastapi.testclient import TestClient

from app.core import paths
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


def test_clip_patch_trim_boundaries(client: TestClient):
    """Verify PATCH /api/clips/{job_id}/{clip_id} trims start and end boundaries (M5)."""
    job_id = "test_job_trim"
    with get_conn() as conn:
        create_job(job_id=job_id, url="https://youtube.com/watch?v=trim", video_id="trim", options={}, ack_fair_use=True, conn=conn)
        upsert_clip(
            {
                "job_id": job_id,
                "id": "c01",
                "idx": 1,
                "start": 10.0,
                "end": 40.0,
                "tier": "B",
                "final_score": 75.0,
                "risk": "low",
                "status": "built",
            },
            conn=conn,
        )

    # Trim start to 12.5 and end to 38.0
    res = client.patch(
        f"/api/clips/{job_id}/c01",
        json={"start": 12.5, "end": 38.0},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["start"] == 12.5
    assert data["end"] == 38.0

    # Invalid end <= start -> 422
    bad_res = client.patch(
        f"/api/clips/{job_id}/c01",
        json={"start": 50.0, "end": 40.0},
    )
    assert bad_res.status_code == 422


def test_clip_edit_list_and_words_endpoints(client: TestClient, tmp_path, monkeypatch):
    """Verify GET/PATCH edit-list and GET words endpoints (M5)."""
    job_id = "test_job_editor"
    clip_id = "c01"

    clip_dir = tmp_path / "work" / job_id / "clips" / clip_id
    clip_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "clip_dir", lambda *a: clip_dir)

    with get_conn() as conn:
        create_job(job_id=job_id, url="https://youtube.com/watch?v=ed", video_id="ed", options={}, ack_fair_use=True, conn=conn)
        upsert_clip(
            {
                "job_id": job_id,
                "id": clip_id,
                "idx": 0,
                "start": 0.0,
                "end": 30.0,
                "tier": "A",
                "final_score": 85.0,
                "risk": "low",
                "status": "built",
            },
            conn=conn,
        )

    # Write dummy words artifact
    words_data = {
        "schema_version": 1,
        "clip_id": clip_id,
        "words": [
            {"w": "Look", "s_clip": 0.5, "e_clip": 0.8},
            {"w": "at", "s_clip": 0.8, "e_clip": 1.0},
            {"w": "this", "s_clip": 1.0, "e_clip": 1.4},
        ],
    }
    (clip_dir / "words.json").write_text(json.dumps(words_data), encoding="utf-8")

    # 1. GET words
    words_res = client.get(f"/api/clips/{job_id}/{clip_id}/words")
    assert words_res.status_code == 200
    assert len(words_res.json()["words"]) == 3

    # 2. PATCH edit-list
    patch_res = client.patch(
        f"/api/clips/{job_id}/{clip_id}/edit-list",
        json={
            "events": [
                {
                    "id": "ev1",
                    "type": "zoom_punch",
                    "t": 0.5,
                    "dur": 1.3,
                    "params": {"scale": 1.15},
                }
            ],
            "caption_emphasis": [0, 2],
        },
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["ok"] is True

    # 3. GET edit-list
    get_edit_res = client.get(f"/api/clips/{job_id}/{clip_id}/edit-list")
    assert get_edit_res.status_code == 200
    edit_data = get_edit_res.json()
    assert len(edit_data["events"]) == 1
    assert edit_data["caption_emphasis"] == [0, 2]


def test_clip_rerender(client: TestClient):
    """Verify POST /api/clips/{job_id}/{clip_id}/rerender queues re-render."""
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

    # Status is updated
    get_res = client.get(f"/api/clips/{job_id}/c01")
    assert get_res.json()["status"] in ("queued", "rendering", "packaged", "built", "failed")
