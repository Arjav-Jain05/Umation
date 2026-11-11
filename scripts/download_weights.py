"""download_weights.py: Download, verify, and catalog weights in D:\\Open_Source_Weights.

Usage:
    python scripts/download_weights.py --core
    python scripts/download_weights.py --all
    python scripts/download_weights.py --only <layer_number>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

WEIGHTS_DIR = Path(os.environ.get("WEIGHTS_DIR", "D:\\Open_Source_Weights"))
MANIFEST_FILE = WEIGHTS_DIR / "manifest.json"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")


def setup_nvidia_dll_paths() -> None:
    if sys.platform == "win32":
        venv_root = Path(sys.prefix)
        site_packages = venv_root / "Lib" / "site-packages"
        candidate_dirs = [
            site_packages / "nvidia" / "cublas" / "bin",
            site_packages / "nvidia" / "cudnn" / "bin",
            site_packages / "nvidia" / "cuda_nvrtc" / "bin",
            site_packages / "ctranslate2",
        ]
        for cdir in candidate_dirs:
            if cdir.exists():
                try:
                    os.add_dll_directory(str(cdir))
                except Exception:
                    pass
                os.environ["PATH"] = str(cdir) + ";" + os.environ.get("PATH", "")


setup_nvidia_dll_paths()


def load_manifest() -> dict[str, Any]:
    if MANIFEST_FILE.exists():
        try:
            with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"models": [], "updated_at": datetime.now().isoformat()}


def save_manifest(manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = datetime.now().isoformat()
    tmp_path = MANIFEST_FILE.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    tmp_path.replace(MANIFEST_FILE)


def update_manifest_entry(name: str, layer: int, local_path: str, size_bytes: int, source: str) -> None:
    manifest = load_manifest()
    models = manifest.get("models", [])
    # Update existing or append
    found = False
    for m in models:
        if m.get("name") == name:
            m["layer"] = layer
            m["local_path"] = str(local_path)
            m["size_bytes"] = size_bytes
            m["source"] = source
            m["verified_at"] = datetime.now().isoformat()
            found = True
            break
    if not found:
        models.append({
            "name": name,
            "layer": layer,
            "local_path": str(local_path),
            "size_bytes": size_bytes,
            "source": source,
            "verified_at": datetime.now().isoformat(),
        })
    manifest["models"] = models
    save_manifest(manifest)


def check_disk_space(required_gb: float = 20.0) -> bool:
    try:
        usage = shutil.disk_usage(WEIGHTS_DIR)
        free_gb = usage.free / (1024**3)
        if free_gb < required_gb:
            print(f"[ERROR] Insufficient disk space on {WEIGHTS_DIR.drive}: {free_gb:.1f} GB free, need {required_gb:.1f} GB.")
            return False
        return True
    except Exception as exc:
        print(f"[WARN] Could not check disk space: {exc}")
        return True


def download_whisper_model(model_name: str = "large-v3-turbo") -> bool:
    """Download faster-whisper model into D:\\Open_Source_Weights\\whisper."""
    whisper_dir = WEIGHTS_DIR / "whisper"
    whisper_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n--- [L0] Checking/Downloading faster-whisper model '{model_name}' ---")

    try:
        from faster_whisper import WhisperModel
        print(f"Loading/downloading '{model_name}' to {whisper_dir}...")
        t0 = time.time()
        # Initialize with device="cpu" just to ensure download without consuming GPU VRAM now
        model = WhisperModel(model_name, device="cpu", compute_type="int8", download_root=str(whisper_dir))
        elapsed = time.time() - t0
        del model

        # Calculate directory size
        total_size = sum(f.stat().st_size for f in whisper_dir.rglob("*") if f.is_file())
        update_manifest_entry(
            name=f"faster-whisper-{model_name}",
            layer=0,
            local_path=str(whisper_dir),
            size_bytes=total_size,
            source=f"Systran/faster-whisper-{model_name}",
        )
        print(f"[PASS] faster-whisper '{model_name}' ready in {elapsed:.1f}s. Size: {total_size / (1024**2):.1f} MB.")
        return True
    except Exception as exc:
        print(f"[FAIL] Failed to download faster-whisper '{model_name}': {exc}")
        return False


def pull_ollama_model(model_name: str, layer: int) -> bool:
    """Pull Ollama model via Ollama CLI or HTTP API."""
    print(f"\n--- [L{layer}] Checking/Pulling Ollama model '{model_name}' ---")

    # Check if already present
    host = OLLAMA_HOST if OLLAMA_HOST.startswith("http") else f"http://{OLLAMA_HOST}"
    try:
        req = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            installed = [m.get("name") for m in data.get("models", [])]
            for m in installed:
                if m == model_name or m.startswith(model_name + ":") or (":" in model_name and m == model_name):
                    print(f"[PASS] Model '{model_name}' is already installed in Ollama.")
                    update_manifest_entry(
                        name=f"ollama-{model_name}",
                        layer=layer,
                        local_path=str(WEIGHTS_DIR / "ollama"),
                        size_bytes=0,
                        source=f"ollama.com/library/{model_name}",
                    )
                    return True
    except Exception as exc:
        print(f"[WARN] Could not query Ollama tags: {exc}")

    # Pull via CLI
    print(f"Pulling '{model_name}' via ollama pull...")
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["ollama", "pull", model_name],
            check=False,
            text=True,
            timeout=1800,  # 30 min max for large models
        )
        if proc.returncode == 0:
            elapsed = time.time() - t0
            print(f"[PASS] Successfully pulled '{model_name}' in {elapsed:.1f}s.")
            update_manifest_entry(
                name=f"ollama-{model_name}",
                layer=layer,
                local_path=str(WEIGHTS_DIR / "ollama"),
                size_bytes=0,
                source=f"ollama.com/library/{model_name}",
            )
            return True
        else:
            print(f"[FAIL] ollama pull '{model_name}' exited with code {proc.returncode}")
            return False
    except Exception as exc:
        print(f"[FAIL] Error pulling '{model_name}': {exc}")
        return False


def download_hf_model(repo_id: str, layer: int, subfolder: str = "") -> bool:
    """Download HuggingFace model snapshot to D:\\Open_Source_Weights\\huggingface."""
    hf_dir = WEIGHTS_DIR / "huggingface"
    hf_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n--- [L{layer}] Downloading HF model '{repo_id}' ---")

    try:
        from huggingface_hub import snapshot_download
        t0 = time.time()
        local_path = snapshot_download(
            repo_id=repo_id,
            cache_dir=str(hf_dir),
            local_files_only=False,
        )
        elapsed = time.time() - t0
        total_size = sum(f.stat().st_size for f in Path(local_path).rglob("*") if f.is_file())
        update_manifest_entry(
            name=repo_id.replace("/", "--"),
            layer=layer,
            local_path=str(local_path),
            size_bytes=total_size,
            source=f"https://huggingface.co/{repo_id}",
        )
        print(f"[PASS] '{repo_id}' downloaded in {elapsed:.1f}s. Size: {total_size / (1024**2):.1f} MB.")
        return True
    except Exception as exc:
        print(f"[FAIL] Failed to download HF model '{repo_id}': {exc}")
        return False


def run_core_downloads() -> bool:
    print("======================================================================")
    print("DOWNLOADING CORE WEIGHTS (L0 Whisper + L2 Ollama LLMs)")
    print("======================================================================")
    if not check_disk_space(20.0):
        return False

    success = True
    # L0: Whisper
    success = download_whisper_model("large-v3-turbo") and success

    # L2: Primary Proposer
    success = pull_ollama_model("qwen3.5:9b", layer=2) and success

    # L2: Secondary Proposer (gemma4:e4b or alternative)
    # Check if gemma4:e4b is pullable; if not, fall back to gemma2:9b or qwen2.5:7b
    print("\nAttempting to pull secondary proposer 'gemma4:e4b'...")
    gemma_ok = pull_ollama_model("gemma4:e4b", layer=2)
    if not gemma_ok:
        print("[NOTICE] 'gemma4:e4b' tag not found on Ollama library. Testing fallback 'gemma2:9b'...")
        gemma_ok = pull_ollama_model("gemma2:9b", layer=2)
        if not gemma_ok:
            print("[NOTICE] Testing fallback 'qwen2.5:7b'...")
            gemma_ok = pull_ollama_model("qwen2.5:7b", layer=2)
    success = gemma_ok and success

    return success


def run_all_downloads() -> bool:
    core_ok = run_core_downloads()

    print("\n======================================================================")
    print("DOWNLOADING AUXILIARY MODELS (L1 Sensors, L5 Visual, L9 Thumbnails)")
    print("======================================================================")

    # L1: BGE small embeddings
    download_hf_model("BAAI/bge-small-en-v1.5", layer=1)

    # L1: Text emotion
    download_hf_model("j-hartmann/emotion-english-distilroberta-base", layer=1)

    # L1: AST audio events
    download_hf_model("MIT/ast-finetuned-audioset-10-10-0.4593", layer=1)

    # L5: SigLIP
    download_hf_model("google/siglip-base-patch16-224", layer=5)

    return core_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and verify weights for shorts-engine.")
    parser.add_argument("--core", action="store_true", help="Download core models (Whisper + primary/secondary LLMs)")
    parser.add_argument("--all", action="store_true", help="Download all models (core + sensors + vision)")
    parser.add_argument("--only", type=int, help="Download models for only a specific layer (0-9)")
    args = parser.parse_args()

    if not any([args.core, args.all, args.only is not None]):
        parser.print_help()
        return 1

    if args.core:
        ok = run_core_downloads()
    elif args.all:
        ok = run_all_downloads()
    elif args.only is not None:
        if args.only == 0:
            ok = download_whisper_model("large-v3-turbo")
        elif args.only == 1:
            ok = download_hf_model("BAAI/bge-small-en-v1.5", layer=1)
            download_hf_model("j-hartmann/emotion-english-distilroberta-base", layer=1)
            download_hf_model("MIT/ast-finetuned-audioset-10-10-0.4593", layer=1)
        elif args.only == 2:
            ok = pull_ollama_model("qwen3.5:9b", layer=2)
        elif args.only == 5:
            ok = download_hf_model("google/siglip-base-patch16-224", layer=5)
        else:
            print(f"Layer {args.only} download not specifically configured.")
            ok = True
    else:
        ok = False

    manifest = load_manifest()
    print("\nCURRENT MANIFEST SUMMARY:")
    for m in manifest.get("models", []):
        sz_mb = m.get("size_bytes", 0) / (1024**2)
        print(f"  Layer {m.get('layer')}: {m.get('name')} -> {sz_mb:.1f} MB [{m.get('source')}]")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
