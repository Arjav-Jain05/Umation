"""Layer 3 Critic and Arc Stitcher: Deep critical review with thinking mode and story arc grouping."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("app.pipeline.s2_select.critic")


class CriticEvaluation(BaseModel):
    cid: str
    hook_strength: float = Field(default=7.0, ge=0.0, le=10.0, description="Strength of first 3s hook")
    standalone_clarity: float = Field(default=8.0, ge=0.0, le=10.0, description="Makes sense alone without setup")
    payoff_delivery: float = Field(default=7.5, ge=0.0, le=10.0, description="Clear ending beat or punchline")
    boring_setup: bool = Field(default=False, description="Has unnecessary dead footage or slow intro")
    compliance_clean: bool = Field(default=True, description="No platform violations")
    critique_notes: str = ""


class CriticBatchOutput(BaseModel):
    evaluations: list[CriticEvaluation] = Field(default_factory=list)


def evaluate_critic_candidate(
    cand: dict[str, Any],
    llm_client: Any = None,
) -> tuple[float, CriticEvaluation]:
    """Critique a candidate clip using critical thinking questions.

    Returns:
        (critic_score_0_to_100, evaluation_object)
    """
    if llm_client is not None and hasattr(llm_client, "generate_json"):
        prompt = (
            "You are a rigorous short-form video critic. Critique this potential short:\n"
            f"ID: {cand.get('cid', 'c01')}\n"
            f"Hook: \"{cand.get('hook_text', '')}\"\n"
            f"Topic: {cand.get('topic', '')}\n"
            f"Duration: {cand.get('duration', 30):.1f}s\n"
            f"Text: \"{cand.get('text', '')[:300]}\"\n\n"
            "Assess:\n"
            "1. Hook strength (0-10): does the first 3s immediately hook curiosity or shock?\n"
            "2. Standalone clarity (0-10): does a viewer scrolling by understand what is happening?\n"
            "3. Payoff (0-10): is there a satisfying punchline, stunt climax, or ending beat?\n"
            "4. Boring setup: does it waste more than 5s on dead setup before action?\n"
            "5. Platform compliance: is it clean of TOS violations?\n"
        )
        try:
            res: CriticEvaluation = llm_client.generate_json(
                prompt,
                CriticEvaluation,
                task="critic",
                temperature=0.3,
            )
            # Compute composite critic score
            base = (
                res.hook_strength * 3.5
                + res.standalone_clarity * 3.0
                + res.payoff_delivery * 3.5
            )
            if res.boring_setup:
                base -= 15.0
            if not res.compliance_clean:
                base -= 30.0
            critic_score = round(max(20.0, min(100.0, base)), 1)
            return critic_score, res
        except Exception as exc:
            logger.debug(f"LLM critic call failed: {exc}; using heuristic critique")

    # Heuristic critic fallback
    hook_len = len(str(cand.get("hook_text", "")).split())
    hook_st = 8.5 if 2 <= hook_len <= 7 else 6.0
    clarity = 8.0 if not cand.get("needs_context", False) else 5.0
    payoff = 7.5
    dur = float(cand.get("duration", 30.0))
    boring = dur > 65.0 and not cand.get("is_story", False)

    base = hook_st * 3.5 + clarity * 3.0 + payoff * 3.5
    if boring:
        base -= 10.0
    critic_score = round(max(30.0, min(100.0, base)), 1)

    eval_obj = CriticEvaluation(
        cid=cand.get("cid", "c01"),
        hook_strength=hook_st,
        standalone_clarity=clarity,
        payoff_delivery=payoff,
        boring_setup=boring,
        compliance_clean=True,
        critique_notes="Heuristic critic review passed",
    )
    return critic_score, eval_obj


def stitch_story_arcs(
    candidates: list[dict[str, Any]],
    max_parts: int = 3,
) -> list[dict[str, Any]]:
    """Group connected story candidates into Part 1/2/3 multi-part splits."""
    if len(candidates) <= 1:
        return candidates

    stitched: list[dict[str, Any]] = []
    # Group by identical or closely matching topic/story
    topic_groups: dict[str, list[dict[str, Any]]] = {}
    for c in candidates:
        top = str(c.get("topic", "")).strip().lower()
        if not top or top == "general":
            stitched.append(c)
        else:
            if top not in topic_groups:
                topic_groups[top] = []
            topic_groups[top].append(c)

    for _top, group in topic_groups.items():
        if len(group) == 1 or not any(c.get("is_story", False) for c in group):
            stitched.extend(group)
            continue

        # Sort chronologically by start time
        sorted_group = sorted(group, key=lambda x: float(x.get("start", x.get("s", 0.0))))
        parts_to_assign = sorted_group[:max_parts]
        total_p = len(parts_to_assign)

        parent_id = parts_to_assign[0].get("id", parts_to_assign[0].get("cid", "part_story"))
        for p_idx, part in enumerate(parts_to_assign):
            part_copy = dict(part)
            part_copy["parent_id"] = parent_id
            part_copy["part_index"] = p_idx + 1
            part_copy["part_total"] = total_p
            # Add Part prefix to hook text
            orig_hook = part_copy.get("hook_text", "")
            part_copy["hook_text"] = f"Part {p_idx + 1}/{total_p}: {orig_hook}"
            stitched.append(part_copy)

        # Append remaining candidates in group as single clips
        if len(sorted_group) > max_parts:
            stitched.extend(sorted_group[max_parts:])

    return stitched
