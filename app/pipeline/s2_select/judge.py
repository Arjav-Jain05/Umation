"""Stage 2: Double-pass Gemini rubric judging for viral candidate scoring."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.core.errors import AppError
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
from app.pipeline.s2_select.completeness_committee import run_completeness_committee
from app.pipeline.s2_select.refine import refine_candidate
from app.pipeline.sensors.visual_evidence import check_candidate_visual_integrity
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

    # Layer 4 Completeness Committee + Layer 6 Boundary Repair + Layer 5 Visual Check
    committee_passed_candidates: list[tuple[Candidate, bool, dict[str, Any]]] = []
    proxy_path = ctx.work_dir / "proxy.mp4"
    video_path = proxy_path if proxy_path.is_file() else (ctx.work_dir / "source.mp4")

    for cand, is_story in refined_candidates:
        c_passed, f_start_sid, f_end_sid, comm_data = run_completeness_committee(
            cand,
            transcript.sentences,
            llm_client=ctx.llm,
            max_clip_s=ctx.options.max_clip_s,
            allow_cliffhanger=is_story,
            judge_model_1=ctx.settings.llm_proposer_model_1,
            judge_model_2=ctx.settings.llm_proposer_model_2,
        )
        if not c_passed:
            logger.info("Candidate %s rejected by Completeness Committee: %s", cand.cid, comm_data.get("verdict"))
            continue

        cand.start_sid = f_start_sid
        cand.end_sid = f_end_sid
        cand.s = transcript.sentences[f_start_sid].s
        cand.e = transcript.sentences[f_end_sid].e

        # Layer 5 Visual Check
        v_passed, _v_start, _v_end, v_reason = check_candidate_visual_integrity(
            video_path if video_path.is_file() else None,
            cand.s,
            cand.e,
        )
        if not v_passed:
            logger.info("Candidate %s rejected by Visual Check: %s", cand.cid, v_reason)
            continue

        comm_data["visual_reason"] = v_reason
        committee_passed_candidates.append((cand, is_story, comm_data))

    if not committee_passed_candidates:
        logger.warning(
            "[%s] Zero candidates survived strict completeness committee; using refined candidates with review flag",
            ctx.job_id,
        )
        candidates_to_judge = [(c, s) for c, s in refined_candidates]
        committee_meta = {c.cid: {} for c, _ in refined_candidates}
    else:
        candidates_to_judge = [(c, s) for c, s, _ in committee_passed_candidates]
        committee_meta = {c.cid: meta for c, _, meta in committee_passed_candidates}

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

    is_fast = bool(getattr(ctx.options, "fast_mode", False) or getattr(ctx.options, "fast_lane", False))
    batch_size = 6 if is_fast else 4
    num_runs = 1 if is_fast else 2

    # Group into batches
    batches: list[list[tuple[Candidate, bool]]] = [
        candidates_to_judge[i : i + batch_size] for i in range(0, len(candidates_to_judge), batch_size)
    ]

    all_judged_by_cid: dict[str, list[RawJudgeItem]] = {cand.cid: [] for cand, _ in candidates_to_judge}

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
            except ConnectionError as ce:
                raise AppError(
                    code="OLLAMA_OFFLINE",
                    message=str(ce),
                    hint="Start Ollama in PowerShell: $env:OLLAMA_MODELS = 'D:\\Open_Source_Weights\\ollama'; ollama serve",
                ) from ce
            except Exception as e:
                logger.warning("Batch %d judge failed: %s", b_idx, e)

    # Average scores and merge runs
    final_judged_items: list[JudgedItem] = []
    cand_map = {c.cid: (c, story) for c, story in candidates_to_judge}

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

        item_reasons = dict(first_run.reasons)
        if cid in committee_meta:
            item_reasons["committee"] = committee_meta[cid]
            item_reasons["ending_type"] = committee_meta[cid].get("judge_1", {}).get("ending_type", "resolution")

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
                reasons=item_reasons,
                llm_score=round(llm_score, 1),
                runs=len(runs_list),
            )
        )

    ctx.write_artifact("judged.json", JudgedArtifact(items=final_judged_items))
    ctx.progress("judge", 1.0, f"Rubric judging complete: {len(final_judged_items)} items scored")
