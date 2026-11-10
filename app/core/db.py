"""Database connection, initialization and transaction helpers for SQLite WAL mode."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from config.settings import get_settings

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        video_id TEXT,
        title TEXT,
        channel TEXT,
        status TEXT NOT NULL,
        stage TEXT,
        progress REAL DEFAULT 0,
        message TEXT,
        options_json TEXT NOT NULL,
        ack_fair_use INTEGER NOT NULL,
        ack_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        error TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS clips (
        job_id TEXT NOT NULL,
        id TEXT NOT NULL,
        idx INTEGER NOT NULL,
        parent_id TEXT,
        part_index INTEGER,
        part_total INTEGER,
        start REAL NOT NULL,
        end REAL NOT NULL,
        tier TEXT NOT NULL,
        final_score REAL NOT NULL,
        risk TEXT NOT NULL,
        status TEXT NOT NULL,
        decision TEXT NOT NULL DEFAULT 'pending',
        title_choice INTEGER DEFAULT 0,
        title_override TEXT,
        description_override TEXT,
        folder TEXT,
        error TEXT,
        PRIMARY KEY (job_id, id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        clip_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        url TEXT,
        views INTEGER,
        likes INTEGER,
        logged_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS cache (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
]


def now_iso() -> str:
    """Return current UTC time formatted as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _resolve_db_path(db_path: Path | str | None = None) -> Path:
    if db_path is not None:
        p = Path(db_path)
    else:
        settings = get_settings()
        p = settings.data_dir / "app.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_conn(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Get a SQLite connection configured with WAL mode and row factory."""
    path = _resolve_db_path(db_path)
    conn = sqlite3.connect(
        str(path),
        check_same_thread=False,
        timeout=10.0,
        isolation_level=None,  # autocommit mode; manage transactions manually
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize database tables and indexes."""
    path = _resolve_db_path(db_path)
    conn = get_conn(path)
    try:
        conn.execute("BEGIN IMMEDIATE;")
        for stmt in DDL_STATEMENTS:
            conn.execute(stmt)
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()


@contextmanager
def transaction(
    conn: sqlite3.Connection | None = None,
    db_path: Path | str | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for an atomic database transaction."""
    managed_conn = conn is None
    c = conn if conn is not None else get_conn(db_path)
    c.execute("BEGIN IMMEDIATE;")
    try:
        yield c
        c.execute("COMMIT;")
    except Exception:
        c.execute("ROLLBACK;")
        raise
    finally:
        if managed_conn:
            c.close()
