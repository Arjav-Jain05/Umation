"""Clip metadata generation, prompt templating, validation, and description assembly."""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.core import paths
from app.core.schemas import Clip, SourceInfo
from app.pipeline.context import JobContext
from app.pipeline.s5_package.credit import build_credit_block

logger = logging.getLogger("app.pipeline.s5_package.metadata")


class TitleOption(BaseModel):
    style: str  # curiosity | direct | bold
    text: str


class RawMetadataOut(BaseModel):
    titles: list[TitleOption] = Field(default_factory=list)
    hook_line: str = ""
    context: str = ""
    hashtags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    instagram_caption: str = ""
    pinned_comment: str = ""


class Metadata(BaseModel):
    """Complete packaged metadata artifact (07 s1)."""

    schema_version: int = 1
    clip_id: str
    titles: list[TitleOption]
    hook_line: str
    context: str
    hashtags: list[str]
    keywords: list[str]
    instagram_caption: str
    pinned_comment: str
    credit_block: str
    description_youtube: str
    description_instagram: str
    tags_youtube: str
    risk: str = "low"
    risk_flags: list[str] = Field(default_factory=list)
    source_risk_notes: str = ""
    thumbnail: dict[str, Any] = Field(default_factory=dict)


def _clean_title(text: str, max_chars: int = 70) -> str:
    """Clean, format, and truncate title to word boundary <= max_chars without trailing punctuation."""
    t = text.strip().strip("\"'").strip()
    # Mask profanity if any
    prof_file = paths.config_dir() / "profanity.yaml"
    if prof_file.is_file():
        import yaml
        try:
            data = yaml.safe_load(prof_file.read_text(encoding="utf-8")) or {}
            for w in data.get("words", []):
                t = re.sub(rf"\b{re.escape(w)}\b", w[0] + "*" * (len(w) - 1), t, flags=re.IGNORECASE)
        except Exception:
            pass

    # At most one ! and at most one ? across the entire title (07 s2)
    t = re.sub(r"!+", "!", t)
    t = re.sub(r"\?+", "?", t)
    while t.count("!") > 1:
        t = t.replace("!", "", 1)
    while t.count("?") > 1:
        t = t.replace("?", "", 1)

    if len(t) <= max_chars:
        return t

    # Truncate at word boundary
    truncated = t[:max_chars]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip(".,!?:;\"' ")


def validate_and_fix_metadata(
    raw: RawMetadataOut,
    clip: Clip,
    source_info: SourceInfo,
    domain: str = "general",
) -> Metadata:
    """Validate titles, hashtags, length constraints, and assemble YouTube/Instagram descriptions."""
    # 1. Validate & fix titles (exactly 3 options)
    clean_titles: list[TitleOption] = []
    seen_texts: set[str] = set()

    part_suffix = f" (Part {clip.part_index}/{clip.part_total})" if (clip.part_index and clip.part_total and clip.part_total > 1) else ""

    for opt in raw.titles:
        c_text = _clean_title(opt.text, max_chars=70)
        if part_suffix and not c_text.endswith(part_suffix):
            c_text = f"{c_text[:70 - len(part_suffix)]}{part_suffix}"
        if c_text and c_text.lower() not in seen_texts:
            seen_texts.add(c_text.lower())
            clean_titles.append(TitleOption(style=opt.style, text=c_text))

    # Fallback titles if less than 3
    topic_label = clip.topic or "Moment"
    fallback_titles = [
        TitleOption(style="curiosity", text=_clean_title(clip.hook_text or f"{topic_label.title()} - What Happened") + part_suffix),
        TitleOption(style="direct", text=_clean_title(f"{topic_label.title()} Highlight") + part_suffix),
        TitleOption(style="bold", text=_clean_title(f"The Craziest {topic_label.title()}") + part_suffix),
    ]
    for fb in fallback_titles:
        if len(clean_titles) >= 3:
            break
        if fb.text.lower() not in seen_texts:
            seen_texts.add(fb.text.lower())
            clean_titles.append(fb)
    clean_titles = clean_titles[:3]

    # 2. Hook line & context
    hook_line = (raw.hook_line or clip.hook_text or "Check out this crazy moment!").strip()
    if len(hook_line) > 110:
        hook_line = hook_line[:110].rsplit(" ", 1)[0]

    context = (raw.context or "An incredible sequence that viewers need to see.").strip()

    # 3. Hashtags (4-5 items, clean #[a-z0-9_]+)
    clean_hashtags: list[str] = []
    seen_tags: set[str] = set()
    for h in raw.hashtags:
        tag = h.strip().lower()
        if not tag.startswith("#"):
            tag = f"#{tag}"
        tag = re.sub(r"[^#a-z0-9_]", "", tag)
        if len(tag) > 1 and tag not in seen_tags:
            seen_tags.add(tag)
            clean_hashtags.append(tag)

    # Ensure #shorts is present
    if "#shorts" not in seen_tags:
        clean_hashtags.insert(0, "#shorts")
    if domain == "gta6" and "#gta6" not in seen_tags:
        clean_hashtags.append("#gta6")
    elif "#viral" not in seen_tags:
        clean_hashtags.append("#viral")
    clean_hashtags = clean_hashtags[:5]

    # 4. Keywords & YouTube tags (<= 450 chars total)
    clean_keywords: list[str] = []
    seen_kw: set[str] = set()
    for kw in raw.keywords:
        c_kw = kw.strip()
        if c_kw and len(c_kw) <= 30 and c_kw.lower() not in seen_kw:
            seen_kw.add(c_kw.lower())
            clean_keywords.append(c_kw)

    # Add domain defaults if needed
    if domain == "gta6":
        for default_kw in ["GTA 6", "GTA VI", "Grand Theft Auto 6", "Vice City"]:
            if default_kw.lower() not in seen_kw:
                clean_keywords.append(default_kw)
                seen_kw.add(default_kw.lower())
    else:
        for default_kw in ["shorts", "viral", "highlights", "trending"]:
            if default_kw.lower() not in seen_kw:
                clean_keywords.append(default_kw)
                seen_kw.add(default_kw.lower())

    # Build tags string
    tags_list: list[str] = []
    curr_len = 0
    for kw in clean_keywords:
        kw_len = len(kw) + (1 if tags_list else 0)
        if curr_len + kw_len <= 450:
            tags_list.append(kw)
            curr_len += kw_len
        else:
            break
    tags_youtube = ",".join(tags_list)

    # 5. Build credit blocks & descriptions
    credit_yt = build_credit_block(source_info, clip, short=False)
    credit_ig = build_credit_block(source_info, clip, short=True)

    part_callout = (
        f"Part {clip.part_index + 1} is on the channel ▶\n\n"
        if (clip.part_index and clip.part_total and clip.part_index < clip.part_total)
        else ""
    )

    hashtags_str = " ".join(clean_hashtags)
    desc_yt = f"{hook_line}\n{context}\n\n{part_callout}{credit_yt}\n\n{hashtags_str}"

    ig_caption = (raw.instagram_caption or f"{hook_line} {hashtags_str}").strip()
    if len(ig_caption) > 150:
        ig_caption = ig_caption[:150].rsplit(" ", 1)[0]
    desc_ig = f"{ig_caption}\n\n{part_callout}{credit_ig}\n\n{hashtags_str}"

    pinned = (raw.pinned_comment or "What was your favorite moment in this clip?").strip()

    return Metadata(
        schema_version=1,
        clip_id=clip.id,
        titles=clean_titles,
        hook_line=hook_line,
        context=context,
        hashtags=clean_hashtags,
        keywords=clean_keywords,
        instagram_caption=ig_caption,
        pinned_comment=pinned,
        credit_block=credit_yt,
        description_youtube=desc_yt,
        description_instagram=desc_ig,
        tags_youtube=tags_youtube,
        risk=clip.risk or "low",
        risk_flags=clip.risk_flags or [],
    )


def fallback_metadata(clip: Clip, source_info: SourceInfo, domain: str = "general") -> Metadata:
    """Template-based metadata fallback when Gemini fails validation or quota."""
    topic = clip.topic or "Highlight"
    hook = clip.hook_text or f"{topic.title()} - what happened"
    raw = RawMetadataOut(
        titles=[
            TitleOption(style="curiosity", text=hook),
            TitleOption(style="direct", text=f"{topic.title()} Highlight"),
            TitleOption(style="bold", text=f"Unbelievable {topic.title()} Revealed"),
        ],
        hook_line=hook[:100],
        context=f"A closer look at {topic} from the latest video.",
        hashtags=["#shorts", "#viral", "#trending", f"#{domain}" if domain != "general" else "#highlight"],
        keywords=["shorts", "viral", "clip", "highlight", topic],
        instagram_caption="Crazy moment! Drop your thoughts below. #shorts #viral",
        pinned_comment="What do you think of this moment?",
    )
    return validate_and_fix_metadata(raw, clip=clip, source_info=source_info, domain=domain)


def generate_metadata(
    ctx: JobContext,
    clip: Clip,
    source_info: SourceInfo,
    domain_description: str | None = None,
) -> Metadata:
    """Generate high-performing titles, SEO, and copy sheets via Gemini or fallback."""
    settings = getattr(ctx, "settings", None)
    domain = getattr(settings, "project_domain", "general") if settings else "general"
    if domain_description is None:
        domain_description = f"{domain.title()} & Video Entertainment" if domain != "general" else "Viral Short-Form Video & Entertainment"

    prompt_file = paths.prompts_dir() / "metadata_text.md"
    prompt_template = prompt_file.read_text(encoding="utf-8")

    part_info = f"Part {clip.part_index}/{clip.part_total}" if clip.part_index else "Standalone"
    entities = getattr(clip, "entities", None)
    entities_str = ", ".join(entities) if entities else domain

    # Read transcript tidy for the clip segment
    clip_text = clip.hook_text or ""
    try:
        words_art = ctx.read_artifact(f"clips/{clip.id}/words.json")
        if words_art and "words" in words_art:
            clip_text = " ".join([w.get("w", "") for w in words_art["words"]])
    except Exception:
        pass

    prompt = (
        prompt_template.replace("{{domain_description}}", domain_description)
        .replace("{{topic}}", clip.topic or "Viral highlight")
        .replace("{{entities}}", entities_str)
        .replace("{{part_info}}", part_info)
        .replace("{{clip_text}}", clip_text[:800])
    )

    try:
        raw_out = ctx.gemini.generate_json(
            prompt,
            schema_model=RawMetadataOut,
            system_instruction="You write viral YouTube Shorts metadata.",
            task="metadata",
        )
        return validate_and_fix_metadata(raw_out, clip=clip, source_info=source_info, domain=domain)
    except Exception as e:
        logger.warning("[%s] Gemini metadata generation failed: %s; using template fallback", ctx.job_id, e)
        return fallback_metadata(clip=clip, source_info=source_info, domain=domain)
