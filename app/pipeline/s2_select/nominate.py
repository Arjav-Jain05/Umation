"""Stage 2: Gemini moment nomination across transcript chunks."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.core.paths import prompts_dir
from app.core.schemas import (
    Candidate,
    CandidatesArtifact,
    Chunk,
    ChunksArtifact,
    SourceInfo,
    Transcript,
)
from app.pipeline.context import JobContext
from app.pipeline.s2_select.chunker import make_chunks, mark_dead_regions, render_chunk_text
from app.utils.timecode import fmt_hms

logger = logging.getLogger("app.pipeline.s2_select.nominate")


class RawNominationItem(BaseModel):
    start_sid: int
    end_sid: int
    hook_sid: int
    reason: str = ""
    hint_score: int = 50
    is_story: bool = False


class NominationOut(BaseModel):
    candidates: list[RawNominationItem] = Field(default_factory=list)


def run(ctx: JobContext) -> None:
    """Execute Stage 2: nominate."""
    if ctx.artifact_ok("candidates.json", CandidatesArtifact):
        logger.info("[%s] candidates.json already exists and validates; skipping nominate", ctx.job_id)
        return

    transcript = ctx.read_artifact("transcript.json", Transcript)
    source_info = ctx.read_artifact("source_info.json", SourceInfo)

    # Ensure chunks exist
    if not ctx.artifact_ok("chunks.json", ChunksArtifact):
        chunks = make_chunks(transcript.sentences)
        ctx.write_artifact("chunks.json", ChunksArtifact(chunks=chunks))
    else:
        chunks = ctx.read_artifact("chunks.json", ChunksArtifact).chunks

    # Load GTA 6 glossary terms
    domain_desc = "General short-form video clipping"
    glossary_terms: list[str] = []
    glossary_path = ctx.settings.project_root / "config" / "glossary_gta6.yaml"
    if glossary_path.exists() and ctx.settings.project_domain == "gta6":
        import yaml

        try:
            with open(glossary_path, encoding="utf-8") as f:
                gdata = yaml.safe_load(f) or {}
            domain_desc = str(gdata.get("domain_description", domain_desc))
            glossary_terms = [str(t) for t in gdata.get("terms", [])]
        except Exception as e:
            logger.warning("Could not load glossary: %s", e)

    # Find heatmap peaks
    heat_peaks: list[str] = []
    if source_info.heatmap:
        sorted_heat = sorted(source_info.heatmap, key=lambda p: p.value, reverse=True)
        for p in sorted_heat[:5]:
            heat_peaks.append(f"{fmt_hms(p.start)}-{fmt_hms(p.end)} (score {int(p.value * 100)})")
    peaks_str = ", ".join(heat_peaks) if heat_peaks else "none"

    dead_flags = mark_dead_regions(transcript.sentences)
    prompt_template = (prompts_dir() / "nominate_candidates.md").read_text(encoding="utf-8")

    all_raw: list[tuple[Chunk, RawNominationItem]] = []
    sid_map = {s.id: s for s in transcript.sentences}

    for idx, ch in enumerate(chunks):
        ctx.check_cancel()
        frac = min(0.90, (idx / max(1, len(chunks))))
        ctx.progress("nominate", frac, f"Nominating candidates in chunk {idx + 1}/{len(chunks)}...")

        chunk_text = render_chunk_text(ch, transcript.sentences, dead_flags)
        filled = (
            prompt_template.replace("{{domain_description}}", domain_desc)
            .replace("{{glossary_terms}}", ", ".join(glossary_terms[:30]))
            .replace("{{heat_peaks}}", peaks_str)
            .replace("{{chunk_text}}", chunk_text)
        )

        try:
            res: NominationOut = ctx.gemini.generate_json(
                filled,
                NominationOut,
                temperature=0.4,
            )
            for cand in res.candidates:
                # Validation: sentence ids must exist and be ordered
                if cand.start_sid not in sid_map or cand.end_sid not in sid_map:
                    continue
                if cand.start_sid > cand.end_sid:
                    continue
                if not (cand.start_sid <= cand.hook_sid <= cand.end_sid):
                    cand.hook_sid = cand.start_sid

                dur = sid_map[cand.end_sid].e - sid_map[cand.start_sid].s
                if 12.0 <= dur <= 180.0:
                    all_raw.append((ch, cand))
        except Exception as e:
            logger.warning("Chunk %s nomination failed: %s", ch.id, e)

    # Merge duplicates across overlapping chunks
    all_raw.sort(key=lambda item: sid_map[item[1].start_sid].s)
    kept_raw: list[tuple[Chunk, RawNominationItem]] = []

    for ch, cand in all_raw:
        c_start = sid_map[cand.start_sid].s
        c_end = sid_map[cand.end_sid].e
        c_dur = c_end - c_start

        duplicate = False
        for k_idx, (_k_ch, k_cand) in enumerate(kept_raw):
            k_start = sid_map[k_cand.start_sid].s
            k_end = sid_map[k_cand.end_sid].e
            k_dur = k_end - k_start

            overlap = max(0.0, min(c_end, k_end) - max(c_start, k_start))
            shorter = min(c_dur, k_dur)
            if shorter > 0 and (overlap / shorter) > 0.50:
                duplicate = True
                # Keep candidate with higher hint_score
                if cand.hint_score > k_cand.hint_score:
                    kept_raw[k_idx] = (ch, cand)
                break

        if not duplicate:
            kept_raw.append((ch, cand))

    candidates: list[Candidate] = []
    for cid_idx, (ch, cand) in enumerate(kept_raw):
        cid = f"n{cid_idx + 1:02d}"
        s = sid_map[cand.start_sid].s
        e = sid_map[cand.end_sid].e
        candidates.append(
            Candidate(
                cid=cid,
                chunk_id=ch.id,
                start_sid=cand.start_sid,
                end_sid=cand.end_sid,
                hook_sid=cand.hook_sid,
                s=round(s, 3),
                e=round(e, 3),
                reason=cand.reason,
                llm_hint_score=float(cand.hint_score),
            )
        )

    ctx.write_artifact("candidates.json", CandidatesArtifact(candidates=candidates))
    ctx.progress("nominate", 1.0, f"Nomination complete: {len(candidates)} candidates found")
