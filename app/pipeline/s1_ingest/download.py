"""Audio downloading (16 kHz mono WAV) and video segment range downloads using yt-dlp."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from app.core.errors import DiskSpace, DownloadFailed
from app.core.schemas import SourceInfo
from app.pipeline.context import JobContext
from app.utils.ffmpeg import probe

logger = logging.getLogger("app.pipeline.s1_ingest.download")


def _check_disk_space(target_dir: Path, source_duration_s: float, min_free_gb: int = 30) -> None:
    """Ensure sufficient disk space exists before initiating large downloads."""
    target_dir.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(target_dir)
    free_gb = usage.free / (1024**3)

    # Estimate: 0.05 GB/hr for audio + 2 GB buffer
    hours = source_duration_s / 3600.0
    needed_gb = (hours * 0.05) + 2.0

    if free_gb < (needed_gb + min_free_gb):
        logger.error(
            "Disk space guard failed: have %.1f GB, need %.1f GB + %d GB safety threshold",
            free_gb,
            needed_gb,
            min_free_gb,
        )
        raise DiskSpace(needed_gb=needed_gb + min_free_gb, have_gb=free_gb)


def download_audio(ctx: JobContext) -> Path:
    """Download audio track from YouTube and convert to 16 kHz mono WAV."""
    final_wav = ctx.work_dir / "audio.wav"
    if final_wav.is_file() and final_wav.stat().st_size > 1000:
        logger.info("[%s] audio.wav already exists and is non-empty; skipping download", ctx.job_id)
        return final_wav

    source_info = ctx.read_artifact("source_info.json", SourceInfo)
    _check_disk_space(ctx.work_dir, source_info.duration_s, ctx.settings.min_free_gb)

    import yt_dlp

    ctx.progress("audio_download", 0.05, "Starting audio stream download from YouTube...")

    out_tmpl = str(ctx.work_dir / "audio_src.%(ext)s")

    def progress_hook(d: dict[str, Any]) -> None:
        ctx.check_cancel()
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            if total > 0:
                fraction = min(0.90, 0.10 + 0.80 * (downloaded / total))
                mb = downloaded / (1024 * 1024)
                total_mb = total / (1024 * 1024)
                ctx.progress(
                    "audio_download",
                    fraction,
                    f"Downloading audio: {mb:.1f} / {total_mb:.1f} MB ({d.get('_speed_str', '')})",
                )

    ydl_opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": out_tmpl,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
        }],
        "postprocessor_args": [
            "-ar",
            "16000",
            "-ac",
            "1",
        ],
        "noplaylist": True,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 4,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([source_info.url])
    except Exception as first_err:
        logger.warning("[%s] Audio download failed (%s). Attempting yt-dlp update and retry...", ctx.job_id, first_err)
        try:
            from scripts.update_ytdlp import update_ytdlp

            update_ytdlp()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([source_info.url])
        except Exception as retry_err:
            raise DownloadFailed(
                f"Audio download failed after retry: {retry_err}",
                hint="Verify YouTube URL, internet connectivity, or check if video is restricted",
            ) from retry_err

    # Look for extracted wav file
    candidate_wav = ctx.work_dir / "audio_src.wav"
    if not candidate_wav.exists():
        # Search directory for any generated wav file
        wavs = list(ctx.work_dir.glob("*.wav"))
        if wavs:
            candidate_wav = wavs[0]
        else:
            raise DownloadFailed("FFmpeg audio extraction failed to produce a WAV file")

    if candidate_wav != final_wav:
        if final_wav.exists():
            final_wav.unlink()
        os.replace(candidate_wav, final_wav)

    # Verify audio file with ffprobe
    p_info = probe(final_wav)
    if not p_info.has_audio:
        raise DownloadFailed("Downloaded audio file has no valid audio stream")

    if abs(p_info.duration - source_info.duration_s) > 3.0 and source_info.duration_s > 10.0:
        logger.warning(
            "Audio duration mismatch: expected %.1fs, got %.1fs",
            source_info.duration_s,
            p_info.duration,
        )

    ctx.progress("audio_download", 1.0, f"Audio download complete ({p_info.duration:.1f}s, 16 kHz mono)")
    return final_wav


def download_range(
    url: str,
    s: float,
    e: float,
    out_path: Path,
    max_height: int = 1080,
    progress_cb: Any = None,
) -> Path:
    """Download a specific time range of video at requested resolution."""
    import yt_dlp

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(out_path.with_suffix("")) + ".%(ext)s"

    h = max(360, min(1440, max_height))
    fmt = f"bv*[height<={h}][vcodec^=avc1]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]"

    def internal_hook(d: dict[str, Any]) -> None:
        if progress_cb and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            frac = (downloaded / total) if total > 0 else 0.0
            progress_cb(frac, d.get("_speed_str", ""))

    ydl_opts: dict[str, Any] = {
        "format": fmt,
        "outtmpl": out_tmpl,
        "download_ranges": yt_dlp.utils.download_range_func(None, [(max(0.0, s), max(s + 1.0, e))]),
        "force_keyframes_at_cuts": True,
        "merge_output_format": "mkv",
        "noplaylist": True,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 4,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [internal_hook] if progress_cb else [],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Find the resulting file
    expected_mkv = out_path.with_suffix(".mkv")
    if expected_mkv.exists():
        if expected_mkv != out_path:
            if out_path.exists():
                out_path.unlink()
            os.replace(expected_mkv, out_path)
        return out_path

    # Fallback to search any generated video file
    for cand in out_path.parent.glob(out_path.stem + ".*"):
        if cand.suffix.lower() in (".mkv", ".mp4", ".webm"):
            if cand != out_path:
                if out_path.exists():
                    out_path.unlink()
                os.replace(cand, out_path)
            return out_path

    raise DownloadFailed(f"Failed to produce video segment for range [{s:.1f}, {e:.1f}]")


def run(ctx: JobContext) -> None:
    """Execute Stage 1: audio_download."""
    download_audio(ctx)
