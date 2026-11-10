"""Plain SQL CRUD helpers for SQLite database (no ORM)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.core.db import get_conn, now_iso


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def create_job(
    job_id: str,
    url: str,
    options: dict[str, Any] | str,
    ack_fair_use: bool,
    video_id: str | None = None,
    title: str | None = None,
    channel: str | None = None,
    status: str = "queued",
    stage: str | None = None,
    progress: float = 0.0,
    message: str | None = None,
    ack_at: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Insert a new job row into the database."""
    now = now_iso()
    opts_json = options if isinstance(options, str) else json.dumps(options)
    ack_int = 1 if ack_fair_use else 0
    ack_time = ack_at or (now if ack_fair_use else None)

    query = """
    INSERT INTO jobs (
        id, url, video_id, title, channel, status, stage, progress, message,
        options_json, ack_fair_use, ack_at, created_at, updated_at, error
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        job_id,
        url,
        video_id,
        title,
        channel,
        status,
        stage,
        progress,
        message,
        opts_json,
        ack_int,
        ack_time,
        now,
        now,
        None,
    )

    c = conn or get_conn()
    try:
        c.execute(query, params)
    finally:
        if conn is None:
            c.close()

    res = get_job(job_id, conn=conn)
    if res is None:
        raise RuntimeError(f"Failed to create job {job_id}")
    return res


def get_job(job_id: str, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """Fetch a single job row by ID."""
    c = conn or get_conn()
    try:
        cur = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        return _row_to_dict(row)
    finally:
        if conn is None:
            c.close()


def list_jobs(limit: int = 50, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """List jobs ordered by created_at descending."""
    c = conn or get_conn()
    try:
        cur = c.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(row) for row in cur.fetchall()]
    finally:
        if conn is None:
            c.close()


def update_job(
    job_id: str,
    conn: sqlite3.Connection | None = None,
    **fields: Any,
) -> None:
    """Update fields of an existing job row."""
    if not fields:
        return
    fields["updated_at"] = now_iso()
    if "options" in fields:
        opts = fields.pop("options")
        fields["options_json"] = opts if isinstance(opts, str) else json.dumps(opts)
    if "ack_fair_use" in fields:
        fields["ack_fair_use"] = 1 if fields["ack_fair_use"] else 0

    set_clauses = [f"{k} = ?" for k in fields]
    values = [*fields.values(), job_id]
    sql = f"UPDATE jobs SET {', '.join(set_clauses)} WHERE id = ?"

    c = conn or get_conn()
    try:
        c.execute(sql, values)
    finally:
        if conn is None:
            c.close()


def upsert_clip(clip_data: dict[str, Any], conn: sqlite3.Connection | None = None) -> None:
    """Insert or update a clip row in the clips table."""
    keys = [
        "job_id",
        "id",
        "idx",
        "parent_id",
        "part_index",
        "part_total",
        "start",
        "end",
        "tier",
        "final_score",
        "risk",
        "status",
        "decision",
        "title_choice",
        "title_override",
        "description_override",
        "folder",
        "error",
    ]
    data = {k: clip_data.get(k) for k in keys}
    if data["status"] is None:
        data["status"] = "planned"
    if data["decision"] is None:
        data["decision"] = "pending"
    if data["title_choice"] is None:
        data["title_choice"] = 0

    cols = ", ".join(keys)
    placeholders = ", ".join(["?"] * len(keys))
    update_cols = ", ".join([f"{k} = excluded.{k}" for k in keys if k not in ("job_id", "id")])

    sql = f"""
    INSERT INTO clips ({cols}) VALUES ({placeholders})
    ON CONFLICT(job_id, id) DO UPDATE SET {update_cols}
    """
    c = conn or get_conn()
    try:
        c.execute(sql, [data[k] for k in keys])
    finally:
        if conn is None:
            c.close()


def list_clips(job_id: str, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """List all clips for a job, ordered by idx ascending."""
    c = conn or get_conn()
    try:
        cur = c.execute("SELECT * FROM clips WHERE job_id = ? ORDER BY idx ASC", (job_id,))
        return [dict(row) for row in cur.fetchall()]
    finally:
        if conn is None:
            c.close()


def get_clip(job_id: str, clip_id: str, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """Fetch a single clip by job_id and clip_id."""
    c = conn or get_conn()
    try:
        cur = c.execute("SELECT * FROM clips WHERE job_id = ? AND id = ?", (job_id, clip_id))
        row = cur.fetchone()
        return _row_to_dict(row)
    finally:
        if conn is None:
            c.close()


def update_clip(
    job_id: str,
    clip_id: str,
    conn: sqlite3.Connection | None = None,
    **fields: Any,
) -> None:
    """Update fields of an existing clip row."""
    if not fields:
        return
    set_clauses = [f"{k} = ?" for k in fields]
    values = [*fields.values(), job_id, clip_id]
    sql = f"UPDATE clips SET {', '.join(set_clauses)} WHERE job_id = ? AND id = ?"

    c = conn or get_conn()
    try:
        c.execute(sql, values)
    finally:
        if conn is None:
            c.close()


def add_result(
    job_id: str,
    clip_id: str,
    platform: str,
    url: str | None = None,
    views: int | None = None,
    likes: int | None = None,
    logged_at: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Log an upload result/metric entry for a clip."""
    time_str = logged_at or now_iso()
    sql = """
    INSERT INTO results (job_id, clip_id, platform, url, views, likes, logged_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    c = conn or get_conn()
    try:
        cur = c.execute(sql, (job_id, clip_id, platform, url, views, likes, time_str))
        return cur.lastrowid or 0
    finally:
        if conn is None:
            c.close()


def list_results(
    job_id: str | None = None,
    clip_id: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """List result rows, optionally filtered by job_id and clip_id."""
    c = conn or get_conn()
    try:
        if job_id and clip_id:
            cur = c.execute(
                "SELECT * FROM results WHERE job_id = ? AND clip_id = ? ORDER BY logged_at DESC",
                (job_id, clip_id),
            )
        elif job_id:
            cur = c.execute("SELECT * FROM results WHERE job_id = ? ORDER BY logged_at DESC", (job_id,))
        else:
            cur = c.execute("SELECT * FROM results ORDER BY logged_at DESC")
        return [dict(row) for row in cur.fetchall()]
    finally:
        if conn is None:
            c.close()
