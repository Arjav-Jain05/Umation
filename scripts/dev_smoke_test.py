"""End-to-end smoke test runner against local shorts-engine server."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("smoke_test")


def http_post(url: str, data: dict) -> dict:
    req = Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get(url: str) -> dict | list:
    req = Request(url, headers={"Accept": "application/json"}, method="GET")
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_smoke_test(target_url: str, base_api: str = "http://127.0.0.1:8000") -> int:
    """Run an end-to-end smoke test for a YouTube URL against local API."""
    logger.info("Starting smoke test on %s via %s", target_url, base_api)

    # 1. Health check
    try:
        health = http_get(f"{base_api}/api/health")
        logger.info("Server health: %s", health)
    except (URLError, HTTPError) as e:
        logger.error("Failed to reach server at %s: %s", base_api, e)
        return 1

    # 2. Submit job
    payload = {
        "url": target_url,
        "ack_fair_use": True,
        "options": {
            "max_source_height": 720,
            "min_tier": "C",
        },
    }

    try:
        res = http_post(f"{base_api}/api/jobs", payload)
        job_id = res["job_id"]
        logger.info("Job created successfully: %s", job_id)
    except Exception as e:
        logger.error("Failed to submit job: %s", e)
        return 1

    # 3. Poll status
    t0 = time.time()
    last_stage = ""
    while time.time() - t0 < 900:  # 15 minutes timeout
        try:
            job_info = http_get(f"{base_api}/api/jobs/{job_id}")
            status = job_info.get("status")
            stage = job_info.get("stage")
            progress = job_info.get("progress", 0.0)
            msg = job_info.get("message", "")

            if stage != last_stage:
                logger.info("[Job %s] Stage changed -> %s (progress: %.1f%%) %s", job_id, stage, progress, msg)
                last_stage = stage

            if status in ("review", "completed"):
                logger.info("Job reached final state: %s", status)
                # Fetch clips
                clips_data = http_get(f"{base_api}/api/jobs/{job_id}/clips")
                clips = clips_data.get("clips", [])
                logger.info("Planned clips count: %d", len(clips))
                print("\n================ PLANNED CLIPS SUMMARY ================")
                print(f"{'CLIP ID':<10} | {'START':<8} | {'END':<8} | {'TIER':<5} | {'SCORE':<6} | {'RISK':<8} | HOOK")
                print("-" * 75)
                for c in clips:
                    print(f"{c['id']:<10} | {c['start']:<8.1f} | {c['end']:<8.1f} | {c['tier']:<5} | {c['final_score']:<6.1f} | {c['risk']:<8} | {c['hook_text'][:30]}")
                print("=======================================================\n")
                return 0
            elif status == "failed":
                logger.error("Job failed: %s", job_info.get("error"))
                return 1

            time.sleep(3)
        except Exception as e:
            logger.warning("Polling error: %s", e)
            time.sleep(3)

    logger.error("Smoke test timed out after 15 minutes")
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="shorts-engine dev smoke test")
    parser.add_argument("url", nargs="?", default="https://www.youtube.com/watch?v=dQw4w9WgXcQ", help="YouTube URL to test")
    parser.add_argument("--server", default="http://127.0.0.1:8000", help="Base server URL")
    args = parser.parse_args()

    sys.exit(run_smoke_test(args.url, args.server))
