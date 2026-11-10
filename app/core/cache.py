"""Persistent sha256 response caching backed by SQLite cache table."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from app.core.db import get_conn, now_iso


def make_key(*parts: Any) -> str:
    """Generate a deterministic sha256 hex digest key from arbitrary parts."""
    hasher = hashlib.sha256()
    for part in parts:
        if isinstance(part, bytes):
            hasher.update(part)
        else:
            hasher.update(str(part).encode("utf-8"))
    return hasher.hexdigest()


def cache_get(key: str, conn: sqlite3.Connection | None = None) -> str | None:
    """Retrieve cached string value by key, or None if not found."""
    c = conn or get_conn()
    try:
        cur = c.execute("SELECT value FROM cache WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row is not None else None
    finally:
        if conn is None:
            c.close()


def cache_set(key: str, value: str, conn: sqlite3.Connection | None = None) -> None:
    """Store or update a string value in the cache table."""
    now = now_iso()
    sql = """
    INSERT INTO cache (key, value, created_at)
    VALUES (?, ?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, created_at = excluded.created_at
    """
    c = conn or get_conn()
    try:
        c.execute(sql, (key, value, now))
    finally:
        if conn is None:
            c.close()
