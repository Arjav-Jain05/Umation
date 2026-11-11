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
    video_path is clip.mp4 (or fx.mp4/framed.mp4 fallback).
    """
    clip_dir = paths.clip_dir(ctx.job_id, clip.id)
    # Prefer single-pass rendered clip.mp4, fallback to framed.mp4
    video_file = clip_dir / "clip.mp4"
    if not video_file.is_file():
        video_file = clip_dir / "framed.mp4"
    if not video_file.is_file():
        raise FileNotFoundError(f"Video file not found for clip {clip.id} in {clip_dir}")

    words_art = ctx.read_artifact(f"clips/{clip.id}/words.json", WordsArtifact)
    layout_art = ctx.read_artifact(f"clips/{clip.id}/layout.json", LayoutArtifact)
    layout_str = layout_art.layout if layout_art else "gameplay"

    # 1. Build & validate edit list
    edit_list = director.build_edit_list(
        ctx=ctx,
        clip=clip,
        words_art=words_art,
        framed_mp4=video_file,
        layout=layout_str,
        enable_gemini=True,
    )
    ctx.write_artifact(f"clips/{clip.id}/edit_list.json", edit_list)

    # 2. Build SFX mix
    sfx_wav = clip_dir / "sfx_mix.wav"
    dur = float(clip.duration or (clip.end - clip.start))
    build_sfx_mix(edit_list.events, duration=dur, out_wav=sfx_wav)

    # 3. Check if external visual compositor pass is strictly necessary
    # (Hook cards, part badges, and end cards are already burned into clip.mp4 via ASS)
    fx_mp4 = clip_dir / "fx.mp4"
    heavy_standalone_types = {"arrow", "highlight_box"}
    needs_extra_compositing = any(e.type in heavy_standalone_types for e in edit_list.events)

    if not needs_extra_compositing:
        logger.info("[%s] Clip %s visual effects handled via ASS; skipping compositor pass", ctx.job_id, clip.id)
        return video_file, sfx_wav

    # 4. Render with Compositor only if heavy standalone overlays are present
    try:
        compositor.render_with_effects(
            framed_path=video_file,
            edit_list=edit_list,
            out_path=fx_mp4,
            cancel_event=ctx.cancel_event,
        )
        return fx_mp4, sfx_wav
    except Exception as e:
        logger.warning("[%s] Compositor failed for clip %s (%s); falling back to base video", ctx.job_id, clip.id, e)
        return video_file, sfx_wav
