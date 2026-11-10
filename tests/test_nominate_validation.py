"""Unit tests for Stage 2 nominate validation (invalid IDs, duration limits, duplicate merging)."""

from unittest.mock import MagicMock

from app.core.schemas import Chunk, Sentence, SourceInfo, Transcript
from app.pipeline.s2_select import nominate
from app.pipeline.s2_select.nominate import NominationOut, RawNominationItem


def test_nominate_validation_and_deduplication():
    """Verify nominate drops invalid IDs and bounds, clamps hook_sid, and merges duplicates."""
    ctx = MagicMock()
    ctx.artifact_ok.side_effect = lambda name, schema: False

    # Create 10 sentences, each 10s long (0s to 100s)
    sentences = [
        Sentence(id=i, s=float(i * 10), e=float(i * 10 + 9), text=f"Sentence {i}", w0=i * 5, w1=i * 5 + 4, wpm=100.0)
        for i in range(10)
    ]
    transcript = Transcript(
        language="en",
        model="fake",
        duration_s=100.0,
        sentences=sentences,
        words=[],
    )
    from pathlib import Path
    source_info = SourceInfo.model_validate_json(
        Path("tests/fixtures/source_info_cc.json").read_text(encoding="utf-8")
    )

    chunks = [Chunk(id="ch01", s=0.0, e=99.0, sentence_ids=[0, 9])]

    def mock_read(name, schema):
        if name == "transcript.json":
            return transcript
        if name == "source_info.json":
            return source_info
        if name == "chunks.json":
            from app.core.schemas import ChunksArtifact
            return ChunksArtifact(chunks=chunks)
        raise ValueError(f"Unknown artifact {name}")

    ctx.read_artifact.side_effect = mock_read

    # Return candidates:
    # 1. Invalid start_sid (999) -> dropped
    # 2. Reversed start/end (5, 2) -> dropped
    # 3. Too short (< 12s, 0 to 0 is 9s) -> dropped
    # 4. Valid cand A (sids 1 to 4: 10s to 49s = 39s), hook_sid out of bounds (99) -> clamped to start_sid (1), hint_score=60
    # 5. Valid cand B overlapping A > 50% (sids 1 to 4: 10s to 49s), hint_score=85 -> duplicate, keeps B
    # 6. Valid cand C (sids 6 to 8: 60s to 89s = 29s), hint_score=75 -> kept
    mock_cands = [
        RawNominationItem(start_sid=999, end_sid=2, hook_sid=999, hint_score=80),
        RawNominationItem(start_sid=5, end_sid=2, hook_sid=5, hint_score=80),
        RawNominationItem(start_sid=0, end_sid=0, hook_sid=0, hint_score=80),
        RawNominationItem(start_sid=1, end_sid=4, hook_sid=99, reason="Cand A", hint_score=60),
        RawNominationItem(start_sid=1, end_sid=4, hook_sid=1, reason="Cand B (higher hint)", hint_score=85),
        RawNominationItem(start_sid=6, end_sid=8, hook_sid=6, reason="Cand C", hint_score=75),
    ]

    ctx.gemini.generate_json.return_value = NominationOut(candidates=mock_cands)

    saved = {}

    def mock_write(name, artifact):
        saved[name] = artifact

    ctx.write_artifact.side_effect = mock_write

    nominate.run(ctx)

    cands_artifact = saved.get("candidates.json")
    assert cands_artifact is not None
    cands = cands_artifact.candidates

    # Only Cand B and Cand C should survive!
    assert len(cands) == 2
    assert cands[0].reason == "Cand B (higher hint)"
    assert cands[0].llm_hint_score == 85.0
    assert cands[0].hook_sid == 1
    assert cands[1].reason == "Cand C"
    assert cands[1].llm_hint_score == 75.0
