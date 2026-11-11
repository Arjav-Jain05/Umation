"""check_local_setup.py: Verify local-only hardware, weights, Ollama, GPU, and dependencies.

Gate 0 verification script per docs/SPEC.md.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def setup_nvidia_dll_paths() -> list[str]:
    added = []
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
                    added.append(str(cdir))
                except Exception:
                    pass
                os.environ["PATH"] = str(cdir) + ";" + os.environ.get("PATH", "")
    return added


setup_nvidia_dll_paths()


@dataclass
class CheckResult:
    name: str
    status: str  # PASS, WARN, FAIL
    detail: str
    fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_python() -> CheckResult:
    v = sys.version_info
    ver_str = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) in [(3, 11), (3, 12)]:
        return CheckResult("Python Version", "PASS", f"Python {ver_str}")
    return CheckResult(
        "Python Version",
        "FAIL",
        f"Python {ver_str} (requires 3.11 or 3.12)",
        "Install Python 3.12 via winget install --id Python.Python.3.12 -e",
    )


def check_gpu_and_vram() -> CheckResult:
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode != 0:
            return CheckResult(
                "NVIDIA GPU & VRAM",
                "FAIL",
                "nvidia-smi returned non-zero",
                "Verify NVIDIA driver is installed and RTX 4060 is detected.",
            )
        line = res.stdout.strip().split("\n")[0]
        parts = [p.strip() for p in line.split(",")]
        name = parts[0]
        total_mb = float(parts[1])
        free_mb = float(parts[2])
        driver = parts[3]

        if total_mb < 7000:
            return CheckResult(
                "NVIDIA GPU & VRAM",
                "WARN",
                f"{name}: Total {total_mb:.0f} MB, Free {free_mb:.0f} MB (Expected >= 8 GB)",
                "Ensure discrete NVIDIA GPU is active rather than integrated GPU.",
            )
        return CheckResult(
            "NVIDIA GPU & VRAM",
            "PASS",
            f"{name} (Driver {driver}): Total {total_mb:.0f} MB, Free {free_mb:.0f} MB",
        )
    except Exception as exc:
        return CheckResult(
            "NVIDIA GPU & VRAM",
            "FAIL",
            f"Failed to query GPU: {exc}",
            "Ensure NVIDIA graphics driver is installed.",
        )


def check_disk_space_d() -> CheckResult:
    try:
        usage = shutil.disk_usage("D:\\")
        free_gb = usage.free / (1024**3)
        if free_gb < 60:
            return CheckResult(
                "D: Drive Space",
                "FAIL",
                f"Free: {free_gb:.1f} GB (Required: >= 60 GB for weights & cache)",
                "Free up space on D: drive to at least 60 GB.",
            )
        return CheckResult("D: Drive Space", "PASS", f"Free: {free_gb:.1f} GB (>= 60 GB target)")
    except Exception as exc:
        return CheckResult(
            "D: Drive Space",
            "FAIL",
            f"Failed to inspect D: drive: {exc}",
            "Ensure D: drive exists and is accessible.",
        )


def check_env_vars() -> CheckResult:
    weights_dir = os.environ.get("WEIGHTS_DIR", "D:\\Open_Source_Weights")
    ollama_models = os.environ.get("OLLAMA_MODELS", "")

    issues = []
    if not Path(weights_dir).exists():
        issues.append(f"WEIGHTS_DIR does not exist: {weights_dir}")
    if "Open_Source_Weights" not in ollama_models and not Path("D:\\Open_Source_Weights\\ollama").exists():
        issues.append("OLLAMA_MODELS not pointing to Open_Source_Weights\\ollama")

    if issues:
        return CheckResult(
            "Environment Variables",
            "WARN",
            "; ".join(issues),
            "Run setx OLLAMA_MODELS D:\\Open_Source_Weights\\ollama and setx WEIGHTS_DIR D:\\Open_Source_Weights",
        )
    return CheckResult(
        "Environment Variables",
        "PASS",
        f"WEIGHTS_DIR={weights_dir}, OLLAMA_MODELS={ollama_models or 'D:\\Open_Source_Weights\\ollama'}",
    )


def check_ffmpeg_and_nvenc() -> CheckResult:
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return CheckResult("FFmpeg & NVENC", "FAIL", "ffmpeg not in PATH", "Install ffmpeg via winget or zip.")

    try:
        res = subprocess.run(["ffmpeg", "-encoders"], capture_output=True, text=True, timeout=10)
        has_nvenc = "h264_nvenc" in res.stdout
        if not has_nvenc:
            return CheckResult(
                "FFmpeg & NVENC",
                "WARN",
                "ffmpeg present but h264_nvenc not detected; CPU libx264 will be used.",
                "Install a full ffmpeg build with NVENC support.",
            )
        return CheckResult("FFmpeg & NVENC", "PASS", f"ffmpeg present with h264_nvenc ({ffmpeg_bin})")
    except Exception as exc:
        return CheckResult("FFmpeg & NVENC", "FAIL", f"Error checking ffmpeg: {exc}")


def check_ollama_service() -> CheckResult:
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    url = f"http://{host}/api/tags" if not host.startswith("http") else f"{host}/api/tags"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shorts-engine/check"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name") for m in data.get("models", [])]
            return CheckResult(
                "Ollama Service",
                "PASS",
                f"Ollama running at {host}, installed models: {models or 'none yet'}",
            )
    except Exception as exc:
        return CheckResult(
            "Ollama Service",
            "FAIL",
            f"Cannot connect to Ollama at {host}: {exc}",
            "Start Ollama service via 'ollama serve' with OLLAMA_MODELS=D:\\Open_Source_Weights\\ollama",
        )


def check_whisper_cuda() -> CheckResult:
    try:
        import ctranslate2
        cuda_count = ctranslate2.get_cuda_device_count()
        if cuda_count == 0:
            return CheckResult(
                "Whisper CUDA",
                "FAIL",
                "ctranslate2 found 0 CUDA devices",
                "pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 and check CUDA libraries.",
            )
        import faster_whisper
        return CheckResult(
            "Whisper CUDA",
            "PASS",
            f"faster-whisper {faster_whisper.__version__} ready on CUDA ({cuda_count} device)",
        )
    except Exception as exc:
        return CheckResult(
            "Whisper CUDA",
            "FAIL",
            f"Failed to initialize faster-whisper on CUDA: {exc}",
            "pip install faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12",
        )


def check_ytdlp() -> CheckResult:
    ytdlp_bin = shutil.which("yt-dlp")
    try:
        import yt_dlp
        ver = yt_dlp.version.__version__
        return CheckResult("yt-dlp", "PASS", f"yt-dlp {ver} installed ({ytdlp_bin or 'python package'})")
    except Exception as exc:
        return CheckResult("yt-dlp", "FAIL", f"yt-dlp check failed: {exc}", "pip install -U yt-dlp")


def check_whisper_models() -> CheckResult:
    weights_dir = Path(os.environ.get("WEIGHTS_DIR", "D:\\Open_Source_Weights"))
    whisper_root = weights_dir / "whisper"
    if not whisper_root.exists():
        return CheckResult("Whisper Models", "FAIL", f"Missing {whisper_root}", "Run download_weights.py --core")

    found = []
    for d in whisper_root.iterdir():
        if d.is_dir() and d.name.startswith("models--"):
            snaps = [s for s in (d / "snapshots").glob("*") if (s / "model.bin").is_file()]
            if snaps:
                sz_mb = (snaps[0] / "model.bin").stat().st_size / (1024**2)
                found.append(f"{d.name.replace('models--', '')} ({sz_mb:.0f} MB)")
    if not found:
        return CheckResult("Whisper Models", "FAIL", "No complete Whisper models with model.bin found", "Download Whisper weights")
    return CheckResult("Whisper Models", "PASS", f"Found: {', '.join(found)}")


def check_cv_models() -> CheckResult:
    weights_dir = Path(os.environ.get("WEIGHTS_DIR", "D:\\Open_Source_Weights"))
    p1 = weights_dir / "models" / "blaze_face_short_range.tflite"
    p2 = Path("assets/models/blaze_face_short_range.tflite")
    if p1.is_file() or p2.is_file():
        loc = p1 if p1.is_file() else p2
        return CheckResult("MediaPipe BlazeFace", "PASS", f"Installed at {loc} ({loc.stat().st_size} bytes)")
    return CheckResult("MediaPipe BlazeFace", "FAIL", "blaze_face_short_range.tflite missing", "Place blaze_face_short_range.tflite in D:\\Open_Source_Weights\\models")


def check_hf_weights() -> CheckResult:
    weights_dir = Path(os.environ.get("WEIGHTS_DIR", "D:\\Open_Source_Weights"))
    hf_root = weights_dir / "huggingface"
    expected = [
        "BAAI--bge-small-en-v1.5",
        "j-hartmann--emotion-english-distilroberta-base",
        "MIT--ast-finetuned-audioset-10-10-0.4593",
        "google--siglip-base-patch16-224",
    ]
    found = []
    missing = []
    for exp in expected:
        cand = hf_root / f"models--{exp}"
        if cand.is_dir():
            found.append(exp)
        else:
            missing.append(exp)
    if missing:
        return CheckResult("HF Auxiliary Models", "WARN", f"Found {len(found)}/{len(expected)}. Missing: {', '.join(missing)}", "Run download_weights.py --all")
    return CheckResult("HF Auxiliary Models", "PASS", f"All {len(expected)} models present in {hf_root}")


def check_ollama_models() -> CheckResult:
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    url = f"http://{host}/api/tags" if not host.startswith("http") else f"{host}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shorts-engine/check"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            installed = [m.get("name") for m in data.get("models", [])]
            has_qwen = any("qwen3.5:9b" in m for m in installed)
            has_gemma = any("gemma4:e4b" in m for m in installed)
            if has_qwen and has_gemma:
                return CheckResult("Ollama LLMs", "PASS", f"Primary (qwen3.5:9b) & Secondary (gemma4:e4b) installed: {installed}")
            elif has_qwen:
                return CheckResult("Ollama LLMs", "PASS", f"Primary qwen3.5:9b installed (Secondary downloading/pending): {installed}")
            return CheckResult("Ollama LLMs", "FAIL", f"Required models missing. Installed: {installed}", "ollama pull qwen3.5:9b")
    except Exception as exc:
        return CheckResult("Ollama LLMs", "FAIL", f"Cannot connect to Ollama: {exc}")


def run_all_checks() -> list[CheckResult]:
    return [
        check_python(),
        check_gpu_and_vram(),
        check_disk_space_d(),
        check_env_vars(),
        check_ffmpeg_and_nvenc(),
        check_ollama_service(),
        check_ollama_models(),
        check_whisper_cuda(),
        check_whisper_models(),
        check_cv_models(),
        check_hf_weights(),
        check_ytdlp(),
    ]


def main() -> int:
    print("=" * 70)
    print("SHORTS-ENGINE LOCAL ENVIRONMENT HEALTH CHECK (Phase 0 Preflight)")
    print("=" * 70)

    results = run_all_checks()
    fail_count = 0
    warn_count = 0

    for r in results:
        status_tag = f"[{r.status}]"
        print(f"{status_tag:<8} {r.name:<24} : {r.detail}")
        if r.fix:
            print(f"         FIX: {r.fix}")
        if r.status == "FAIL":
            fail_count += 1
        elif r.status == "WARN":
            warn_count += 1

    print("-" * 70)
    print(f"Summary: {len(results) - fail_count - warn_count} PASS, {warn_count} WARN, {fail_count} FAIL")

    if fail_count > 0:
        print("RESULT: PREFLIGHT FAILED. Follow fixes above before proceeding.")
        return 1
    print("RESULT: PREFLIGHT PASSED. Core environment ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
