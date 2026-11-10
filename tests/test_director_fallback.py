"""Unit tests for Stage 4 fallback director and SFX audio mix generation."""

from pathlib import Path

import numpy as np

from app.core.schemas import Clip, WordClip, WordsArtifact
from app.pipeline.s4_director.director import fallback_director
from app.pipeline.s4_director.effects.sfx import _read_wav_floats, build_sfx_mix


def test_fallback_director_structure():
    """Verify fallback director generates compliant EditList with hook, zoom punches, progress bar."""
    words = [
        WordClip(w="This", s_clip=0.1, e_clip=0.4, idx=0),
        WordClip(w="is", s_clip=0.4, e_clip=0.6, idx=1),
        WordClip(w="GTA6.", s_clip=0.6, e_clip=1.2, idx=2),
        WordClip(w="Look", s_clip=7.0, e_clip=7.5, idx=3),
        WordClip(w="at", s_clip=7.5, e_clip=7.8, idx=4),
        WordClip(w="Vice", s_clip=7.8, e_clip=8.2, idx=5),
        WordClip(w="City.", s_clip=8.2, e_clip=8.9, idx=6),
    ]
    words_art = WordsArtifact(clip_id="c01", words=words)
    clip = Clip(
        id="c01",
        idx=1,
        start=10.0,
        end=35.0,
        duration=25.0,
        tier="A",
        final_score=85.0,
        llm_score=85.0,
        hook_text="UNBELIEVABLE GRAPHICS LEAK",
        part_index=2,
        part_total=3,
    )

    edit_list = fallback_director(clip, words_art)

    assert edit_list.clip_id == "c01"
    assert edit_list.duration == 25.0

    types = [e.type for e in edit_list.events]
    assert "hook_card" in types
    assert "progress_bar" in types
    assert "part_label" in types
    assert "recap_line" in types
    # Rule 06 s6: No arrows, no emoji in fallback
    assert "arrow" not in types
    assert "emoji_pop" not in types


def test_build_sfx_mix(tmp_path: Path):
    """Verify build_sfx_mix creates valid 48kHz WAV with master limiting."""
    from app.pipeline.s4_director.edit_schema import EditEvent

    events = [
        EditEvent(id="s01", type="sfx", t=0.0, dur=0.35, params={"name": "whoosh", "gain_db": -12.0}),
        EditEvent(id="s02", type="sfx", t=2.0, dur=0.08, params={"name": "pop", "gain_db": -10.0}),
        EditEvent(id="s03", type="sfx", t=4.5, dur=0.45, params={"name": "ding", "gain_db": -8.0}),
    ]

    out_wav = tmp_path / "sfx_mix.wav"
    build_sfx_mix(events, duration=10.0, out_wav=out_wav)

    assert out_wav.is_file()
    assert out_wav.stat().st_size > 1000

    samples, sr = _read_wav_floats(out_wav)
    assert sr == 48000
    assert len(samples) == 480000  # 10s * 48000
    # Peak limited to -1.0 dBFS (~0.8912)
    assert np.max(np.abs(samples)) <= 0.895
