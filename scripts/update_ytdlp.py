"""Update yt-dlp to the latest release."""

from __future__ import annotations

import subprocess
import sys


def update_ytdlp() -> bool:
    """Run pip upgrade for yt-dlp."""
    print("Checking for yt-dlp updates...")
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.returncode == 0:
        print(res.stdout)
        print("yt-dlp update check completed successfully.")
        return True
    else:
        print(f"Failed to update yt-dlp:\n{res.stderr}", file=sys.stderr)
        return False


if __name__ == "__main__":
    success = update_ytdlp()
    sys.exit(0 if success else 1)
