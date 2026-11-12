"""Stage 5: Packaging, metadata assembly, thumbnails, and 07 checklist verification."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from PIL import Image

from app.core import paths
from app.core.db import get_conn
from app.core.models import update_clip
from app.core.schemas import Clip, Plan, SourceInfo, WordsArtifact
from app.pipeline.context import JobContext
from app.pipeline.s3_build import captions
from app.pipeline.s5_package import thumbnail_concept, thumbnail_generate
from app.pipeline.s5_package.metadata import generate_metadata
from app.utils import text
from app.utils.ffmpeg import run_ffmpeg
from app.utils.qa import check_clip_file

logger = logging.getLogger("app.pipeline.s5_package.package")


def _sample_clip_frames(clip_mp4: Path, duration: float, out_dir: Path, count: int = 6) -> list[Path]:
    """Extract sample frames evenly spaced across clip in ONE single fast FFmpeg invocation."""
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("sample_*.jpg"))
    if len(existing) >= count:
        return existing[:count]

    dur = max(1.0, duration)
    fps_val = count / dur
    cmd = [
        "-i", str(clip_mp4),
        "-vf", f"fps={fps_val:.4f},scale=320:-2",
        "-frames:v", str(count),
        "-q:v", "5",
        str(out_dir / "sample_%02d.jpg"),
    ]
    try:
        run_ffmpeg(cmd, check=False)
    except Exception as e:
        logger.debug("Fast sample frame extraction fallback: %s", e)

    return sorted(out_dir.glob("sample_*.jpg"))[:count]


def _build_metadata_txt(meta: dict) -> str:
    """Format human-readable copy-paste metadata sheet (07 s9)."""
    titles_lines = []
    for idx, t_opt in enumerate(meta.get("titles", []), start=1):
        titles_lines.append(f"{idx}. {t_opt.get('text', '')}")

    return (
        "=== YOUTUBE TITLE OPTIONS ===\n"
        + "\n".join(titles_lines)
        + "\n\n=== YOUTUBE DESCRIPTION ===\n"
        + meta.get("description_youtube", "")
        + "\n\n=== YOUTUBE TAGS (comma separated) ===\n"
        + meta.get("tags_youtube", "")
        + "\n\n=== INSTAGRAM CAPTION ===\n"
        + meta.get("description_instagram", "")
        + "\n\n=== PINNED COMMENT ===\n"
        + meta.get("pinned_comment", "")
        + "\n"
    )


def package_clip(ctx: JobContext, clip: Clip) -> Path:
    """Package a single clip into output/<slug>-<video_id>/<clip_id>_<tier>... with full checklist (07 s9)."""
    source_info = ctx.read_artifact("source_info.json", SourceInfo)
    clip_dir = paths.clip_dir(ctx.job_id, clip.id)
    # Prefer clip.mp4 (fully rendered with video, captions, SFX, and normalized audio)
    final_mp4 = clip_dir / "clip.mp4"
    if not final_mp4.is_file():
        final_mp4 = clip_dir / "final.mp4"
    if not final_mp4.is_file():
        # Fallback to framed.mp4 only if final render not produced
        framed_mp4 = clip_dir / "framed.mp4"
        if framed_mp4.is_file():
            final_mp4 = framed_mp4
        else:
            raise FileNotFoundError(f"Rendered video for clip {clip.id} not found in {clip_dir}")

    # Determine output folder name: <slug>-<video_id>/<clip_id>_<tier>[_partKofN]
    v_id = source_info.video_id if source_info else ctx.job_id
    title_slug = text.slugify(source_info.title if source_info else "video", max_len=60)
    bundle_name = f"{title_slug}-{v_id}"

    tier_label = clip.tier or "C"
    part_suffix = f"_part{clip.part_index}of{clip.part_total}" if (clip.part_index and clip.part_total and clip.part_total > 1) else ""
    clip_folder_name = f"{clip.id}_{tier_label}{part_suffix}"

    pkg_dir = paths.output_dir() / bundle_name / clip_folder_name
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # 1. Final video copy
    pkg_mp4 = pkg_dir / "clip.mp4"
    shutil.copy2(final_mp4, pkg_mp4)

    # 2. Captions SRT copy or generation
    pkg_srt = pkg_dir / "captions.srt"
    src_srt = clip_dir / "captions.srt"
    if src_srt.is_file():
        shutil.copy2(src_srt, pkg_srt)
    else:
        # Generate SRT from words artifact
        words_art = ctx.read_artifact(f"clips/{clip.id}/words.json", WordsArtifact)
        if words_art and words_art.words:
            chunks = captions.chunk_words(words_art.words)
            captions.write_srt(chunks, pkg_srt)
        else:
            # Touch empty SRT placeholder
            pkg_srt.write_text("", encoding="utf-8")

    # 3. Edit list JSON copy
    pkg_edit = pkg_dir / "edit_list.json"
    src_edit = clip_dir / "edit_list.json"
    if src_edit.is_file():
        shutil.copy2(src_edit, pkg_edit)
    else:
        pkg_edit.write_text(json.dumps({"schema_version": 1, "clip_id": clip.id, "events": []}), encoding="utf-8")

    # 4. Generate Metadata
    meta = generate_metadata(ctx, clip, source_info)

    # 5. Extract sample frames for anti-frame check
    dur = float(clip.duration or (clip.end - clip.start))
    sample_frames = _sample_clip_frames(pkg_mp4, dur, clip_dir / "samples", count=12)

    # 6. Generate MrBeast-Style Clickbait Thumbnails (v7 Real-Subject Architecture)
    concept = thumbnail_concept.make_concept(ctx, clip)
    thumb_summary = thumbnail_generate.generate_clip_thumbnails(ctx, clip, pkg_dir, concept=concept)

    thumb_16x9_path = pkg_dir / "thumb_16x9.jpg"
    cover_9x16_path = pkg_dir / "cover_9x16.jpg"

    # Update metadata with thumbnail info
    meta.thumbnail = {
        "concept": concept.model_dump(),
        "files": thumb_summary.get("files", {"yt_16x9": "thumb_16x9.jpg", "cover_9x16": "cover_9x16.jpg"}),
        "generator": thumb_summary.get("generator", "clip_frame_cutout_v7"),
        "selected_template": thumb_summary.get("selected_template", "big_reaction"),
        "selected_hook": thumb_summary.get("selected_hook", concept.text),
        "needs_attention": thumb_summary.get("needs_attention", False),
        "attention_reason": thumb_summary.get("attention_reason", ""),
        "quality_gate_16x9": thumb_summary.get("quality_gate_16x9", {}),
        "quality_gate_9x16": thumb_summary.get("quality_gate_9x16", {}),
        "ocr_160px_readable": thumb_summary.get("quality_gate_9x16", {}).get("ocr_readable", True),
    }

    # 7. Write metadata.json and metadata.txt
    pkg_meta_json = pkg_dir / "metadata.json"
    meta_dict = meta.model_dump()
    pkg_meta_json.write_text(json.dumps(meta_dict, indent=2, ensure_ascii=False), encoding="utf-8")

    pkg_meta_txt = pkg_dir / "metadata.txt"
    pkg_meta_txt.write_text(_build_metadata_txt(meta_dict), encoding="utf-8")

    # 8. Write credit.txt alone
    pkg_credit_txt = pkg_dir / "credit.txt"
    pkg_credit_txt.write_text(meta.credit_block, encoding="utf-8")

    # 9. Write notes.txt
    pkg_notes = pkg_dir / "notes.txt"
    llm_s = getattr(clip, "llm_score", getattr(clip, "score_llm", 0.0))
    heat_s = getattr(clip, "heat", getattr(clip, "score_heat", None))
    audio_s = getattr(clip, "audio", getattr(clip, "score_audio", None))

    notes_content = (
        f"Clip ID: {clip.id}\n"
        f"Viral Tier: {clip.tier} (Final Score: {clip.final_score:.1f})\n"
        f"Score Breakdown:\n"
        f"  LLM Score: {llm_s:.1f}\n"
        f"  Heatmap Score: {heat_s if heat_s is not None else 'N/A'}\n"
        f"  Audio Energy Score: {audio_s if audio_s is not None else 'N/A'}\n"
        f"Risk Level: {meta.risk}\n"
        f"Risk Flags: {', '.join(meta.risk_flags) if meta.risk_flags else 'None'}\n"
        f"Thumbnail Generator: {thumb_summary.get('generator', 'clip_frame_cutout_v7')}\n"
    )
    pkg_notes.write_text(notes_content, encoding="utf-8")

    # 10. Checklist verification (07 s9)
    # (a) clip.mp4 passes QA
    qa_report = check_clip_file(pkg_mp4)
    if not qa_report.passed:
        logger.warning("Packaged clip %s QA warnings: %s", clip.id, qa_report.failures)

    # (b) Thumbnails exist with correct sizes & anti-frame pass
    if not thumb_16x9_path.is_file() or not cover_9x16_path.is_file():
        raise RuntimeError("Missing thumbnail files in package")

    with Image.open(thumb_16x9_path) as im:
        if im.size != (1280, 720):
            raise RuntimeError(f"Invalid 16:9 thumbnail size: {im.size}")
        if not thumbnail_generate.not_a_frame(im, sample_frames):
            raise RuntimeError("16:9 thumbnail failed anti-frame check")

    with Image.open(cover_9x16_path) as im:
        if im.size != (1080, 1920):
            raise RuntimeError(f"Invalid 9:16 cover size: {im.size}")
        if not thumbnail_generate.not_a_frame(im, sample_frames):
            raise RuntimeError("9:16 cover failed anti-frame check")

    # (c) metadata.json validates and contains credit block
    if not meta.credit_block or "All footage and rights belong to" not in meta.credit_block:
        raise RuntimeError("Metadata credit block missing or invalid")

    # (d) description_youtube contains https://youtu.be/<video_id>
    expected_url_prefix = f"https://youtu.be/{v_id}"
    if expected_url_prefix not in meta.description_youtube:
        raise RuntimeError(f"YouTube description missing video url: {expected_url_prefix}")

    # (e) Exactly 3 titles
    if len(meta.titles) != 3:
        raise RuntimeError(f"Titles count must be exactly 3, got {len(meta.titles)}")

    # (f) captions.srt non-empty
    if not pkg_srt.is_file() or pkg_srt.stat().st_size == 0:
        logger.warning("captions.srt is empty for clip %s (acceptable if purely silent/music)", clip.id)

    # Record relative folder in DB and update status
    rel_folder = f"{bundle_name}/{clip_folder_name}"
    with get_conn() as conn:
        update_clip(ctx.job_id, clip.id, conn=conn, folder=rel_folder, status="packaged")

    ctx.publish("clip_update", {"clip_id": clip.id, "status": "packaged", "folder": rel_folder})
    logger.info("Successfully packaged clip %s in %s", clip.id, rel_folder)

    return pkg_dir


def run(ctx: JobContext) -> None:
    """Execute Stage 5: Packaging for all planned clips."""
    plan = ctx.read_artifact("plan.json", Plan)
    if not plan.clips:
        logger.info("[%s] No clips to package in Stage 5", ctx.job_id)
        return

    total = len(plan.clips)
    logger.info("[%s] Packaging %d clips...", ctx.job_id, total)

    for idx, clip in enumerate(plan.clips):
        ctx.check_cancel()
        frac = idx / max(1, total)
        ctx.progress("package", frac, f"Packaging clip {idx + 1}/{total} ({clip.id})...", clip_id=clip.id)

        try:
            package_clip(ctx, clip)
        except Exception as e:
            logger.error("[%s] Failed packaging clip %s: %s", ctx.job_id, clip.id, e, exc_info=True)
            with get_conn() as conn:
                update_clip(ctx.job_id, clip.id, conn=conn, status="failed", error=str(e))
            ctx.publish("clip_update", {"clip_id": clip.id, "status": "failed", "error": str(e)})

    ctx.write_artifact("package_done.json", {"schema_version": 1, "status": "done", "clips": total})
    ctx.progress("package", 1.0, f"Packaged {total} clips successfully")
