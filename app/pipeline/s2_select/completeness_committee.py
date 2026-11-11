"""Layer 4 Completeness Committee: Two-judge cross-family completeness evaluation and boundary repair loop."""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.schemas import Candidate, Sentence

logger = logging.getLogger("app.pipeline.s2_select.completeness_committee")


class CompletenessVerdict(BaseModel):
    understandable_cold: bool = Field(default=True, description="Understood by cold viewer without seeing full video")
    starts_cleanly: bool = Field(default=True, description="Starts at complete thought without dangling pronouns")
    ends_on_finished_thought: bool = Field(default=True, description="Ends on completed thought or payoff beat")
    dangling_references: list[str] = Field(default_factory=list, description="List of unexplained pronouns at opening")
    missing_context: str = Field(default="", description="Description of any missing setup")
    ending_type: Literal["resolution", "punchline", "conclusion", "cliffhanger", "abrupt"] = Field(
        default="resolution", description="Type of clip ending beat"
    )
    verdict: Literal["pass", "extend_end", "extend_start", "reject"] = Field(
        default="pass", description="Completeness verdict"
    )


def build_committee_prompt(
    sentences: list[Sentence],
    start_sid: int,
    end_sid: int,
    allow_cliffhanger: bool = False,
) -> str:
    """Build standardized prompt for completeness judge showing candidate plus next 3 sentences."""
    cand_lines: list[str] = []
    for sid in range(start_sid, min(end_sid + 1, len(sentences))):
        s = sentences[sid]
        cand_lines.append(f"[{s.id}] {s.text}")

    after_lines: list[str] = []
    for sid in range(end_sid + 1, min(len(sentences), end_sid + 4)):
        s = sentences[sid]
        after_lines.append(f"(what comes after the clip) [{s.id}] {s.text}")

    cliffhanger_instruction = (
        "This candidate is evaluated for a multi-part series; intentional cliffhangers (unanswered dramatic questions, impending danger) are VALID endings."
        if allow_cliffhanger
        else "A complete standalone short must have a clear resolution, punchline, or conclusion. An abrupt cutoff or cliffhanger without payoff should be extended or rejected."
    )

    return f"""You are a strict short-form video completeness judge. Assess if this clip is self-contained and complete in meaning.

Rules:
1. Cold viewer test: Does a viewer scrolling by understand who/what is happening without having seen prior context?
2. Starts cleanly: Does it begin at the start of a clear thought, or does it start on an unexplained pronoun ("he did that", "so this happened")?
3. Thought completion test: Did the speaker finish their thought by the end of the candidate text, or does the thought cut off mid-idea and continue into the sentences that come after the clip?
4. {cliffhanger_instruction}

CANDIDATE SENTENCES:
{chr(10).join(cand_lines)}

SENTENCES AFTER THE CLIP:
{chr(10).join(after_lines) if after_lines else "(End of video)"}

Decide:
- understandable_cold: true if self-explanatory, false if baffling without previous context.
- starts_cleanly: true if opening is natural, false if dangling pronoun.
- ends_on_finished_thought: true if the ending beat feels complete.
- dangling_references: list of unexplained pronouns or names if any.
- missing_context: brief explanation if context is missing.
- ending_type: "resolution" | "punchline" | "conclusion" | "cliffhanger" | "abrupt"
- verdict:
    "pass": thought is finished and clip is self-contained.
    "extend_end": the thought trails off and completes in the sentences after the clip.
    "extend_start": the opening needs the sentence immediately preceding it.
    "reject": incoherent, rambling, or cannot be made standalone.
"""


def evaluate_judge(
    sentences: list[Sentence],
    start_sid: int,
    end_sid: int,
    model_name: str,
    llm_client: Any,
    allow_cliffhanger: bool = False,
) -> CompletenessVerdict:
    """Run a single completeness judge pass on a candidate range."""
    prompt = build_committee_prompt(sentences, start_sid, end_sid, allow_cliffhanger=allow_cliffhanger)

    if llm_client is not None and hasattr(llm_client, "provider"):
        try:
            res_dict = llm_client.provider.generate_json(
                task="completeness_judge",
                prompt=prompt,
                schema=CompletenessVerdict.model_json_schema(),
                model=model_name,
                keep_alive=0,
                temperature=0.1,
            )
            return CompletenessVerdict.model_validate(res_dict)
        except Exception as exc:
            logger.warning("Judge %s failed: %s; using heuristic fallback", model_name, exc)

    # Heuristic fallback if local LLM call fails
    cand_sents = sentences[start_sid : min(end_sid + 1, len(sentences))]
    first_text = cand_sents[0].text.strip() if cand_sents else ""
    last_text = cand_sents[-1].text.strip() if cand_sents else ""

    first_word = first_text.split()[0].lower().rstrip(",.?!") if first_text else ""
    last_word = last_text.split()[-1].lower().rstrip(",.?!") if last_text else ""

    dangling = ["he", "she", "they", "it", "this", "that", "these", "those"]
    disallowed_tails = ["and", "but", "so", "because", "to", "the", "like", "um", "uh", "you know"]

    starts_clean = first_word not in dangling
    ends_clean = last_word not in disallowed_tails and (last_text.endswith((".", "!", "?")) or len(cand_sents) >= 2)

    verdict_val: Literal["pass", "extend_end", "extend_start", "reject"] = "pass"
    if not ends_clean:
        verdict_val = "extend_end"
    elif not starts_clean:
        verdict_val = "extend_start"

    return CompletenessVerdict(
        understandable_cold=starts_clean,
        starts_cleanly=starts_clean,
        ends_on_finished_thought=ends_clean,
        ending_type="resolution" if ends_clean else "abrupt",
        verdict=verdict_val,
    )


def run_completeness_committee(
    candidate: Candidate | dict[str, Any],
    sentences: list[Sentence],
    llm_client: Any,
    max_clip_s: float = 90.0,
    max_repairs: int = 2,
    allow_cliffhanger: bool = False,
    judge_model_1: str = "qwen3.5:9b",
    judge_model_2: str = "gemma4:e4b",
) -> tuple[bool, int, int, dict[str, Any]]:
    """Run two-judge cross-family completeness committee with boundary repair loop (L4 & L6).

    Returns:
        (passed: bool, final_start_sid: int, final_end_sid: int, committee_details: dict)
    """
    if hasattr(candidate, "start_sid"):
        start_sid = int(candidate.start_sid)
    elif isinstance(candidate, dict):
        start_sid = int(candidate.get("start_sid", 0))
    else:
        start_sid = int(getattr(candidate, "start_sid", 0))

    if hasattr(candidate, "end_sid"):
        end_sid = int(candidate.end_sid)
    elif isinstance(candidate, dict):
        end_sid = int(candidate.get("end_sid", len(sentences) - 1))
    else:
        end_sid = int(getattr(candidate, "end_sid", len(sentences) - 1))
    sid_map = {s.id: s for s in sentences}

    repair_count = 0
    committee_history: list[dict[str, Any]] = []

    while repair_count <= max_repairs:
        # Check current duration
        if start_sid not in sid_map or end_sid not in sid_map or start_sid > end_sid:
            return False, start_sid, end_sid, {"error": "Invalid sentence IDs"}

        dur = sid_map[end_sid].e - sid_map[start_sid].s
        if dur > max_clip_s:
            logger.info("Candidate %s exceeded max_clip_s (%.1fs > %.1fs) during repair", getattr(candidate, "cid", "clip"), dur, max_clip_s)
            return False, start_sid, end_sid, {"reason": "exceeded_max_clip_seconds", "history": committee_history}

        # Judge 1 (Qwen family)
        v1 = evaluate_judge(
            sentences,
            start_sid,
            end_sid,
            model_name=judge_model_1,
            llm_client=llm_client,
            allow_cliffhanger=allow_cliffhanger,
        )

        # Judge 2 (Gemma family)
        v2 = evaluate_judge(
            sentences,
            start_sid,
            end_sid,
            model_name=judge_model_2,
            llm_client=llm_client,
            allow_cliffhanger=allow_cliffhanger,
        )

        step_record = {
            "attempt": repair_count,
            "start_sid": start_sid,
            "end_sid": end_sid,
            "duration": round(dur, 2),
            "judge_1": v1.model_dump(),
            "judge_2": v2.model_dump(),
        }
        committee_history.append(step_record)

        # Agreement check: both must pass
        if v1.verdict == "pass" and v2.verdict == "pass":
            return True, start_sid, end_sid, {
                "verdict": "pass",
                "repairs": repair_count,
                "judge_1": v1.model_dump(),
                "judge_2": v2.model_dump(),
                "history": committee_history,
            }

        # If both explicitly reject, stop immediately
        if v1.verdict == "reject" and v2.verdict == "reject":
            return False, start_sid, end_sid, {
                "verdict": "reject",
                "reason": "both_judges_rejected",
                "history": committee_history,
            }

        # Check if repair is possible
        if repair_count >= max_repairs:
            break

        # Boundary repair logic:
        # 1. If either judge requested extend_end
        extended = False
        if (v1.verdict == "extend_end" or v2.verdict == "extend_end") and end_sid + 1 < len(sentences):
            end_sid += 1
            extended = True

        # 2. If either judge requested extend_start
        if (v1.verdict == "extend_start" or v2.verdict == "extend_start") and start_sid > 0:
            start_sid -= 1
            extended = True

        if not extended:
            # Cannot extend further in requested direction
            break

        repair_count += 1
        logger.info("Completeness committee repair %d for %s: new range [%d, %d]", repair_count, getattr(candidate, "cid", "clip"), start_sid, end_sid)

    return False, start_sid, end_sid, {
        "verdict": "disagreement_or_unresolved",
        "repairs": repair_count,
        "history": committee_history,
    }
