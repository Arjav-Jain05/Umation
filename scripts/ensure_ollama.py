"""ensure_ollama.py: Check if Ollama is running, and auto-start it if not.

Configures OLLAMA_MODELS from .env (defaults to D:\\Open_Source_Weights\\ollama).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("scripts.ensure_ollama")

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_WEIGHTS_DIR = ROOT_DIR / "weights" / "ollama"
DEFAULT_HOST = "127.0.0.1:11434"


def find_ollama_binary() -> Path | None:
    """Locate the ollama.exe binary on the system."""
    # 1. PATH lookup
    which_path = shutil.which("ollama")
    if which_path:
        return Path(which_path)

    # 2. Standard Windows LocalAppData install location
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        cand = Path(local_app) / "Programs" / "Ollama" / "ollama.exe"
        if cand.exists():
            return cand

    # 3. Standard Program Files location
    for pf in ["ProgramFiles", "ProgramFiles(x86)"]:
        base = os.environ.get(pf)
        if base:
            cand = Path(base) / "Ollama" / "ollama.exe"
            if cand.exists():
                return cand

    return None


def is_ollama_ready(host: str = DEFAULT_HOST, timeout: float = 1.0) -> tuple[bool, list[str]]:
    """Check if Ollama server responds on the specified host, returning (is_ready, model_names)."""
    url = f"http://{host}/api/tags" if not host.startswith("http") else f"{host}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shorts-engine"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            return True, models
    except Exception:
        return False, []


def ensure_ollama(
    env_path: Path | None = None,
    max_wait_s: float = 15.0,
    verbose: bool = True,
) -> bool:
    """Ensure Ollama is running. If not, auto-launch it in background with configured models."""
    root_dir = Path(__file__).resolve().parent.parent
    if env_path is None:
        env_path = root_dir / ".env"

    host = DEFAULT_HOST
    models_dir = DEFAULT_WEIGHTS_DIR

    # Load configuration from .env
    if env_path.exists():
        try:
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("OLLAMA_HOST="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            host = val
                    elif line.startswith("OLLAMA_MODELS="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            p = Path(val)
                            models_dir = p if p.is_absolute() else (root_dir / p).resolve()
        except Exception as exc:
            if verbose:
                print(f"[WARN] Could not parse .env: {exc}")

    # Ensure environment variables are set in current process
    os.environ["OLLAMA_HOST"] = host
    os.environ["OLLAMA_MODELS"] = str(models_dir)

    # 1. Check if already responding
    ready, models = is_ollama_ready(host=host, timeout=1.0)
    if ready:
        if verbose:
            model_summary = ", ".join(models[:4]) if models else "none"
            print(f"[OK] Ollama is active on http://{host} ({len(models)} models: {model_summary})")
        return True

    # 2. Locate binary
    binary = find_ollama_binary()
    if not binary:
        if verbose:
            print("[ERROR] ollama.exe not found on PATH or in AppData.")
            print("Please install Ollama from https://ollama.ai and run 'ollama pull qwen3.5:9b'")
        return False

    if verbose:
        print("[*] Starting local Ollama server in background...")
        print(f"    Binary: {binary}")
        print(f"    Models: {models_dir}")
        print(f"    Host:   http://{host}")

    # 3. Launch in detached background process
    env = os.environ.copy()
    env["OLLAMA_MODELS"] = str(models_dir)
    env["OLLAMA_HOST"] = host
    env["OLLAMA_KEEP_ALIVE"] = "60m"
    env["OLLAMA_MAX_LOADED_MODELS"] = "3"
    env["OLLAMA_NUM_PARALLEL"] = "1"

    creationflags = 0
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE

    try:
        subprocess.Popen(
            [str(binary), "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
    except Exception as exc:
        if verbose:
            print(f"[ERROR] Failed to spawn Ollama process: {exc}")
        return False

    # 4. Wait for Ollama to become ready
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_wait_s:
        time.sleep(0.5)
        ready, models = is_ollama_ready(host=host, timeout=1.0)
        if ready:
            if verbose:
                model_summary = ", ".join(models[:4]) if models else "none"
                elapsed = time.monotonic() - t0
                print(f"[OK] Ollama ready in {elapsed:.1f}s on http://{host} ({len(models)} models: {model_summary})")
            return True

    if verbose:
        print(f"[WARN] Ollama launched but port {host} has not responded after {max_wait_s}s.")
        print("Continuing startup anyway...")
    return False


def main() -> None:
    ok = ensure_ollama(verbose=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
