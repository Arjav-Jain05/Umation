"""Stage 3: Build vertical clips (cut, layout, captions, audio cleanup, final render)."""

from __future__ import annotations

import logging

from app.core import paths
from app.core.db import get_conn
from app.core.models import update_clip
from app.core.schemas import Plan, SegmentsArtifact, Transcript
from app.pipeline.context import JobContext
from app.pipeline.s3_build import audio_clean, captions, cutter, final_render, layout, segments
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
    audio_path = ctx.work_dir / "audio.wav"

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

        # Check if clip is already rendered and valid (resumability)
        if final_mp4.is_file():
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

            # 2. Cutter: compute keep intervals and cut video
            keep_intervals = cutter.compute_keep_intervals(
                clip_start=clip.start,
                clip_end=clip.end,
                words=transcript.words,
                fillers=transcript.fillers,
                audio_path=audio_path,
            )

            cut_video, cuts_art, words_art = cutter.cut_clip(
                seg_path=seg_file,
                seg_start=seg_obj.s,
                intervals=keep_intervals,
                out_dir=clip_dir,
                words=transcript.words,
                fillers=transcript.fillers,
            )
            ctx.write_artifact(f"clips/{clip.id}/cuts.json", cuts_art)
            ctx.write_artifact(f"clips/{clip.id}/words.json", words_art)

            # 3. Layout: sample faces and classify layout
            face_samples = sample_faces(cut_video, every_s=2.0)
            layout_override = getattr(ctx.options, "layout", None)
            layout_decision = layout.detect_layout(face_samples, override=layout_override, clip_id=clip.id)
            ctx.write_artifact(f"clips/{clip.id}/layout.json", layout_decision)

            # Render 9:16 framed video
            layout.build_framed_clip(cut_video, layout_decision, clip_dir)

            # 4. Captions: chunk words and write ASS / SRT
            caption_chunks = captions.chunk_words(words_art.words)
            captions.write_ass(
                caption_chunks,
                layout=layout_decision.layout,
                out_path=clip_dir / "captions.ass",
                mask_profanity_flag=getattr(ctx.options, "mask_profanity", True),
                preset=getattr(ctx.options, "caption_preset", "modern_box"),
            )
            captions.write_srt(
                caption_chunks,
                out_path=clip_dir / "captions.srt",
                mask_profanity_flag=getattr(ctx.options, "mask_profanity", True),
            )

            # 5. Audio Clean-up
            audio_clean.clean_audio(
                cut_video_or_audio=cut_video,
                layout=layout_decision.layout,
                out_wav=clip_dir / "audio_clean.wav",
            )

            # 6. Final Render
            final_mp4, qa_report = final_render.render_final(
                clip_dir=clip_dir,
                fps=30.0,
                has_captions=True,
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
