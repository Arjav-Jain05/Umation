"""Plain SQL CRUD helpers for SQLite database (no ORM)."""

from __future__ import annotations

import contextlib
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


def upsert_candidate(data: dict[str, Any], conn: sqlite3.Connection | None = None) -> None:
    """Insert or update a candidate in the candidates store."""
    sql = """
    INSERT INTO candidates (
        job_id, id, start_s, end_s, hook_text, topic, llm_score,
        audio_score, heat_score, final_score, tier, scores_json,
        selected, pinned, excluded, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(job_id, id) DO UPDATE SET
        start_s=excluded.start_s,
        end_s=excluded.end_s,
        hook_text=excluded.hook_text,
        topic=excluded.topic,
        llm_score=excluded.llm_score,
        audio_score=excluded.audio_score,
        heat_score=excluded.heat_score,
        final_score=excluded.final_score,
        tier=excluded.tier,
        scores_json=excluded.scores_json,
        selected=excluded.selected,
        pinned=excluded.pinned,
        excluded=excluded.excluded
    """
    scores_str = data.get("scores_json")
    if not isinstance(scores_str, str):
        scores_str = json.dumps(scores_str or {})

    params = (
        data["job_id"],
        data["id"],
        float(data["start_s"]),
        float(data["end_s"]),
        data.get("hook_text"),
        data.get("topic"),
        float(data["llm_score"]),
        data.get("audio_score"),
        data.get("heat_score"),
        float(data["final_score"]),
        data.get("tier", "C"),
        scores_str,
        1 if data.get("selected", True) else 0,
        1 if data.get("pinned", False) else 0,
        1 if data.get("excluded", False) else 0,
        data.get("created_at") or now_iso(),
    )
    c = conn or get_conn()
    try:
        c.execute(sql, params)
    finally:
        if conn is None:
            c.close()


def list_candidates(
    job_id: str,
    min_score: float | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Fetch candidates for a job, optionally filtered by minimum score."""
    c = conn or get_conn()
    try:
        if min_score is not None:
            cur = c.execute(
                "SELECT * FROM candidates WHERE job_id = ? AND final_score >= ? ORDER BY final_score DESC",
                (job_id, min_score),
            )
        else:
            cur = c.execute(
                "SELECT * FROM candidates WHERE job_id = ? ORDER BY final_score DESC",
                (job_id,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            if isinstance(r.get("scores_json"), str):
                with contextlib.suppress(Exception):
                    r["scores"] = json.loads(r["scores_json"])
        return rows
    finally:
        if conn is None:
            c.close()


def update_candidate_selection(
    job_id: str,
    candidate_id: str,
    selected: bool | None = None,
    pinned: bool | None = None,
    excluded: bool | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Update selection flags (selected, pinned, excluded) for a candidate."""
    updates: list[str] = []
    params: list[Any] = []
    if selected is not None:
        updates.append("selected = ?")
        params.append(1 if selected else 0)
    if pinned is not None:
        updates.append("pinned = ?")
        params.append(1 if pinned else 0)
    if excluded is not None:
        updates.append("excluded = ?")
        params.append(1 if excluded else 0)

    if not updates:
        return

    params.extend([job_id, candidate_id])
    sql = f"UPDATE candidates SET {', '.join(updates)} WHERE job_id = ? AND id = ?"
    c = conn or get_conn()
    try:
        c.execute(sql, tuple(params))
    finally:
        if conn is None:
            c.close()
