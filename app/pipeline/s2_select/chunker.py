"""Transcript chunking for Gemini nomination with dead-air compression."""

from __future__ import annotations

from typing import Any

from app.core.schemas import Chunk, ChunksArtifact, Sentence
from app.utils.timecode import fmt_hms


def mark_dead_regions(sentences: list[Sentence]) -> list[bool]:
    """Identify low-information / dead regions (wpm < 40 for > 90s) to compress in prompt text."""
    if not sentences:
        return []

    is_dead = [False] * len(sentences)
    run_start_idx = 0
    run_start_t = sentences[0].s

    for i, s in enumerate(sentences):
        if s.wpm >= 40.0:
            run_dur = sentences[i - 1].e - run_start_t if i > run_start_idx else 0.0
            if run_dur >= 90.0:
                for k in range(run_start_idx, i):
                    is_dead[k] = True
            run_start_idx = i + 1
            run_start_t = s.e

    # Check trailing run
    if sentences[-1].e - run_start_t >= 90.0:
        for k in range(run_start_idx, len(sentences)):
            is_dead[k] = True

    return is_dead


def make_chunks(
    sentences: list[Sentence],
    minutes: int = 4,
    overlap_s: int = 45,
) -> list[Chunk]:
    """Slice sentences into overlapping chunks cut on sentence boundaries.

    Uses 4-minute chunks with 45s overlap to ensure prompt context easily fits
    local LLM context windows (4096 tokens) without any token truncation.
    """
    if not sentences:
        return []

    total_duration = sentences[-1].e
    chunk_dur_s = float(minutes * 60)
    overlap_dur_s = float(overlap_s)

    chunks: list[Chunk] = []
    chunk_idx = 1
    start_time = 0.0

    while start_time < total_duration:
        end_target = start_time + chunk_dur_s

        # Find sentences whose intervals intersect [start_time, end_target]
        matched_sids: list[int] = []
        for s in sentences:
            if s.e >= start_time and s.s <= end_target:
                matched_sids.append(s.id)

        if not matched_sids:
            # Advance if no sentences matched
            start_time += chunk_dur_s - overlap_dur_s
            continue

        first_sid = matched_sids[0]
        last_sid = matched_sids[-1]
        c_start = sentences[first_sid].s
        c_end = sentences[last_sid].e

        cid = f"ch{chunk_idx:02d}"
        chunks.append(
            Chunk(
                id=cid,
                s=round(c_start, 3),
                e=round(c_end, 3),
                sentence_ids=[first_sid, last_sid],
            )
        )

        chunk_idx += 1
        start_time += chunk_dur_s - overlap_dur_s

        # Stop if this chunk covered the rest of the video
        if c_end >= total_duration:
            break

    return chunks


def render_chunk_text(
    chunk: Chunk,
    sentences: list[Sentence],
    dead_flags: list[bool] | None = None,
) -> str:
    """Format chunk sentences into prompt lines, replacing contiguous dead stretches with placeholder."""
    first_sid, last_sid = chunk.sentence_ids
    lines: list[str] = []

    in_dead_region = False
    dead_start_t = 0.0

    for sid in range(first_sid, min(last_sid + 1, len(sentences))):
        s = sentences[sid]
        dead = dead_flags[sid] if dead_flags and sid < len(dead_flags) else False

        if dead:
            if not in_dead_region:
                in_dead_region = True
                dead_start_t = s.s
            continue
        else:
            if in_dead_region:
                dead_dur = max(1, round(s.s - dead_start_t))
                lines.append(f"[... quiet {dead_dur}s ...]")
                in_dead_region = False

            ts = fmt_hms(s.s)
            lines.append(f"[{s.id}] {ts} {s.text}")

    if in_dead_region:
        dead_dur = max(1, round(sentences[last_sid].e - dead_start_t))
        lines.append(f"[... quiet {dead_dur}s ...]")

    return "\n".join(lines)


def run(ctx: Any) -> None:
    """Stage helper: chunk transcript sentences and save chunks.json."""
    if ctx.artifact_ok("chunks.json", ChunksArtifact):
        return

    from app.core.schemas import Transcript

    transcript = ctx.read_artifact("transcript.json", Transcript)
    chunks = make_chunks(transcript.sentences)
    ctx.write_artifact("chunks.json", ChunksArtifact(chunks=chunks))
