"""test_phase_5_visual_metadata.py: Phase 5 Visual Evidence, Metadata, Thumbnails, and Presets test suite.

Verifies:
1. Layer 5 Visual Evidence (dead footage detection, visual action levels, OCR trigger checks).
2. Layer 8 Metadata Ensemble and mandatory Creator Credit Block.
3. Layer 9 Thumbnails generation (both 1280x720 and 1080x1920 cover dimensions).
4. Pipeline Presets (Fast, Balanced, Best).
"""

from __future__ import annotations

import numpy as np

from app.core.schemas import Clip, JobOptions, SourceInfo
from app.pipeline.s5_package.credit import build_credit_block
from app.pipeline.s5_package.metadata import RawMetadataOut, TitleOption, validate_and_fix_metadata
from app.pipeline.s5_package.thumbnail_concept import ThumbConcept
from app.pipeline.s5_package.thumbnail_generate import ahash, generate_pillow_art, not_a_frame
from app.pipeline.sensors.visual_evidence import (
    detect_dead_frame,
    detect_visual_action_level,
    inspect_candidate_visuals,
)


def test_dead_frame_detection():
    # 1. Solid black frame -> dead
    black_frame = np.zeros((180, 320, 3), dtype=np.uint8)
    assert detect_dead_frame(black_frame) is True

    # 2. Random noisy action frame -> not dead
    rng = np.random.default_rng(42)
    action_frame = rng.integers(30, 220, size=(180, 320, 3), dtype=np.uint8)
    assert detect_dead_frame(action_frame) is False

    # 3. Consecutive identical frames -> dead (static footage)
    gray_1 = np.ones((180, 320), dtype=np.uint8) * 120
    gray_2 = np.ones((180, 320), dtype=np.uint8) * 120
    assert detect_dead_frame(gray_1, gray_2) is True


def test_visual_action_level():
    # Dynamic frames with high edge variance
    rng = np.random.default_rng(42)
    f1 = rng.integers(0, 255, size=(180, 320, 3), dtype=np.uint8)
    f2 = rng.integers(0, 255, size=(180, 320, 3), dtype=np.uint8)

    action_score = detect_visual_action_level([f1, f2])
    assert action_score > 60.0

    # Static flat frames -> low action
    flat1 = np.ones((180, 320, 3), dtype=np.uint8) * 100
    flat2 = np.ones((180, 320, 3), dtype=np.uint8) * 100
    low_action = detect_visual_action_level([flat1, flat2])
    assert low_action < 40.0


def test_inspect_candidate_visuals_fail_soft():
    # Missing video file fails soft with default score
    res = inspect_candidate_visuals(None, 0.0, 30.0)
    assert res.visual_action_score == 50.0
    assert res.is_dead_footage is False
    assert res.ocr_triggers_found == []


def test_credit_block_mandatory():
    source = SourceInfo(
        video_id="dQw4w9WgXcQ",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        webpage_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Epic GTA 6 Stunt Montage",
        channel="ViceCityStunts",
        channel_url="https://www.youtube.com/@ViceCityStunts",
        uploader="ViceCityStunts",
        upload_date="20261015",
        duration_s=300.0,
        live_status="not_live",
        width=1920,
        height=1080,
        fps=60.0,
        fetched_at="2026-11-11T12:00:00Z",
    )
    clip = Clip(
        id="c01",
        start=15.0,
        end=45.0,
        duration=30.0,
        tier="A",
        final_score=85.0,
        llm_score=88.0,
    )

    credit = build_credit_block(source, clip)
    # Mandatory inclusions
    assert "ViceCityStunts" in credit
    assert "https://www.youtube.com/@ViceCityStunts" in credit
    assert "dQw4w9WgXcQ" in credit
    assert "t=15" in credit
    # Never claim fair use
    assert "fair use" not in credit.lower()
    assert "no infringement intended" not in credit.lower()


def test_validate_and_fix_metadata():
    raw = RawMetadataOut(
        titles=[
            TitleOption(style="bold", text="LOOK AT THIS INSANE GTA 6 STUNT!!!!???"),
            TitleOption(style="curiosity", text="You won't believe how this helicopter escaped"),
            TitleOption(style="direct", text="Vice City Police Chase"),
        ],
        hashtags=["#GTA6", "#Gaming", "#ViceCity"],
        keywords=["stunt", "gta 6", "helicopter"],
        instagram_caption="Epic stunt moment",
        pinned_comment="Which part was your favorite?",
    )
    source = SourceInfo(
        video_id="dQw4w9WgXcQ",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        webpage_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Epic GTA 6 Stunt Montage",
        channel="ViceCityStunts",
        channel_url="https://www.youtube.com/@ViceCityStunts",
        uploader="ViceCityStunts",
        upload_date="20261015",
        duration_s=300.0,
        live_status="not_live",
        width=1920,
        height=1080,
        fps=60.0,
        fetched_at="2026-11-11T12:00:00Z",
    )
    clip = Clip(
        id="c01",
        start=15.0,
        end=45.0,
        duration=30.0,
        tier="A",
        final_score=85.0,
        llm_score=88.0,
    )

    meta = validate_and_fix_metadata(raw, clip, source)
    assert len(meta.titles) == 3
    # Punctuation constraint: at most one ! and ?
    bold_title = meta.titles[0].text
    assert bold_title.count("!") <= 1
    assert bold_title.count("?") <= 1
    assert len(bold_title) <= 70
    assert "ViceCityStunts" in meta.description_youtube


def test_pillow_thumbnail_generation():
    concept = ThumbConcept(
        scene="Helicopter spiraling down over sunset skyline",
        focal_subject="Helicopter",
        style="Synthwave vector art",
        palette=["#FFD400", "#FF007F", "#0F1115"],
        text="INSANE STUNT",
    )

    # 1. 16:9 ratio (1280x720)
    thumb_16_9 = generate_pillow_art(concept, aspect="16:9")
    assert thumb_16_9.size == (1280, 720)

    # 2. 9:16 vertical ratio (1080x1920)
    thumb_9_16 = generate_pillow_art(concept, aspect="9:16")
    assert thumb_9_16.size == (1080, 1920)

    # ahash and anti-frame check
    hash_val = ahash(thumb_16_9)
    assert hash_val.shape == (16, 16)
    assert not_a_frame(thumb_16_9, []) is True


def test_job_options_presets():
    # 1. Fast Preset
    opt_fast = JobOptions(preset="fast")
    opt_fast.apply_preset()
    assert opt_fast.enable_visual_layer is False
    assert opt_fast.enable_critic is False
    assert opt_fast.enable_rerank is False
    assert opt_fast.fast_mode is True

    # 2. Balanced Preset (Default)
    opt_bal = JobOptions(preset="balanced")
    opt_bal.apply_preset()
    assert opt_bal.enable_visual_layer is False
    assert opt_bal.enable_critic is True
    assert opt_bal.enable_rerank is True

    # 3. Best Preset
    opt_best = JobOptions(preset="best")
    opt_best.apply_preset()
    assert opt_best.enable_visual_layer is True
    assert opt_best.enable_critic is True
    assert opt_best.enable_rerank is True
    assert opt_best.second_look is True
    assert opt_best.enable_thumbnails is True


def test_query_vlm_frame(monkeypatch):
    """Verify VLM frame inspection formats base64 payload and parses Ollama response."""
    import json
    from unittest.mock import MagicMock

    from app.pipeline.sensors.visual_evidence import query_vlm_frame

    test_frame = np.zeros((100, 100, 3), dtype=np.uint8)

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"response": "The frame shows a dramatic explosion"}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: mock_resp)

    res = query_vlm_frame(test_frame, "Describe this frame")
    assert res == "The frame shows a dramatic explosion"

