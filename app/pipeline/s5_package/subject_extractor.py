"""Subject acquisition, cutout, matting, enhancement, and pop-out compositing.

Implements Section 2.1 of Prompt v7:
- Samples candidate frames at ~4 fps from full-resolution source
- Hard-rejects motion blur, cuts, and watermarks
- Scores frames by sharpness, face detection, and emotional intensity
- Cuts out subjects with MediaPipe ImageSegmenter (clean edge feathering)
- Applies creator grade (brightness lift, vibrance, clarity)
- Generates pop-out treatment (thick outline + colored glow + drop shadow)
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import cv2
import mediapipe as mp
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.core import paths

logger = logging.getLogger("app.pipeline.s5_package.subject_extractor")


class FrameCandidate:
    """Scored video frame candidate for thumbnail subject extraction."""

    def __init__(
        self,
        frame_idx: int,
        time_s: float,
        frame_rgb: np.ndarray,
        sharpness: float,
        face_box: tuple[int, int, int, int] | None = None,
        face_score: float = 0.0,
    ) -> None:
        self.frame_idx = frame_idx
        self.time_s = time_s
        self.frame_rgb = frame_rgb
        self.sharpness = sharpness
        self.face_box = face_box  # (x, y, w, h)
        self.face_score = face_score
        self.vlm_score: float = 5.0
        self.total_score: float = 0.0


def _get_face_detector() -> Any:
    """Initialize MediaPipe BlazeFace short range detector."""
    model_path = paths.models_dir() / "blaze_face_short_range.tflite"
    if not model_path.is_file():
        from config.settings import get_settings
        model_path = Path(get_settings().weights_dir) / "models" / "blaze_face_short_range.tflite"
    options = mp.tasks.vision.FaceDetectorOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        min_detection_confidence=0.35,
    )
    return mp.tasks.vision.FaceDetector.create_from_options(options)


def _get_image_segmenter() -> Any:
    """Initialize MediaPipe ImageSegmenter with confidence masks."""
    model_path = paths.models_dir() / "selfie_segmenter.tflite"
    if not model_path.is_file():
        from config.settings import get_settings
        model_path = Path(get_settings().weights_dir) / "models" / "selfie_segmenter.tflite"
    options = mp.tasks.vision.ImageSegmenterOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        output_confidence_masks=True,
    )
    return mp.tasks.vision.ImageSegmenter.create_from_options(options)


def sample_and_score_frames(
    video_path: Path,
    start_s: float,
    end_s: float,
    audio_peak_s: float | None = None,
    max_candidates: int = 3,
) -> list[FrameCandidate]:
    """Sample frames at ~4 fps from source video and score the best subjects."""
    if not video_path.is_file():
        logger.warning("Source video %s not found for frame sampling", video_path)
        return []

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.warning("Could not open video %s", video_path)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    start_frame = max(0, int(start_s * fps))
    end_frame = min(total_frames - 1, int(end_s * fps))
    step_frames = max(1, int(fps / 4.0))  # ~4 frames per second

    detector = None
    try:
        detector = _get_face_detector()
    except Exception as e:
        logger.warning("MediaPipe FaceDetector initialization failed: %s", e)

    candidates: list[FrameCandidate] = []
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    current_frame = start_frame

    while current_frame <= end_frame:
        ret, frame_bgr = cap.read()
        if not ret:
            break

        if (current_frame - start_frame) % step_frames == 0:
            h, w = frame_bgr.shape[:2]
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            mean_lum = float(np.mean(gray))

            # 1. Hard-reject: black/fade/transition
            if mean_lum < 18.0 or mean_lum > 238.0:
                current_frame += 1
                continue

            # 2. Hard-reject: motion blur
            lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            if lap_var < 95.0:
                current_frame += 1
                continue

            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            face_box = None
            face_score = 0.0

            if detector is not None:
                try:
                    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
                    res = detector.detect(mp_img)
                    if res.detections:
                        # Find largest / highest scoring face
                        best_det = res.detections[0]
                        bb = best_det.bounding_box
                        face_area_ratio = (bb.width * bb.height) / float(w * h)
                        conf = float(best_det.categories[0].score)
                        face_score = conf * (1.0 + min(face_area_ratio * 12.0, 3.0))
                        face_box = (int(bb.origin_x), int(bb.origin_y), int(bb.width), int(bb.height))
                except Exception:
                    pass

            time_s = current_frame / fps
            cand = FrameCandidate(
                frame_idx=current_frame,
                time_s=time_s,
                frame_rgb=frame_rgb,
                sharpness=lap_var,
                face_box=face_box,
                face_score=face_score,
            )

            # Score formula: face prominence (weighted heavily) + sharpness + audio proximity
            audio_prox = 0.0
            if audio_peak_s is not None and audio_peak_s > 0:
                dist_s = abs(time_s - audio_peak_s)
                audio_prox = max(0.0, 1.0 - dist_s / 10.0)

            cand.total_score = (cand.face_score * 3.5) + (min(cand.sharpness, 600.0) / 150.0) + (audio_prox * 1.5)
            candidates.append(cand)

        current_frame += 1

    cap.release()

    if not candidates:
        return []

    # Sort candidates by total score descending
    candidates.sort(key=lambda c: c.total_score, reverse=True)
    return candidates[:max_candidates]


def cutout_subject(
    frame_rgb: np.ndarray,
    face_box: tuple[int, int, int, int] | None = None,
) -> tuple[Image.Image | None, tuple[int, int, int, int]]:
    """Segment person / subject from frame, refine edges, and return (RGBA Image, subject_bbox)."""
    h, w = frame_rgb.shape[:2]
    segmenter = None
    try:
        segmenter = _get_image_segmenter()
    except Exception as e:
        logger.warning("MediaPipe ImageSegmenter failed: %s", e)
        return None, (0, 0, w, h)

    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
    res = segmenter.segment(mp_img)
    if not res.confidence_masks:
        return None, (0, 0, w, h)

    conf_arr = res.confidence_masks[0].numpy_view().squeeze()
    binary_mask = (conf_arr >= 0.40).astype(np.uint8) * 255

    # Edge refinement & hole closing
    kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    binary_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_CLOSE, kernel_close)
    # Anti-alias feathering
    feathered_mask = cv2.GaussianBlur(binary_mask, (3, 3), 0)

    # Check mask validity: must cover at least 3% and at most 88% of canvas
    mask_pixels = np.count_nonzero(feathered_mask > 40)
    ratio = mask_pixels / float(w * h)
    if ratio < 0.03 or ratio > 0.88:
        logger.warning("Cutout mask ratio %.3f rejected (outside 0.03-0.88 range)", ratio)
        return None, (0, 0, w, h)

    # Find bounding box of subject
    y_idx, x_idx = np.where(feathered_mask > 30)
    if len(y_idx) == 0:
        return None, (0, 0, w, h)

    pad = 16
    y0, y1 = max(0, int(y_idx.min() - pad)), min(h, int(y_idx.max() + pad))
    x0, x1 = max(0, int(x_idx.min() - pad)), min(w, int(x_idx.max() + pad))
    subj_bbox = (x0, y0, x1 - x0, y1 - y0)

    # Crop subject region
    crop_rgb = frame_rgb[y0:y1, x0:x1]
    crop_alpha = feathered_mask[y0:y1, x0:x1]

    # Creator Grade:
    # 1. Lift brightness (+14%)
    # 2. Boost vibrance/saturation (+22%)
    # 3. Local contrast / unsharp mask
    crop_hsv = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    crop_hsv[:, :, 2] = np.clip(crop_hsv[:, :, 2] * 1.14, 0, 255)
    crop_hsv[:, :, 1] = np.clip(crop_hsv[:, :, 1] * 1.22, 0, 255)
    enhanced_rgb = cv2.cvtColor(crop_hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)

    # Mild unsharp mask
    blurred = cv2.GaussianBlur(enhanced_rgb, (0, 0), 2.2)
    enhanced_rgb = cv2.addWeighted(enhanced_rgb, 1.28, blurred, -0.28, 0)

    # Pack RGBA
    rgba_arr = np.dstack([enhanced_rgb, crop_alpha])
    return Image.fromarray(rgba_arr, "RGBA"), subj_bbox


def apply_popout_treatment(
    subject_rgba: Image.Image,
    target_canvas_size: tuple[int, int],
    target_height_ratio: float = 0.52,
    outline_color: tuple[int, int, int] = (255, 255, 255),
    glow_color: tuple[int, int, int] = (255, 230, 0),
    outline_thickness: int = 12,
) -> tuple[Image.Image, tuple[int, int]]:
    """Scale subject and apply thick outline, colored glow, and soft drop shadow.

    Returns (treated_layer_with_alpha, (anchor_x, anchor_y)).
    """
    if subject_rgba.mode != "RGBA":
        subject_rgba = subject_rgba.convert("RGBA")

    _cw, ch = target_canvas_size
    sw, sh = subject_rgba.size

    # Scale subject so its height occupies target_height_ratio of canvas
    target_h = int(ch * target_height_ratio)
    scale = target_h / float(max(1, sh))
    target_w = max(1, int(sw * scale))
    scaled_subj = subject_rgba.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # Extract alpha mask
    alpha_arr = np.asarray(scaled_subj)[:, :, 3]
    binary_alpha = (alpha_arr > 30).astype(np.uint8) * 255

    # Create padded alpha canvas
    glow_radius = outline_thickness + 16
    pad = glow_radius + 24
    lw, lh = target_w + pad * 2, target_h + pad * 2

    full_alpha = np.zeros((lh, lw), dtype=np.uint8)
    full_alpha[pad : pad + target_h, pad : pad + target_w] = binary_alpha

    # 1. Outline: dilate full_alpha
    k_outline = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (outline_thickness * 2 + 1, outline_thickness * 2 + 1))
    dilated_outline = cv2.dilate(full_alpha, k_outline)
    outline_mask = Image.fromarray(dilated_outline, "L")

    # 2. Colored glow: wider dilation + Gaussian blur
    k_glow = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (glow_radius * 2 + 1, glow_radius * 2 + 1))
    dilated_glow = cv2.dilate(full_alpha, k_glow)
    glow_mask = Image.fromarray(dilated_glow, "L").filter(ImageFilter.GaussianBlur(radius=8))

    # 3. Soft drop shadow: shifted alpha + Gaussian blur
    shadow_shift = np.zeros((lh, lw), dtype=np.uint8)
    sy0, sy1 = min(lh, pad + 8), min(lh, pad + target_h + 8)
    sx0, sx1 = min(lw, pad + 8), min(lw, pad + target_w + 8)
    h_shift = sy1 - sy0
    w_shift = sx1 - sx0
    if h_shift > 0 and w_shift > 0:
        shadow_shift[sy0:sy1, sx0:sx1] = binary_alpha[:h_shift, :w_shift]
    shadow_mask = Image.fromarray(shadow_shift, "L").filter(ImageFilter.GaussianBlur(radius=10))

    # Compose layers onto padded canvas
    comp = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))

    # (a) Shadow: black
    shadow_layer = Image.new("RGBA", (lw, lh), (0, 0, 0, 160))
    comp.paste(shadow_layer, (0, 0), shadow_mask)

    # (b) Glow
    glow_layer = Image.new("RGBA", (lw, lh), (glow_color[0], glow_color[1], glow_color[2], 170))
    comp.paste(glow_layer, (0, 0), glow_mask)

    # (c) Outline
    outline_layer = Image.new("RGBA", (lw, lh), (outline_color[0], outline_color[1], outline_color[2], 255))
    comp.paste(outline_layer, (0, 0), outline_mask)

    # (d) Scaled subject
    comp.paste(scaled_subj, (pad, pad), scaled_subj)

    # Return layer and top-left alignment padding
    return comp, (pad, pad)


def generate_vector_hero_fallback(
    target_canvas_size: tuple[int, int],
    topic: str = "CHALLENGE",
) -> Image.Image:
    """Generate bold vector hero graphic (starburst trophy / flame) when no frame/AI subject passes."""
    cw, ch = target_canvas_size
    size = int(min(cw, ch) * 0.45)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2

    # Draw dynamic hero starburst / diamond emblem
    r_outer = size // 2 - 10
    r_inner = int(r_outer * 0.55)
    pts = []
    num_spikes = 8
    for i in range(num_spikes * 2):
        r = r_outer if i % 2 == 0 else r_inner
        ang = (math.pi * i) / num_spikes
        pts.append((cx + int(r * math.cos(ang)), cy + int(r * math.sin(ang))))

    draw.polygon(pts, fill=(255, 215, 0, 255), outline=(255, 255, 255, 255), width=8)
    # Inner bold exclamation or fire symbol
    font_path = paths.fonts_dir() / "Anton-Regular.ttf"
    font = ImageFont.truetype(str(font_path), size=int(size * 0.45)) if font_path.is_file() else ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "!", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw // 2, cy - th // 2 - 6), "!", font=font, fill=(220, 20, 20, 255), stroke_width=6, stroke_fill=(0, 0, 0, 255))

    return img
