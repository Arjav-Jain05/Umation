"""Tests for thumbnail concept, generation, composition, and anti-frame guarantee (07 s6-s8)."""

from __future__ import annotations

import numpy as np
from PIL import Image

from app.pipeline.s5_package import thumbnail_compose, thumbnail_generate
from app.pipeline.s5_package.thumbnail_concept import ThumbConcept


def test_thumbnail_anti_frame_rejection(tmp_path):
    """Assert that a video frame passed in as a thumbnail fails the anti-frame check (N9)."""
    frame_path = tmp_path / "frame_01.jpg"

    # Create synthetic frame with horizontal split pattern
    frame_arr = np.zeros((360, 640, 3), dtype=np.uint8)
    frame_arr[:180, :, :] = 255  # Top white, bottom black
    frame_img = Image.fromarray(frame_arr)
    frame_img.save(frame_path)

    # Identical or near-identical image tested as thumbnail
    thumb_same = Image.fromarray(frame_arr)
    passed = thumbnail_generate.not_a_frame(thumb_same, [frame_path])
    assert not passed, "Anti-frame guarantee MUST reject video frames"

    # Distinct artwork with vertical split pattern
    diff_arr = np.zeros((720, 1280, 3), dtype=np.uint8)
    diff_arr[:, :640, :] = 255  # Left white, right black
    diff_img = Image.fromarray(diff_arr)

    # Hamming distance between horizontal split and vertical split is ~128 / 256 (> 40)
    assert thumbnail_generate.not_a_frame(diff_img, [frame_path])


def test_thumbnail_composition_sizes_and_text(tmp_path):
    concept = ThumbConcept(
        scene="Neon Florida highway",
        focal_subject="Sports car",
        style="Synthwave",
        palette=["#FFD400", "#FF007F", "#0F1115"],
        text="SECRET CAR",
        text_position="top",
    )

    art_16x9 = thumbnail_generate.generate_pillow_art(concept, aspect="16:9", seed_str="test_169")
    art_9x16 = thumbnail_generate.generate_pillow_art(concept, aspect="9:16", seed_str="test_916")

    out_16x9 = tmp_path / "thumb_16x9.jpg"
    out_9x16 = tmp_path / "cover_9x16.jpg"

    thumbnail_compose.compose_16x9(art_16x9, concept, out_16x9)
    thumbnail_compose.compose_9x16(art_9x16, concept, out_9x16)

    assert out_16x9.is_file()
    assert out_9x16.is_file()

    with Image.open(out_16x9) as im1:
        assert im1.size == (1280, 720)
        assert im1.format == "JPEG"

    with Image.open(out_9x16) as im2:
        assert im2.size == (1080, 1920)
        assert im2.format == "JPEG"

    # Both under 2 MB
    assert out_16x9.stat().st_size < 2 * 1024 * 1024
    assert out_9x16.stat().st_size < 2 * 1024 * 1024
