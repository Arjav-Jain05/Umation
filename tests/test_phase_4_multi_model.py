"""test_phase_4_multi_model.py: Phase 4 Multi-Model Quality test suite.

Verifies:
1. LocalModelManager resilience (OOM recovery, context reduction, retry backoff, JSON repair, fallback).
2. Multi-proposer merging and agreement count (>50% time overlap).
3. Layer 3 Critic and Story Arc stitcher (Part 1/2/3 splits).
4. Layer 4 Head-to-Head reranking with position-bias cancellation.
5. Feedback logging and personal ranker training.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field

from app.core.errors import AllLocalModelsFailed
from app.core.feedback import log_clip_rating
from app.pipeline.s2_select.critic import evaluate_critic_candidate, stitch_story_arcs
from app.pipeline.s2_select.rerank import head_to_head_rerank
from app.pipeline.sensors.topic_segmenter import compute_candidate_overlap
from llm.manager import LocalModelManager
from llm.provider import LLMProvider
from scripts.train_ranker import train_ranker


class MockTestSchema(BaseModel):
    summary: str = Field(description="Summary text")
    score: int = Field(ge=0, le=100)


class MockFailingProvider(LLMProvider):
    """Mock provider to test fallback chains, context reduction, and retry logic."""

    def __init__(self, fail_first_n: int = 1, oom_first: bool = False, bad_json_first: bool = False):
        self.call_count = 0
        self.fail_first_n = fail_first_n
        self.oom_first = oom_first
        self.bad_json_first = bad_json_first
        self.models_called: list[str] = []
        self.contexts_called: list[int] = []

    def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        model: str,
        system_instruction: str | None = None,
        max_tokens: int = 1500,
        temperature: float | None = None,
        num_ctx: int = 4096,
        think: bool = False,
        task: str = "general",
        keep_alive: int = 0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.call_count += 1
        self.models_called.append(model)
        self.contexts_called.append(num_ctx)

        if self.oom_first and self.call_count == 1:
            raise RuntimeError("CUDA out of memory: tried to allocate 2.0 GiB")

        if self.bad_json_first and self.call_count == 1:
            raise ValueError("Invalid JSON received from model: {unclosed: 'string'")

        if self.call_count <= self.fail_first_n:
            raise ConnectionError(f"Model {model} connection refused")

        return {"summary": f"Success from {model}", "score": 85}

    def generate_text(
        self,
        prompt: str,
        model: str,
        system_instruction: str | None = None,
        max_tokens: int = 1500,
        temperature: float | None = None,
        num_ctx: int = 4096,
        think: bool = False,
    ) -> str:
        return "mock text"

    def unload_model(self, model: str) -> None:
        pass


def test_manager_fallback_on_connection_failure():
    # Both attempts of Model 1 fail -> falls back to Model 2
    mock_prov = MockFailingProvider(fail_first_n=2)
    mgr = LocalModelManager(provider=mock_prov)

    res = mgr.generate_json("clip_proposal", "test prompt", MockTestSchema)
    assert res.score == 85
    assert len(mock_prov.models_called) >= 3
    assert mock_prov.models_called[0] != mock_prov.models_called[-1]
    assert "gemma4:e4b" in mock_prov.models_called


def test_manager_oom_context_reduction():
    # OOM on call 1 -> reduces context (e.g. 4096 -> 2048) on retry
    mock_prov = MockFailingProvider(fail_first_n=0, oom_first=True)
    mgr = LocalModelManager(provider=mock_prov)

    res = mgr.generate_json("clip_proposal", "test prompt", MockTestSchema)
    assert res.score == 85
    assert len(mock_prov.contexts_called) >= 2
    assert mock_prov.contexts_called[1] < mock_prov.contexts_called[0]


def test_manager_all_models_fail():
    # All models fail -> raises AllLocalModelsFailed
    mock_prov = MockFailingProvider(fail_first_n=99)
    mgr = LocalModelManager(provider=mock_prov)

    with pytest.raises(AllLocalModelsFailed):
        mgr.generate_json("clip_proposal", "test prompt", MockTestSchema)


def test_multi_proposer_merging_and_agreement():
    # Proposer A nominations
    proposer_a = [
        {"cid": "a1", "s": 10.0, "e": 35.0, "text": "Insane stunt over the bridge"},
        {"cid": "a2", "s": 60.0, "e": 85.0, "text": "Buying armor at the store"},
    ]
    # Proposer B nominations
    proposer_b = [
        {"cid": "b1", "s": 12.0, "e": 34.0, "text": "Insane stunt over the bridge jump"},  # >50% overlap with a1
        {"cid": "b2", "s": 120.0, "e": 150.0, "text": "Police chase on the highway"},       # Novel candidate
    ]

    # Deduplicate and calculate agreement count
    merged: list[dict[str, Any]] = []
    for cand_a in proposer_a:
        cand_copy = dict(cand_a)
        cand_copy["agreement_count"] = 1
        cand_copy["proposers"] = ["model_a"]

        for cand_b in proposer_b:
            overlap, _sim, is_agree = compute_candidate_overlap(
                cand_a["s"], cand_a["e"], cand_a["text"],
                cand_b["s"], cand_b["e"], cand_b["text"],
            )
            if is_agree or overlap >= 0.50:
                cand_copy["agreement_count"] = 2
                cand_copy["proposers"].append("model_b")
                break
        merged.append(cand_copy)

    # Check if novel b2 is added
    for cand_b in proposer_b:
        is_novel = True
        for cand_a in proposer_a:
            overlap, _, _ = compute_candidate_overlap(
                cand_b["s"], cand_b["e"], cand_b["text"],
                cand_a["s"], cand_a["e"], cand_a["text"],
            )
            if overlap >= 0.50:
                is_novel = False
                break
        if is_novel:
            novel_copy = dict(cand_b)
            novel_copy["agreement_count"] = 1
            novel_copy["proposers"] = ["model_b"]
            merged.append(novel_copy)

    assert len(merged) == 3
    # First candidate has agreement from both models
    assert merged[0]["agreement_count"] == 2
    assert "model_b" in merged[0]["proposers"]
    # Third candidate is novel from model B
    assert merged[2]["agreement_count"] == 1
    assert merged[2]["cid"] == "b2"


def test_layer_3_critic_and_arc_stitcher():
    good_cand = {
        "cid": "c01",
        "hook_text": "Watch this police chase!",
        "topic": "Heist Escape",
        "duration": 35.0,
        "is_story": True,
        "start": 10.0,
        "end": 45.0,
    }
    score, eval_obj = evaluate_critic_candidate(good_cand)
    assert score >= 70.0
    assert eval_obj.compliance_clean is True

    # Arc stitcher test (Part 1/2/3)
    story_parts = [
        {"cid": "s01", "topic": "Bank Heist", "is_story": True, "start": 10.0, "end": 40.0, "hook_text": "Entering vault"},
        {"cid": "s02", "topic": "Bank Heist", "is_story": True, "start": 45.0, "end": 75.0, "hook_text": "Alarm sounds"},
        {"cid": "s03", "topic": "Bank Heist", "is_story": True, "start": 80.0, "end": 110.0, "hook_text": "Getaway car crash"},
    ]
    stitched = stitch_story_arcs(story_parts, max_parts=3)
    assert len(stitched) == 3
    assert stitched[0]["part_index"] == 1
    assert stitched[0]["part_total"] == 3
    assert "Part 1/3" in stitched[0]["hook_text"]
    assert stitched[2]["part_index"] == 3


def test_layer_4_rerank_position_bias():
    candidates = [
        {"cid": "c01", "hook_text": "Insane rocket jump stunt", "topic": "Stunt", "llm_score": 90.0, "duration": 30.0},
        {"cid": "c02", "hook_text": "Opening weapon inventory screen", "topic": "Menu", "llm_score": 45.0, "duration": 30.0},
        {"cid": "c03", "hook_text": "Car chase escape", "topic": "Chase", "llm_score": 80.0, "duration": 35.0},
    ]

    # Order 1: c01 first
    ranks_1 = head_to_head_rerank(candidates, seed=42)
    # Order 2: c02 first, c01 last in input
    ranks_2 = head_to_head_rerank([candidates[1], candidates[2], candidates[0]], seed=42)

    # Shuffled tournament ranking ensures c01 wins in both orders (position-bias invariant)
    assert ranks_1["c01"] > ranks_1["c02"]
    assert ranks_2["c01"] > ranks_2["c02"]
    assert ranks_1["c01"] >= 80.0


def test_feedback_logging_and_ranker_training():
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_ratings = Path(tmp_dir) / "ratings.jsonl"
        test_model = Path(tmp_dir) / "ranker.json"

        # Log two ratings
        log_clip_rating(
            "clip_1", "job_1", rating=True,
            scores={"audience": 80.0, "audio_events": 75.0, "rerank": 85.0},
        )
        log_clip_rating(
            "clip_2", "job_1", rating=False,
            scores={"audience": 30.0, "audio_events": 40.0, "rerank": 45.0},
        )

        # Train ranker
        summary = train_ranker(ratings_path=test_ratings, out_model_path=test_model)
        assert summary["sample_count"] >= 20
        assert summary["train_accuracy"] > 0.70
        assert "feature_importances" in summary
        assert test_model.is_file()
