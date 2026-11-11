"""Multi-part story splitting for long continuous moments."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.core.schemas import Clip, Sentence
from app.utils.timecode import fmt_hms

logger = logging.getLogger("app.pipeline.s2_select.part_splitter")


class StoryPartRaw(BaseModel):
    part_index: int
    start_sid: int
    end_sid: int
    cliffhanger_text: str = ""
    cliffhanger_type: str = "cliffhanger"
    cliffhanger_reason: str = ""
    recap_line: str | None = None
    hook_text: str = ""


class PartSplitOut(BaseModel):
    parts: list[StoryPartRaw] = Field(default_factory=list)


def split_story(
    clip: Clip,
    sentences: list[Sentence],
    gemini_client: Any,
    max_parts: int = 4,
) -> list[Clip]:
    """Split a story clip into sequential standalone part clips (Part 1/2/3).

    Enforces Task C strict part-splitting rules:
    - Split ONLY if genuine cliffhanger exists (cliffhanger | tension_peak | pending_reveal | question_posed).
    - 'Time ran out' is never a reason.
    - Each part is at least 25s; at most 4 parts.
    """
    # Filter sentences within clip boundary
    clip_sentences = [s for s in sentences if s.s >= clip.start - 1.0 and s.e <= clip.end + 1.0]
    if len(clip_sentences) < 4:
        return [clip]

    story_lines: list[str] = []
    for s in clip_sentences:
        story_lines.append(f"[{s.id}] {fmt_hms(s.s)} {s.text}")
    story_block = "\n".join(story_lines)

    from app.core.paths import prompts_dir

    prompt_template = (prompts_dir() / "plan_parts.md").read_text(encoding="utf-8")
    filled_prompt = (
        prompt_template.replace("{{max_parts}}", str(min(4, max_parts))).replace("{{story_block}}", story_block)
    )

    try:
        res: PartSplitOut = gemini_client.generate_json(
            filled_prompt,
            PartSplitOut,
            temperature=0.2,
        )
    except Exception as e:
        logger.warning("Part split LLM call failed (%s); keeping single clip", e)
        return [clip]

    raw_parts = res.parts
    if len(raw_parts) < 2:
        return [clip]

    # Validate part boundaries and cliffhanger validity
    sid_map = {s.id: s for s in sentences}
    valid_parts: list[StoryPartRaw] = []
    prev_end_sid = -1
    valid_cliffhangers = {"cliffhanger", "tension_peak", "pending_reveal", "question_posed", "resolution"}

    for idx, p in enumerate(raw_parts):
        if p.start_sid <= prev_end_sid or p.start_sid > p.end_sid:
            continue

        s_obj = sid_map.get(p.start_sid)
        e_obj = sid_map.get(p.end_sid)
        if not s_obj or not e_obj:
            continue

        p_dur = e_obj.e - s_obj.s
        # Each part must be at least 25 seconds
        if p_dur < 24.5:
            logger.info("Part %d rejected: duration %.1fs < 25s; aborting split", p.part_index, p_dur)
            return [clip]

        # Non-final parts must end on a valid cliffhanger
        if idx < len(raw_parts) - 1:
            reason_lower = (p.cliffhanger_reason or "").lower()
            if "time ran out" in reason_lower or "ran out of time" in reason_lower:
                logger.info("Part %d rejected: 'time ran out' is not a valid cliffhanger; aborting split", p.part_index)
                return [clip]
            if p.cliffhanger_type not in valid_cliffhangers:
                logger.info("Part %d rejected: invalid cliffhanger type '%s'; aborting split", p.part_index, p.cliffhanger_type)
                return [clip]

        valid_parts.append(p)
        prev_end_sid = p.end_sid

    if len(valid_parts) < 2:
        return [clip]

    part_clips: list[Clip] = []
    n_parts = len(valid_parts)

    for i, p in enumerate(valid_parts):
        part_idx = i + 1
        s_obj = sid_map.get(p.start_sid)
        e_obj = sid_map.get(p.end_sid)
        if not s_obj or not e_obj:
            continue

        p_start = round(s_obj.s, 3)
        p_end = round(e_obj.e, 3)
        p_dur = round(p_end - p_start, 3)

        # Child ID: c01p1, c01p2, etc.
        child_id = f"{clip.id}p{part_idx}"
        child_final = max(0.0, clip.final_score - (0.0 if part_idx == 1 else 3.0))

        # Tier calculation
        tier = "A" if child_final >= 80.0 else ("B" if child_final >= 70.0 else "C")

        part_clips.append(
            Clip(
                id=child_id,
                parent_id=clip.id,
                part_index=part_idx,
                part_total=n_parts,
                start=p_start,
                end=p_end,
                duration=p_dur,
                tier=tier,
                final_score=child_final,
                llm_score=clip.llm_score,
                heat=clip.heat,
                audio=clip.audio,
                speech_ratio=clip.speech_ratio,
                hook_text=p.hook_text or clip.hook_text,
                topic=clip.topic,
                risk=clip.risk,
                risk_flags=clip.risk_flags,
                needs_context=False,
                context_fix=None,
                recap_line=p.recap_line if part_idx > 1 else None,
            )
        )

    return part_clips if len(part_clips) >= 2 else [clip]
