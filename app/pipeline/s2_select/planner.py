"""Stage 2: Signal blending, tier thresholding, deduplication, and clip planning."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import yaml
from rapidfuzz import fuzz

from app.core.schemas import (
    Clip,
    JudgedArtifact,
    JudgedItem,
    Plan,
    Signals,
    SignalsArtifact,
    SourceInfo,
    Transcript,
)
from app.pipeline.context import JobContext
from app.pipeline.s2_select.blend import blend
from app.pipeline.s2_select.part_splitter import split_story
from app.pipeline.s2_select.risk import assess
from app.pipeline.s2_select.signal_audio import audio_score, compute_baseline_z, frame_db
from app.pipeline.s2_select.signal_heatmap import heat_score
from app.pipeline.s2_select.signal_speech import speech_ratio, topical_hits

logger = logging.getLogger("app.pipeline.s2_select.planner")


def _get_clip_text(start_sid: int, end_sid: int, sentences: list[Any]) -> str:
    sub = sentences[start_sid : min(end_sid + 1, len(sentences))]
    return " ".join(s.text for s in sub).strip()


def plan_clips(
    judged_items: list[JudgedItem],
    signals_map: dict[str, Signals],
    coarse_heatmap_map: dict[str, bool],
    source_info: SourceInfo,
    transcript: Transcript,
    scoring_cfg: dict[str, Any],
    domain: str = "gta6",
    min_tier: str = "C",
    gemini_client: Any = None,
) -> list[Clip]:
    """Execute planning pipeline: blend scores, assess risk, deduplicate, and split stories."""
    thresholds = scoring_cfg.get("thresholds", {"min_final": 60, "tier_a": 80, "tier_b": 70})
    min_final = float(thresholds.get("min_final", 60))
    tier_a_min = float(thresholds.get("tier_a", 80))
    tier_b_min = float(thresholds.get("tier_b", 70))

    tier_rank_order = {"A": 3, "B": 2, "C": 1}
    target_rank = tier_rank_order.get(min_tier.upper(), 1)

    scored_candidates: list[tuple[float, Clip, str]] = []

    for item in judged_items:
        sig = signals_map.get(item.cid)
        if sig is None:
            continue

        coarse_heat = coarse_heatmap_map.get(item.cid, False)
        final = blend(item, sig, scoring_cfg, domain=domain, heat_coarse_override=coarse_heat)

        # Risk assessment
        dur = item.e - item.s
        risk_lvl, risk_flags = assess(dur, sig.speech_ratio, source_info, item.content_flags)

        # Cap final score if risk is high (cannot reach Tier A)
        if risk_lvl == "high" and final >= 80.0:
            final = 79.0

        if final < min_final:
            continue

        tier = "A" if final >= tier_a_min else ("B" if final >= tier_b_min else "C")
        if tier_rank_order.get(tier, 1) < target_rank:
            continue

        text = _get_clip_text(item.start_sid, item.end_sid, transcript.sentences)

        c = Clip(
            id=item.cid,
            start=item.s,
            end=item.e,
            duration=round(dur, 3),
            tier=tier,
            final_score=final,
            llm_score=item.llm_score,
            heat=sig.heat,
            audio=sig.audio,
            speech_ratio=sig.speech_ratio,
            hook_text=item.hook_text,
            topic=item.topic,
            risk=risk_lvl,
            risk_flags=risk_flags,
            needs_context=item.needs_context,
            context_fix=item.context_fix,
        )
        scored_candidates.append((final, c, text))

    # Sort descending by final score for deduplication
    scored_candidates.sort(key=lambda x: x[0], reverse=True)

    kept: list[tuple[Clip, str]] = []
    for _final, clip_cand, text in scored_candidates:
        dup = False
        c_dur = clip_cand.end - clip_cand.start

        for k_clip, k_text in kept:
            k_dur = k_clip.end - k_clip.start
            overlap = max(0.0, min(clip_cand.end, k_clip.end) - max(clip_cand.start, k_clip.start))
            shorter = min(c_dur, k_dur)

            # Time overlap > 30% of shorter
            if shorter > 0 and (overlap / shorter) >= 0.30:
                dup = True
                break

            # Text similarity >= 85
            sim = fuzz.token_set_ratio(text, k_text)
            if sim >= 85:
                dup = True
                break

        if not dup:
            kept.append((clip_cand, text))

    # Multi-part story splitting for long continuous moments
    final_clips: list[Clip] = []
    for clip_obj, _ in kept:
        if (clip_obj.duration > 75.0 or clip_obj.duration > 65.0) and clip_obj.final_score >= 70.0 and gemini_client:
            parts = split_story(clip_obj, transcript.sentences, gemini_client)
            final_clips.extend(parts)
        else:
            final_clips.append(clip_obj)

    # Soft cap at 40 clips
    limits = scoring_cfg.get("limits", {})
    max_clips_soft = int(limits.get("max_clips_soft", 40))
    if len(final_clips) > max_clips_soft:
        logger.warning("Clips exceed soft cap (%d > %d); retaining top %d", len(final_clips), max_clips_soft, max_clips_soft)
        final_clips.sort(key=lambda c: c.final_score, reverse=True)
        final_clips = final_clips[:max_clips_soft]

    # Re-order by start time and assign clean sequential IDs (c01, c02, ...)
    final_clips.sort(key=lambda c: c.start)
    for idx, c in enumerate(final_clips):
        if c.parent_id is None:
            c.id = f"c{idx + 1:02d}"
        else:
            # Maintain parent-child index
            c.id = f"c{idx + 1:02d}p{c.part_index}"

    return final_clips


def run(ctx: JobContext) -> None:
    """Execute Stage 2: compute signals and plan final clips."""
    if ctx.artifact_ok("plan.json", Plan):
        logger.info("[%s] plan.json already exists and validates; skipping plan", ctx.job_id)
        return

    judged_art = ctx.read_artifact("judged.json", JudgedArtifact)
    source_info = ctx.read_artifact("source_info.json", SourceInfo)
    transcript = ctx.read_artifact("transcript.json", Transcript)

    # Load scoring config

    scoring_path = ctx.settings.project_root / "config" / "scoring.yaml"
    with open(scoring_path, encoding="utf-8") as f:
        scoring_cfg = yaml.safe_load(f) or {}

    # Load GTA 6 glossary terms
    glossary_terms: list[str] = []
    glossary_path = ctx.settings.project_root / "config" / "glossary_gta6.yaml"
    if glossary_path.exists() and ctx.settings.project_domain == "gta6":
        with open(glossary_path, encoding="utf-8") as f:
            gdata = yaml.safe_load(f) or {}
        glossary_terms = [str(t) for t in gdata.get("terms", [])]

    # Pre-compute audio z-scores across whole audio
    audio_wav = ctx.work_dir / "audio.wav"
    audio_db = frame_db(audio_wav)
    z_scores = compute_baseline_z(audio_db)

    ctx.progress("plan", 0.3, f"Extracted audio signal across {len(audio_db)} frames...")

    signals_dict: dict[str, Signals] = {}
    coarse_heat_dict: dict[str, bool] = {}

    for item in judged_art.items:
        w = (item.s, item.e)
        # 1. Heatmap
        h_score, coarse = heat_score(w, source_info.heatmap, source_info.heatmap_avg_seg_s)
        coarse_heat_dict[item.cid] = coarse

        # 2. Audio energy
        a_score, bursts = audio_score(w, z_scores)

        # 3. Speech ratio & topicality
        s_ratio = speech_ratio(transcript.words, item.s, item.e)
        t_text = _get_clip_text(item.start_sid, item.end_sid, transcript.sentences)
        t_hits = topical_hits(t_text, glossary_terms)

        sig = Signals(
            cid=item.cid,
            heat=h_score,
            audio=a_score,
            speech_ratio=s_ratio,
            burst_count=bursts,
            topical_hits=t_hits,
        )
        signals_dict[item.cid] = sig

    ctx.write_artifact("signals.json", SignalsArtifact(signals=signals_dict))

    # Plan clips
    ctx.progress("plan", 0.7, "Blending signals and selecting clips above viral threshold...")
    clips = plan_clips(
        judged_art.items,
        signals_dict,
        coarse_heat_dict,
        source_info,
        transcript,
        scoring_cfg,
        domain=ctx.settings.project_domain,
        min_tier=ctx.options.min_tier,
        gemini_client=ctx.gemini,
    )

    plan = Plan(
        job_id=ctx.job_id,
        generated_at=datetime.now(UTC).isoformat(),
        weights=scoring_cfg.get("weights", {}),
        thresholds=scoring_cfg.get("thresholds", {}),
        clips=clips,
    )
    ctx.write_artifact("plan.json", plan)

    # Sync planned clips into SQLite clips table
    from app.core.db import get_conn
    from app.core.models import upsert_clip

    with get_conn(ctx.db_path) as conn:
        for idx, c in enumerate(clips):
            upsert_clip(
                {
                    "job_id": ctx.job_id,
                    "id": c.id,
                    "idx": idx,
                    "parent_id": c.parent_id,
                    "part_index": c.part_index,
                    "part_total": c.part_total,
                    "start": c.start,
                    "end": c.end,
                    "tier": c.tier,
                    "final_score": c.final_score,
                    "risk": c.risk,
                    "status": "planned",
                    "decision": "pending",
                },
                conn=conn,
            )

    ctx.progress("plan", 1.0, f"Plan complete: {len(clips)} viral clips selected")
