"""Download required models and fonts into assets/."""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "assets"
MODELS_DIR = ASSETS_DIR / "models"
FONTS_DIR = ASSETS_DIR / "fonts"

DOWNLOADS = {
    "models": [
        {
            "name": "blaze_face_short_range.tflite",
            "url": "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
            "dest_dir": MODELS_DIR,
            "min_size_kb": 100,
        },
        {
            "name": "selfie_segmenter.tflite",
            "url": "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite",
            "dest_dir": MODELS_DIR,
            "min_size_kb": 100,
        },
    ],
    "fonts": [
        {
            "name": "Anton-Regular.ttf",
            "url": "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
            "dest_dir": FONTS_DIR,
            "min_size_kb": 10,
        },
        {
            "name": "Montserrat-ExtraBold.ttf",
            "url": "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-ExtraBold.ttf",
            "dest_dir": FONTS_DIR,
            "min_size_kb": 10,
        },
        {
            "name": "NotoColorEmoji.ttf",
            "url": "https://github.com/google/fonts/raw/main/ofl/notocoloremoji/NotoColorEmoji-Regular.ttf",
            "dest_dir": FONTS_DIR,
            "min_size_kb": 500,
        },
    ],
}


def download_file(url: str, dest_path: Path, min_size_kb: int = 10) -> bool:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
    print(f"Downloading {dest_path.name} from {url}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(tmp_path, "wb") as out_f:
            while chunk := resp.read(65536):
                out_f.write(chunk)

        size_kb = tmp_path.stat().st_size / 1024
        if size_kb < min_size_kb:
            print(f"FAIL: {dest_path.name} is too small ({size_kb:.1f} KB < {min_size_kb} KB)")
            if tmp_path.exists():
                tmp_path.unlink()
            return False
        tmp_path.replace(dest_path)
        print(f"PASS: {dest_path.name} ({size_kb:.1f} KB) saved to {dest_path}")
        return True
    except Exception as e:
        print(f"FAIL: Error downloading {url}: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        return False


def run_downloads(include_models: bool = True, include_fonts: bool = True) -> int:
    success = True
    items = []
    if include_models:
        items.extend(DOWNLOADS["models"])
    if include_fonts:
        items.extend(DOWNLOADS["fonts"])

    for item in items:
        target = item["dest_dir"] / item["name"]
        if target.exists() and target.stat().st_size / 1024 >= item["min_size_kb"]:
            print(f"ALREADY PRESENT: {item['name']} ({target.stat().st_size / 1024:.1f} KB)")
            continue
        ok = download_file(item["url"], target, item["min_size_kb"])
        if not ok:
            success = False

    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description="Download assets for shorts-engine")
    parser.add_argument("--models", action="store_true", help="Download models only")
    parser.add_argument("--fonts", action="store_true", help="Download fonts only")
    args = parser.parse_args()

    include_models = True
    include_fonts = True
    if args.models and not args.fonts:
        include_fonts = False
    elif args.fonts and not args.models:
        include_models = False

    code = run_downloads(include_models=include_models, include_fonts=include_fonts)
    sys.exit(code)


if __name__ == "__main__":
    main()
