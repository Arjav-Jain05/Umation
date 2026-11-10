"""Stage 2: Double-pass Gemini rubric judging for viral candidate scoring."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.core.paths import prompts_dir
from app.core.schemas import (
    Candidate,
    CandidatesArtifact,
    JudgedArtifact,
    JudgedItem,
    JudgedScores,
    Transcript,
)
from app.pipeline.context import JobContext
from app.pipeline.s2_select.refine import refine_candidate
from app.utils.timecode import fmt_hms

logger = logging.getLogger("app.pipeline.s2_select.judge")


class RawJudgeItem(BaseModel):
    cid: str
    scores: JudgedScores = Field(default_factory=JudgedScores)
    needs_context: bool = False
    context_fix: str | None = None
    is_story: bool = False
    topic: str = ""
    entities: list[str] = Field(default_factory=list)
    content_flags: list[str] = Field(default_factory=list)
    hook_text: str = ""
    reasons: dict[str, Any] = Field(default_factory=dict)


class JudgeBatchOut(BaseModel):
    results: list[RawJudgeItem] = Field(default_factory=list)


def _compute_llm_score(scores: JudgedScores, weights: dict[str, float]) -> float:
    return 10.0 * (
        weights.get("hook", 0.25) * scores.hook
        + weights.get("payoff", 0.20) * scores.payoff
        + weights.get("clarity", 0.15) * scores.clarity
        + weights.get("emotion", 0.15) * scores.emotion
        + weights.get("novelty", 0.10) * scores.novelty
        + weights.get("shareability", 0.10) * scores.shareability
        + weights.get("pace", 0.05) * scores.pace
    )


def run(ctx: JobContext) -> None:
    """Execute Stage 2: judge."""
    if ctx.artifact_ok("judged.json", JudgedArtifact):
        logger.info("[%s] judged.json already exists and validates; skipping judge", ctx.job_id)
        return

    transcript = ctx.read_artifact("transcript.json", Transcript)
    candidates_art = ctx.read_artifact("candidates.json", CandidatesArtifact)
    raw_candidates = candidates_art.candidates

    if not raw_candidates:
        ctx.write_artifact("judged.json", JudgedArtifact(items=[]))
        ctx.progress("judge", 1.0, "No candidate clips to judge")
        return

    # Refine candidate boundaries before judging
    refined_candidates: list[tuple[Candidate, bool]] = []
    for cand in raw_candidates:
        ref = refine_candidate(cand, transcript.sentences, max_clip_s=ctx.options.max_clip_s)
        if ref is not None:
            refined_candidates.append(ref)

    if not refined_candidates:
        ctx.write_artifact("judged.json", JudgedArtifact(items=[]))
        ctx.progress("judge", 1.0, "No candidates survived boundary refinement")
        return

    # Load scoring rubric weights
    import yaml

    scoring_path = ctx.settings.project_root / "config" / "scoring.yaml"
    with open(scoring_path, encoding="utf-8") as f:
        scoring_cfg = yaml.safe_load(f) or {}
    rubric_weights = scoring_cfg.get("rubric_weights", {})

    domain_desc = "GTA 6 clipping"
    glossary_terms: list[str] = []
    glossary_path = ctx.settings.project_root / "config" / "glossary_gta6.yaml"
    if glossary_path.exists():
        with open(glossary_path, encoding="utf-8") as f:
            gdata = yaml.safe_load(f) or {}
        domain_desc = str(gdata.get("domain_description", domain_desc))
        glossary_terms = [str(t) for t in gdata.get("terms", [])]

    prompt_template = (prompts_dir() / "judge_candidate.md").read_text(encoding="utf-8")

    batch_size = 6 if ctx.options.fast_mode else 4
    num_runs = 1 if ctx.options.fast_mode else 2

    # Group into batches
    batches: list[list[tuple[Candidate, bool]]] = [
        refined_candidates[i : i + batch_size] for i in range(0, len(refined_candidates), batch_size)
    ]

    all_judged_by_cid: dict[str, list[RawJudgeItem]] = {cand.cid: [] for cand, _ in refined_candidates}

    total_ops = len(batches) * num_runs
    op_counter = 0

    for run_idx in range(num_runs):
        for b_idx, batch in enumerate(batches):
            ctx.check_cancel()
            frac = min(0.95, op_counter / max(1, total_ops))
            ctx.progress(
                "judge",
                frac,
                f"Judging candidates pass {run_idx + 1}/{num_runs} (batch {b_idx + 1}/{len(batches)})...",
            )
            op_counter += 1

            # Format candidates block
            cand_blocks: list[dict[str, Any]] = []
            for cand, is_story in batch:
                c_lines: list[str] = []
                # 2 context sentences before
                for sid in range(max(0, cand.start_sid - 2), cand.start_sid):
                    c_lines.append(f"(context before) [{sid}] {fmt_hms(transcript.sentences[sid].s)} {transcript.sentences[sid].text}")
                # Candidate sentences
                for sid in range(cand.start_sid, min(cand.end_sid + 1, len(transcript.sentences))):
                    c_lines.append(f"[{sid}] {fmt_hms(transcript.sentences[sid].s)} {transcript.sentences[sid].text}")
                # 2 context sentences after
                for sid in range(cand.end_sid + 1, min(len(transcript.sentences), cand.end_sid + 3)):
                    c_lines.append(f"(context after) [{sid}] {fmt_hms(transcript.sentences[sid].s)} {transcript.sentences[sid].text}")

                cand_blocks.append({
                    "cid": cand.cid,
                    "start_time": fmt_hms(cand.s),
                    "end_time": fmt_hms(cand.e),
                    "is_story_hint": is_story,
                    "text_lines": c_lines,
                })

            filled = (
                prompt_template.replace("{{domain_description}}", domain_desc)
                .replace("{{glossary_terms}}", ", ".join(glossary_terms[:30]))
                .replace("{{candidates_block}}", json.dumps(cand_blocks, indent=2))
            )

            cache_key = f"judge_run{run_idx + 1}_" + "_".join(c.cid for c, _ in batch)
            try:
                out: JudgeBatchOut = ctx.gemini.generate_json(
                    filled,
                    JudgeBatchOut,
                    temperature=0.2,
                    cache_key=cache_key,
                )
                for item in out.results:
                    if item.cid in all_judged_by_cid:
                        all_judged_by_cid[item.cid].append(item)
            except Exception as e:
                logger.warning("Batch %d judge failed: %s", b_idx, e)

    # Average scores and merge runs
    final_judged_items: list[JudgedItem] = []
    cand_map = {c.cid: (c, story) for c, story in refined_candidates}

    for cid, runs_list in all_judged_by_cid.items():
        if not runs_list:
            continue
        c_obj, story_flag = cand_map[cid]

        # Average numeric scores
        avg_hook = sum(r.scores.hook for r in runs_list) / len(runs_list)
        avg_payoff = sum(r.scores.payoff for r in runs_list) / len(runs_list)
        avg_clarity = sum(r.scores.clarity for r in runs_list) / len(runs_list)
        avg_emotion = sum(r.scores.emotion for r in runs_list) / len(runs_list)
        avg_novelty = sum(r.scores.novelty for r in runs_list) / len(runs_list)
        avg_share = sum(r.scores.shareability for r in runs_list) / len(runs_list)
        avg_pace = sum(r.scores.pace for r in runs_list) / len(runs_list)

        avg_scores = JudgedScores(
            hook=round(avg_hook, 2),
            payoff=round(avg_payoff, 2),
            clarity=round(avg_clarity, 2),
            emotion=round(avg_emotion, 2),
            novelty=round(avg_novelty, 2),
            shareability=round(avg_share, 2),
            pace=round(avg_pace, 2),
        )

        llm_score = _compute_llm_score(avg_scores, rubric_weights)

        # Conservative consensus on needs_context: if any run needed context, require it
        needs_context = any(r.needs_context for r in runs_list)
        context_fix = next((r.context_fix for r in runs_list if r.context_fix), None)
        is_story = story_flag or any(r.is_story for r in runs_list)

        # Collect entities and flags
        first_run = runs_list[0]
        topic = first_run.topic or "GTA 6 Moment"
        hook_text = first_run.hook_text or c_obj.reason

        final_judged_items.append(
            JudgedItem(
                cid=cid,
                s=c_obj.s,
                e=c_obj.e,
                start_sid=c_obj.start_sid,
                end_sid=c_obj.end_sid,
                hook_text=hook_text,
                scores=avg_scores,
                needs_context=needs_context,
                context_fix=context_fix,
                is_story=is_story,
                topic=topic,
                entities=first_run.entities,
                content_flags=first_run.content_flags,
                reasons=first_run.reasons,
                llm_score=round(llm_score, 1),
                runs=len(runs_list),
            )
        )

    ctx.write_artifact("judged.json", JudgedArtifact(items=final_judged_items))
    ctx.progress("judge", 1.0, f"Rubric judging complete: {len(final_judged_items)} items scored")
