"""Stage 3: Layout classification and 9:16 vertical video composition."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from app.core.schemas import LayoutArtifact
from app.pipeline.s3_build.face_track import FaceSample, track_face_trajectory
from app.utils.ffmpeg import has_encoder, probe, run_ffmpeg

logger = logging.getLogger("app.pipeline.s3_build.layout")


def detect_layout(
    samples: list[FaceSample],
    override: str | None = None,
    clip_id: str = "c01",
) -> LayoutArtifact:
    """Classify video into gameplay, talking_head, or facecam based on face presence and positions."""
    if override and override.lower() in ("gameplay", "talking_head", "facecam"):
        logger.info("Using layout override: %s", override)
        return LayoutArtifact(clip_id=clip_id, layout=override.lower(), confidence=1.0)

    if not samples:
        return LayoutArtifact(clip_id=clip_id, layout="gameplay", confidence=0.8, samples_count=0)

    # Filter samples with detections
    active_samples = [s for s in samples if s.faces]
    presence_ratio = len(active_samples) / max(1, len(samples))

    # If faces present in < 40% of samples -> gameplay
    if presence_ratio < 0.40:
        return LayoutArtifact(
            clip_id=clip_id,
            layout="gameplay",
            confidence=round(1.0 - presence_ratio, 2),
            samples_count=len(samples),
        )

    # Analyze primary face (largest area in each active sample)
    areas = []
    cxs = []
    cys = []
    boxes = []

    for s in active_samples:
        primary = max(s.faces, key=lambda f: f.area_ratio)
        areas.append(primary.area_ratio)
        cxs.append(primary.center_x)
        cys.append(primary.center_y)
        boxes.append((primary.x, primary.y, primary.w, primary.h))

    med_r = float(np.median(areas))
    med_cx = float(np.median(cxs))
    med_cy = float(np.median(cys))
    std_cx = float(np.std(cxs))

    # Rule 2: Large central face -> talking_head
    if med_r >= 0.06 and (0.20 <= med_cx <= 0.80) and (0.15 <= med_cy <= 0.85):
        return LayoutArtifact(
            clip_id=clip_id,
            layout="talking_head",
            confidence=0.95,
            samples_count=len(samples),
        )

    # Rule 3: Small corner/border face with static position -> facecam
    is_outer_border = med_cx < 0.30 or med_cx > 0.70 or med_cy < 0.25 or med_cy > 0.75
    if 0.004 <= med_r < 0.06 and is_outer_border and std_cx < 0.035:
        # Calculate cam_rect: median face expanded 1.7x with 1080:560 aspect ratio (1.9286)
        med_w = float(np.median([b[2] for b in boxes]))

        exp_w = min(1.0, med_w * 1.7)
        exp_h = exp_w / 1.9286  # Target cam panel aspect
        if exp_h > 1.0:
            exp_h = 1.0
            exp_w = exp_h * 1.9286

        cam_x = max(0.0, min(1.0 - exp_w, med_cx - (exp_w / 2.0)))
        cam_y = max(0.0, min(1.0 - exp_h, med_cy - (exp_h / 2.0)))

        return LayoutArtifact(
            clip_id=clip_id,
            layout="facecam",
            confidence=0.90,
            cam_rect=[round(cam_x, 4), round(cam_y, 4), round(exp_w, 4), round(exp_h, 4)],
            samples_count=len(samples),
        )

    # Rule 4: Default fallback -> gameplay
    return LayoutArtifact(
        clip_id=clip_id,
        layout="gameplay",
        confidence=0.85,
        samples_count=len(samples),
    )


def render_gameplay(cut_video: Path, out_framed: Path) -> Path:
    """Render gameplay layout: blurred background fill with 1:1 sharp centered foreground at y=560."""
    v_enc = [
        "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "16", "-b:v", "0",
    ] if has_encoder("h264_nvenc") else ["-c:v", "libx264", "-preset", "fast", "-crf", "16"]

    filter_graph = (
        "[0:v]split=2[bg_in][fg_in];"
        "[bg_in]scale=-2:1920,crop=1080:1920,boxblur=40:6,eq=brightness=-0.12:saturation=1.1[bg];"
        "[fg_in]scale=1080:-2[fg];"
        "[bg][fg]overlay=0:560[v]"
    )

    args = [
        "-i", str(cut_video),
        "-filter_complex", filter_graph,
        "-map", "[v]",
        "-an",
        *v_enc,
        "-pix_fmt", "yuv420p",
        str(out_framed),
    ]
    run_ffmpeg(args, check=True)
    return out_framed


def render_facecam(cut_video: Path, cam_rect: list[float], out_framed: Path) -> Path:
    """Render facecam layout: gameplay panel at y=300 and cam panel at y=930 on blurred background."""
    info = probe(cut_video)
    w, h = info.width, info.height

    rx, ry, rw, rh = cam_rect
    cx_px = int(rx * w)
    cy_px = int(ry * h)
    cw_px = max(100, int(rw * w))
    ch_px = max(50, int(rh * h))

    v_enc = [
        "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "16", "-b:v", "0",
    ] if has_encoder("h264_nvenc") else ["-c:v", "libx264", "-preset", "fast", "-crf", "16"]

    filter_graph = (
        f"[0:v]split=3[bg_in][gp_in][cam_in];"
        f"[bg_in]scale=-2:1920,crop=1080:1920,boxblur=40:6,eq=brightness=-0.12:saturation=1.1[bg];"
        f"[gp_in]scale=1080:608[gp];"
        f"[cam_in]crop=w={cw_px}:h={ch_px}:x={cx_px}:y={cy_px},scale=1080:560:flags=lanczos[cam];"
        f"[bg][gp]overlay=0:300[bg_gp];"
        f"[bg_gp][cam]overlay=0:930[v]"
    )

    args = [
        "-i", str(cut_video),
        "-filter_complex", filter_graph,
        "-map", "[v]",
        "-an",
        *v_enc,
        "-pix_fmt", "yuv420p",
        str(out_framed),
    ]
    run_ffmpeg(args, check=True)
    return out_framed


def render_talking_head(cut_video: Path, out_framed: Path) -> Path:
    """Render talking_head layout: 9:16 crop window following smoothed face tracking."""
    info = probe(cut_video)
    w, h = info.width, info.height
    fps = info.fps or 30.0

    crop_w_px = round(h * (9.0 / 16.0))
    crop_w_norm = crop_w_px / max(1, w)

    # Track smoothed face center
    trajectory = track_face_trajectory(cut_video, fps=fps, crop_w=crop_w_norm)
    med_cx = float(np.median(trajectory)) if trajectory else 0.5
    pan_range = (max(trajectory) - min(trajectory)) * w if trajectory else 0.0

    v_enc = [
        "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "16", "-b:v", "0",
    ] if has_encoder("h264_nvenc") else ["-c:v", "libx264", "-preset", "fast", "-crf", "16"]

    # If movement is small (< 40px), use fast static crop
    if pan_range < 40.0:
        crop_x = max(0, min(w - crop_w_px, round((med_cx * w) - (crop_w_px / 2.0))))
        filter_graph = f"crop=w={crop_w_px}:h={h}:x={crop_x}:y=0,scale=1080:1920:flags=lanczos"
        args = [
            "-i", str(cut_video),
            "-vf", filter_graph,
            "-an",
            *v_enc,
            "-pix_fmt", "yuv420p",
            str(out_framed),
        ]
        run_ffmpeg(args, check=True)
        return out_framed

    # Dynamic pan path via Python pipe
    cap = cv2.VideoCapture(str(cut_video))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    tmp_out = out_framed.with_suffix(".tmp.mp4")
    writer = cv2.VideoWriter(str(tmp_out), fourcc, fps, (1080, 1920))

    frame_idx = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        cx_norm = trajectory[frame_idx] if frame_idx < len(trajectory) else med_cx
        crop_x = max(0, min(w - crop_w_px, round((cx_norm * w) - (crop_w_px / 2.0))))

        cropped = frame[0:h, crop_x : crop_x + crop_w_px]
        scaled = cv2.resize(cropped, (1080, 1920), interpolation=cv2.INTER_LANCZOS4)
        writer.write(scaled)
        frame_idx += 1

    cap.release()
    writer.release()

    # Re-encode with NVENC / libx264
    args = [
        "-i", str(tmp_out),
        "-an",
        *v_enc,
        "-pix_fmt", "yuv420p",
        str(out_framed),
    ]
    run_ffmpeg(args, check=True)
    if tmp_out.is_file():
        tmp_out.unlink()

    return out_framed


def build_framed_clip(
    cut_video: Path,
    layout_decision: LayoutArtifact,
    out_dir: Path,
) -> Path:
    """Compose framed 1080x1920 video based on layout decision."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_framed = out_dir / "framed.mp4"

    if layout_decision.layout == "talking_head":
        return render_talking_head(cut_video, out_framed)
    elif layout_decision.layout == "facecam" and layout_decision.cam_rect:
        return render_facecam(cut_video, layout_decision.cam_rect, out_framed)
    else:
        return render_gameplay(cut_video, out_framed)
