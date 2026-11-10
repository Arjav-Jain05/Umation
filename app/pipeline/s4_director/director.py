"""AI Director: plans on-screen vertical video effects with Gemini or deterministic fallback."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.core import paths
from app.core.schemas import Clip, WordsArtifact
from app.pipeline.context import JobContext
from app.pipeline.s4_director import edit_schema, target_locator, tracker
from app.pipeline.s4_director.edit_schema import EditEvent, EditList

logger = logging.getLogger("app.pipeline.s4_director.director")


class ZoomPunchItem(BaseModel):
    t: float
    dur: float = 0.9
    scale: float = 1.12


class PointerItem(BaseModel):
    t: float
    dur: float = 1.8
    target_description: str


class EmojiItem(BaseModel):
    t: float
    emoji: str


class SfxItem(BaseModel):
    t: float
    name: str = "whoosh"


class DirectorOut(BaseModel):
    """Raw director suggestions from Gemini or rule-based fallback."""

    hook_text: str | None = None
    zoom_punches: list[ZoomPunchItem] = Field(default_factory=list)
    pointers: list[PointerItem] = Field(default_factory=list)
    emojis: list[EmojiItem] = Field(default_factory=list)
    caption_emphasis: list[int] = Field(default_factory=list)
    sfx: list[SfxItem] = Field(default_factory=list)


def _load_effects_config() -> dict[str, Any]:
    cfg_file = paths.config_dir() / "effects.yaml"
    if not cfg_file.is_file():
        return {}
    try:
        return yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def fallback_director(
    clip: Clip,
    words_art: WordsArtifact,
    cfg: dict[str, Any] | None = None,
    layout: str = "gameplay",
) -> EditList:
    """Deterministic rule-based director (06 s6) when Gemini fails or is disabled."""
    words = words_art.words
    dur = float(clip.duration or (clip.end - clip.start))
    events: list[EditEvent] = []

    # 1. Hook card
    hook_text = clip.hook_text or ""
    if not hook_text and words:
        first_few = [getattr(w, "w", getattr(w, "word", "")) for w in words[:6]]
        hook_text = " ".join(first_few).upper()
    if not hook_text:
        hook_text = "WATCH THIS"

    events.append(
        EditEvent(
            id="e01",
            type="hook_card",
            t=0.0,
            dur=2.4,
            params={"text": hook_text},
        )
    )
    events.append(
        EditEvent(
            id="e02",
            type="sfx",
            t=0.0,
            dur=0.35,
            params={"name": "whoosh", "gain_db": -12.0},
        )
    )

    # 2. Zoom punch: start of every 3rd sentence or every ~8s
    event_idx = 3
    last_zoom_t = -99.0
    for w_idx, w in enumerate(words):
        w_text = getattr(w, "w", getattr(w, "word", ""))
        if w_text.endswith((".", "!", "?")) and w_idx + 1 < len(words):
            next_start = getattr(words[w_idx + 1], "s_clip", getattr(words[w_idx + 1], "start", 0.0))
            if next_start - last_zoom_t >= 6.0 and next_start < dur - 2.0:
                events.append(
                    EditEvent(
                        id=f"e{event_idx:02d}",
                        type="zoom_punch",
                        t=round(next_start, 2),
                        dur=0.9,
                        params={"scale": 1.12, "anchor": "center"},
                    )
                )
                last_zoom_t = next_start
                event_idx += 1

    # 3. Caption emphasis: numbers and capitalized proper nouns
    emphasis_indices: list[int] = []
    for idx, w in enumerate(words):
        w_text = getattr(w, "w", getattr(w, "word", ""))
        clean_w = w_text.strip(".,!?:;\"'()[]")
        if clean_w.isdigit() or (clean_w.istitle() and len(clean_w) > 3):
            emphasis_indices.append(idx)
        if len(emphasis_indices) >= 8:
            break

    # 4. Part label & recap
    if clip.part_index and clip.part_total and clip.part_total > 1:
        events.append(
            EditEvent(
                id=f"e{event_idx:02d}",
                type="part_label",
                t=0.0,
                dur=dur,
                params={"text": f"PART {clip.part_index}/{clip.part_total}"},
            )
        )
        event_idx += 1
        if clip.part_index > 1:
            events.append(
                EditEvent(
                    id=f"e{event_idx:02d}",
                    type="recap_line",
                    t=0.0,
                    dur=2.0,
                    params={"text": "Previously: Part " + str(clip.part_index - 1)},
                )
            )
            event_idx += 1

    # 5. Progress bar
    events.append(
        EditEvent(
            id=f"e{event_idx:02d}",
            type="progress_bar",
            t=0.0,
            dur=dur,
            params={},
        )
    )

    raw_edit = EditList(
        schema_version=1,
        clip_id=clip.id,
        fps=30,
        duration=dur,
        layout=layout,
        caption_emphasis=emphasis_indices,
        events=events,
    )
    fixed, _ = edit_schema.validate_and_fix(raw_edit, words=words, cfg=cfg, layout=layout)
    return fixed


def plan_with_gemini(
    ctx: JobContext,
    clip: Clip,
    words_art: WordsArtifact,
    layout: str = "gameplay",
) -> DirectorOut:
    """Request effect plan suggestions from Gemini model."""
    prompt_file = paths.prompts_dir() / "director_edit_list.md"
    prompt_template = prompt_file.read_text(encoding="utf-8")

    words = words_art.words
    dur = float(clip.duration or (clip.end - clip.start))

    # Format words block
    words_lines = []
    for idx, w in enumerate(words):
        w_text = getattr(w, "w", getattr(w, "word", ""))
        w_start = getattr(w, "s_clip", getattr(w, "start", 0.0))
        words_lines.append(f"{idx}: {w_start:.2f}s - {w_text}")
    words_block = "\n".join(words_lines[:250])  # Cap tokens

    part_info = f"Part {clip.part_index}/{clip.part_total}" if clip.part_index else "Standalone"
    context_fix = clip.context_fix or ""
    hook_text = clip.hook_text or ""

    prompt = (
        prompt_template.replace("{{topic}}", clip.topic or "Highlight clip")
        .replace("{{domain_description}}", "Gaming & Entertainment vertical short")
        .replace("{{layout}}", layout)
        .replace("{{duration}}", f"{dur:.1f}")
        .replace("{{part_info}}", part_info)
        .replace("{{hook_text}}", hook_text)
        .replace("{{context_fix}}", context_fix)
        .replace("{{words_block}}", words_block)
    )

    try:
        data = ctx.gemini.call_json(prompt, schema=DirectorOut, system_instruction="You are a professional video editor.")
        return data
    except Exception as e:
        logger.warning("[%s] Gemini director planning failed: %s; falling back", ctx.job_id, e)
        # Empty DirectorOut triggers fallback logic
        return DirectorOut(hook_text=hook_text)


def build_edit_list(
    ctx: JobContext,
    clip: Clip,
    words_art: WordsArtifact,
    framed_mp4: Path,
    layout: str = "gameplay",
    enable_gemini: bool = True,
) -> EditList:
    """Build, track, validate and return the final complete EditList for a clip."""
    cfg = _load_effects_config()
    dur = float(clip.duration or (clip.end - clip.start))

    # Check if effects are disabled via options
    effects_enabled = getattr(ctx.options, "effects", True)
    if not effects_enabled:
        logger.info("[%s] Effects disabled by options for clip %s; emitting minimal edit list", ctx.job_id, clip.id)
        events = [EditEvent(id="e01", type="progress_bar", t=0.0, dur=dur, params={})]
        if clip.part_index and clip.part_total and clip.part_total > 1:
            events.append(EditEvent(id="e02", type="part_label", t=0.0, dur=dur, params={"text": f"PART {clip.part_index}/{clip.part_total}"}))
        return EditList(schema_version=1, clip_id=clip.id, fps=30, duration=dur, layout=layout, events=events)

    director_out: DirectorOut | None = None
    if enable_gemini:
        director_out = plan_with_gemini(ctx, clip, words_art, layout=layout)

    # If Gemini failed or produced no visual events, use fallback
    if not director_out or (not director_out.zoom_punches and not director_out.pointers and not director_out.hook_text):
        logger.info("[%s] Using fallback director for clip %s", ctx.job_id, clip.id)
        return fallback_director(clip, words_art, cfg=cfg, layout=layout)

    events: list[EditEvent] = []
    ev_idx = 1

    # 1. Hook card
    hook_text = director_out.hook_text or clip.hook_text or ""
    if hook_text:
        events.append(EditEvent(id=f"e{ev_idx:02d}", type="hook_card", t=0.0, dur=2.4, params={"text": hook_text}))
        ev_idx += 1
        events.append(EditEvent(id=f"e{ev_idx:02d}", type="sfx", t=0.0, dur=0.35, params={"name": "whoosh", "gain_db": -12.0}))
        ev_idx += 1

    # 2. Zoom punches
    for zp in director_out.zoom_punches:
        events.append(EditEvent(id=f"e{ev_idx:02d}", type="zoom_punch", t=zp.t, dur=zp.dur, params={"scale": zp.scale, "anchor": "center"}))
        ev_idx += 1

    # 3. Vision-located pointers (arrows + highlight boxes)
    temp_frames_dir = ctx.work_dir / "temp_frames"
    temp_frames_dir.mkdir(parents=True, exist_ok=True)

    for ptr in director_out.pointers:
        t_mid = ptr.t + (ptr.dur / 2.0)
        frame_jpeg = temp_frames_dir / f"{clip.id}_t_{t_mid:.2f}.jpg"
        try:
            target_locator.extract_frame(framed_mp4, t_mid, frame_jpeg)
            loc_box = target_locator.locate(frame_jpeg, ptr.target_description, ctx.gemini)
            if loc_box:
                # Track box over duration
                tracks = tracker.track_box(
                    framed_mp4,
                    t0=ptr.t,
                    dur=ptr.dur,
                    bbox=loc_box.as_list,
                    fps=30.0,
                    static=(layout != "gameplay"),
                )

                events.append(
                    EditEvent(
                        id=f"e{ev_idx:02d}",
                        type="arrow",
                        t=ptr.t,
                        dur=ptr.dur,
                        params={
                            "bbox": loc_box.as_list,
                            "track": tracks,
                            "label": loc_box.label,
                            "source": "vision",
                            "confidence": loc_box.confidence,
                        },
                    )
                )
                ev_idx += 1

                events.append(
                    EditEvent(
                        id=f"e{ev_idx:02d}",
                        type="highlight_box",
                        t=ptr.t,
                        dur=ptr.dur,
                        params={
                            "bbox": loc_box.as_list,
                            "track": tracks,
                        },
                    )
                )
                ev_idx += 1

                events.append(
                    EditEvent(
                        id=f"e{ev_idx:02d}",
                        type="sfx",
                        t=ptr.t,
                        dur=0.08,
                        params={"name": "pop", "gain_db": -10.0},
                    )
                )
                ev_idx += 1
        except Exception as e:
            logger.warning("[%s] Failed to locate pointer '%s': %s", ctx.job_id, ptr.target_description, e)

    # 4. Emojis
    for em in director_out.emojis:
        events.append(EditEvent(id=f"e{ev_idx:02d}", type="emoji_pop", t=em.t, dur=0.9, params={"emoji": em.emoji, "x": 820, "y": 700}))
        ev_idx += 1
        events.append(EditEvent(id=f"e{ev_idx:02d}", type="sfx", t=em.t, dur=0.08, params={"name": "pop", "gain_db": -12.0}))
        ev_idx += 1

    # 5. Part label & recap
    if clip.part_index and clip.part_total and clip.part_total > 1:
        events.append(EditEvent(id=f"e{ev_idx:02d}", type="part_label", t=0.0, dur=dur, params={"text": f"PART {clip.part_index}/{clip.part_total}"}))
        ev_idx += 1
        if clip.part_index > 1:
            events.append(EditEvent(id=f"e{ev_idx:02d}", type="recap_line", t=0.0, dur=2.0, params={"text": f"Previously: Part {clip.part_index - 1}"}))
            ev_idx += 1

    # 6. Progress bar
    events.append(EditEvent(id=f"e{ev_idx:02d}", type="progress_bar", t=0.0, dur=dur, params={}))
    ev_idx += 1

    # 7. Extra SFX from director
    for s in director_out.sfx:
        events.append(EditEvent(id=f"e{ev_idx:02d}", type="sfx", t=s.t, dur=0.35, params={"name": s.name, "gain_db": -12.0}))
        ev_idx += 1

    raw_edit = EditList(
        schema_version=1,
        clip_id=clip.id,
        fps=30,
        duration=dur,
        layout=layout,
        caption_emphasis=director_out.caption_emphasis,
        events=events,
    )

    fixed, msgs = edit_schema.validate_and_fix(raw_edit, words=words_art.words, cfg=cfg, layout=layout)
    for m in msgs:
        logger.debug("[%s] Edit list validator: %s", ctx.job_id, m)

    return fixed
