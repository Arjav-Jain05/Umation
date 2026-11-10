"""Thumbnail concept design generator (07 s6).

Generates original artwork concepts referencing clip topics, never screenshots.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.core import paths
from app.core.schemas import Clip
from app.pipeline.context import JobContext

logger = logging.getLogger("app.pipeline.s5_package.thumbnail_concept")


class ThumbConcept(BaseModel):
    """Concept for original artwork thumbnail."""

    scene: str
    focal_subject: str
    style: str
    palette: list[str] = Field(default_factory=lambda: ["#FFD400", "#FF007F", "#0F1115"])
    text: str = "VIRAL MOMENT"
    text_position: str = "top"  # top | left | bottom
    avoid: list[str] = Field(
        default_factory=lambda: [
            "people faces",
            "game logos",
            "screenshots",
            "official key art",
            "text in image",
        ]
    )


def clean_concept_text(text: str) -> str:
    """Ensure thumbnail overlay text is 1-3 words in ALL CAPS without trailing punctuation."""
    words = re.findall(r"[A-Za-z0-9_#]+", text.strip())
    if not words:
        return "WATCH THIS"
    words = words[:3]
    return " ".join(words).upper()


def fallback_concept(clip: Clip | dict[str, Any], domain: str = "gta6") -> ThumbConcept:
    """Deterministic fallback concept per 07 s6 when Gemini is unavailable."""
    topic = clip.topic if isinstance(clip, Clip) else clip.get("topic", "")
    hook = clip.hook_text if isinstance(clip, Clip) else clip.get("hook_text", "")
    topic_str = topic or (domain.upper() if domain else "GTA 6")

    words = re.findall(r"[A-Za-z0-9]+", hook or topic_str)
    overlay_text = " ".join(words[:2]).upper() if words else "MUST SEE"

    return ThumbConcept(
        scene=f"bold abstract neon gradient with a large symbolic icon for {topic_str}",
        focal_subject=topic_str,
        style="digital neon vector illustration with high contrast",
        palette=["#FFD400", "#FF007F", "#0F1115"],
        text=clean_concept_text(overlay_text),
        text_position="top",
        avoid=[
            "people faces",
            "game logos",
            "screenshots",
            "official key art",
            "text in image",
        ],
    )


def make_concept(ctx: JobContext, clip: Clip) -> ThumbConcept:
    """Generate thumbnail concept via Gemini prompt or deterministic fallback."""
    prompt_path = paths.prompts_dir() / "thumbnail_concept.md"
    template = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else ""

    domain_desc = "GTA 6 news, gameplay, rumors, and leaks"
    domain = getattr(ctx.options, "domain", "gta6") if hasattr(ctx, "options") else "gta6"

    entities = getattr(clip, "entities", None)
    entities_str = ", ".join(entities) if entities else "GTA 6"
    mood_str = "energetic and exciting"

    prompt = (
        template.replace("{{topic}}", clip.topic or "GTA 6")
        .replace("{{entities}}", entities_str)
        .replace("{{hook_text}}", clip.hook_text or "")
        .replace("{{mood}}", mood_str)
        .replace("{{domain_description}}", domain_desc)
    )

    try:
        concept = ctx.gemini.generate_json(
            prompt,
            ThumbConcept,
            temperature=0.7,
            cache_key=f"thumb_concept_{ctx.job.id}_{clip.id}",
        )
        concept.text = clean_concept_text(concept.text)
        if concept.text_position not in ("top", "left", "bottom"):
            concept.text_position = "top"
        if not concept.palette:
            concept.palette = ["#FFD400", "#FF007F", "#0F1115"]
        return concept
    except Exception as e:
        logger.warning(
            "Thumbnail concept generation failed for clip %s (%s); using fallback concept",
            clip.id,
            e,
        )
        return fallback_concept(clip, domain=domain)
