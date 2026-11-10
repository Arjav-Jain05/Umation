"""Sentence building, word-per-minute calculation, and filler word detection."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.schemas import Sentence, Word
from app.utils.text import strip_punct
from app.utils.timecode import fmt_hms

# Exact filler words specified in references/03-stage1-ingest.md section 6
FILLERS = {"um", "uh", "erm", "er", "ah", "hmm", "uhm", "mm"}


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


def build_sentences(words: list[Word]) -> list[Sentence]:
    """Segment raw ASR word stream into coherent sentences using punctuation, pauses, and length limits."""
    if not words:
        return []

    # Step 1: Initial grouping by punctuation and silence gaps (> 0.80s)
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
            if (ends_punct and next_starts_capital) or gap > 0.80:
                split_here = True

        if is_last or split_here:
            raw_groups.append(curr_group)
            curr_group = []

    # Step 2: Split sentences with > 30 words at comma or gap nearest to middle
    split_groups: list[list[int]] = []
    for grp in raw_groups:
        if len(grp) <= 30:
            split_groups.append(grp)
        else:
            # Recursively split large group
            queue = [grp]
            while queue:
                current = queue.pop(0)
                if len(current) <= 30:
                    split_groups.append(current)
                    continue

                mid = len(current) // 2
                best_split = mid
                best_dist = 999

                # Check candidates around mid
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

    # Step 3: Merge small sentences (< 3 words) into previous if gap < 0.5s
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

    # Step 4: Construct Sentence models
    sentences: list[Sentence] = []
    for sid, grp in enumerate(merged_groups):
        w0 = grp[0]
        w1 = grp[-1]
        s = round(words[w0].s, 3)
        e = round(words[w1].e, 3)
        text = " ".join(words[idx].w for idx in grp).strip()
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
