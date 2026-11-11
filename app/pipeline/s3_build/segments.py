"""Stage 3: Plan and download video segments covering all planned clips."""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.errors import DownloadFailed
from app.core.schemas import Clip, Plan, Segment, SegmentsArtifact, SourceInfo
from app.pipeline.context import JobContext
from app.utils.ffmpeg import probe

logger = logging.getLogger("app.pipeline.s3_build.segments")


def plan_segments(
    clips: list[Clip],
    source_duration: float,
    small_video_min: int = 40,
) -> list[Segment]:
    """Calculate minimal non-redundant video ranges to download covering all planned clips."""
    if not clips:
        return []

    # If full video is <= 40 minutes, download as a single full segment
    if source_duration <= (small_video_min * 60.0):
        all_ids = [c.id for c in clips]
        return [
            Segment(
                id="seg01",
                s=0.0,
                e=round(source_duration, 3),
                path="seg01.mkv",
                clip_ids=all_ids,
            )
        ]

    # Expand each clip by 6s padding on both sides
    raw_ranges: list[tuple[float, float, str]] = []
    for c in clips:
        s = max(0.0, c.start - 6.0)
        e = min(source_duration, c.end + 6.0)
        raw_ranges.append((s, e, c.id))

    raw_ranges.sort(key=lambda r: r[0])

    # Merge overlapping or close ranges (gap < 20s)
    merged: list[dict] = []
    for s, e, cid in raw_ranges:
        if not merged:
            merged.append({"s": s, "e": e, "cids": [cid]})
            continue

        prev = merged[-1]
        if s <= (prev["e"] + 20.0):
            # Extend previous segment
            prev["e"] = max(prev["e"], e)
            if cid not in prev["cids"]:
                prev["cids"].append(cid)
        else:
            merged.append({"s": s, "e": e, "cids": [cid]})

    segments: list[Segment] = []
    for idx, item in enumerate(merged):
        seg_id = f"seg{idx + 1:02d}"
        segments.append(
            Segment(
                id=seg_id,
                s=round(item["s"], 3),
                e=round(item["e"], 3),
                path=f"{seg_id}.mkv",
                clip_ids=item["cids"],
            )
        )

    return segments


def segment_for(clip: Clip, segments: list[Segment]) -> tuple[Segment, float]:
    """Find the Segment containing this clip and calculate offset from segment start."""
    for seg in segments:
        if seg.s <= clip.start + 0.5 and seg.e >= clip.end - 0.5:
            offset = max(0.0, clip.start - seg.s)
            return seg, round(offset, 3)

    # Fallback to closest segment
    closest = min(segments, key=lambda s: abs(s.s - clip.start))
    offset = max(0.0, clip.start - closest.s)
    return closest, round(offset, 3)


def download_segment(
    url: str,
    seg: Segment,
    out_path: Path,
    max_height: int = 1080,
    is_full: bool = False,
) -> Path:
    """Download single segment using yt-dlp or slice from local file."""
    if Path(url).is_file():
        from app.utils.ffmpeg import run_ffmpeg
        out_mkv = out_path.with_suffix(".mkv")
        cmd = [
            "-ss", f"{seg.s:.3f}",
            "-to", f"{seg.e:.3f}",
            "-i", url,
            "-c:v", "copy",
            "-c:a", "copy",
            str(out_mkv),
        ]
        run_ffmpeg(cmd, check=True)
        return out_mkv

    import yt_dlp

    format_selector = (
        f"bv*[height<={max_height}][vcodec^=avc1]+ba[ext=m4a]/"
        f"bv*[height<={max_height}]+ba/b[height<={max_height}]"
    )

    ydl_opts: dict = {
        "format": format_selector,
        "outtmpl": str(out_path.with_suffix("")),
        "merge_output_format": "mkv",
        "quiet": True,
        "no_warnings": True,
        "overwrites": True,
    }

    if not is_full:
        ydl_opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(seg.s, seg.e)])
        ydl_opts["force_keyframes_at_cuts"] = True

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        raise DownloadFailed(f"Failed to download video segment {seg.id}: {e}") from e

    # Find the resulting file
    mkv_candidate = out_path.with_suffix(".mkv")
    if mkv_candidate.is_file():
        return mkv_candidate
    if out_path.is_file():
        return out_path

    # Check any file matching seg name
    candidates = list(out_path.parent.glob(f"{seg.id}*"))
    if candidates:
        return candidates[0]

    raise DownloadFailed(f"Expected segment output file {out_path} not found after download")


def run(ctx: JobContext) -> None:
    """Execute Stage 3 segment planning and downloading."""
    if ctx.artifact_ok("segments.json", SegmentsArtifact):
        logger.info("[%s] segments.json already exists and validates; skipping segments stage", ctx.job_id)
        return

    plan = ctx.read_artifact("plan.json", Plan)
    source_info = ctx.read_artifact("source_info.json", SourceInfo)

    if not plan.clips:
        logger.info("[%s] No clips in plan.json; saving empty segments.json", ctx.job_id)
        ctx.write_artifact("segments.json", SegmentsArtifact(segments=[]))
        return

    segments = plan_segments(plan.clips, source_info.duration_s, small_video_min=40)
    is_full = len(segments) == 1 and segments[0].s == 0.0 and segments[0].e >= source_info.duration_s - 1.0

    max_h = getattr(ctx.options, "max_source_height", None) or getattr(ctx.options, "max_height", 1080) or 1080

    for idx, seg in enumerate(segments):
        ctx.check_cancel()
        frac = idx / max(1, len(segments))
        ctx.progress("segments", frac, f"Downloading video segment {idx + 1}/{len(segments)} ({seg.s:.0f}s-{seg.e:.0f}s)...")

        out_file = ctx.work_dir / seg.path
        if not out_file.is_file() or out_file.stat().st_size == 0:
            download_segment(source_info.url, seg, out_file, max_height=max_h, is_full=is_full)

        # Verify with ffprobe
        info = probe(out_file)
        if not info.has_audio or info.width == 0:
            raise DownloadFailed(f"Segment {seg.id} downloaded but contains missing audio or video streams")

    # Generate lightweight 480p 5fps proxy for fast visual sensors and VLM frame sampling
    proxy_mp4 = ctx.work_dir / "proxy_480p.mp4"
    if not proxy_mp4.is_file() and segments:
        first_seg = ctx.work_dir / segments[0].path
        if first_seg.is_file():
            try:
                from app.utils.ffmpeg import has_encoder, run_ffmpeg
                v_enc = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "26"] if has_encoder("h264_nvenc") else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28"]
                cmd = [
                    "-i", str(first_seg),
                    "-vf", "scale=-2:480,fps=5",
                    "-an",
                    *v_enc,
                    str(proxy_mp4),
                ]
                run_ffmpeg(cmd, check=False)
                logger.info("[%s] Generated 480p 5fps proxy for visual sensors: %s", ctx.job_id, proxy_mp4.name)
            except Exception as e:
                logger.debug("[%s] Failed creating proxy: %s", ctx.job_id, e)

    ctx.write_artifact("segments.json", SegmentsArtifact(segments=segments))
    ctx.progress("segments", 1.0, f"All {len(segments)} video segments downloaded and verified")
