"""Stage 3: Final 1080x1920 clip rendering with NVENC, two-pass loudnorm, and QA checks."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path

from app.core import paths
from app.core.errors import FfmpegFailed
from app.core.schemas import QAReport
from app.utils.ffmpeg import has_encoder, probe, run_ffmpeg
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
    is_non_final_part: bool = False,
    dur: float | None = None,
) -> tuple[Path, QAReport]:
    """Render final 1080x1920 clip.mp4 with subtitles burned in and audio normalized."""
    import os
    clip_dir = Path(clip_dir)
    framed_file = clip_dir / "fx.mp4" if (clip_dir / "fx.mp4").is_file() else (clip_dir / "framed.mp4")
    if not framed_file.is_file():
        raise FileNotFoundError(f"Neither fx.mp4 nor framed.mp4 found in {clip_dir}")

    # Prepare audio source
    clean_audio = clip_dir / "audio_clean.wav"
    sfx_mix = clip_dir / "sfx_mix.wav"
    audio_mix = clip_dir / "audio_mix.wav"

    if not clean_audio.is_file() and framed_file.is_file():
        # Extract audio track from framed_file if audio_clean.wav is missing
        extract_cmd = ["-i", framed_file.name, "-vn", "-c:a", "pcm_s16le", "-ar", "48000", clean_audio.name]
        try:
            run_ffmpeg(extract_cmd, cwd=clip_dir, check=True)
        except Exception as exc:
            logger.debug("Failed extracting audio from %s: %s", framed_file, exc)

    if sfx_mix.is_file() and clean_audio.is_file():
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
    elif sfx_mix.is_file():
        audio_mix = sfx_mix
    else:
        # Fall back to extracting framed_file audio directly
        audio_mix = clean_audio
        extract_cmd = ["-i", framed_file.name, "-vn", "-c:a", "pcm_s16le", "-ar", "48000", clean_audio.name]
        run_ffmpeg(extract_cmd, cwd=clip_dir, check=True)

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

    if is_non_final_part and dur:
        af_loudnorm = f"apad=pad_dur=1.8,afade=t=out:st={dur:.3f}:d=1.8,{af_loudnorm}"
    elif dur:
        fade_st = max(0.0, dur - 0.20)
        af_loudnorm = f"afade=t=out:st={fade_st:.3f}:d=0.20,{af_loudnorm}"

    # Subtitle filter (relative path with fontsdir=fonts)
    ass_file = clip_dir / "captions.ass"
    vf_chain: list[str] = []
    if is_non_final_part:
        vf_chain.append("tpad=stop_duration=1.8:stop_mode=clone")
    if has_captions and ass_file.is_file():
        vf_chain.append("ass=captions.ass:fontsdir=fonts")

    out_clip = clip_dir / "clip.mp4"
    tmp_out = clip_dir / f"clip.tmp.{os.getpid()}.mp4"
    if tmp_out.exists():
        tmp_out.unlink()

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
        tmp_out.name,
    ])

    try:
        run_ffmpeg(render_cmd, cwd=clip_dir, check=True)
        if tmp_out.is_file():
            os.replace(tmp_out, out_clip)
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
                tmp_out.name,
            ])
            run_ffmpeg(render_cmd_fallback, cwd=clip_dir, check=True)
            if tmp_out.is_file():
                os.replace(tmp_out, out_clip)
        else:
            raise

    # Verify rendered output with QA suite
    qa_report = check_clip_file(out_clip, cut_points=cut_points)
    if not qa_report.passed:
        logger.warning("Rendered clip %s failed QA checks: %s", out_clip.name, qa_report.failures)

    return out_clip, qa_report


def render_framed_and_audio(
    seg_path: Path,
    rel_start: float,
    dur: float,
    clip_dir: Path,
    layout: str = "gameplay",
    cam_rect: list[float] | None = None,
    fps: float = 30.0,
) -> tuple[Path, Path]:
    """Render 1080x1920 framed.mp4 (clean video layout without captions) and extract 48kHz audio_clean.wav."""
    import os
    clip_dir = Path(clip_dir)
    clip_dir.mkdir(parents=True, exist_ok=True)
    out_framed = clip_dir / "framed.mp4"
    out_audio = clip_dir / "audio_clean.wav"

    fps_val = min(60.0, max(24.0, fps))
    gop_size = int(2 * fps_val)
    use_nvenc = has_encoder("h264_nvenc")

    # 1. Video filter graph for 1080x1920 layout
    if layout == "facecam" and cam_rect and len(cam_rect) == 4:
        info = probe(seg_path)
        sw, sh = info.width, info.height
        rx, ry, rw, rh = cam_rect
        cx_px = int(rx * sw)
        cy_px = int(ry * sh)
        cw_px = max(100, int(rw * sw))
        ch_px = max(50, int(rh * sh))
        v_filter = (
            f"[0:v]split=3[bg_in][gp_in][cam_in];"
            f"[bg_in]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,scale=1080:1920:flags=fast_bilinear,eq=brightness=-0.12:saturation=1.1[bg];"
            f"[gp_in]scale=1080:608[gp];"
            f"[cam_in]crop=w={cw_px}:h={ch_px}:x={cx_px}:y={cy_px},scale=1080:560:flags=fast_bilinear[cam];"
            f"[bg][gp]overlay=0:300[bg_gp];"
            f"[bg_gp][cam]overlay=0:930[v_out]"
        )
    elif layout == "talking_head":
        v_filter = "[0:v]crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=fast_bilinear[v_out]"
    else:  # gameplay default
        v_filter = (
            "[0:v]split=2[bg_in][fg_in];"
            "[bg_in]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,scale=1080:1920:flags=fast_bilinear,eq=brightness=-0.12:saturation=1.1[bg];"
            "[fg_in]scale=1080:608:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[v_out]"
        )

    if use_nvenc:
        v_enc_args = [
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
        v_enc_args = [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "18",
            "-maxrate", "16M",
            "-bufsize", "32M",
        ]

    tmp_framed = clip_dir / f"framed.tmp.{os.getpid()}.mp4"
    if tmp_framed.exists():
        tmp_framed.unlink()

    cmd_video = [
        "-ss", f"{rel_start:.3f}",
        "-t", f"{dur:.3f}",
        "-i", str(seg_path.resolve()),
        "-filter_complex", v_filter,
        "-map", "[v_out]",
        "-an",
        *v_enc_args,
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-r", str(round(fps_val)),
        "-g", str(gop_size),
        "-movflags", "+faststart",
        str(tmp_framed.resolve()),
    ]

    try:
        run_ffmpeg(cmd_video, cwd=clip_dir, check=True)
        if tmp_framed.is_file():
            os.replace(tmp_framed, out_framed)
    except FfmpegFailed as e:
        if use_nvenc:
            logger.warning("NVENC framed render failed (%s); retrying with CPU libx264...", e)
            v_enc_cpu = [
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "18",
                "-maxrate", "16M",
                "-bufsize", "32M",
            ]
            cmd_fallback = [
                "-ss", f"{rel_start:.3f}",
                "-t", f"{dur:.3f}",
                "-i", str(seg_path.resolve()),
                "-filter_complex", v_filter,
                "-map", "[v_out]",
                "-an",
                *v_enc_cpu,
                "-profile:v", "high",
                "-pix_fmt", "yuv420p",
                "-r", str(round(fps_val)),
                "-g", str(gop_size),
                "-movflags", "+faststart",
                str(tmp_framed.resolve()),
            ]
            run_ffmpeg(cmd_fallback, cwd=clip_dir, check=True)
            if tmp_framed.is_file():
                os.replace(tmp_framed, out_framed)
        else:
            raise

    # 2. Extract clean audio
    tmp_audio = clip_dir / f"audio_clean.tmp.{os.getpid()}.wav"
    if tmp_audio.exists():
        tmp_audio.unlink()

    cmd_audio = [
        "-ss", f"{rel_start:.3f}",
        "-t", f"{dur:.3f}",
        "-i", str(seg_path.resolve()),
        "-vn",
        "-c:a", "pcm_s16le",
        "-ar", "48000",
        "-ac", "2",
        str(tmp_audio.resolve()),
    ]
    run_ffmpeg(cmd_audio, cwd=clip_dir, check=True)
    if tmp_audio.is_file():
        os.replace(tmp_audio, out_audio)

    return out_framed, out_audio


def render_clip_fast_single_pass(
    seg_path: Path,
    rel_start: float,
    dur: float,
    clip_dir: Path,
    layout: str = "gameplay",
    cam_rect: list[float] | None = None,
    has_captions: bool = True,
    is_non_final_part: bool = False,
    sfx_wav: Path | None = None,
    fps: float = 30.0,
    cut_points: list[float] | None = None,
) -> tuple[Path, QAReport]:
    """Render 1080x1920 short in ONE unified FFmpeg pass (-ss before -i, bokeh, ASS, NVENC)."""
    clip_dir = Path(clip_dir)
    clip_dir.mkdir(parents=True, exist_ok=True)
    out_clip = clip_dir / "clip.mp4"
    tmp_out = clip_dir / f"clip.tmp.{os.getpid()}.mp4"
    if tmp_out.exists():
        tmp_out.unlink()

    fonts_dir = clip_dir / "fonts"
    _copy_fonts(fonts_dir)

    # 1. Video filter graph
    v_filters: list[str] = []
    if layout == "facecam" and cam_rect and len(cam_rect) == 4:
        info = probe(seg_path)
        sw, sh = info.width, info.height
        rx, ry, rw, rh = cam_rect
        cx_px = int(rx * sw)
        cy_px = int(ry * sh)
        cw_px = max(100, int(rw * sw))
        ch_px = max(50, int(rh * sh))
        v_filters.append(
            f"[0:v]split=3[bg_in][gp_in][cam_in];"
            f"[bg_in]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,scale=1080:1920:flags=fast_bilinear,eq=brightness=-0.12:saturation=1.1[bg];"
            f"[gp_in]scale=1080:608[gp];"
            f"[cam_in]crop=w={cw_px}:h={ch_px}:x={cx_px}:y={cy_px},scale=1080:560:flags=fast_bilinear[cam];"
            f"[bg][gp]overlay=0:300[bg_gp];"
            f"[bg_gp][cam]overlay=0:930[base]"
        )
    elif layout == "talking_head":
        v_filters.append(
            "[0:v]crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=fast_bilinear[base]"
        )
    else:  # gameplay default
        v_filters.append(
            "[0:v]split=2[bg_in][fg_in];"
            "[bg_in]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,scale=1080:1920:flags=fast_bilinear,eq=brightness=-0.12:saturation=1.1[bg];"
            "[fg_in]scale=1080:608:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]"
        )

    last_v = "base"
    if is_non_final_part:
        v_filters.append(f"[{last_v}]tpad=stop_duration=1.8:stop_mode=clone[padded]")
        last_v = "padded"

    ass_file = clip_dir / "captions.ass"
    if has_captions and ass_file.is_file():
        v_filters.append(f"[{last_v}]ass=captions.ass:fontsdir=fonts[v_out]")
    else:
        v_filters.append(f"[{last_v}]null[v_out]")

    filter_complex_str = ";".join(v_filters)

    # 2. Audio filters
    a_filters: list[str] = []
    has_sfx = bool(sfx_wav and sfx_wav.is_file())
    if has_sfx:
        a_filters.append("[1:a]volume=-12dB[sfx];[0:a][sfx]amix=inputs=2:normalize=0[a_base]")
        last_a = "a_base"
    else:
        last_a = "0:a"

    if is_non_final_part:
        a_filters.append(f"[{last_a}]apad=pad_dur=1.8,afade=t=out:st={dur:.3f}:d=1.8,loudnorm=I=-14:TP=-1.5:LRA=11[a_out]")
    else:
        fade_st = max(0.0, dur - 0.20)
        a_filters.append(f"[{last_a}]afade=t=out:st={fade_st:.3f}:d=0.20,loudnorm=I=-14:TP=-1.5:LRA=11[a_out]")

    full_filter_complex = filter_complex_str + ";" + ";".join(a_filters)

    # 3. Formulate FFmpeg command with -ss before -i
    fps_val = min(60.0, max(24.0, fps))
    gop_size = int(2 * fps_val)
    use_nvenc = has_encoder("h264_nvenc")

    if use_nvenc:
        v_enc_args = [
            "-c:v", "h264_nvenc",
            "-preset", "p5",
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", "21",
            "-b:v", "0",
            "-maxrate", "16M",
            "-bufsize", "32M",
        ]
    else:
        v_enc_args = [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-maxrate", "16M",
            "-bufsize", "32M",
        ]

    cmd = [
        "-ss", f"{rel_start:.3f}",
        "-t", f"{dur:.3f}",
        "-i", str(seg_path.resolve()),
    ]
    if has_sfx:
        cmd.extend(["-i", str(sfx_wav.resolve())])

    cmd.extend([
        "-filter_complex", full_filter_complex,
        "-map", "[v_out]",
        "-map", "[a_out]",
        *v_enc_args,
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-r", str(round(fps_val)),
        "-g", str(gop_size),
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-movflags", "+faststart",
        tmp_out.name,
    ])

    try:
        run_ffmpeg(cmd, cwd=clip_dir, check=True)
        if tmp_out.is_file():
            os.replace(tmp_out, out_clip)
    except FfmpegFailed as e:
        if use_nvenc:
            logger.warning("NVENC single-pass render failed (%s); retrying with CPU libx264...", e)
            v_enc_cpu = [
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "20",
                "-maxrate", "16M",
                "-bufsize", "32M",
            ]
            cmd_fallback = [
                "-ss", f"{rel_start:.3f}",
                "-t", f"{dur:.3f}",
                "-i", str(seg_path.resolve()),
            ]
            if has_sfx:
                cmd_fallback.extend(["-i", str(sfx_wav.resolve())])
            cmd_fallback.extend([
                "-filter_complex", full_filter_complex,
                "-map", "[v_out]",
                "-map", "[a_out]",
                *v_enc_cpu,
                "-profile:v", "high",
                "-pix_fmt", "yuv420p",
                "-r", str(round(fps_val)),
                "-g", str(gop_size),
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "48000",
                "-movflags", "+faststart",
                tmp_out.name,
            ])
            run_ffmpeg(cmd_fallback, cwd=clip_dir, check=True)
            if tmp_out.is_file():
                os.replace(tmp_out, out_clip)
        else:
            raise

    qa_report = check_clip_file(out_clip, cut_points=cut_points)
    if not qa_report.passed:
        logger.warning("Single-pass rendered clip %s failed QA checks: %s", out_clip.name, qa_report.failures)

    return out_clip, qa_report
