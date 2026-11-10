"""Comprehensive unit tests for Milestone M0: scaffold, paths, db, models, schemas, and API."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_conn, init_db, now_iso, transaction
from app.core.errors import (
    AppError,
    Canceled,
    DiskSpace,
    GeminiQuotaExceeded,
    GeminiUnavailable,
    InvalidUrl,
    LiveNotFinished,
    SourceBlocked,
    SourceUnavailable,
    TooLong,
    to_api,
)
from app.core.models import (
    add_result,
    create_job,
    get_clip,
    get_job,
    list_clips,
    list_jobs,
    list_results,
    update_clip,
    update_job,
    upsert_clip,
)
from app.core.paths import (
    assets_dir,
    clip_dir,
    data_dir,
    ensure,
    job_dir,
    output_clip_dir,
    output_dir,
    prompts_dir,
    slugify,
)
from app.core.schemas import (
    Chapter,
    Clip,
    EditEvent,
    EditList,
    Metadata,
    Plan,
    Sentence,
    SourceInfo,
    SourcePolicyMatch,
    TitleOption,
    Transcript,
    Word,
    read_artifact,
    write_artifact,
)
from app.utils.logging_setup import ContextAdapter, get_logger, setup_logging
from config.settings import get_settings


def test_paths_and_slugify(temp_dirs: dict[str, Path]):
    """Verify paths resolver, slugify, and directory creators."""
    settings = get_settings()
    assert data_dir() == settings.data_dir
    assert output_dir() == settings.output_dir
    assert assets_dir() == settings.project_root / "assets"
    assert prompts_dir() == settings.project_root / "prompts"

    # Job and clip directories
    j_dir = job_dir("20261110-120000-abc12345")
    assert j_dir == settings.data_dir / "work" / "20261110-120000-abc12345"

    c_dir = clip_dir("20261110-120000-abc12345", "c01")
    assert c_dir == j_dir / "clips" / "c01"

    out_c_dir = output_clip_dir("gta-6-trailer-breakdown", "abc12345", "c01", "A")
    assert out_c_dir == settings.output_dir / "gta-6-trailer-breakdown-abc12345" / "c01_A"

    out_c_part_dir = output_clip_dir(
        "gta-6-trailer-breakdown", "abc12345", "c04p1", "A", part=(1, 3)
    )
    assert out_c_part_dir == (
        settings.output_dir / "gta-6-trailer-breakdown-abc12345" / "c04p1_A_part1of3"
    )

    # Slugify rules: lowercase, ASCII, hyphens, max 60 chars
    assert slugify("GTA 6: Vice City Reborn! (Official 2026)") == "gta-6-vice-city-reborn-official-2026"
    assert slugify("///Multiple---Spaces   and   Symbols***") == "multiple-spaces-and-symbols"
    long_text = "a" * 100
    assert len(slugify(long_text, max_len=40)) <= 40

    # Ensure creates directory
    test_target = temp_dirs["root"] / "nested" / "subfolder"
    created = ensure(test_target)
    assert created.is_dir()


def test_errors_and_to_api():
    """Verify AppError hierarchy, codes, hints, and API serialization."""
    err = InvalidUrl("URL must be a single YouTube video", hint="Check formatting")
    assert isinstance(err, AppError)
    assert err.code.lower() == "invalid_url"
    assert err.message == "URL must be a single YouTube video"
    assert err.hint == "Check formatting"

    api_dict = to_api(err)
    assert api_dict["code"].lower() == "invalid_url"
    assert api_dict["message"] == "URL must be a single YouTube video"
    assert api_dict["hint"] == "Check formatting"

    # Test all specific subclasses
    instances = [
        SourceBlocked("TestChannel", "Not allowed"),
        SourceUnavailable("Private video"),
        LiveNotFinished("Still streaming"),
        TooLong(36000.0, 5),
        DiskSpace(50.0, 10.0),
        GeminiUnavailable("503 timeout"),
        GeminiQuotaExceeded("Daily quota reached"),
        Canceled("User clicked cancel"),
    ]
    for instance in instances:
        assert instance.code.lower() != "app_error"
        assert to_api(instance)["code"] == instance.code


def test_database_init_and_transaction(temp_dirs: dict[str, Path]):
    """Verify WAL mode, pragmas, table schemas, and transactions."""
    db_file = temp_dirs["data"] / "test_app.db"
    init_db(db_file)
    conn = get_conn(db_file)

    # Check PRAGMAs
    journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert journal_mode.lower() == "wal"

    foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    assert foreign_keys == 1

    # Check tables exist
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        ).fetchall()
    ]
    assert "jobs" in tables
    assert "clips" in tables
    assert "results" in tables
    assert "cache" in tables

    # Test transaction rollback on failure
    with pytest.raises(ValueError), transaction(conn):
        conn.execute(
            "INSERT INTO cache (key, value, created_at) VALUES (?, ?, ?)",
            ("rollback_key", "val", now_iso()),
        )
        raise ValueError("Intentional rollback")

    row = conn.execute("SELECT * FROM cache WHERE key = 'rollback_key'").fetchone()
    assert row is None

    # Test transaction commit on success
    with transaction(conn):
        conn.execute(
            "INSERT INTO cache (key, value, created_at) VALUES (?, ?, ?)",
            ("commit_key", "val", now_iso()),
        )

    row = conn.execute("SELECT * FROM cache WHERE key = 'commit_key'").fetchone()
    assert row is not None
    assert row["value"] == "val"
    conn.close()


def test_models_crud(temp_db: sqlite3.Connection):
    """Verify CRUD helpers for jobs, clips, and results."""
    # 1. Job CRUD
    job = create_job(
        job_id="20261110-150000-abc12345",
        url="https://www.youtube.com/watch?v=abc12345",
        options={"min_tier": "B", "max_clip_s": 60},
        ack_fair_use=True,
        video_id="abc12345",
        title="GTA 6 Trailer Breakdown",
        channel="Rockstar Fan",
        conn=temp_db,
    )
    assert job["id"] == "20261110-150000-abc12345"
    assert job["status"] == "queued"
    assert job["ack_fair_use"] == 1

    fetched = get_job("20261110-150000-abc12345", conn=temp_db)
    assert fetched is not None
    assert fetched["title"] == "GTA 6 Trailer Breakdown"

    update_job("20261110-150000-abc12345", conn=temp_db, status="running", stage="transcribe", progress=25.0)
    updated = get_job("20261110-150000-abc12345", conn=temp_db)
    assert updated["status"] == "running"
    assert updated["stage"] == "transcribe"
    assert updated["progress"] == 25.0

    jobs = list_jobs(conn=temp_db)
    assert len(jobs) == 1

    # 2. Clips CRUD
    clip_data = {
        "job_id": "20261110-150000-abc12345",
        "id": "c01",
        "idx": 0,
        "start": 10.5,
        "end": 55.2,
        "tier": "A",
        "final_score": 88.5,
        "risk": "low",
        "status": "planned",
        "decision": "pending",
    }
    upsert_clip(clip_data, conn=temp_db)

    clip = get_clip("20261110-150000-abc12345", "c01", conn=temp_db)
    assert clip is not None
    assert clip["tier"] == "A"
    assert clip["final_score"] == 88.5

    # Update clip
    update_clip("20261110-150000-abc12345", "c01", conn=temp_db, decision="approved", title_choice=1)
    clip_up = get_clip("20261110-150000-abc12345", "c01", conn=temp_db)
    assert clip_up["decision"] == "approved"
    assert clip_up["title_choice"] == 1

    clips = list_clips("20261110-150000-abc12345", conn=temp_db)
    assert len(clips) == 1

    # 3. Results CRUD
    rid = add_result(
        job_id="20261110-150000-abc12345",
        clip_id="c01",
        platform="youtube",
        url="https://youtube.com/shorts/testclip",
        views=1500,
        likes=250,
        conn=temp_db,
    )
    assert rid > 0

    results = list_results("20261110-150000-abc12345", "c01", conn=temp_db)
    assert len(results) == 1
    assert results[0]["platform"] == "youtube"
    assert results[0]["views"] == 1500


def test_schemas_and_artifact_io(temp_dirs: dict[str, Path]):
    """Verify Pydantic schemas validation and atomic artifact I/O."""
    # 1. SourceInfo
    src = SourceInfo(
        video_id="dQw4w9WgXcQ",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        webpage_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Rick Astley - Never Gonna Give You Up",
        channel="Rick Astley",
        channel_url="https://www.youtube.com/@RickAstley",
        uploader="RickAstleyVEVO",
        upload_date="20091025",
        duration_s=213.0,
        live_status="was_live",
        width=1920,
        height=1080,
        fps=25.0,
        view_count=1500000000,
        chapters=[Chapter(start=0.0, end=30.0, title="Intro")],
        source_policy=SourcePolicyMatch(status="allow", matched_rule="allowlist_music"),
        fetched_at=now_iso(),
    )
    src_path = temp_dirs["data"] / "source_info.json"
    write_artifact(src_path, src)
    assert src_path.is_file()

    loaded_src = read_artifact(src_path, SourceInfo)
    assert loaded_src.schema_version == 1
    assert loaded_src.video_id == "dQw4w9WgXcQ"
    assert loaded_src.chapters[0].title == "Intro"

    # 2. Transcript
    transcript = Transcript(
        language="en",
        model="large-v3",
        duration_s=120.0,
        words=[Word(i=0, w="Hello", s=0.0, e=0.4, p=0.98)],
        sentences=[Sentence(id=0, s=0.0, e=2.5, text="Hello world.", w0=0, w1=1, wpm=140.0)],
        fillers=[1],
    )
    tr_path = temp_dirs["data"] / "transcript.json"
    write_artifact(tr_path, transcript)
    loaded_tr = read_artifact(tr_path, Transcript)
    assert loaded_tr.words[0].w == "Hello"

    # 3. Plan
    plan = Plan(
        job_id="test_job",
        generated_at=now_iso(),
        clips=[
            Clip(
                id="c01",
                start=10.0,
                end=45.0,
                duration=35.0,
                tier="A",
                final_score=92.0,
                llm_score=88.0,
                hook_text="Check out this physics bug",
                topic="GTA 6 Physics",
                risk="low",
            )
        ],
    )
    plan_path = temp_dirs["data"] / "plan.json"
    write_artifact(plan_path, plan)
    loaded_plan = read_artifact(plan_path, Plan)
    assert len(loaded_plan.clips) == 1
    assert loaded_plan.clips[0].tier == "A"

    # 4. EditList
    edit_list = EditList(
        clip_id="c01",
        fps=30,
        duration=35.0,
        layout="gameplay",
        events=[
            EditEvent(id="e01", type="hook_card", t=0.0, dur=2.0, params={"text": "INSANE BUG"}),
            EditEvent(id="e02", type="zoom_punch", t=5.0, dur=0.8, params={"scale": 1.12}),
        ],
    )
    el_path = temp_dirs["data"] / "edit_list.json"
    write_artifact(el_path, edit_list)
    loaded_el = read_artifact(el_path, EditList)
    assert len(loaded_el.events) == 2
    assert loaded_el.events[0].type == "hook_card"

    # 5. Metadata
    meta = Metadata(
        clip_id="c01",
        titles=[
            TitleOption(style="curiosity", text="Did Rockstar just leak this?"),
            TitleOption(style="direct", text="Insane GTA 6 Physics Breakdown"),
        ],
        hook_line="You won't believe this physics detail in GTA 6.",
        hashtags=["#gta6", "#shorts"],
        keywords=["gta 6", "vice city"],
    )
    meta_path = temp_dirs["data"] / "metadata.json"
    write_artifact(meta_path, meta)
    loaded_meta = read_artifact(meta_path, Metadata)
    assert len(loaded_meta.titles) == 2


def test_logging_adapter(temp_dirs: dict[str, Path]):
    """Verify logging setup, log file creation, and context adapter."""
    settings = get_settings()
    setup_logging(settings)

    logger = get_logger("test.module", job="job_123", clip="c01")
    assert isinstance(logger, ContextAdapter)
    logger.info("Test log message with context")

    log_file = settings.data_dir / "logs" / "app.log"
    assert log_file.is_file()
    content = log_file.read_text(encoding="utf-8")
    assert "[job:job_123]" in content
    assert "[clip:c01]" in content
    assert "Test log message with context" in content


def test_api_system_health(client: TestClient):
    """Verify GET /api/health endpoint."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["version"] == "1.0.0"


def test_api_system_check(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Verify GET /api/system/check returns environment check list."""
    from scripts.check_env import CheckResult

    mock_results = [
        CheckResult("Python version", "PASS", "Python 3.12.10"),
        CheckResult("Disk space", "PASS", "100.0 GB free"),
        CheckResult("HTTP Port", "PASS", "127.0.0.1:8000 is free"),
    ]
    monkeypatch.setattr("app.api.system.run_checks", lambda **kwargs: mock_results)

    res = client.get("/api/system/check")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) == 3
    check_names = [item["check"] for item in data]
    assert "Python version" in check_names
    assert "Disk space" in check_names
    assert "HTTP Port" in check_names


def test_api_system_open_folder(client: TestClient, temp_dirs: dict[str, Path]):
    """Verify POST /api/system/open-folder path security and validation."""
    valid_folder = temp_dirs["output"] / "job_01" / "c01"
    valid_folder.mkdir(parents=True, exist_ok=True)

    # 1. Valid path inside output_dir
    res = client.post("/api/system/open-folder", json={"path": str(valid_folder)})
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    # 2. Path outside output_dir (Forbidden)
    outside_folder = temp_dirs["root"] / "forbidden"
    outside_folder.mkdir(parents=True, exist_ok=True)
    res = client.post("/api/system/open-folder", json={"path": str(outside_folder)})
    assert res.status_code == 400
    assert "output_dir" in res.json()["detail"]

    # 3. Path that does not exist inside output_dir
    missing_folder = temp_dirs["output"] / "missing_dir"
    res = client.post("/api/system/open-folder", json={"path": str(missing_folder)})
    assert res.status_code == 404


def test_api_root_redirect_and_web(client: TestClient):
    """Verify root / redirects to /web/index.html and static file serves index.html."""
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/web/index.html"

    web_res = client.get("/web/index.html")
    assert web_res.status_code == 200
    assert "Shorts Engine" in web_res.text
    assert 'id="sys-banner"' in web_res.text
    assert 'id="start-btn"' in web_res.text
