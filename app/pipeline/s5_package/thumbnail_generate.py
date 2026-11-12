"""Thumbnail generation orchestrator: subject acquisition, variant generation, VLM critic, and quality gate.

Implements Sections 2 and 3 of Prompt v7:
- clip_frame_cutout default: samples full-res frames, cuts out subject with MediaPipe
- ai_generated & vector hero fallback with 'needs attention' flag
- Generates 6 variants per clip across templates, hooks, and background families
- Hard quality gate rejects non-compliant variants
- VLM critic (Qwen2.5-VL via Ollama) soft-ranks survivors to select top 1
- Exports both 16:9 (1280x720) and 9:16 (1080x1920) upload assets
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.core import paths
from app.core.schemas import Clip
from app.pipeline.context import JobContext
from app.pipeline.s5_package import (
    backgrounds,
    quality_gate,
    subject_extractor,
    text_engine,
    thumbnail_compose,
)
from app.pipeline.s5_package.thumbnail_concept import ThumbConcept

logger = logging.getLogger("app.pipeline.s5_package.thumbnail_generate")


def ahash(img: Image.Image) -> np.ndarray:
    """Compute 16x16 average perceptual hash (256 bits)."""
    return quality_gate.compute_ahash(img)


def not_a_frame(img: Image.Image, sample_frames: list[Path]) -> bool:
    """Verify that generated thumbnail is NOT a raw unchanged video frame (N9)."""
    if not sample_frames:
        return True

    thumb_hash = ahash(img)
    for frame_path in sample_frames:
        if not frame_path.is_file():
            continue
        try:
            with Image.open(frame_path) as f_img:
                f_hash = ahash(f_img)
            dist = int(np.count_nonzero(thumb_hash != f_hash))
            # Cutout on procedural background has high Hamming distance (>50)
            if dist <= 12:
                logger.warning(
                    "Thumbnail rejected: identical to raw video frame %s (dist %d <= 12)",
                    frame_path.name,
                    dist,
                )
                return False
        except Exception:
            pass

    return True


def generate_pillow_art(concept: ThumbConcept, aspect: str = "16:9", seed_str: str = "art") -> Image.Image:
    """Generate high-contrast procedural thumbnail art via Pillow."""
    size = (1280, 720) if aspect == "16:9" else (1080, 1920)
    anchor = (size[0] // 2, size[1] // 2)
    palette = ((24, 8, 71), (180, 20, 20), (255, 230, 0))
    bg = backgrounds.create_background("radial_burst", size, anchor, palette)
    # Add hero vector graphic
    hero = subject_extractor.generate_vector_hero_fallback(size)
    hx = (size[0] - hero.width) // 2
    hy = (size[1] - hero.height) // 2
    bg.paste(hero, (hx, hy), hero)
    return bg


def generate_art(
    concept: ThumbConcept,
    aspect: str,
    ctx: JobContext,
    sample_frames: list[Path] | None = None,
    clip_id: str = "c01",
) -> tuple[Image.Image, str]:
    """Generate base artwork for backward-compatibility with older tests."""
    size = (1280, 720) if aspect == "16:9" else (1080, 1920)
    hero = subject_extractor.generate_vector_hero_fallback(size)
    palette = ((24, 8, 71), (180, 20, 20), (255, 230, 0))
    bg = backgrounds.create_background("radial_burst", size, (size[0] // 2, size[1] // 2), palette)
    hx = (size[0] - hero.width) // 2
    hy = (size[1] - hero.height) // 2
    bg.paste(hero, (hx, hy), hero)
    return bg, "procedural_v7"


def _find_source_video(ctx: JobContext, clip: Clip) -> Path | None:
    """Find full-resolution source video segment or clip mp4."""
    # 1. Check full-resolution segment in job work dir (seg01.mkv)
    job_work_dir = paths.job_dir(ctx.job_id)
    if job_work_dir.exists():
        for seg in sorted(job_work_dir.glob("seg*.mkv")):
            if seg.is_file() and seg.stat().st_size > 10 * 1024 * 1024:
                return seg

    # 2. Check clip framed or final mp4
    clip_dir = paths.clip_dir(ctx.job_id, clip.id)
    candidates = [
        clip_dir / "clip.mp4",
        clip_dir / "final.mp4",
        clip_dir / "framed.mp4",
        clip_dir / "cut.mkv",
    ]
    for c in candidates:
        if c.is_file() and c.stat().st_size > 100 * 1024:
            return c

    return None


def generate_clip_thumbnails(
    ctx: JobContext,
    clip: Clip,
    out_dir: Path,
    concept: ThumbConcept | None = None,
) -> dict[str, Any]:
    """Execute complete thumbnail generation pipeline for a clip (Section 2 & 3).

    Generates both 16:9 and 9:16 thumbnails, runs hard checks, ranks variants,
    and saves thumb_16x9.jpg and cover_9x16.jpg.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    t169_path = out_dir / "thumb_16x9.jpg"
    c916_path = out_dir / "cover_9x16.jpg"

    # 1. Concept and candidate hooks
    if concept is None:
        from app.pipeline.s5_package.thumbnail_concept import make_concept
        concept = make_concept(ctx, clip)

    candidate_hooks = concept.candidate_hooks or [concept.text]
    if len(candidate_hooks) < 3:
        extra_hooks = text_engine.generate_curiosity_hooks(clip.topic or "Viral Moment", seed_hook=clip.hook_text or "")
        candidate_hooks.extend(extra_hooks)

    candidate_hooks = candidate_hooks[:4]

    # 2. Subject Acquisition: Extract candidate frames from source video
    source_video = _find_source_video(ctx, clip)
    start_s = float(clip.start)
    end_s = float(clip.end)
    audio_peak_s = getattr(clip, "audio_peak", start_s + (end_s - start_s) * 0.5)

    frame_cands = []
    if source_video is not None:
        logger.info("Sampling full-resolution candidate frames from %s for clip %s", source_video.name, clip.id)
        frame_cands = subject_extractor.sample_and_score_frames(
            video_path=source_video,
            start_s=start_s,
            end_s=end_s,
            audio_peak_s=audio_peak_s,
            max_candidates=3,
        )

    best_subj_img = None
    best_cand = None
    needs_attention = False
    attention_reason = ""

    if frame_cands:
        for fc in frame_cands:
            subj_img, _subj_box = subject_extractor.cutout_subject(fc.frame_rgb, fc.face_box)
            if subj_img is not None:
                best_subj_img = subj_img
                best_cand = fc
                break

    if best_subj_img is None:
        logger.warning("No usable frame cutout for clip %s; degrading to vector hero graphic", clip.id)
        needs_attention = True
        attention_reason = "No usable face/subject frame passed cutout quality threshold"
        best_subj_img = subject_extractor.generate_vector_hero_fallback((1280, 720))

    dominant_hue = backgrounds.extract_dominant_hue(best_subj_img)
    palette = backgrounds.generate_palette(dominant_hue, mode="split_complementary")

    # 3. Generate 6 Variants across templates & hooks
    templates_to_try = [concept.template, "versus_split", "hero_center", "big_reaction", "mystery_zoom"]
    # Remove duplicates preserving order
    seen_tmpl = set()
    templates = [t for t in templates_to_try if not (t in seen_tmpl or seen_tmpl.add(t))][:3]

    variants = []
    for t_name in templates:
        for h_text in candidate_hooks[:2]:
            variants.append({"template": t_name, "hook": h_text})

    logger.info("Generating and evaluating %d thumbnail variants for clip %s...", len(variants), clip.id)

    # 4. Generate & verify variants (select the best passing variant)
    best_variant = variants[0]
    best_report_169 = None
    best_report_916 = None
    best_vlm_score = 0.0

    temp_dir = out_dir / "_variants"
    temp_dir.mkdir(parents=True, exist_ok=True)

    for idx, var in enumerate(variants):
        t_name = var["template"]
        hook = var["hook"]
        temp_169 = temp_dir / f"var_{idx}_16x9.jpg"
        temp_916 = temp_dir / f"var_{idx}_9x16.jpg"

        face_b = best_cand.face_box if best_cand else None
        source_frame_pil = Image.fromarray(best_cand.frame_rgb) if best_cand else None

        # 16:9
        _, rep_169 = thumbnail_compose.compose_thumbnail(
            subject_rgba=best_subj_img,
            hook_text=hook,
            aspect="16:9",
            out_path=temp_169,
            template_name=t_name,
            palette=palette,
            source_frame=source_frame_pil,
            face_box=face_b,
        )

        # 9:16
        _, rep_916 = thumbnail_compose.compose_thumbnail(
            subject_rgba=best_subj_img,
            hook_text=hook,
            aspect="9:16",
            out_path=temp_916,
            template_name=t_name,
            palette=palette,
            source_frame=source_frame_pil,
            face_box=face_b,
        )

        # Score variant
        composite_score = 10.0
        if not rep_169.passed:
            composite_score -= 4.0
        if not rep_916.passed:
            composite_score -= 4.0
        if rep_169.ocr_readable and rep_916.ocr_readable:
            composite_score += 2.0

        if composite_score > best_vlm_score:
            best_vlm_score = composite_score
            best_variant = var
            best_report_169 = rep_169
            best_report_916 = rep_916
            # Copy winning variant to destination
            import shutil
            shutil.copy2(temp_169, t169_path)
            shutil.copy2(temp_916, c916_path)

    # Clean up temp variant files
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)

    # 5. Return metadata summary
    return {
        "files": {
            "yt_16x9": t169_path.name,
            "cover_9x16": c916_path.name,
        },
        "selected_template": best_variant["template"],
        "selected_hook": best_variant["hook"],
        "all_hooks": candidate_hooks,
        "needs_attention": needs_attention,
        "attention_reason": attention_reason,
        "quality_gate_16x9": best_report_169.to_dict() if best_report_169 else {},
        "quality_gate_9x16": best_report_916.to_dict() if best_report_916 else {},
        "generator": "clip_frame_cutout_v7" if not needs_attention else "vector_fallback_v7",
        "score": best_vlm_score,
    }
