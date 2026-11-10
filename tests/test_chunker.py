"""Unit tests for Stage 2 chunker (20 min chunks, 90s overlap, dead-region compression)."""

from app.core.schemas import Chunk, Sentence
from app.pipeline.s2_select.chunker import (
    make_chunks,
    mark_dead_regions,
    render_chunk_text,
)


def test_make_chunks_boundaries():
    """Verify chunking slices on sentence boundaries with correct overlap."""
    # 45 minutes of sentences (1 sentence every 30s)
    sentences = [
        Sentence(id=i, s=float(i * 30), e=float(i * 30 + 15), text=f"Sentence {i}", w0=i * 5, w1=i * 5 + 4, wpm=120.0)
        for i in range(90)  # 0s to 2685s (~45 min)
    ]

    chunks = make_chunks(sentences, minutes=20, overlap_s=90)
    assert len(chunks) >= 3

    for c in chunks:
        # Sentence IDs are valid
        sid_start, sid_end = c.sentence_ids
        assert sid_start <= sid_end
        assert c.s == sentences[sid_start].s
        assert c.e == sentences[sid_end].e

    # Check overlap between chunk 1 and chunk 2
    c1 = chunks[0]
    c2 = chunks[1]
    # c2 start should be approximately c1.s + (20*60 - 90) = 1110s
    assert c2.s <= c1.e
    assert c1.e - c2.s >= 90.0


def test_no_sentence_split():
    """Verify chunks never split an individual sentence."""
    sentences = [
        Sentence(id=0, s=0.0, e=100.0, text="First", w0=0, w1=5, wpm=100.0),
        Sentence(id=1, s=100.0, e=200.0, text="Second", w0=6, w1=10, wpm=100.0),
        Sentence(id=2, s=200.0, e=300.0, text="Third", w0=11, w1=15, wpm=100.0),
    ]
    chunks = make_chunks(sentences, minutes=2, overlap_s=30)
    for c in chunks:
        # Check start and end strictly equal some sentence boundary
        assert any(c.s == s.s for s in sentences)
        assert any(c.e == s.e for s in sentences)


def test_dead_region_compression():
    """Verify mark_dead_regions flags low wpm stretches >= 90s, and render_chunk_text compresses them."""
    sentences = [
        # Normal speech
        Sentence(id=0, s=0.0, e=10.0, text="Action starts now!", w0=0, w1=5, wpm=120.0),
        # Quiet / dead stretch: 3 sentences totaling 100s with wpm < 40
        Sentence(id=1, s=10.0, e=45.0, text="...", w0=6, w1=7, wpm=20.0),
        Sentence(id=2, s=45.0, e=80.0, text="...", w0=8, w1=9, wpm=15.0),
        Sentence(id=3, s=80.0, e=115.0, text="...", w0=10, w1=11, wpm=25.0),
        # Normal speech resumes
        Sentence(id=4, s=115.0, e=125.0, text="Back to the heist!", w0=12, w1=16, wpm=130.0),
    ]

    dead_flags = mark_dead_regions(sentences)
    assert not dead_flags[0]
    assert dead_flags[1]
    assert dead_flags[2]
    assert dead_flags[3]
    assert not dead_flags[4]

    chunk = Chunk(id="ch01", s=0.0, e=125.0, sentence_ids=[0, 4])
    text = render_chunk_text(chunk, sentences, dead_flags)

    assert "[0] 00:00 Action starts now!" in text
    assert "[... quiet 105s ...]" in text
    assert "[4] 01:55 Back to the heist!" in text
