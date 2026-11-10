"""Scoring calibration script (09 s7).

Computes Spearman correlation between candidate scores and real outcomes,
grid-searches optimal signal weights, and safely proposes/applies scoring updates.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from app.core import paths
from app.core.db import get_conn


def compute_ranks(x: np.ndarray) -> np.ndarray:
    """Compute fractional ranks for 1D array."""
    temp = x.argsort()
    ranks = np.empty_like(temp, dtype=np.float64)
    ranks[temp] = np.arange(len(x), dtype=np.float64)

    # Handle ties with average rank
    unique_vals, inverse_indices = np.unique(x, return_inverse=True)
    for i in range(len(unique_vals)):
        mask = inverse_indices == i
        if np.count_nonzero(mask) > 1:
            ranks[mask] = np.mean(ranks[mask])
    return ranks


def spearman_correlation(x: list[float] | np.ndarray, y: list[float] | np.ndarray) -> float:
    """Calculate Spearman rank-order correlation coefficient."""
    xa = np.asarray(x, dtype=np.float64)
    ya = np.asarray(y, dtype=np.float64)
    if len(xa) < 2 or np.all(xa == xa[0]) or np.all(ya == ya[0]):
        return 0.0

    rx = compute_ranks(xa)
    ry = compute_ranks(ya)

    cov = np.cov(rx, ry)
    if cov[0, 0] == 0 or cov[1, 1] == 0:
        return 0.0
    corr = cov[0, 1] / (np.sqrt(cov[0, 0] * cov[1, 1]))
    return float(corr)


def load_data(csv_path: Path | None = None) -> list[dict[str, Any]]:
    """Load evaluation samples from CSV or database results table."""
    records: list[dict[str, Any]] = []

    if csv_path and csv_path.is_file():
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                with contextlib.suppress(Exception):
                    records.append({
                        "clip_id": row.get("clip_id", ""),
                        "rating": float(row.get("rating", row.get("score", 0))),
                        "score_final": float(row.get("final_score", 0)),
                        "score_llm": float(row.get("score_llm", 0)),
                        "score_heat": float(row.get("score_heat", 0)),
                        "score_audio": float(row.get("score_audio", 0)),
                    })
        return records

    # Load from DB results table
    with get_conn() as conn:
        cur = conn.execute("""
            SELECT r.clip_id, r.views, r.likes, c.final_score
            FROM results r
            LEFT JOIN clips c ON r.job_id = c.job_id AND r.clip_id = c.id
        """)
        for row in cur.fetchall():
            views = float(row["views"] or 0)
            final_s = float(row["final_score"] or 0)
            if views > 0 or final_s > 0:
                records.append({
                    "clip_id": row["clip_id"],
                    "rating": views,
                    "score_final": final_s,
                    "score_llm": final_s,  # Proxies when signals not stored in results table
                    "score_heat": 50.0,
                    "score_audio": 50.0,
                })
    return records


def run_calibration(records: list[dict[str, Any]], apply: bool = False) -> None:
    """Run calibration routine and print detailed evaluation report."""
    n = len(records)
    print(f"Loaded {n} clip performance samples.")

    if n < 30:
        print("WARNING: Too few samples (N < 30). Optimal weights not calculated.")
        print("At least 30 samples are required to calibrate scoring safely.")
        return

    ratings = np.array([r["rating"] for r in records])
    finals = np.array([r["score_final"] for r in records])
    llms = np.array([r["score_llm"] for r in records])
    heats = np.array([r["score_heat"] for r in records])
    audios = np.array([r["score_audio"] for r in records])

    r_final = spearman_correlation(finals, ratings)
    r_llm = spearman_correlation(llms, ratings)
    r_heat = spearman_correlation(heats, ratings)
    r_audio = spearman_correlation(audios, ratings)

    print("\n--- Spearman Correlations with Real Outcomes ---")
    print(f"Final Score:  r = {r_final:+.3f} {'(noise)' if abs(r_final) < 0.2 else ''}")
    print(f"LLM Signal:   r = {r_llm:+.3f} {'(noise)' if abs(r_llm) < 0.2 else ''}")
    print(f"Heat Signal:  r = {r_heat:+.3f} {'(noise)' if abs(r_heat) < 0.2 else ''}")
    print(f"Audio Signal: r = {r_audio:+.3f} {'(noise)' if abs(r_audio) < 0.2 else ''}")

    # Grid search optimal weights
    best_r = -1.0
    best_weights = (0.65, 0.20, 0.15)

    steps = [round(x * 0.05, 2) for x in range(1, 20)]
    for w_llm in steps:
        for w_heat in steps:
            w_audio = round(1.0 - w_llm - w_heat, 2)
            if w_audio <= 0:
                continue
            blended = w_llm * llms + w_heat * heats + w_audio * audios
            corr = spearman_correlation(blended, ratings)
            if corr > best_r:
                best_r = corr
                best_weights = (w_llm, w_heat, w_audio)

    print("\n--- Grid Search Results ---")
    print(f"Current Weights:  llm: 0.65, heat: 0.20, audio: 0.15 (r = {r_final:+.3f})")
    print(f"Proposed Weights: llm: {best_weights[0]:.2f}, heat: {best_weights[1]:.2f}, audio: {best_weights[2]:.2f} (r = {best_r:+.3f})")

    # A-tier hit rate
    a_mask = finals >= 80.0
    if np.count_nonzero(a_mask) > 0:
        a_ratings = ratings[a_mask]
        hit_rate = np.mean(a_ratings >= 4.0) if np.max(ratings) <= 5.0 else np.mean(a_ratings >= np.percentile(ratings, 75))
        print(f"A-tier Hit Rate: {hit_rate * 100:.1f}%")

    if apply:
        cfg_path = paths.config_dir() / "scoring.yaml"
        bak_path = paths.config_dir() / "scoring.yaml.bak"
        shutil.copy2(cfg_path, bak_path)

        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        cfg["weights"] = {
            "llm": float(best_weights[0]),
            "heat": float(best_weights[1]),
            "audio": float(best_weights[2]),
        }

        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, default_flow_style=False)

        print(f"\nApplied proposed weights to {cfg_path.name} (backup written to {bak_path.name}).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate shorts-engine clip scoring weights")
    parser.add_argument("--csv", type=Path, help="CSV file containing clip_id and rating")
    parser.add_argument("--apply", action="store_true", help="Apply proposed weights to config/scoring.yaml")
    args = parser.parse_args()

    data = load_data(args.csv)
    run_calibration(data, apply=args.apply)


if __name__ == "__main__":
    main()
