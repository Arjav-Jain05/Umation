"""Unit tests for Stage 2 signal extraction (heatmap, audio energy, speech ratio)."""

import numpy as np

from app.core.schemas import HeatmapPoint, Word
from app.pipeline.s2_select.signal_audio import audio_score, compute_baseline_z
from app.pipeline.s2_select.signal_heatmap import heat_score
from app.pipeline.s2_select.signal_speech import speech_ratio, topical_hits


def test_heatmap_score_and_coarse_override():
    """Verify heatmap score normalization and coarse-segment override detection."""
    # 5 segments: median is 0.5, max is 1.0
    heatmap = [
        HeatmapPoint(start=0.0, end=10.0, value=0.1),
        HeatmapPoint(start=10.0, end=20.0, value=0.5),
        HeatmapPoint(start=20.0, end=30.0, value=0.5),
        HeatmapPoint(start=30.0, end=40.0, value=0.8),
        HeatmapPoint(start=40.0, end=50.0, value=1.0),
    ]

    # Test peak window [40.0, 50.0]: value is 1.0 (max) -> score 100.0
    score, coarse = heat_score((40.0, 50.0), heatmap, avg_seg=10.0)
    assert score == 100.0
    assert not coarse

    # Test below-median window [0.0, 10.0]: value is 0.1 (< 0.5) -> score 0.0
    score_low, _ = heat_score((0.0, 10.0), heatmap, avg_seg=10.0)
    assert score_low == 0.0

    # Test coarse override when avg_seg > 90s
    _, coarse_yes = heat_score((40.0, 50.0), heatmap, avg_seg=95.0)
    assert coarse_yes is True


def test_audio_zscore_and_bursts():
    """Verify audio z-score computation and burst detection on a synthetic loud section."""
    # Create baseline db: 100 frames at -40 dBFS, then 10 frames burst at -15 dBFS
    baseline = np.full(100, -40.0, dtype=np.float32)
    burst = np.full(10, -15.0, dtype=np.float32)
    trailing = np.full(100, -40.0, dtype=np.float32)
    db = np.concatenate([baseline, burst, trailing])

    z = compute_baseline_z(db, window_radius_frames=50)

    # In the burst region (frames 100-110, times 50s to 55s at 0.5s/frame): z should be large
    score, bursts = audio_score((50.0, 55.0), z, frame_s=0.5)
    assert bursts >= 8
    assert score > 70.0

    # In baseline region (frames 10-30, times 5s to 15s): z should be near 0
    score_base, bursts_base = audio_score((5.0, 15.0), z, frame_s=0.5)
    assert bursts_base == 0
    assert score_base == 0.0


def test_speech_ratio_and_topical_hits():
    """Verify speech ratio computation and domain topical keyword hits."""
    words = [
        Word(i=0, w="Vice", s=10.0, e=12.0, p=0.9),  # 2.0s
        Word(i=1, w="City", s=13.0, e=15.0, p=0.9),  # 2.0s
    ]
    # Total window 10.0 to 20.0 = 10s. Speech is 4.0s -> ratio 0.40
    ratio = speech_ratio(words, 10.0, 20.0)
    assert ratio == 0.40

    # Test topical hits
    text = "We are exploring Vice City with Jason and Lucia in GTA 6."
    terms = ["Vice City", "Lucia", "Leonida", "Oppressor"]
    hits = topical_hits(text, terms)
    assert hits == 2  # Vice City and Lucia
