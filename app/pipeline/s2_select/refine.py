"""Deterministic candidate boundary clean-up: hook trim, tail trim, padding, and length fitting."""

from __future__ import annotations

import logging

from app.core.schemas import Candidate, Sentence
from app.utils.text import strip_punct

logger = logging.getLogger("app.pipeline.s2_select.refine")

HOOK_TRIM_PREFIXES = (
    "so",
    "um",
    "uh",
    "yeah",
    "okay",
    "ok",
    "alright",
    "well",
    "and",
    "but",
    "anyway",
    "right",
)

TAIL_TRIM_PREFIXES = (
    "thanks",
    "thank you",
    "anyway",
    "so yeah",
    "alright",
    "subscribe",
    "see you",
)


def refine_candidate(
    cand: Candidate,
    sentences: list[Sentence],
    max_clip_s: int = 60,
    is_story: bool = False,
) -> tuple[Candidate, bool] | None:
    """Refine candidate boundaries per spec 04 section 4. Returns (refined_candidate, is_story) or None."""
    start_sid = cand.start_sid
    end_sid = cand.end_sid
    hook_sid = cand.hook_sid

    if start_sid < 0 or end_sid >= len(sentences) or start_sid > end_sid:
        return None

    # Step 1: Initial bounds
    orig_start_t = sentences[start_sid].s
    total_trim_s = 0.0

    # Step 2: Hook trim (drop weak lead-in sentences, never drop hook_sid)
    while start_sid < end_sid and start_sid < hook_sid:
        s_obj = sentences[start_sid]
        words = s_obj.text.strip().split()
        first_token = strip_punct(words[0]).lower() if words else ""
        lead_starts_filler = any(first_token == p or s_obj.text.lower().startswith(p + " ") for p in HOOK_TRIM_PREFIXES)

        if len(words) < 4 or lead_starts_filler:
            next_start_t = sentences[start_sid + 1].s
            if (next_start_t - orig_start_t) < 8.0:
                total_trim_s += next_start_t - s_obj.s
                start_sid += 1
                continue
        break

    # Step 3: Tail trim (drop trailing wrap-up sentences)
    while end_sid > start_sid and end_sid > hook_sid:
        s_obj = sentences[end_sid]
        text_lower = s_obj.text.lower().strip()
        if any(text_lower.startswith(p) for p in TAIL_TRIM_PREFIXES):
            end_sid -= 1
            continue
        break

    s = sentences[start_sid].s
    e = sentences[end_sid].e

    # Step 4: Padding
    prev_end = sentences[start_sid - 1].e if start_sid > 0 else 0.0
    next_start = sentences[end_sid + 1].s if end_sid + 1 < len(sentences) else (e + 10.0)

    s_padded = max(prev_end, s - 0.15)
    e_padded = min(next_start, e + 0.35)
    dur = e_padded - s_padded

    # Step 5: Length fit
    story_flag = is_story
    if dur > max_clip_s and not story_flag:
        # Remove sentences from the start up to hook_sid
        while start_sid < hook_sid and (e_padded - sentences[start_sid].s) > max_clip_s:
            start_sid += 1

        s_padded = max(prev_end, sentences[start_sid].s - 0.15)
        dur = e_padded - s_padded

        if dur > max_clip_s:
            # Still too long because hook_sid is at start
            story_flag = True

    # Step 6: Minimum duration 15s
    if dur < 15.0:
        # Extend forward sentence by sentence if added sentences have wpm > 80
        curr_end_sid = end_sid
        while dur < 15.0 and curr_end_sid + 1 < len(sentences):
            next_s = sentences[curr_end_sid + 1]
            if next_s.wpm >= 80.0:
                curr_end_sid += 1
                e_padded = next_s.e + 0.35
                dur = e_padded - s_padded
            else:
                break
        end_sid = curr_end_sid

    if dur < 15.0:
        logger.debug("Candidate %s discarded: duration %.1fs < 15s minimum", cand.cid, dur)
        return None

    refined = Candidate(
        cid=cand.cid,
        chunk_id=cand.chunk_id,
        start_sid=start_sid,
        end_sid=end_sid,
        hook_sid=hook_sid,
        s=round(s_padded, 3),
        e=round(e_padded, 3),
        reason=cand.reason,
        llm_hint_score=cand.llm_hint_score,
    )
    return refined, story_flag
