"""Stage 4 entry: effect planning, compositor rendering, and SFX mixing per clip."""

from __future__ import annotations

import logging
from pathlib import Path

from app.core import paths
from app.core.schemas import Clip, LayoutArtifact, WordsArtifact
from app.pipeline.context import JobContext
from app.pipeline.s4_director import compositor, director
from app.pipeline.s4_director.effects.sfx import build_sfx_mix

logger = logging.getLogger("app.pipeline.s4_director.apply_effects")


def render_effects(ctx: JobContext, clip: Clip) -> tuple[Path, Path]:
    """Execute AI director and apply all visual and audio effects for a single clip.

    Returns (video_path, sfx_wav_path).
    video_path is fx.mp4 if overlays were composited, or framed.mp4 if skipped/failed.
    """
    clip_dir = paths.clip_dir(ctx.job_id, clip.id)
    framed_mp4 = clip_dir / "framed.mp4"
    if not framed_mp4.is_file():
        raise FileNotFoundError(f"Framed video {framed_mp4} not found for clip {clip.id}")

    words_art = ctx.read_artifact(f"clips/{clip.id}/words.json", WordsArtifact)
    layout_art = ctx.read_artifact(f"clips/{clip.id}/layout.json", LayoutArtifact)
    layout_str = layout_art.layout if layout_art else "gameplay"

    # 1. Build & validate edit list
    edit_list = director.build_edit_list(
        ctx=ctx,
        clip=clip,
        words_art=words_art,
        framed_mp4=framed_mp4,
        layout=layout_str,
        enable_gemini=True,
    )
    ctx.write_artifact(f"clips/{clip.id}/edit_list.json", edit_list)

    # 2. Build SFX mix
    sfx_wav = clip_dir / "sfx_mix.wav"
    dur = float(clip.duration or (clip.end - clip.start))
    build_sfx_mix(edit_list.events, duration=dur, out_wav=sfx_wav)

    # 3. Check if visual compositor pass is necessary
    heavy_visual_types = {"zoom_punch", "hook_card", "arrow", "highlight_box", "emoji_pop", "recap_line"}
    has_heavy_visuals = any(e.type in heavy_visual_types for e in edit_list.events)

    fx_mp4 = clip_dir / "fx.mp4"

    if not has_heavy_visuals:
        logger.info("[%s] No heavy visual events for clip %s; skipping compositor", ctx.job_id, clip.id)
        # Progress bar / part label can still be drawn or framed.mp4 used directly
        # If there are progress_bar or part_label events, render them quickly
        has_any_visuals = any(e.type in ("progress_bar", "part_label") for e in edit_list.events)
        if not has_any_visuals:
            return framed_mp4, sfx_wav

    # 4. Render with Compositor (with retry and failure isolation per 06 s12)
    try:
        compositor.render_with_effects(
            framed_path=framed_mp4,
            edit_list=edit_list,
            out_path=fx_mp4,
            cancel_event=ctx.cancel_event,
        )
        return fx_mp4, sfx_wav
    except Exception as e:
        logger.warning("[%s] Compositor failed for clip %s (%s); retrying once...", ctx.job_id, clip.id, e)
        try:
            compositor.render_with_effects(
                framed_path=framed_mp4,
                edit_list=edit_list,
                out_path=fx_mp4,
                cancel_event=ctx.cancel_event,
            )
            return fx_mp4, sfx_wav
        except Exception as retry_err:
            logger.error("[%s] Compositor retry failed for clip %s: %s; falling back to framed.mp4", ctx.job_id, clip.id, retry_err)
            return framed_mp4, sfx_wav
