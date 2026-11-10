"""Generate test fixtures: synthetic test video (ffmpeg lavfi), heatmap, and canned JSON."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("make_fixtures")

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "tests" / "fixtures"


def make_synthetic_video() -> Path:
    """Generate 60s 1920x1080 30fps test video with 440Hz sine audio."""
    out_path = FIXTURES_DIR / "synthetic.mp4"
    if out_path.exists() and out_path.stat().st_size > 10000:
        logger.info("synthetic.mp4 already exists (%d bytes)", out_path.stat().st_size)
        return out_path

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", "60",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(out_path),
    ]
    logger.info("Generating synthetic.mp4 with ffmpeg lavfi...")
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        logger.error("ffmpeg failed: %s", res.stderr)
        raise RuntimeError(f"ffmpeg failed to create synthetic.mp4: {res.stderr}")

    logger.info("synthetic.mp4 created successfully (%d bytes)", out_path.stat().st_size)
    return out_path


def make_heatmap_100() -> Path:
    """Generate 100-segment heatmap fixture with 3 peaks."""
    out_path = FIXTURES_DIR / "heatmap_100.json"
    if out_path.exists():
        logger.info("heatmap_100.json already exists")
        return out_path

    # 100 segments (10 seconds each, 1000 seconds total)
    # Base values 0.10 to 0.30, with peaks at seg 15-18, 45-48, 80-83
    points = []
    for i in range(100):
        start = float(i * 10)
        end = float(i * 10 + 10)
        val = 0.20
        if 15 <= i <= 18:
            val = 0.90
        elif 45 <= i <= 48:
            val = 0.95
        elif 80 <= i <= 83:
            val = 0.85
        points.append({"start": start, "end": end, "value": val})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(points, indent=2), encoding="utf-8")
    logger.info("heatmap_100.json created successfully")
    return out_path


def make_canned_gemini() -> None:
    """Create canned Gemini responses under tests/fixtures/gemini/."""
    gemini_dir = FIXTURES_DIR / "gemini"
    gemini_dir.mkdir(parents=True, exist_ok=True)

    nominate_file = gemini_dir / "nominate.json"
    if not nominate_file.exists():
        nominate_file.write_text(
            json.dumps(
                {
                    "candidates": [
                        {
                            "start_sid": 1,
                            "end_sid": 5,
                            "hook_sid": 1,
                            "reason": "Dramatic car chase and helicopter escape",
                            "hint_score": 88,
                            "is_story": False,
                        },
                        {
                            "start_sid": 8,
                            "end_sid": 14,
                            "hook_sid": 8,
                            "reason": "Secret military bunker discovery and jet steal",
                            "hint_score": 92,
                            "is_story": True,
                        },
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    judge_file = gemini_dir / "judge.json"
    if not judge_file.exists():
        judge_file.write_text(
            json.dumps(
                {
                    "evaluations": [
                        {
                            "cid": "n01",
                            "scores": {
                                "hook": 9.0,
                                "payoff": 8.5,
                                "clarity": 8.5,
                                "emotion": 8.0,
                                "novelty": 8.5,
                                "shareability": 8.0,
                                "pace": 8.5,
                            },
                            "needs_context": False,
                            "context_fix": None,
                            "is_story": False,
                            "topic": "GTA 6 Vehicle Physics",
                            "entities": ["Lucia", "Vice City"],
                            "content_flags": [],
                            "reasons": {"hook": "Instant high speed action"},
                        }
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def main() -> None:
    make_synthetic_video()
    make_heatmap_100()
    make_canned_gemini()
    logger.info("All fixtures generated successfully!")


if __name__ == "__main__":
    main()
