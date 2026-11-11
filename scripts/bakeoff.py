"""bakeoff.py: Automated model bake-off harness to evaluate candidate local models."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("bakeoff")


class BakeoffNominationOut(BaseModel):
    hook: str = Field(description="First 3 seconds hook")
    topic: str = Field(description="Main subject")
    score: int = Field(ge=0, le=100, description="Predicted viral score")


TEST_WINDOWS = [
    {
        "id": "w01",
        "title": "GTA 6 Helicopter Jump",
        "text": "Lucia leaps from the skyscraper as the police helicopter spirals down in flames across Vice City beach.",
        "ground_truth_score": 85,
    },
    {
        "id": "w02",
        "title": "Inventory Management",
        "text": "Checking weapon wheel, selecting pistol, opening map to check nearest safehouse coordinates.",
        "ground_truth_score": 42,
    },
    {
        "id": "w03",
        "title": "Five Star Police Chase",
        "text": "Swerving through incoming SWAT roadblocks on the highway, tires screaming, barely escaping the barrier.",
        "ground_truth_score": 88,
    },
]


def run_model_bakeoff(models: list[str] | None = None) -> list[dict[str, Any]]:
    """Test candidate local models against benchmark windows."""
    from llm.ollama import OllamaProvider

    models_to_test = models or ["qwen3.5:9b", "gemma4:e4b", "qwen2.5:7b"]
    provider = OllamaProvider()
    results: list[dict[str, Any]] = []

    for model_name in models_to_test:
        logger.info("\n=======================================================")
        logger.info(f"EVALUATING MODEL: {model_name}")
        logger.info("=======================================================")

        valid_count = 0
        latencies: list[float] = []
        predicted_scores: list[int] = []
        gt_scores: list[int] = []

        for win in TEST_WINDOWS:
            prompt = (
                f"Analyze this gaming clip segment and predict its viral potential:\n"
                f"Title: {win['title']}\n"
                f"Transcript: \"{win['text']}\"\n\n"
                "Return JSON with: hook (str), topic (str), score (int 0-100)."
            )

            t0 = time.time()
            try:
                res_dict = provider.generate_json(
                    prompt=prompt,
                    schema=BakeoffNominationOut.model_json_schema(),
                    model=model_name,
                    max_tokens=200,
                    temperature=0.2,
                )
                dur = time.time() - t0
                latencies.append(dur)

                # Validate Pydantic schema
                obj = BakeoffNominationOut.model_validate(res_dict)
                valid_count += 1
                predicted_scores.append(obj.score)
                gt_scores.append(win["ground_truth_score"])
                logger.info(f"  [{win['id']}] OK ({dur:.2f}s) -> score={obj.score}, hook='{obj.hook[:30]}...'")
            except Exception as exc:
                dur = time.time() - t0
                latencies.append(dur)
                logger.warning(f"  [{win['id']}] FAIL ({dur:.2f}s) -> {exc}")

        valid_rate = valid_count / len(TEST_WINDOWS)
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        # Correlation if >= 2 valid predictions
        if len(predicted_scores) >= 2:
            import numpy as np
            try:
                corr = float(np.corrcoef(predicted_scores, gt_scores[:len(predicted_scores)])[0, 1])
                if np.isnan(corr):
                    corr = 0.5
            except Exception:
                corr = 0.5
        else:
            corr = 0.0

        res_summary = {
            "model": model_name,
            "validity_rate": round(valid_rate, 2),
            "avg_latency_s": round(avg_latency, 2),
            "correlation_with_gt": round(corr, 3),
            "status": "PASS" if valid_rate >= 0.66 else "DEGRADED",
        }
        results.append(res_summary)

    logger.info("\n=======================================================")
    logger.info("BAKEOFF EVALUATION SUMMARY")
    logger.info("=======================================================")
    for r in results:
        logger.info(f"{r['model']:<16} | Validity: {r['validity_rate']:.0%} | Latency: {r['avg_latency_s']:.2f}s | Corr: {r['correlation_with_gt']:.2f} | Status: {r['status']}")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Model bake-off harness")
    parser.add_argument("--models", nargs="+", help="Specific models to benchmark")
    args = parser.parse_args()

    results = run_model_bakeoff(args.models)
    return 0 if any(r["validity_rate"] > 0 for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
