"""test_phase_3_signals.py: Phase 3 Audience Signals and Layer 1 Sensors test suite.

Verifies:
1. Audience signals parsing (YouTube heatmap, timestamped comments, chat replay, chapters).
2. Fail-soft behavior (missing signals marked missing, never 0, zero crashes).
3. Layer 1 Sensors (Audio energy, Sound events, Voice emotion, Video motion, Topic segmenter).
4. Hot-zone map and timeline event generator for LLM prompt context.
5. Layer 6 dynamic fusion with automatic weight redistribution when signals are missing.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.pipeline.s1_ingest.audience import (
    AudienceSignalsData,
    get_audience_score_for_window,
    parse_chat_replay,
    parse_timestamped_comments,
    parse_yt_heatmap,
)
from app.pipeline.s2_select.fusion import calculate_fusion_score
from app.pipeline.sensors.audio_energy import extract_audio_energy, score_audio_window
from app.pipeline.sensors.sound_events import extract_sound_events, score_sound_events_window
from app.pipeline.sensors.timeline_generator import (
    format_timeline_for_prompt,
    generate_timeline_and_hot_zones,
)
from app.pipeline.sensors.topic_segmenter import compute_candidate_overlap, detect_topic_boundaries
from app.pipeline.sensors.voice_emotion import (
    compute_window_wpm,
    match_hype_lexicon,
    score_voice_emotion,
)


def test_parse_yt_heatmap():
    raw_heatmap = [
        {"start_time": 0.0, "end_time": 10.0, "value": 100.0},
        {"start_time": 10.0, "end_time": 20.0, "value": 500.0},
        {"start_time": 20.0, "end_time": 30.0, "value": 300.0},
    ]
    norm, available = parse_yt_heatmap(raw_heatmap)
    assert available is True
    assert len(norm) == 3
    # 500 is max (1.0), 100 is min (0.0), 300 is (300-100)/(500-100) = 0.5
    assert norm[0]["value"] == 0.0
    assert norm[1]["value"] == 1.0
    assert norm[2]["value"] == 0.5

    # Empty heatmap returns available=False
    norm_empty, available_empty = parse_yt_heatmap(None)
    assert available_empty is False
    assert norm_empty == []


def test_parse_timestamped_comments():
    comments = [
        {"text": "Omg the car jump at 0:25 was insane!", "like_count": 50},
        {"text": "Check out 0:28 lol", "like_count": 10},
        {"text": "1:15 is pure gold", "like_count": 5},
        {"text": "No timestamp in this regular comment", "like_count": 100},
    ]
    bins, available = parse_timestamped_comments(comments, duration_s=120.0)
    assert available is True
    # 0:25 and 0:28 fall into bin 2 (20-30s)
    assert 2 in bins
    # 1:15 falls into bin 7 (70-80s)
    assert 7 in bins
    # Bin 2 has higher combined weighted score
    assert bins[2] >= bins[7]


def test_parse_chat_replay():
    chat_msgs = [
        {"offset_seconds": 15.0, "text": "POG POG POG"},
        {"offset_seconds": 16.0, "text": "clip it right now!!"},
        {"offset_seconds": 17.0, "text": "LMAO THAT WAS CRAZY"},
        {"offset_seconds": 55.0, "text": "regular message"},
    ]
    bins, hypes, available = parse_chat_replay(chat_msgs, duration_s=60.0)
    assert available is True
    assert 1 in bins  # 15s is bin 1
    assert "clip it" in hypes[1] or "pog" in hypes[1] or "lmao" in hypes[1]


def test_fail_soft_missing_audience():
    audience = AudienceSignalsData(
        has_heatmap=False,
        has_comments=False,
        has_chat=False,
        has_chapters=False,
    )
    score, breakdown = get_audience_score_for_window(10.0, 30.0, audience)
    assert score is None
    assert breakdown["available"] is False


def test_audio_energy_sensor():
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_wav = Path(tmp_dir) / "synth_audio.wav"
        sr = 16000
        dur_s = 6.0
        # 0-3s quiet, 3-6s loud burst (simulating silence-to-explosion)
        t = np.linspace(0, dur_s, int(sr * dur_s), endpoint=False)
        audio = np.zeros_like(t)
        # Quiet first 3s
        audio[: sr * 3] = 0.02 * np.sin(2 * np.pi * 220 * t[: sr * 3])
        # Loud burst 3-6s
        audio[sr * 3 :] = 0.80 * np.sin(2 * np.pi * 440 * t[sr * 3 :])
        sf.write(str(test_wav), audio, sr)

        profile = extract_audio_energy(test_wav)
        assert profile.duration_s >= 5.9
        assert len(profile.per_second_rms) == 6
        assert len(profile.silence_explosion_indices) >= 1

        score, bursts, has_expl = score_audio_window(3.0, 6.0, profile)
        assert score > 60.0
        assert bursts >= 1
        assert has_expl is True


def test_sound_events_sensor():
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_wav = Path(tmp_dir) / "synth_events.wav"
        sr = 16000
        dur_s = 4.0
        t = np.linspace(0, dur_s, int(sr * dur_s), endpoint=False)
        audio = np.zeros_like(t)
        # Explosion: heavy low frequency (80 Hz) at high amplitude
        audio[sr * 1 : sr * 2] = 0.85 * np.sin(2 * np.pi * 80 * t[sr * 1 : sr * 2])
        sf.write(str(test_wav), audio, sr)

        events_prof = extract_sound_events(test_wav)
        assert events_prof.duration_s >= 3.9

        score, tags = score_sound_events_window(0.5, 2.5, events_prof)
        assert score >= 50.0
        assert "explosion" in tags


def test_voice_emotion_and_hype():
    class MockWord:
        def __init__(self, s, e):
            self.s = s
            self.e = e

    class MockSentence:
        def __init__(self, s, e, text):
            self.start = s
            self.end = e
            self.text = text

    words = [MockWord(s=i * 0.3, e=i * 0.3 + 0.25) for i in range(25)]  # ~160 WPM
    sentences = [
        MockSentence(0.0, 4.0, "Holy shit look at this stunt!"),
        MockSentence(4.0, 7.5, "No way he survived that?!"),
    ]

    wpm = compute_window_wpm(words, 0.0, 7.5)
    assert wpm > 150.0

    matched = match_hype_lexicon("Holy shit look at this stunt! No way!")
    assert "holy shit" in matched or "no way" in matched

    emo_score, hype_score, hypes = score_voice_emotion(
        0.0, 7.5, words, sentences, custom_hype_words=["holy shit", "no way"]
    )
    assert emo_score >= 70.0
    assert hype_score >= 70.0
    assert len(hypes) >= 1


def test_topic_segmenter_and_dedup():
    class MockSent:
        def __init__(self, s, text):
            self.start = s
            self.text = text

    sents = [
        MockSent(0.0, "Let us talk about the GTA 6 map size and graphics."),
        MockSent(5.0, "The Vice City map is huge and detailed."),
        MockSent(10.0, "Graphics and water physics look incredible."),
        # Topic shift here to unrelated topic
        MockSent(15.0, "Now for something completely different cooking breakfast."),
        MockSent(20.0, "Pancakes and syrup recipe tips for Sunday morning."),
        MockSent(25.0, "Eggs bacon and orange juice preparation."),
    ]
    boundaries = detect_topic_boundaries(sents, window_size=2)
    assert len(boundaries) >= 1

    # Overlap dedup check
    t_overlap, text_sim, is_agree = compute_candidate_overlap(
        start_a=10.0, end_a=40.0, text_a="Insane helicopter stunt over Vice City",
        start_b=15.0, end_b=45.0, text_b="Insane helicopter stunt over Vice City",
    )
    assert t_overlap >= 0.80
    assert text_sim >= 90.0
    assert is_agree is True


def test_timeline_and_hot_zones():
    from app.pipeline.sensors.audio_energy import AudioEnergyProfile
    from app.pipeline.sensors.sound_events import SoundEventItem, SoundEventsProfile

    audio_prof = AudioEnergyProfile(
        duration_s=60.0,
        per_second_rms=np.array([0.1] * 60, dtype=np.float32),
        per_second_z=np.array([0.0] * 60, dtype=np.float32),
        mean_rms=0.1,
        std_rms=0.05,
        silence_explosion_indices=[15],
    )
    audio_prof.per_second_z[15] = 3.5

    sound_prof = SoundEventsProfile(
        duration_s=60.0,
        events=[SoundEventItem(time_s=15.2, event="explosion", confidence=0.92)],
        per_second_scores={15: 92.0},
        per_second_tags={15: ["explosion"]},
    )

    audience = AudienceSignalsData(
        has_chat=True,
        chat_bins={1: 0.95},  # 10-20s has chat spike
        chat_hype_tags={1: ["clip it", "pog"]},
    )

    events, hot_zones = generate_timeline_and_hot_zones(60.0, audio_prof, sound_prof, audience)
    assert len(events) >= 2
    # At t=15s: silence_explosion + sound event explosion + chat spike overlap
    assert len(hot_zones) >= 1
    assert hot_zones[0].start_s <= 15.0 <= hot_zones[0].end_s

    prompt_summary = format_timeline_for_prompt(events, 10.0, 20.0)
    assert "explosion" in prompt_summary.lower()


def test_fusion_dynamic_weight_redistribution():
    # Case 1: All signals present
    signals_full = {
        "audience": 80.0,
        "audio_events": 75.0,
        "emotion": 70.0,
        "text_hype": 65.0,
        "llm_consensus": 80.0,
        "critic": 78.0,
        "rerank": 82.0,
        "visual": 70.0,
        "agreement": 85.0,
    }
    score_full, _tier_full, breakdown_full = calculate_fusion_score(signals_full)
    assert score_full >= 75.0
    assert sum(breakdown_full["active_weights"].values()) == pytest.approx(1.0, abs=1e-3)
    assert breakdown_full["active_weights"]["audience"] > 0.15

    # Case 2: Audience signals missing (None)
    signals_no_audience = dict(signals_full)
    signals_no_audience["audience"] = None

    score_no_aud, _tier_no_aud, breakdown_no_aud = calculate_fusion_score(signals_no_audience)
    assert score_no_aud >= 70.0
    # Active weights must dynamically sum to 1.0 without error
    assert sum(breakdown_no_aud["active_weights"].values()) == pytest.approx(1.0, abs=1e-3)
    assert "audience" not in breakdown_no_aud["active_weights"]
    # Remaining weights proportionally increased
    assert breakdown_no_aud["active_weights"]["audio_events"] > breakdown_full["active_weights"]["audio_events"]
