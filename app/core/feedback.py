"""Feedback collection for personal fine-tuning and ranking model calibration."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.settings import get_settings

logger = logging.getLogger("app.core.feedback")


def get_ratings_path() -> Path:
    settings = get_settings()
    feedback_dir = settings.project_root / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    return feedback_dir / "ratings.jsonl"


def log_clip_rating(
    clip_id: str,
    job_id: str,
    rating: bool | int,
    scores: dict[str, Any],
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a human rating (1=thumbs up, 0=thumbs down) and score features to ratings.jsonl."""
    record = {
        "clip_id": clip_id,
        "job_id": job_id,
        "rating": 1 if rating in (True, 1) else 0,
        "scores": scores,
        "metrics": metrics or {},
        "logged_at": datetime.now(UTC).isoformat(),
    }

    path = get_ratings_path()
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        logger.info(f"Logged rating for clip {clip_id}: {record['rating']}")
    except Exception as exc:
        logger.warning(f"Failed to append rating: {exc}")

    return record


def load_all_ratings() -> list[dict[str, Any]]:
    """Load all recorded clip ratings from feedback/ratings.jsonl."""
    path = get_ratings_path()
    if not path.is_file():
        return []

    records: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception as exc:
        logger.warning(f"Failed to read ratings: {exc}")

    return records
