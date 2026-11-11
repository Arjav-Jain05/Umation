"""Sentence building, word-per-minute calculation, and filler word detection."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.core.schemas import Sentence, Word
from app.utils.text import strip_punct
from app.utils.timecode import fmt_hms

logger = logging.getLogger("app.pipeline.s1_ingest.tidy_transcript")

# Exact filler words specified in references/03-stage1-ingest.md section 6
FILLERS = {"um", "uh", "erm", "er", "ah", "hmm", "uhm", "mm"}

# Conjunctions, prepositions, articles, and fillers that must NEVER end a sentence
DISALLOWED_TAIL_WORDS = {
    "and", "but", "so", "because", "to", "the", "a", "an", "like", "um", "uh",
    "or", "if", "that", "which", "then", "with", "for", "as", "at", "by", "from",
    "in", "into", "of", "on", "onto", "my", "your", "his", "her", "our", "their",
    "whose", "who", "whom", "where", "when", "why", "how", "i", "we", "he", "she",
}

_SAT_MODEL_INSTANCE: Any = None


def _get_sat_model() -> Any | None:
    """Load cached SaT model instance if local ONNX weights exist."""
    global _SAT_MODEL_INSTANCE
    if _SAT_MODEL_INSTANCE is not None:
        return _SAT_MODEL_INSTANCE

    try:
        from config.settings import get_settings
        settings = get_settings()
        weights_dir = settings.weights_dir
        sat_dir = weights_dir / "onnx" / "sat-3l-sm"
        tok_dir = (
            weights_dir / "huggingface" / "hub" / "models--facebookAI--xlm-roberta-base" /
            "snapshots" / "e73636d4f797dec63c3081bb6ed5c7b0bb3f2089"
        )

        if (sat_dir / "model_optimized.onnx").is_file() and tok_dir.is_dir():
            from wtpsplit import SaT
            _SAT_MODEL_INSTANCE = SaT(
                str(sat_dir),
                tokenizer_name_or_path=str(tok_dir),
                ort_providers=["CPUExecutionProvider"],
            )
            logger.info("Loaded SaT ONNX model from %s", sat_dir)
            return _SAT_MODEL_INSTANCE
    except Exception as exc:
        logger.debug("Local SaT ONNX model not loaded: %s", exc)
    return None


def detect_fillers(words: list[Word]) -> list[int]:
    """Return indices of words identified as standard hesitation fillers."""
    filler_indices: list[int] = []
    for idx, w in enumerate(words):
        token = strip_punct(w.w).lower()
        if token in FILLERS:
            filler_indices.append(idx)
    return filler_indices


def _compute_wpm(word_count: int, start: float, end: float) -> float:
    dur = max(0.2, end - start)
    return round((word_count / dur) * 60.0, 1)


def _clean_token(w: str) -> str:
    return re.sub(r"[^\w]", "", w).lower()


def _split_via_sat(sat_model: Any, words: list[Word]) -> list[list[int]]:
    """Segment words into sentences using Segment Any Text (SaT ONNX)."""
    word_spans: list[tuple[int, int]] = []
    full_chars: list[str] = []
    curr_pos = 0

    for w in words:
        token = w.w
        start_pos = curr_pos
        end_pos = start_pos + len(token)
        word_spans.append((start_pos, end_pos))
        full_chars.append(token)
        curr_pos = end_pos + 1

    full_text = " ".join(full_chars)
    sat_sents = sat_model.split(full_text)

    char_to_widx: dict[int, int] = {}
    for widx, (sp, ep) in enumerate(word_spans):
        for cp in range(sp, ep + 1):
            char_to_widx[cp] = widx

    raw_groups: list[list[int]] = []
    c_offset = 0
    for s_text in sat_sents:
        s_len = len(s_text)
        s_start_char = c_offset
        s_end_char = min(len(full_text) - 1, s_start_char + s_len - 1)
        while s_start_char < len(full_text) and full_text[s_start_char].isspace():
            s_start_char += 1
        while s_end_char > s_start_char and full_text[s_end_char].isspace():
            s_end_char -= 1

        w0 = char_to_widx.get(s_start_char, 0)
        w1 = char_to_widx.get(s_end_char, len(words) - 1)
        if w1 < w0:
            w1 = w0
        raw_groups.append(list(range(w0, w1 + 1)))
        c_offset += s_len

    return raw_groups


def _split_via_heuristics(words: list[Word]) -> list[list[int]]:
    """Heuristic fallback sentence segmenter based on punctuation and silence pauses."""
    raw_groups: list[list[int]] = []
    curr_group: list[int] = []

    for i, w in enumerate(words):
        curr_group.append(i)
        is_last = i == len(words) - 1

        ends_punct = bool(re.search(r"[.?!]+$", w.w))
        gap = (words[i + 1].s - w.e) if not is_last else 0.0

        split_here = False
        if not is_last:
            next_w = words[i + 1].w
            next_starts_capital = bool(next_w and (next_w[0].isupper() or next_w[0].isdigit()))
            if (ends_punct and next_starts_capital) or gap > 0.75:
                split_here = True

        if is_last or split_here:
            raw_groups.append(curr_group)
            curr_group = []

    # Handle sentences exceeding 30 words: split at comma or natural pause nearest to mid
    split_groups: list[list[int]] = []
    for grp in raw_groups:
        if len(grp) <= 30:
            split_groups.append(grp)
        else:
            queue = [grp]
            while queue:
                current = queue.pop(0)
                if len(current) <= 30:
                    split_groups.append(current)
                    continue

                mid = len(current) // 2
                best_split = mid
                best_dist = 999

                for offset in range(-mid // 2, mid // 2 + 1):
                    cand_idx = mid + offset
                    if 3 <= cand_idx <= len(current) - 3:
                        w_cand = words[current[cand_idx - 1]]
                        gap = words[current[cand_idx]].s - w_cand.e
                        is_comma = bool(re.search(r"[,;]+$", w_cand.w))
                        dist = abs(offset)
                        if is_comma and dist < best_dist:
                            best_split = cand_idx
                            best_dist = dist
                        elif gap > 0.35 and dist + 2 < best_dist:
                            best_split = cand_idx
                            best_dist = dist + 2

                part1 = current[:best_split]
                part2 = current[best_split:]
                queue.insert(0, part2)
                queue.insert(0, part1)

    return split_groups


def build_sentences(words: list[Word], use_sat: bool = True) -> list[Sentence]:
    """Segment raw ASR word stream into coherent sentences using SaT and strict tail boundary rules."""
    if not words:
        return []

    # Step 1: Use SaT if available; fall back to punctuation & pause heuristics
    sat_model = _get_sat_model() if use_sat else None
    initial_groups: list[list[int]] = []
    if sat_model is not None and len(words) > 5:
        try:
            initial_groups = _split_via_sat(sat_model, words)
        except Exception as exc:
            logger.warning("SaT segmentation failed; falling back to heuristics: %s", exc)
            initial_groups = _split_via_heuristics(words)
    else:
        initial_groups = _split_via_heuristics(words)

    # Step 1b: Split sentences exceeding 30 words at comma or gap
    split_groups: list[list[int]] = []
    for grp in initial_groups:
        if len(grp) <= 30:
            split_groups.append(grp)
        else:
            queue = [grp]
            while queue:
                current = queue.pop(0)
                if len(current) <= 30:
                    split_groups.append(current)
                    continue

                mid = len(current) // 2
                best_split = mid
                best_dist = 999

                for offset in range(-mid // 2, mid // 2 + 1):
                    cand_idx = mid + offset
                    if 3 <= cand_idx <= len(current) - 3:
                        w_cand = words[current[cand_idx - 1]]
                        gap = words[current[cand_idx]].s - w_cand.e
                        is_comma = bool(re.search(r"[,;]+$", w_cand.w))
                        dist = abs(offset)
                        if is_comma and dist < best_dist:
                            best_split = cand_idx
                            best_dist = dist
                        elif gap > 0.35 and dist + 2 < best_dist:
                            best_split = cand_idx
                            best_dist = dist + 2

                part1 = current[:best_split]
                part2 = current[best_split:]
                queue.insert(0, part2)
                queue.insert(0, part1)

    # Step 2: Merge small sentence fragments (< 3 words) into previous if gap < 0.5s
    merged_groups: list[list[int]] = []
    for grp in split_groups:
        if not merged_groups:
            merged_groups.append(grp)
            continue

        prev_grp = merged_groups[-1]
        gap = words[grp[0]].s - words[prev_grp[-1]].e
        if len(grp) < 3 and gap < 0.5 and (len(prev_grp) + len(grp)) <= 35:
            prev_grp.extend(grp)
        else:
            merged_groups.append(grp)

    # Step 3: Hard completeness gate: merge forward any sentence ending on disallowed tail words
    tail_cleaned_groups: list[list[int]] = []
    idx = 0
    while idx < len(merged_groups):
        curr = list(merged_groups[idx])
        while idx + 1 < len(merged_groups):
            last_word = words[curr[-1]].w
            token = _clean_token(last_word)
            if token in DISALLOWED_TAIL_WORDS:
                nxt = merged_groups[idx + 1]
                curr.extend(nxt)
                idx += 1
            else:
                break
        tail_cleaned_groups.append(curr)
        idx += 1

    # Step 4: Construct Sentence models
    sentences: list[Sentence] = []
    for sid, grp in enumerate(tail_cleaned_groups):
        w0 = grp[0]
        w1 = grp[-1]
        s = round(words[w0].s, 3)
        e = round(words[w1].e, 3)
        text = " ".join(words[k].w for k in grp).strip()
        wpm = _compute_wpm(len(grp), s, e)
        sentences.append(
            Sentence(
                id=sid,
                s=s,
                e=e,
                text=text,
                w0=w0,
                w1=w1,
                wpm=wpm,
            )
        )

    return sentences


def write_debug_txt(sentences: list[Sentence], out_path: Path) -> None:
    """Write plain-text transcript formatted with timestamp and sentence id."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for s in sentences:
        ts = fmt_hms(s.s, force_hours=True)
        lines.append(f"[{ts}] sid={s.id:03d} {s.text}")
    out_path.write_text("\n".join(lines), encoding="utf-8")
