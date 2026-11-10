"""Stage 3: Final 1080x1920 clip rendering with NVENC, two-pass loudnorm, and QA checks."""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from app.core import paths
from app.core.errors import FfmpegFailed
from app.core.schemas import QAReport
from app.utils.ffmpeg import has_encoder, run_ffmpeg
from app.utils.qa import check_clip_file

logger = logging.getLogger("app.pipeline.s3_build.final_render")


def _copy_fonts(dest_dir: Path) -> None:
    """Copy project fonts into fonts/ directory relative to clip work folder for ffmpeg ass filter."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    src_fonts = paths.fonts_dir()
    if src_fonts.is_dir():
        for f in src_fonts.glob("*.ttf"):
            dest_file = dest_dir / f.name
            if not dest_file.exists():
                shutil.copy2(f, dest_file)


def _measure_loudnorm_pass1(audio_file: Path) -> dict[str, str]:
    """Measure EBU R128 loudness targeting -14 LUFS and -1.5 dBTP."""
    cmd = [
        "-i", audio_file.name,
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    res = run_ffmpeg(cmd, cwd=audio_file.parent, check=False)
    stderr = res.stderr

    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.DOTALL)
    if not match:
        logger.warning("Could not parse loudnorm pass 1 JSON from stderr; using defaults")
        return {
            "input_i": "-24.0",
            "input_tp": "-1.5",
            "input_lra": "7.0",
            "input_thresh": "-34.0",
            "target_offset": "0.0",
        }

    try:
        return json.loads(match.group(0))
    except Exception:
        return {
            "input_i": "-24.0",
            "input_tp": "-1.5",
            "input_lra": "7.0",
            "input_thresh": "-34.0",
            "target_offset": "0.0",
        }


def render_final(
    clip_dir: Path,
    fps: float = 30.0,
    has_captions: bool = True,
    cut_points: list[float] | None = None,
) -> tuple[Path, QAReport]:
    """Render final 1080x1920 clip.mp4 with subtitles burned in and audio normalized."""
    clip_dir = Path(clip_dir)
    framed_file = clip_dir / "fx.mp4" if (clip_dir / "fx.mp4").is_file() else (clip_dir / "framed.mp4")
    if not framed_file.is_file():
        raise FileNotFoundError(f"Neither fx.mp4 nor framed.mp4 found in {clip_dir}")

    # Prepare audio source
    clean_audio = clip_dir / "audio_clean.wav"
    sfx_mix = clip_dir / "sfx_mix.wav"
    audio_mix = clip_dir / "audio_mix.wav"

    if sfx_mix.is_file():
        # Mix clean speech with SFX (-12 dB)
        mix_cmd = [
            "-i", clean_audio.name,
            "-i", sfx_mix.name,
            "-filter_complex", "[1:a]volume=-12dB[sfx];[0:a][sfx]amix=inputs=2:normalize=0[a]",
            "-map", "[a]",
            "-c:a", "pcm_s16le",
            "-ar", "48000",
            audio_mix.name,
        ]
        run_ffmpeg(mix_cmd, cwd=clip_dir, check=True)
    elif clean_audio.is_file():
        audio_mix = clean_audio
    else:
        raise FileNotFoundError(f"audio_clean.wav not found in {clip_dir}")

    # Copy fonts to fonts/ subdir for ass filter
    fonts_dir = clip_dir / "fonts"
    _copy_fonts(fonts_dir)

    # Pass 1: Measure loudness
    ln = _measure_loudnorm_pass1(audio_mix)
    af_loudnorm = (
        f"loudnorm=I=-14:TP=-1.5:LRA=11:"
        f"measured_I={ln.get('input_i', '-24.0')}:"
        f"measured_TP={ln.get('input_tp', '-1.5')}:"
        f"measured_LRA={ln.get('input_lra', '7.0')}:"
        f"measured_thresh={ln.get('input_thresh', '-34.0')}:"
        f"offset={ln.get('target_offset', '0.0')}:"
        f"linear=true"
    )

    # Subtitle filter (relative path with fontsdir=fonts)
    ass_file = clip_dir / "captions.ass"
    vf_chain: list[str] = []
    if has_captions and ass_file.is_file():
        vf_chain.append("ass=captions.ass:fontsdir=fonts")

    out_clip = clip_dir / "clip.mp4"
    fps_val = min(60.0, max(24.0, fps))
    gop_size = int(2 * fps_val)

    # Hardware acceleration args
    use_nvenc = has_encoder("h264_nvenc")
    if use_nvenc:
        v_args = [
            "-c:v", "h264_nvenc",
            "-preset", "p5",
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", "19",
            "-b:v", "0",
            "-maxrate", "16M",
            "-bufsize", "32M",
        ]
    else:
        v_args = [
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-maxrate", "16M",
            "-bufsize", "32M",
        ]

    render_cmd = [
        "-i", framed_file.name,
        "-i", audio_mix.name,
    ]
    if vf_chain:
        render_cmd.extend(["-vf", ",".join(vf_chain)])

    render_cmd.extend([
        "-af", af_loudnorm,
        *v_args,
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-r", str(round(fps_val)),
        "-g", str(gop_size),
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-movflags", "+faststart",
        "-shortest",
        out_clip.name,
    ])

    try:
        run_ffmpeg(render_cmd, cwd=clip_dir, check=True)
    except FfmpegFailed as e:
        if use_nvenc:
            logger.warning("NVENC render failed (%s); retrying with CPU libx264...", e)
            # Replace NVENC with libx264
            v_args_fallback = [
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "18",
                "-maxrate", "16M",
                "-bufsize", "32M",
            ]
            render_cmd_fallback = [
                "-i", framed_file.name,
                "-i", audio_mix.name,
            ]
            if vf_chain:
                render_cmd_fallback.extend(["-vf", ",".join(vf_chain)])
            render_cmd_fallback.extend([
                "-af", af_loudnorm,
                *v_args_fallback,
                "-profile:v", "high",
                "-pix_fmt", "yuv420p",
                "-r", str(round(fps_val)),
                "-g", str(gop_size),
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "48000",
                "-movflags", "+faststart",
                "-shortest",
                out_clip.name,
            ])
            run_ffmpeg(render_cmd_fallback, cwd=clip_dir, check=True)
        else:
            raise

    # Verify rendered output with QA suite
    qa_report = check_clip_file(out_clip, cut_points=cut_points)
    if not qa_report.passed:
        logger.warning("Rendered clip %s failed QA checks: %s", out_clip.name, qa_report.failures)

    return out_clip, qa_report
