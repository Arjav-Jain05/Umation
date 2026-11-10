"""Global pytest fixtures for shorts-engine tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.db import init_db
from app.main import create_app
from config.settings import get_settings


@pytest.fixture(autouse=True)
def disable_background_worker(monkeypatch: pytest.MonkeyPatch):
    """Prevent background worker thread from running during automated unit/API tests."""
    monkeypatch.setattr("app.core.worker.Worker.start", lambda self: None)
    monkeypatch.setattr("app.core.worker.Worker.stop", lambda self: None)


@pytest.fixture
def temp_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Provide isolated temp directories for data, output, and logs."""
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    data_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("OUTPUT_DIR", str(output_dir))
    get_settings.cache_clear()

    return {
        "root": tmp_path,
        "data": data_dir,
        "output": output_dir,
    }


@pytest.fixture
def temp_db(temp_dirs: dict[str, Path]) -> Generator[sqlite3.Connection, None, None]:
    """Initialize an isolated test database and yield a connection."""
    db_path = temp_dirs["data"] / "app.db"
    init_db(db_path)
    from app.core.db import get_conn
    conn = get_conn(db_path)
    yield conn
    conn.close()


@pytest.fixture
def client(temp_dirs: dict[str, Path]) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with temp settings."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
