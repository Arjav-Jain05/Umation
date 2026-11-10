"""Filesystem path helpers for shorts-engine.

The ONLY place in the application where job, clip, and output paths are constructed.
Spec: references/02-architecture-and-data-contracts.md section 10; docs/FILE-MAP.md row 48.
"""

from __future__ import annotations

import re
from pathlib import Path

from config.settings import get_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def ensure(path: Path) -> Path:
    """Ensure parent directory (or directory itself) exists, returning the path."""
    if path.suffix:  # Has file extension -> create parent
        path.parent.mkdir(parents=True, exist_ok=True)
    else:  # Directory -> create itself
        path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    """Runtime working directory (data/)."""
    return ensure(get_settings().data_dir)


def output_dir() -> Path:
    """Finished clips output directory (output/)."""
    return ensure(get_settings().output_dir)


def assets_dir() -> Path:
    """Assets directory containing fonts, models, sfx, overlays."""
    return ensure(PROJECT_ROOT / "assets")


def prompts_dir() -> Path:
    """Prompts directory containing plain-text prompt templates."""
    return ensure(PROJECT_ROOT / "prompts")


def job_dir(job_id: str) -> Path:
    """Per-job working directory under data/work/<job_id>/."""
    return ensure(data_dir() / "work" / job_id)


def clip_dir(job_id: str, clip_id: str) -> Path:
    """Per-clip working directory under data/work/<job_id>/clips/<clip_id>/."""
    return ensure(job_dir(job_id) / "clips" / clip_id)


def slugify(text: str, max_len: int = 60) -> str:
    """Generate clean URL/folder-safe slug: lowercase ASCII with hyphens."""
    clean = re.sub(r"[^\w\s-]", "", text.strip()).strip().lower()
    slug = re.sub(r"[-\s]+", "-", clean)
    return slug[:max_len].strip("-") or "video"


def output_clip_dir(
    video_slug: str,
    video_id: str,
    clip_id: str,
    tier: str,
    part: tuple[int, int] | None = None,
    part_index: int | None = None,
    part_total: int | None = None,
) -> Path:
    """Final output folder for a clip:

    output/<slug>-<video_id>/<clip_id>_<tier>[_part<k>of<n>]/
    """
    clean_slug = slugify(video_slug)
    video_folder_name = f"{clean_slug}-{video_id}"

    clip_folder_name = f"{clip_id}_{tier.upper()}"
    if part is not None:
        k, n = part
        if n > 1:
            clip_folder_name += f"_part{k}of{n}"
    elif part_index is not None and part_total is not None and part_total > 1:
        clip_folder_name += f"_part{part_index}of{part_total}"

    return ensure(output_dir() / video_folder_name / clip_folder_name)
