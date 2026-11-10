"""Stage 4: AI Director and visual/audio effects application."""

from __future__ import annotations

import logging

from app.core import paths
from app.core.db import get_conn
from app.core.models import update_clip
from app.core.schemas import LayoutArtifact, Plan, WordsArtifact
from app.pipeline.context import JobContext
from app.pipeline.s3_build import captions, final_render
from app.pipeline.s4_director import apply_effects
from app.pipeline.s4_director.edit_schema import EditList

logger = logging.getLogger("app.pipeline.s4_director")


def run(ctx: JobContext) -> None:
    """Execute Stage 4: AI Director and effects application across all planned clips."""
    plan = ctx.read_artifact("plan.json", Plan)
    if not plan.clips:
        logger.info("[%s] No clips to process in Stage 4", ctx.job_id)
        return

    total = len(plan.clips)
    logger.info("[%s] Directing and compositing effects for %d clips...", ctx.job_id, total)

    for idx, clip in enumerate(plan.clips):
        ctx.check_cancel()
        frac = idx / max(1, total)
        ctx.progress("direct", frac, f"AI Director for clip {idx + 1}/{total} ({clip.id})...", clip_id=clip.id)

        clip_dir = paths.clip_dir(ctx.job_id, clip.id)
        try:
            # 1. Render effects & SFX mix
            _fx_video, _sfx_wav = apply_effects.render_effects(ctx, clip)

            # 2. Update captions with caption_emphasis orange styling
            edit_list = ctx.read_artifact(f"clips/{clip.id}/edit_list.json", EditList)
            words_art = ctx.read_artifact(f"clips/{clip.id}/words.json", WordsArtifact)
            layout_art = ctx.read_artifact(f"clips/{clip.id}/layout.json", LayoutArtifact)

            if edit_list and words_art:
                caption_chunks = captions.chunk_words(words_art.words)
                captions.write_ass(
                    caption_chunks,
                    layout=layout_art.layout if layout_art else "gameplay",
                    out_path=clip_dir / "captions.ass",
                    mask_profanity_flag=getattr(ctx.options, "mask_profanity", True),
                    emphasis_indices=edit_list.caption_emphasis,
                )

            # 3. Final re-render with composited fx and mixed SFX
            _final_mp4, _qa_report = final_render.render_final(
                clip_dir=clip_dir,
                fps=30.0,
                has_captions=True,
            )

            with get_conn(ctx.db_path) as conn:
                update_clip(ctx.job_id, clip.id, conn=conn, status="directed")

            logger.info("[%s] Successfully applied effects and rendered clip %s", ctx.job_id, clip.id)

        except Exception as e:
            logger.error("[%s] Failed to direct clip %s: %s; keeping framed output", ctx.job_id, clip.id, e)
            # Clip failure is isolated per 06 s12
            with get_conn(ctx.db_path) as conn:
                update_clip(ctx.job_id, clip.id, conn=conn, error=str(e))

    ctx.write_artifact("direct_done.json", {"schema_version": 1, "status": "done", "clips": total})
    logger.info("[%s] Completed Stage 4 (direct) for %d clips", ctx.job_id, total)

