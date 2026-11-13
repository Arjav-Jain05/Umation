"""setup_wizard.py: Interactive first-run setup wizard for shorts-engine.

Checks for missing models (Whisper, Ollama, MediaPipe, fonts) and prompts the user
to download them automatically if missing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def find_ollama_binary() -> Path | None:
    """Locate the ollama.exe binary on the system."""
    which_path = shutil.which("ollama")
    if which_path:
        return Path(which_path)
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        cand = Path(local_app) / "Programs" / "Ollama" / "ollama.exe"
        if cand.exists():
            return cand
    for pf in ["ProgramFiles", "ProgramFiles(x86)"]:
        base = os.environ.get(pf)
        if base:
            cand = Path(base) / "Ollama" / "ollama.exe"
            if cand.exists():
                return cand
    return None


def get_configured_paths() -> tuple[Path, Path]:
    """Determine the configured weights and ollama models directories."""
    weights_dir = None
    ollama_models = None

    env_file = ROOT_DIR / ".env"
    if env_file.exists():
        try:
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#"):
                        continue
                    if line.startswith("WEIGHTS_DIR="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            p = Path(val)
                            weights_dir = p if p.is_absolute() else (ROOT_DIR / p).resolve()
                    elif line.startswith("OLLAMA_MODELS="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            p = Path(val)
                            ollama_models = p if p.is_absolute() else (ROOT_DIR / p).resolve()
        except Exception:
            pass

    if weights_dir is None:
        raw = os.environ.get("WEIGHTS_DIR", "./weights")
        p = Path(raw)
        weights_dir = p if p.is_absolute() else (ROOT_DIR / p).resolve()

    if ollama_models is None:
        raw_ollama = os.environ.get("OLLAMA_MODELS")
        if raw_ollama:
            p = Path(raw_ollama)
            ollama_models = p if p.is_absolute() else (ROOT_DIR / p).resolve()
        else:
            ollama_models = weights_dir / "ollama"

    return weights_dir, ollama_models


def ensure_env_file() -> None:
    """Create .env from .env.example if missing."""
    env_file = ROOT_DIR / ".env"
    example = ROOT_DIR / ".env.example"
    if not env_file.exists() and example.exists():
        shutil.copy(example, env_file)
        print("[SETUP] Created default .env configuration from .env.example")


def check_missing_components() -> list[str]:
    """Check what models and assets are missing."""
    missing = []
    weights_dir, ollama_dir = get_configured_paths()

    # 1. Fonts
    fonts_dir = ROOT_DIR / "assets" / "fonts"
    required_fonts = ["Anton-Regular.ttf", "Montserrat-ExtraBold.ttf"]
    if not all((fonts_dir / f).exists() for f in required_fonts):
        missing.append("Open-source typography fonts (assets/fonts)")

    # 2. MediaPipe models
    models_dir = ROOT_DIR / "assets" / "models"
    detector = models_dir / "blaze_face_short_range.tflite"
    alt_detector = weights_dir / "models" / "blaze_face_short_range.tflite"
    if not detector.exists() and not alt_detector.exists():
        missing.append("MediaPipe BlazeFace face detector (assets/models)")

    segmenter = models_dir / "selfie_segmenter.tflite"
    alt_segmenter = weights_dir / "models" / "selfie_segmenter.tflite"
    if not segmenter.exists() and not alt_segmenter.exists():
        missing.append("MediaPipe Selfie Segmenter (assets/models)")

    # 3. Whisper model
    whisper_dir = weights_dir / "whisper"
    has_whisper = False
    if whisper_dir.exists():
        candidates = list(whisper_dir.glob("**/model.bin"))
        if candidates and any(c.stat().st_size > 500_000_000 for c in candidates):
            has_whisper = True
    if not has_whisper:
        missing.append("Faster-Whisper model in weights/whisper (~1.5 GB)")

    # 4. Ollama binary check
    binary = find_ollama_binary()

    # 5. Ollama model (check running service OR check disk manifests)
    ollama_ready = False
    ollama_host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    url = f"http://{ollama_host}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shorts-engine"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=0.8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            if any("qwen3.5" in m or "qwen2.5" in m for m in models):
                ollama_ready = True
    except Exception:
        pass

    # Fallback check directly in Ollama manifests directory on disk
    if not ollama_ready and ollama_dir.exists():
        manifests = list((ollama_dir / "manifests").glob("**/*"))
        if any("qwen" in str(p).lower() for p in manifests):
            ollama_ready = True

    if not binary and not ollama_ready:
        missing.append("Ollama AI Engine runtime (not installed - needed for local AI)")

    if not ollama_ready:
        missing.append("Ollama LLM model 'qwen3.5:9b' (~5.5 GB)")

    return missing


def run_setup_downloads() -> bool:
    """Download required fonts, MediaPipe models, and AI weights."""
    print("\n[1/3] Downloading open-source fonts and MediaPipe assets...")
    cmd_assets = [sys.executable, str(ROOT_DIR / "scripts" / "download_models.py")]
    subprocess.run(cmd_assets, check=False)

    # Ensure Ollama is installed
    binary = find_ollama_binary()
    if not binary:
        print("\n[!] Ollama is not installed on this machine.")
        print("[*] Attempting automatic installation via winget...")
        try:
            p = subprocess.run(
                ["winget", "install", "--id", "Ollama.Ollama", "-e", "--accept-source-agreements", "--accept-package-agreements"],
                check=False,
            )
            time.sleep(2)
            binary = find_ollama_binary()
        except Exception:
            pass
        if not binary:
            print("\n" + "!" * 64)
            print("[ACTION REQUIRED] Please install Ollama from: https://ollama.com/download")
            print("Run the official installer, then press [Enter] here once complete.")
            print("!" * 64)
            try:
                input("Press [Enter] after installing Ollama to continue...")
            except (EOFError, KeyboardInterrupt):
                pass
            binary = find_ollama_binary()

    print("\n[2/3] Ensuring Ollama AI service is running...")
    cmd_ollama = [sys.executable, str(ROOT_DIR / "scripts" / "ensure_ollama.py")]
    subprocess.run(cmd_ollama, check=False)

    print("\n[3/3] Downloading core AI model weights (Whisper + Ollama LLM)...")
    cmd_weights = [sys.executable, str(ROOT_DIR / "scripts" / "download_weights.py"), "--core"]
    res = subprocess.run(cmd_weights)

    return res.returncode == 0


def interactive_wizard() -> bool:
    """Run interactive setup wizard if any components are missing."""
    ensure_env_file()
    missing = check_missing_components()

    if not missing:
        return True

    print("\n" + "=" * 64)
    print("           SHORTS ENGINE - FIRST-TIME SETUP WIZARD")
    print("=" * 64)
    print("The following components are not yet installed:")
    for item in missing:
        print(f"  * {item}")
    print("-" * 64)
    print("Shorts Engine runs 100% locally and needs these models to operate.")
    print("Approximate total download size: ~7-8 GB (one-time download).")
    print("=" * 64)

    try:
        choice = input("\nWould you like to download all required models now? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n[INFO] Setup cancelled.")
        return False

    if choice in ("", "y", "yes"):
        print("\n[*] Starting automated download process. This may take a few minutes...")
        ok = run_setup_downloads()
        if ok:
            print("\n" + "=" * 64)
            print("[SUCCESS] All required models and assets are ready!")
            print("=" * 64 + "\n")
            return True
        else:
            print("\n[WARN] Some downloads did not complete successfully.")
            print("You can retry at any time by running: python scripts/download_weights.py --core\n")
            return False
    else:
        print("\n[INFO] Skipping model downloads.")
        print("You can download them later using: python scripts/download_weights.py --core\n")
        return False


if __name__ == "__main__":
    interactive_wizard()
