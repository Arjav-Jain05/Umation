"""Stage 3: Build vertical clips (cut, layout, captions, audio cleanup, final render)."""

from __future__ import annotations

import logging

from app.core import paths
from app.core.db import get_conn
from app.core.models import update_clip
from app.core.schemas import Plan, SegmentsArtifact, Transcript, WordClip, WordsClipArtifact
from app.pipeline.context import JobContext
from app.pipeline.s3_build import captions, final_render, layout, segments
from app.pipeline.s3_build.face_track import sample_faces
from app.utils.qa import check_clip_file

logger = logging.getLogger("app.pipeline.s3_build")


def run(ctx: JobContext) -> None:
    """Execute Stage 3: build each planned short-form clip."""
    plan = ctx.read_artifact("plan.json", Plan)
    if not plan.clips:
        logger.info("[%s] No clips to build in plan.json", ctx.job_id)
        return

    # Ensure segments exist
    if not ctx.artifact_ok("segments.json", SegmentsArtifact):
        segments.run(ctx)
    seg_artifact = ctx.read_artifact("segments.json", SegmentsArtifact)
    all_segments = seg_artifact.segments

    transcript = ctx.read_artifact("transcript.json", Transcript)

    total_clips = len(plan.clips)
    logger.info("[%s] Building %d clips...", ctx.job_id, total_clips)

    # Sort clips descending by final_score so highest quality clips build first
    sorted_clips = sorted(plan.clips, key=lambda c: c.final_score, reverse=True)

    for idx, clip in enumerate(sorted_clips):
        ctx.check_cancel()
        frac = idx / max(1, total_clips)
        ctx.progress("build", frac, f"Building clip {idx + 1}/{total_clips} ({clip.id}, Tier {clip.tier})...", clip_id=clip.id)

        clip_dir = paths.clip_dir(ctx.job_id, clip.id)
        clip_dir.mkdir(parents=True, exist_ok=True)
        final_mp4 = clip_dir / "clip.mp4"
        framed_mp4 = clip_dir / "framed.mp4"
        clean_audio = clip_dir / "audio_clean.wav"

        # Check if clip is already rendered and valid (resumability)
        if final_mp4.is_file() and framed_mp4.is_file() and clean_audio.is_file():
            qa_res = check_clip_file(final_mp4, allow_short=True)
            if qa_res.passed:
                logger.info("[%s] Clip %s already built and verified; skipping", ctx.job_id, clip.id)
                with get_conn(ctx.db_path) as conn:
                    update_clip(ctx.job_id, clip.id, conn=conn, status="built")
                continue

        try:
            # 1. Match video segment
            seg_obj, _seg_offset = segments.segment_for(clip, all_segments)
            seg_file = ctx.work_dir / seg_obj.path
            if not seg_file.is_file():
                # Segment file not found; fallback to any matching segment
                candidates = list(ctx.work_dir.glob(f"{seg_obj.id}*"))
                if candidates:
                    seg_file = candidates[0]
                else:
                    raise FileNotFoundError(f"Segment video file {seg_obj.path} not found in work directory")

            rel_start = max(0.0, clip.start - seg_obj.s)
            dur = float(clip.duration or (clip.end - clip.start))

            # 2. Extract words strictly inside [clip.start, clip.end]
            clip_words = [w for w in transcript.words if w.s >= clip.start - 0.1 and w.e <= clip.end + 0.1]
            words_clip = [
                WordClip(
                    w=w.w,
                    s_clip=max(0.0, round(w.s - clip.start, 3)),
                    e_clip=max(0.05, round(w.e - clip.start, 3)),
                    idx=w.i,
                )
                for w in clip_words
            ]
            words_art = WordsClipArtifact(clip_id=clip.id, count=len(words_clip), words=words_clip)
            ctx.write_artifact(f"clips/{clip.id}/words.json", words_art)

            # 3. Layout: sample faces (prefer fast 480p proxy if available)
            proxy_file = ctx.work_dir / "proxy_480p.mp4"
            face_source = proxy_file if proxy_file.is_file() else seg_file
            face_samples = sample_faces(face_source, every_s=2.0)
            layout_override = getattr(ctx.options, "layout", None)
            layout_decision = layout.detect_layout(face_samples, override=layout_override, clip_id=clip.id)
            ctx.write_artifact(f"clips/{clip.id}/layout.json", layout_decision)

            # 4. Captions & Badges / Cards
            is_non_final_part = bool(clip.part_index and clip.part_total and clip.part_index < clip.part_total)
            part_badge = f"PART {clip.part_index}" if (clip.part_index and clip.part_index > 1) else None
            end_card = f"Part {clip.part_index + 1} is on the channel ▶" if is_non_final_part else None
            hook_text = clip.hook_text if getattr(ctx.options, "hook_card", True) else None

            caption_chunks = captions.chunk_words(words_clip)
            captions.write_ass(
                caption_chunks,
                layout=layout_decision.layout,
                out_path=clip_dir / "captions.ass",
                mask_profanity_flag=getattr(ctx.options, "mask_profanity", True),
                preset=getattr(ctx.options, "caption_preset", "modern_box"),
                hook_card_text=hook_text,
                part_badge_text=part_badge,
                end_card_text=end_card,
                end_card_start_s=dur if is_non_final_part else None,
            )
            captions.write_srt(
                caption_chunks,
                out_path=clip_dir / "captions.srt",
                mask_profanity_flag=getattr(ctx.options, "mask_profanity", True),
            )

            # 5. Render framed.mp4 (clean 9:16 layout without captions) and audio_clean.wav (48kHz audio)
            framed_mp4, clean_audio = final_render.render_framed_and_audio(
                seg_path=seg_file,
                rel_start=rel_start,
                dur=dur,
                clip_dir=clip_dir,
                layout=layout_decision.layout,
                cam_rect=layout_decision.cam_rect,
                fps=30.0,
            )

            # 6. Render initial clip.mp4 with captions burned in and audio normalized
            final_mp4, qa_report = final_render.render_final(
                clip_dir=clip_dir,
                fps=30.0,
                has_captions=True,
                is_non_final_part=is_non_final_part,
                dur=dur,
            )

            # Update database status
            with get_conn(ctx.db_path) as conn:
                update_clip(
                    ctx.job_id,
                    clip.id,
                    conn=conn,
                    status="built" if qa_report.passed else "qa_warning",
                )

            logger.info("[%s] Successfully built clip %s (QA passed: %s)", ctx.job_id, clip.id, qa_report.passed)

        except Exception as e:
            logger.error("[%s] Failed building clip %s: %s", ctx.job_id, clip.id, e, exc_info=True)
            with get_conn(ctx.db_path) as conn:
                update_clip(ctx.job_id, clip.id, conn=conn, status="failed", error=str(e))
            ctx.warning(f"Clip {clip.id} build failed: {e}")

    ctx.write_artifact("build_done.json", {"schema_version": 1, "status": "done", "clips": total_clips})
    ctx.progress("build", 1.0, f"Stage build complete: processed {total_clips} clips")
