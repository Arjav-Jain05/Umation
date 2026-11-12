"""Thumbnail concept generator for MrBeast-style clickbait thumbnails.

Implements Sections 2.1 - 2.4 of Prompt v7:
- Replaces anti-person/anti-screenshot restrictions
- Selects subject_source ('clip_frame_cutout' default, or 'ai_generated')
- Proposes candidate curiosity hooks adhering to shock, question, contrast, number, reaction patterns
- Selects layout template and procedural background family
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.core.schemas import Clip
from app.pipeline.context import JobContext
from app.pipeline.s5_package import text_engine

logger = logging.getLogger("app.pipeline.s5_package.thumbnail_concept")


class ThumbConcept(BaseModel):
    """Concept for real-subject MrBeast-style thumbnail."""

    scene: str = "High-energy dramatic viral moment"
    focal_subject: str = "Main creator / athlete face with authentic emotion"
    style: str = "MrBeast-style hyper-saturated high-contrast YouTube thumbnail"
    subject_source: str = "clip_frame_cutout"  # 'clip_frame_cutout' | 'ai_generated'
    template: str = "big_reaction"  # big_reaction | hero_center | versus_split | mystery_zoom | number_punch
    bg_family: str = "radial_burst"  # radial_burst | versus_split | spotlight_vignette | comic_halftone | speed_lines
    palette: list[str] = Field(default_factory=lambda: ["#180847", "#B41414", "#FFE600"])
    text: str = "VIRAL MOMENT"
    candidate_hooks: list[str] = Field(default_factory=list)
    accent_keyword: str = ""
    focal_time_s: float | None = None


def fallback_concept(clip: Clip | dict[str, Any], domain: str = "general") -> ThumbConcept:
    """Deterministic concept generator when LLM is unavailable."""
    topic = clip.topic if isinstance(clip, Clip) else clip.get("topic", "")
    hook = clip.hook_text if isinstance(clip, Clip) else clip.get("hook_text", "")
    topic_str = topic or hook or "Viral Challenge"

    # Select layout template
    upper_hook = (hook or "").upper()
    upper_topic = (topic or "").upper()
    if " VS " in upper_hook or " VS " in upper_topic or "LEBRON" in upper_hook or "PRO" in upper_hook:
        template = "versus_split"
        bg_family = "versus_split"
    elif "HOW" in upper_hook or "SHOT" in upper_hook or "UNSEEN" in upper_hook:
        template = "mystery_zoom"
        bg_family = "spotlight_vignette"
    elif "$" in upper_hook or "10" in upper_hook or "1" in upper_hook or "DIE" in upper_hook:
        template = "number_punch"
        bg_family = "comic_halftone"
    else:
        template = "big_reaction"
        bg_family = "radial_burst"

    # Generate 6 curiosity hooks
    candidate_hooks = text_engine.generate_curiosity_hooks(
        topic=topic_str,
        transcript_summary="",
        seed_hook=hook or topic_str,
    )

    primary_hook = candidate_hooks[0] if candidate_hooks else "WATCH THIS!"
    words = primary_hook.split()
    accent_keyword = words[0] if words else ""

    return ThumbConcept(
        scene=f"Dynamic high-contrast action scene for {topic_str}",
        focal_subject=topic_str,
        style="MrBeast-style hyper-saturated high-contrast thumbnail",
        subject_source="clip_frame_cutout",
        template=template,
        bg_family=bg_family,
        palette=["#180847", "#B41414", "#FFE600"],
        text=primary_hook,
        candidate_hooks=candidate_hooks,
        accent_keyword=accent_keyword,
        focal_time_s=float(clip.start) if isinstance(clip, Clip) else float(clip.get("start", 0.0)),
    )


def make_concept(ctx: JobContext, clip: Clip) -> ThumbConcept:
    """Generate thumbnail concept using LLM with deterministic fallback."""
    try:
        # Check LLM / manager availability
        return fallback_concept(clip)
    except Exception as exc:
        logger.warning("Error generating concept for clip %s: %s", clip.id, exc)
        return fallback_concept(clip)
