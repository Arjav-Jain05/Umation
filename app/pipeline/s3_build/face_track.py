"""Face detection using MediaPipe Tasks (with OpenCV Haar fallback) and frame sampling."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.core import paths
from app.pipeline.s3_build.smoothing import smooth_face_trajectory

logger = logging.getLogger("app.pipeline.s3_build.face_track")


@dataclass
class FaceBox:
    x: float  # Normalized [0, 1]
    y: float
    w: float
    h: float
    confidence: float

    @property
    def area_ratio(self) -> float:
        return self.w * self.h

    @property
    def center_x(self) -> float:
        return self.x + (self.w / 2.0)

    @property
    def center_y(self) -> float:
        return self.y + (self.h / 2.0)


@dataclass
class FaceSample:
    t: float
    faces: list[FaceBox]


class FaceDetectorWrapper:
    """Wrapper encapsulating MediaPipe FaceDetector with OpenCV Haar fallback."""

    def __init__(self) -> None:
        self.mp_detector: Any = None
        self.haar_cascade: Any = None
        self._init_detector()

    def _init_detector(self) -> None:
        model_path = paths.models_dir() / "blaze_face_short_range.tflite"
        if not model_path.is_file():
            from config.settings import get_settings
            alt_path = Path(get_settings().weights_dir) / "models" / "blaze_face_short_range.tflite"
            if alt_path.is_file():
                model_path = alt_path

        if model_path.is_file():
            try:
                import mediapipe as mp

                base_options = mp.tasks.BaseOptions(model_asset_path=str(model_path))
                options = mp.tasks.vision.FaceDetectorOptions(
                    base_options=base_options,
                    min_detection_confidence=0.5,
                )
                self.mp_detector = mp.tasks.vision.FaceDetector.create_from_options(options)
                logger.debug("MediaPipe FaceDetector loaded successfully")
                return
            except Exception as e:
                logger.warning("MediaPipe FaceDetector initialization failed: %s", e)

        # Fallback to OpenCV Haar
        haar_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if Path(haar_path).is_file():
            try:
                self.haar_cascade = cv2.CascadeClassifier(haar_path)
                logger.info("Using OpenCV Haar cascade fallback for face detection")
            except Exception as e:
                logger.error("OpenCV Haar cascade initialization failed: %s", e)

    def detect(self, bgr_frame: np.ndarray) -> list[FaceBox]:
        """Detect faces in a BGR frame, returning normalized bounding boxes."""
        h, w = bgr_frame.shape[:2]
        if h == 0 or w == 0:
            return []

        # 1. MediaPipe path
        if self.mp_detector is not None:
            try:
                import mediapipe as mp

                rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                res = self.mp_detector.detect(mp_img)

                boxes: list[FaceBox] = []
                for d in res.detections:
                    bb = d.bounding_box
                    score = float(d.categories[0].score) if d.categories else 0.8
                    if score >= 0.5:
                        norm_x = max(0.0, float(bb.origin_x) / w)
                        norm_y = max(0.0, float(bb.origin_y) / h)
                        norm_w = min(1.0 - norm_x, float(bb.width) / w)
                        norm_h = min(1.0 - norm_y, float(bb.height) / h)
                        boxes.append(FaceBox(x=norm_x, y=norm_y, w=norm_w, h=norm_h, confidence=score))
                return boxes
            except Exception as e:
                logger.debug("MediaPipe detection error: %s", e)

        # 2. Haar cascade fallback
        if self.haar_cascade is not None:
            gray = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)
            faces = self.haar_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
            boxes = []
            for hx, hy, hw, hh in faces:
                boxes.append(
                    FaceBox(
                        x=float(hx) / w,
                        y=float(hy) / h,
                        w=float(hw) / w,
                        h=float(hh) / h,
                        confidence=0.7,
                    )
                )
            return boxes

        return []


def load_detector() -> FaceDetectorWrapper:
    """Instantiate a cached or fresh FaceDetectorWrapper."""
    return FaceDetectorWrapper()


def sample_faces(video_path: Path | str, every_s: float = 2.0, min_samples: int = 12) -> list[FaceSample]:
    """Sample frames periodically across video and detect faces for layout classification."""
    detector = load_detector()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.warning("Could not open video %s for face sampling", video_path)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / max(1.0, fps)

    step_s = every_s
    if duration > 0 and (duration / step_s) < min_samples:
        step_s = max(0.5, duration / min_samples)

    frame_step = max(1, int(step_s * fps))
    samples: list[FaceSample] = []

    curr_frame = 0
    while curr_frame < total_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, curr_frame)
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        t = curr_frame / fps
        detected = detector.detect(frame)
        samples.append(FaceSample(t=round(t, 2), faces=detected))
        curr_frame += frame_step

    cap.release()
    return samples


def track_face_trajectory(
    video_path: Path | str,
    fps: float = 30.0,
    crop_w: float = 0.5625,
) -> list[float]:
    """Track primary face per frame, with detection every 3rd frame and smoothing."""
    detector = load_detector()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    raw_targets: list[float | None] = []

    frame_idx = 0
    last_detected_cx: float | None = None

    while frame_idx < total_frames:
        if frame_idx % 3 == 0:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            faces = detector.detect(frame)
            if faces:
                # Follow face with largest area
                faces.sort(key=lambda f: f.area_ratio, reverse=True)
                last_detected_cx = faces[0].center_x
            else:
                last_detected_cx = None
        else:
            # Skip read for speed
            cap.grab()

        raw_targets.append(last_detected_cx)
        frame_idx += 1

    cap.release()
    return smooth_face_trajectory(raw_targets, fps=fps, crop_w=crop_w)
