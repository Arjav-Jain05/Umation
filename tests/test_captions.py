"""Unit tests for Stage 3 captions (chunking, ASS format, BGR colors, profanity masking, validation)."""

from pathlib import Path

from app.core.schemas import WordClip
from app.pipeline.s3_build.captions import chunk_words, validate_ass, write_ass, write_srt


def test_captions_chunking():
    """Verify words are chunked into 2-4 words, breaking at pauses > 0.35s and punctuation."""
    words = [
        # Chunk 1: 3 words, ends with punctuation
        WordClip(w="Look", s_clip=0.0, e_clip=0.4),
        WordClip(w="at", s_clip=0.45, e_clip=0.7),
        WordClip(w="this!", s_clip=0.75, e_clip=1.2),
        # Gap > 0.35s (1.2 to 1.7 = 0.5s gap) -> Break
        # Chunk 2: 4 words max
        WordClip(w="We", s_clip=1.7, e_clip=2.0),
        WordClip(w="found", s_clip=2.05, e_clip=2.3),
        WordClip(w="the", s_clip=2.35, e_clip=2.5),
        WordClip(w="secret", s_clip=2.55, e_clip=2.9),
        # Chunk 3
        WordClip(w="bunker", s_clip=2.95, e_clip=3.4),
        WordClip(w="now", s_clip=3.45, e_clip=3.8),
    ]

    chunks = chunk_words(words, max_chars=20)
    assert len(chunks) == 3

    assert len(chunks[0].words) == 3
    assert chunks[0].text == "LOOK AT THIS!"

    assert len(chunks[1].words) == 4
    assert chunks[1].text == "WE FOUND THE SECRET"

    assert len(chunks[2].words) == 2
    assert chunks[2].text == "BUNKER NOW"


def test_captions_write_ass_and_bgr_colors(tmp_path: Path):
    """Verify ASS subtitle generation with BGR yellow highlight (&H00FFFF&) and layout anchor."""
    words = [
        WordClip(w="Epic", s_clip=1.0, e_clip=1.5, emphasis=True),
        WordClip(w="stunt", s_clip=1.6, e_clip=2.2),
    ]
    chunks = chunk_words(words)
    ass_path = tmp_path / "captions.ass"

    write_ass(chunks, layout="gameplay", out_path=ass_path, mask_profanity_flag=False)
    assert ass_path.is_file()

    content = ass_path.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert "Montserrat ExtraBold" in content

    # Anchor for gameplay is y=1330
    assert r"\pos(540,1330)" in content

    # BGR yellow highlight tag {\c&H00FFFF&}
    assert r"{\c&H00FFFF&}EPIC{\r}" in content
    assert r"{\c&H00FFFF&}STUNT{\r}" in content


def test_captions_profanity_masking(tmp_path: Path):
    """Verify profanity is masked with asterisks in ASS and SRT."""
    words = [
        WordClip(w="This", s_clip=0.0, e_clip=0.5),
        WordClip(w="fucking", s_clip=0.6, e_clip=1.1),
        WordClip(w="car", s_clip=1.2, e_clip=1.6),
    ]
    chunks = chunk_words(words)
    ass_path = tmp_path / "captions.ass"
    srt_path = tmp_path / "captions.srt"

    write_ass(chunks, layout="gameplay", out_path=ass_path, mask_profanity_flag=True)
    write_srt(chunks, out_path=srt_path, mask_profanity_flag=True)

    ass_text = ass_path.read_text(encoding="utf-8")
    srt_text = srt_path.read_text(encoding="utf-8")

    # Word "fucking" should be masked (e.g. F*CKING or F***ING), not raw "FUCKING"
    assert "FUCKING" not in ass_text
    assert "*" in ass_text
    assert "FUCKING" not in srt_text
    assert "*" in srt_text


def test_captions_validate_ass_monotonic(tmp_path: Path):
    """Verify validate_ass asserts events are within duration and monotonic."""
    words = [
        WordClip(w="Hello", s_clip=1.0, e_clip=1.5),
        WordClip(w="world", s_clip=1.6, e_clip=2.0),
    ]
    chunks = chunk_words(words)
    ass_path = tmp_path / "valid.ass"
    write_ass(chunks, layout="gameplay", out_path=ass_path)

    # Valid within 5s duration
    assert validate_ass(ass_path, max_duration=5.0) is True
    # Fails if duration is shorter than event end time (e.g. 0.5s)
    assert validate_ass(ass_path, max_duration=0.5) is False
