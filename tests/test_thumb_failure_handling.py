"""tests/test_thumb_failure_handling.py: Verify graceful failure handling for Prompt v7 Section 5 #4.

Covers:
1. No usable video frame -> degrades gracefully to vector hero graphic, flags needs_attention, logs reason.
2. Failing cut-out / segmentation -> degrades gracefully to vector hero fallback, flags needs_attention.
3. Failing AI model / segmenter -> catches exception, degrades gracefully, flags needs_attention.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from app.core.schemas import Clip
from app.pipeline.orchestrator import JobContext
from app.pipeline.s5_package import (
    subject_extractor,
    thumbnail_generate,
)


def _make_dummy_clip(clip_id: str = "fail_test_01") -> tuple[JobContext, Clip]:
    ctx = JobContext(
        job={
            "id": "job_failure_test",
            "url": "https://youtube.com/watch?v=dummyfail",
            "title": "Failure Handling Simulation Test",
        }
    )
    clip = Clip(
        id=clip_id,
        start=0.0,
        end=15.0,
        duration=15.0,
        tier="A",
        final_score=9.0,
        llm_score=9.0,
        hook_text="WHAT HAPPENED?!",
        topic="Simulation Test",
    )
    return ctx, clip


def test_failure_handling_no_usable_video_frame(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test 1: When source video has no usable frames, degrade to vector hero graphic and flag needs_attention."""
    ctx, clip = _make_dummy_clip("no_frame_clip")
    out_dir = tmp_path / "out_no_frame"
    out_dir.mkdir(parents=True, exist_ok=True)

    with (
        caplog.at_level(logging.WARNING),
        patch("app.pipeline.s5_package.thumbnail_generate._find_source_video", return_value=tmp_path / "missing.mp4"),
    ):
        res = thumbnail_generate.generate_clip_thumbnails(ctx, clip, out_dir)

    assert res is not None
    assert res.get("needs_attention") is True
    assert "No usable face/subject frame" in res.get("attention_reason", "")
    assert res.get("generator") == "vector_fallback_v7"

    # Verify output files exist and are not empty / blank
    t169 = out_dir / "thumb_16x9.jpg"
    c916 = out_dir / "cover_9x16.jpg"
    assert t169.is_file()
    assert c916.is_file()
    assert t169.stat().st_size > 5000
    assert c916.stat().st_size > 5000

    # Ensure log captured the warning
    assert any("degrading to vector hero graphic" in rec.message for rec in caplog.records)


def test_failure_handling_failing_cutout(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test 2: When subject cut-out / segmentation fails, degrade gracefully to vector hero graphic."""
    ctx, clip = _make_dummy_clip("failing_cutout_clip")
    out_dir = tmp_path / "out_cutout_fail"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Mock candidate frames returning but cutout_subject returning None
    fake_frame = np.full((720, 1280, 3), 120, dtype=np.uint8)
    fake_cand = subject_extractor.FrameCandidate(
        frame_idx=10,
        time_s=1.0,
        frame_rgb=fake_frame,
        sharpness=200.0,
        face_box=(100, 100, 200, 200),
    )

    with (
        caplog.at_level(logging.WARNING),
        patch("app.pipeline.s5_package.subject_extractor.sample_and_score_frames", return_value=[fake_cand]),
        patch("app.pipeline.s5_package.subject_extractor.cutout_subject", return_value=(None, (0, 0, 1280, 720))),
        patch("app.pipeline.s5_package.thumbnail_generate._find_source_video", return_value=tmp_path / "dummy.mp4"),
    ):
        res = thumbnail_generate.generate_clip_thumbnails(ctx, clip, out_dir)

    assert res.get("needs_attention") is True
    assert res.get("generator") == "vector_fallback_v7"
    assert (out_dir / "thumb_16x9.jpg").is_file()
    assert (out_dir / "cover_9x16.jpg").is_file()


def test_failure_handling_failing_model_corrupted(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test 3: When model initialization or inference raises an exception, handle cleanly and fall back."""
    ctx, clip = _make_dummy_clip("corrupted_model_clip")
    out_dir = tmp_path / "out_corrupt_model"
    out_dir.mkdir(parents=True, exist_ok=True)

    with (
        caplog.at_level(logging.WARNING),
        patch("app.pipeline.s5_package.subject_extractor._get_image_segmenter", side_effect=RuntimeError("LiteRT model tensor corruption")),
        patch("app.pipeline.s5_package.thumbnail_generate._find_source_video", return_value=tmp_path / "dummy.mp4"),
    ):
        res = thumbnail_generate.generate_clip_thumbnails(ctx, clip, out_dir)

    assert res.get("needs_attention") is True
    assert (out_dir / "thumb_16x9.jpg").is_file()
    assert (out_dir / "cover_9x16.jpg").is_file()


def test_vector_hero_fallback_graphic_quality() -> None:
    """Test 4: Verify the generated vector hero fallback graphic itself is high quality and non-blank."""
    canvas_size = (1280, 720)
    hero_rgba = subject_extractor.generate_vector_hero_fallback(canvas_size)

    assert isinstance(hero_rgba, Image.Image)
    assert hero_rgba.mode == "RGBA"
    assert hero_rgba.size[0] >= 200 and hero_rgba.size[1] >= 200

    # Verify non-blank alpha channel
    alpha_arr = np.array(hero_rgba)[:, :, 3]
    opaque_pixels = np.sum(alpha_arr > 50)
    assert opaque_pixels > 10000, "Vector hero graphic must have substantial non-transparent silhouette content"
