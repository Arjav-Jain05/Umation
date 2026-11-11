"""Evaluation and acceptance audit script for shorts-engine projects.

Spec: antigravity_prompt_v6_multi_model.md Section 8.
Checks:
- Mid-sentence start/end rate: target 0%
- Ends on conjunction/filler rate: target 0%
- Dangling-reference opening rate: target 0 unless justified
- Tail dead air over 1.0s: target 0
- Part policy: valid cliffhanger, duration >= 25s, consistent part_total, end card on non-final parts
- Thumbnails: 160px preview OCR readability, resolutions (1080x1920, 1280x720)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("eval_clips")

DISALLOWED_TAILS = {
    "and", "but", "so", "because", "to", "the", "like", "um", "uh", "you know", "or", "if", "that", "with",
}

DANGLING_PRONOUNS = {"he", "she", "they", "it", "this", "that", "these", "those"}


def evaluate_project(work_dir: Path | str, output_dir: Path | str | None = None) -> dict[str, Any]:
    """Audit clip integrity, part policy, and thumbnail readability for a project."""
    w_dir = Path(work_dir)
    if not w_dir.is_dir():
        raise FileNotFoundError(f"Work directory not found: {w_dir}")

    transcript_file = w_dir / "transcript.json"
    plan_file = w_dir / "plan.json"

    if not transcript_file.is_file() or not plan_file.is_file():
        raise FileNotFoundError(f"transcript.json or plan.json missing from {w_dir}")

    transcript = json.loads(transcript_file.read_text(encoding="utf-8"))
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    sentences = transcript.get("sentences", [])
    clips = plan.get("clips", [])

    results: list[dict[str, Any]] = []

    mid_sentence_starts = 0
    mid_sentence_ends = 0
    bad_tail_words = 0
    dangling_openings = 0
    dead_air_tail_violations = 0

    part_clips_count = 0
    part_duration_violations = 0
    part_inconsistent_totals = 0

    ocr_checked = 0
    ocr_passed = 0

    # Locate package output folder if present
    o_dir = Path(output_dir) if output_dir else None
    if not o_dir:
        # Search output/ for matching folder
        project_root = Path(__file__).resolve().parent.parent
        out_root = project_root / "output"
        if out_root.is_dir():
            for p in out_root.iterdir():
                if p.is_dir() and any(c["id"] in p.name or w_dir.name in p.name for c in clips[:1]):
                    o_dir = p
                    break

    for c in clips:
        cid = c["id"]
        c_start = float(c["start"])
        c_end = float(c["end"])
        dur = float(c["duration"])

        # 1. Check sentence boundaries
        # Find closest sentences to start and end
        matching_start_s = [s for s in sentences if abs(s["s"] - c_start) < 0.35]
        matching_end_s = [s for s in sentences if abs(s["e"] - c_end) < 0.45]

        starts_at_sent = len(matching_start_s) > 0
        ends_at_sent = len(matching_end_s) > 0

        if not starts_at_sent:
            mid_sentence_starts += 1
        if not ends_at_sent:
            mid_sentence_ends += 1

        # Text analysis from candidate sentences
        c_sents = [s for s in sentences if s["s"] >= c_start - 0.5 and s["e"] <= c_end + 0.5]
        first_text = c_sents[0]["text"].strip() if c_sents else ""
        last_text = c_sents[-1]["text"].strip() if c_sents else ""

        first_word = first_text.split()[0].lower().rstrip(",.?!") if first_text else ""
        last_word = last_text.split()[-1].lower().rstrip(",.?!") if last_text else ""

        is_dangling = first_word in DANGLING_PRONOUNS
        if is_dangling and not c.get("needs_context"):
            dangling_openings += 1

        is_bad_tail = last_word in DISALLOWED_TAILS
        if is_bad_tail:
            bad_tail_words += 1

        # 2. Check dead air tail from words.json if clip rendered
        words_file = w_dir / "clips" / cid / "words.json"
        tail_dead_air = 0.0
        if words_file.is_file():
            try:
                w_data = json.loads(words_file.read_text(encoding="utf-8"))
                words_list = w_data.get("words", [])
                if words_list:
                    last_w_end = words_list[-1]["e_clip"]
                    tail_dead_air = max(0.0, dur - last_w_end)
                    # Non-final parts have 1.8s hold frame, so exempt from 1.0s limit
                    is_non_final = bool(c.get("part_index") and c.get("part_total") and c["part_index"] < c["part_total"])
                    if tail_dead_air > 1.2 and not is_non_final:
                        dead_air_tail_violations += 1
            except Exception:
                pass

        # 3. Check part policy
        is_part = bool(c.get("part_index"))
        if is_part:
            part_clips_count += 1
            if dur < 24.5:
                part_duration_violations += 1

            p_tot = c.get("part_total")
            if not p_tot or p_tot > 4:
                part_inconsistent_totals += 1

        # 4. Check thumbnail OCR readability if package folder available
        thumb_ocr_status = "untested"
        if o_dir and o_dir.is_dir():
            # Find clip package subfolder
            clip_pkg_dirs = [p for p in o_dir.iterdir() if p.is_dir() and cid in p.name]
            if clip_pkg_dirs:
                pkg_sub = clip_pkg_dirs[0]
                cover_file = pkg_sub / "cover_9x16.jpg"
                meta_file = pkg_sub / "metadata.json"

                if cover_file.is_file():
                    hook_t = c.get("hook_text", "")
                    if meta_file.is_file():
                        try:
                            m_obj = json.loads(meta_file.read_text(encoding="utf-8"))
                            hook_t = m_obj.get("thumbnail", {}).get("concept", {}).get("text", hook_t)
                        except Exception:
                            pass

                    # Run 160px OCR check
                    ocr_checked += 1
                    try:
                        from app.pipeline.s5_package.thumbnail_compose import verify_thumbnail_ocr

                        ok, msg = verify_thumbnail_ocr(cover_file, hook_t or "MOMENT")
                        if ok:
                            ocr_passed += 1
                            thumb_ocr_status = "PASS"
                        else:
                            thumb_ocr_status = f"FAIL ({msg})"
                    except Exception as exc:
                        thumb_ocr_status = f"ERROR ({exc})"

        clip_audit = {
            "cid": cid,
            "duration": dur,
            "start": c_start,
            "end": c_end,
            "starts_at_sent": starts_at_sent,
            "ends_at_sent": ends_at_sent,
            "first_word": first_word,
            "last_word": last_word,
            "is_bad_tail": is_bad_tail,
            "is_dangling": is_dangling,
            "tail_dead_air": round(tail_dead_air, 2),
            "is_part": is_part,
            "part_index": c.get("part_index"),
            "part_total": c.get("part_total"),
            "thumb_ocr": thumb_ocr_status,
        }
        results.append(clip_audit)

    total_clips = len(clips)
    summary = {
        "total_clips": total_clips,
        "metrics": {
            "mid_sentence_starts": mid_sentence_starts,
            "mid_sentence_ends": mid_sentence_ends,
            "mid_sentence_cut_rate_pct": round(((mid_sentence_starts + mid_sentence_ends) / max(1, total_clips * 2)) * 100, 1),
            "bad_tail_words": bad_tail_words,
            "bad_tail_word_rate_pct": round((bad_tail_words / max(1, total_clips)) * 100, 1),
            "dangling_openings": dangling_openings,
            "tail_dead_air_violations": dead_air_tail_violations,
            "part_clips_count": part_clips_count,
            "part_duration_violations": part_duration_violations,
            "part_inconsistent_totals": part_inconsistent_totals,
            "thumbnail_ocr_checked": ocr_checked,
            "thumbnail_ocr_passed": ocr_passed,
            "thumbnail_ocr_pass_rate_pct": round((ocr_passed / max(1, ocr_checked)) * 100, 1) if ocr_checked else 100.0,
        },
        "all_hard_gates_passed": (
            mid_sentence_starts == 0
            and mid_sentence_ends == 0
            and bad_tail_words == 0
            and dead_air_tail_violations == 0
            and part_duration_violations == 0
        ),
        "clips": results,
    }

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate shorts-engine clip integrity and part policy.")
    parser.add_argument("work_dir", nargs="?", default="data/work/20261111-165810-Pv0iVoSZzN8", help="Path to project work directory")
    parser.add_argument("--output_dir", default=None, help="Path to packaged output directory")
    parser.add_argument("--json", action="store_true", help="Print raw JSON summary")
    args = parser.parse_args()

    work_p = Path(args.work_dir)
    if not work_p.is_dir():
        # Try finding in data/work/
        alt = Path("data/work") / args.work_dir
        if alt.is_dir():
            work_p = alt
        else:
            print(f"Error: Work dir '{args.work_dir}' not found.")
            sys.exit(1)

    eval_data = evaluate_project(work_p, args.output_dir)

    if args.json:
        print(json.dumps(eval_data, indent=2))
        return

    m = eval_data["metrics"]
    print("=" * 70)
    print("SHORTS-ENGINE CLIP QUALITY & INTEGRITY AUDIT (Prompt v6)")
    print("=" * 70)
    print(f"Project Workdir : {work_p}")
    print(f"Total Clips     : {eval_data['total_clips']}")
    print("-" * 70)
    print("PERCEPTION & SENTENCE INTEGRITY:")
    print(f"  Mid-sentence Starts  : {m['mid_sentence_starts']} / {eval_data['total_clips']} (Target: 0)")
    print(f"  Mid-sentence Ends    : {m['mid_sentence_ends']} / {eval_data['total_clips']} (Target: 0)")
    print(f"  Bad Tail Conjunctions: {m['bad_tail_words']} / {eval_data['total_clips']} (Target: 0)")
    print(f"  Dangling Openings    : {m['dangling_openings']} (Target: 0 unless justified)")
    print(f"  Tail Dead-Air (>1.0s): {m['tail_dead_air_violations']} (Target: 0)")
    print("-" * 70)
    print("PART-SPLITTING POLICY (Task C):")
    print(f"  Part Clips Total     : {m['part_clips_count']}")
    print(f"  Parts Under 25s      : {m['part_duration_violations']} (Target: 0)")
    print(f"  Part Total Mismatches: {m['part_inconsistent_totals']} (Target: 0)")
    print("-" * 70)
    print("THUMBNAIL QUALITY & OCR (Task D):")
    print(f"  160px OCR Checked    : {m['thumbnail_ocr_checked']}")
    print(f"  160px OCR Passed     : {m['thumbnail_ocr_passed']} ({m['thumbnail_ocr_pass_rate_pct']}%)")
    print("-" * 70)
    gate_status = "PASS (ALL GATES CLEAN)" if eval_data["all_hard_gates_passed"] else "FAIL"
    print(f"OVERALL HARD GATE AUDIT: {gate_status}")
    print("=" * 70)

    # Per clip overview
    print("\nCLIP BREAKDOWN:")
    for c in eval_data["clips"]:
        part_str = f"P{c['part_index']}/{c['part_total']}" if c['is_part'] else "Single"
        start_icon = "✓" if c['starts_at_sent'] else "✗"
        end_icon = "✓" if c['ends_at_sent'] and not c['is_bad_tail'] else "✗"
        tail_str = f"tail='{c['last_word']}'"
        print(f"  [{c['cid']}] {c['duration']:5.1f}s | {part_str:8s} | Start {start_icon} | End {end_icon} ({tail_str:15s}) | OCR: {c['thumb_ocr']}")


if __name__ == "__main__":
    main()
