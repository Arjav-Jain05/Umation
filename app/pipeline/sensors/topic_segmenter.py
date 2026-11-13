"""Layer 1 Topic Boundary Segmentation with BGE-Small TextTiling and Candidate Deduplication."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from rapidfuzz import fuzz

from app.core import paths
from config.settings import get_settings

logger = logging.getLogger("app.pipeline.sensors.topic_segmenter")

_BGE_SESSION = None
_BGE_TOKENIZER = None
_BGE_LOAD_ATTEMPTED = False


def _get_bge_resources() -> tuple[Any, Any]:
    """Lazy load BGE-small ONNX model and tokenizer on CPUExecutionProvider."""
    global _BGE_SESSION, _BGE_TOKENIZER, _BGE_LOAD_ATTEMPTED
    if _BGE_LOAD_ATTEMPTED:
        return _BGE_SESSION, _BGE_TOKENIZER

    _BGE_LOAD_ATTEMPTED = True
    settings = get_settings()
    weights_dir = getattr(settings, "weights_dir", paths.project_root() / "weights")
    bge_root = Path(weights_dir) / "huggingface" / "models--BAAI--bge-small-en-v1.5" / "snapshots"

    if not bge_root.is_dir():
        logger.debug("BGE-small directory not found at %s", bge_root)
        return None, None

    snapshots = [p for p in bge_root.iterdir() if p.is_dir()]
    if not snapshots:
        return None, None

    snap_dir = snapshots[0]
    onnx_path = snap_dir / "onnx" / "model.onnx"
    if not onnx_path.is_file():
        return None, None

    try:
        import onnxruntime as ort
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(str(snap_dir))
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        session = ort.InferenceSession(
            str(onnx_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        _BGE_SESSION = session
        _BGE_TOKENIZER = tokenizer
        logger.info("Loaded BGE-small-en-v1.5 ONNX model on CPU from %s", onnx_path)
    except Exception as exc:
        logger.warning("Could not load BGE-small ONNX model: %s", exc)

    return _BGE_SESSION, _BGE_TOKENIZER


def embed_sentences(sentences: list[Any], max_length: int = 128, batch_size: int = 32) -> np.ndarray | None:
    """Generate 384-dimensional normalized sentence embeddings using BGE-small ONNX on CPU.

    Returns:
        np.ndarray of shape (len(sentences), 384) with L2-normalized embeddings, or None if unavailable.
    """
    if not sentences:
        return None

    session, tokenizer = _get_bge_resources()
    if session is None or tokenizer is None:
        return None

    texts: list[str] = []
    for s in sentences:
        t = getattr(s, "text", "")
        if not t and isinstance(s, dict):
            t = s.get("text", "")
        elif not t and isinstance(s, str):
            t = s
        texts.append(str(t).strip())

    try:
        all_embeds: list[np.ndarray] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            encoded = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="np",
            )
            input_ids = encoded["input_ids"].astype(np.int64)
            attn_mask = encoded["attention_mask"].astype(np.int64)
            token_types = encoded.get("token_type_ids", np.zeros_like(input_ids)).astype(np.int64)

            feed = {
                "input_ids": input_ids,
                "attention_mask": attn_mask,
                "token_type_ids": token_types,
            }
            outputs = session.run(None, feed)
            token_embeddings = outputs[0]

            # Mean pooling with attention mask
            mask_expanded = np.expand_dims(attn_mask, -1)
            sum_embeddings = np.sum(token_embeddings * mask_expanded, axis=1)
            sum_mask = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
            embeds = sum_embeddings / sum_mask

            # L2 normalize
            norms = np.linalg.norm(embeds, axis=1, keepdims=True)
            embeds = embeds / np.clip(norms, a_min=1e-9, a_max=None)
            all_embeds.append(embeds)

        return np.vstack(all_embeds)
    except Exception as exc:
        logger.warning("BGE sentence embedding failed: %s", exc)
        return None


def detect_topic_boundaries(
    sentences: list[Any],
    window_size: int = 3,
    return_sids: bool = False,
) -> list[float] | list[int]:
    """Find timestamps or sentence indices of topical shift points where coherence drops.

    Uses TextTiling depth scoring on BGE-small embeddings, with fuzzy lexical fallback.
    """
    if len(sentences) < window_size * 2:
        return []

    # 1. Attempt BGE-small embedding TextTiling
    embeds = embed_sentences(sentences)
    if embeds is not None and len(embeds) == len(sentences):
        k = window_size
        sims: list[float] = []
        gaps = list(range(k, len(sentences) - k))

        for i in gaps:
            w_before = np.mean(embeds[i - k : i], axis=0)
            norm_b = np.linalg.norm(w_before)
            w_before = w_before / norm_b if norm_b > 1e-9 else w_before

            w_after = np.mean(embeds[i : i + k], axis=0)
            norm_a = np.linalg.norm(w_after)
            w_after = w_after / norm_a if norm_a > 1e-9 else w_after

            sims.append(float(np.dot(w_before, w_after)))

        if sims:
            depths: list[float] = []
            for idx in range(len(sims)):
                # Left peak
                left_peak = sims[idx]
                for l_idx in range(idx - 1, -1, -1):
                    if sims[l_idx] >= left_peak:
                        left_peak = sims[l_idx]
                    else:
                        break
                # Right peak
                right_peak = sims[idx]
                for r_idx in range(idx + 1, len(sims)):
                    if sims[r_idx] >= right_peak:
                        right_peak = sims[r_idx]
                    else:
                        break
                depth = (left_peak - sims[idx]) + (right_peak - sims[idx])
                depths.append(depth)

            # Threshold: mean + 0.3 * std or absolute depth > 0.06
            threshold = max(0.06, float(np.mean(depths)) + 0.3 * float(np.std(depths)))
            boundaries: list[Any] = []
            for idx, d in enumerate(depths):
                if d >= threshold:
                    sid = gaps[idx]
                    if return_sids:
                        boundaries.append(sid)
                    else:
                        t = float(getattr(sentences[sid], "start", getattr(sentences[sid], "s", 0.0)))
                        boundaries.append(round(t, 2))
            return boundaries

    # 2. Fuzzy lexical fallback
    boundaries_fallback: list[Any] = []
    for i in range(window_size, len(sentences) - window_size):
        w_before = " ".join([str(getattr(s, "text", "")) for s in sentences[i - window_size : i]])
        w_after = " ".join([str(getattr(s, "text", "")) for s in sentences[i : i + window_size]])

        if not w_before or not w_after:
            continue

        sim = fuzz.token_set_ratio(w_before, w_after)
        if sim < 40:
            if return_sids:
                boundaries_fallback.append(i)
            else:
                t = float(getattr(sentences[i], "start", getattr(sentences[i], "s", 0.0)))
                boundaries_fallback.append(round(t, 2))

    return boundaries_fallback


def get_story_blocks(
    sentences: list[Any],
    min_dur: float = 60.0,
    max_dur: float = 240.0,
    overlap_s: float = 30.0,
) -> list[tuple[int, int]]:
    """Partition sentences into cohesive story blocks using detected topic boundaries with overlap."""
    if not sentences:
        return []

    n = len(sentences)
    if n <= 3:
        return [(0, n - 1)]

    # Detect topic shift sentence IDs
    shift_sids = detect_topic_boundaries(sentences, window_size=2, return_sids=True)
    boundary_set = {int(s) for s in shift_sids if isinstance(s, (int, np.integer))}

    blocks: list[tuple[int, int]] = []
    curr_start_sid = 0

    while curr_start_sid < n:
        start_t = float(getattr(sentences[curr_start_sid], "start", getattr(sentences[curr_start_sid], "s", 0.0)))
        end_sid = curr_start_sid

        for i in range(curr_start_sid, n):
            end_t = float(getattr(sentences[i], "end", getattr(sentences[i], "e", 0.0)))
            dur = end_t - start_t
            end_sid = i

            # If we crossed a topic boundary after min_dur, cut the block here
            if dur >= min_dur and i in boundary_set:
                break
            # Hard limit max_dur
            if dur >= max_dur:
                break

        blocks.append((curr_start_sid, end_sid))

        if end_sid >= n - 1:
            break

        # Calculate next block start with at least overlap_s overlap
        end_t_val = float(getattr(sentences[end_sid], "end", getattr(sentences[end_sid], "e", 0.0)))
        target_next_t = max(start_t + 10.0, end_t_val - overlap_s)
        next_sid = end_sid
        for j in range(end_sid, curr_start_sid, -1):
            s_t = float(getattr(sentences[j], "start", getattr(sentences[j], "s", 0.0)))
            if s_t <= target_next_t:
                next_sid = j
                break

        if next_sid <= curr_start_sid:
            next_sid = min(curr_start_sid + 1, n - 1)
        curr_start_sid = next_sid

    return blocks


def compute_candidate_overlap(
    start_a: float,
    end_a: float,
    text_a: str,
    start_b: float,
    end_b: float,
    text_b: str,
) -> tuple[float, float, bool]:
    """Calculate time overlap ratio and text similarity between two candidates.

    Returns:
        (time_overlap_ratio, text_similarity_0_to_100, is_agreement)
    """
    len_a = max(0.1, end_a - start_a)
    len_b = max(0.1, end_b - start_b)

    overlap_start = max(start_a, start_b)
    overlap_end = min(end_a, end_b)
    overlap_duration = max(0.0, overlap_end - overlap_start)

    time_ratio = overlap_duration / min(len_a, len_b)
    text_sim = float(fuzz.token_set_ratio(text_a, text_b)) if text_a and text_b else 0.0
    is_agreement = (time_ratio >= 0.50) or (time_ratio >= 0.30 and text_sim >= 85.0)

    return round(time_ratio, 3), round(text_sim, 1), is_agreement
