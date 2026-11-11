"""Layer 4 Head-to-Head Reranker: Shuffled batch tournaments to cancel position bias and score relative viral potential."""

from __future__ import annotations

import logging
import random
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("app.pipeline.s2_select.rerank")


class RerankBatchOutput(BaseModel):
    ranked_cids: list[str] = Field(
        default_factory=list,
        description="Candidate IDs ordered from most to least viral",
    )
    reasons: dict[str, str] = Field(default_factory=dict)


def compute_heuristic_relative_rank(batch: list[dict[str, Any]]) -> list[str]:
    """Fallback ranking based on objective multi-signal criteria when LLM is unavailable."""
    def sort_key(cand: dict[str, Any]) -> tuple[float, float, float]:
        hook_len = len(str(cand.get("hook_text", "")).split())
        hook_score = 10.0 if 2 <= hook_len <= 8 else 5.0
        llm = float(cand.get("llm_score", cand.get("llm_hint_score", 50.0)))
        dur = float(cand.get("duration", 30.0))
        dur_score = 10.0 if 15.0 <= dur <= 60.0 else 5.0
        return (llm, hook_score, dur_score)

    sorted_batch = sorted(batch, key=sort_key, reverse=True)
    return [str(c["cid"]) for c in sorted_batch]


def head_to_head_rerank(
    candidates: list[dict[str, Any]],
    llm_client: Any = None,
    trials_per_batch: int = 3,
    batch_size: int = 5,
    seed: int = 42,
) -> dict[str, float]:
    """Execute head-to-head tournament reranking with multiple shuffles.

    Returns:
        dict mapping cid -> rerank_score (0.0 to 100.0)
    """
    if not candidates:
        return {}

    if len(candidates) == 1:
        return {candidates[0]["cid"]: 80.0}

    rng = random.Random(seed)
    n = len(candidates)
    cid_to_ranks: dict[str, list[int]] = {c["cid"]: [] for c in candidates}

    # If small number of candidates, run full batch
    effective_batch_size = min(batch_size, n)

    # Run multiple shuffled tournament trials
    for _trial in range(trials_per_batch):
        # Shuffle presentation order
        shuffled_indices = list(range(n))
        rng.shuffle(shuffled_indices)

        for i in range(0, n, effective_batch_size):
            batch_slice = shuffled_indices[i : i + effective_batch_size]
            if len(batch_slice) <= 1:
                if batch_slice:
                    cid_to_ranks[candidates[batch_slice[0]]["cid"]].append(1)
                continue

            batch_cands = [candidates[idx] for idx in batch_slice]

            ranked_cids: list[str] = []
            if llm_client is not None and hasattr(llm_client, "generate_json"):
                prompt = (
                    "You are an expert viral video editor. Rank these video clip candidates from "
                    "MOST likely to hold audience attention to LEAST likely.\n\n"
                    "Criteria:\n"
                    "1. Instant hook in first 3 seconds\n"
                    "2. Clear standalone narrative or payoff\n"
                    "3. High emotional or entertaining energy\n\n"
                    "Candidates:\n"
                )
                for _pos, c in enumerate(batch_cands):
                    prompt += f"- ID: {c['cid']} | Hook: \"{c.get('hook_text', '')}\" | Topic: {c.get('topic', '')} | Dur: {c.get('duration', 30):.1f}s\n"

                prompt += "\nOutput JSON with `ranked_cids` listed from best to worst."

                try:
                    res: RerankBatchOutput = llm_client.generate_json(
                        prompt,
                        RerankBatchOutput,
                        task="rerank",
                        temperature=0.1,
                    )
                    ranked_cids = [cid for cid in res.ranked_cids if any(c["cid"] == cid for c in batch_cands)]
                except Exception as exc:
                    logger.debug(f"LLM rerank call failed: {exc}; using comparative heuristic")
                    ranked_cids = []

            if not ranked_cids or len(ranked_cids) != len(batch_cands):
                ranked_cids = compute_heuristic_relative_rank(batch_cands)

            for rank_idx, cid in enumerate(ranked_cids):
                cid_to_ranks[cid].append(rank_idx + 1)

    # Convert average ranks to 0-100 scores
    rerank_scores: dict[str, float] = {}
    for cid, ranks in cid_to_ranks.items():
        if not ranks:
            rerank_scores[cid] = 60.0
            continue
        avg_rank = sum(ranks) / len(ranks)
        # 1st place -> 95-100, last place -> 40-50
        max_possible_rank = float(effective_batch_size)
        norm_rank = (avg_rank - 1.0) / max(1.0, max_possible_rank - 1.0)
        score = 95.0 - (norm_rank * 45.0)
        rerank_scores[cid] = round(max(30.0, min(100.0, score)), 1)

    return rerank_scores
