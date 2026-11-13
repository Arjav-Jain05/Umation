"""check_env.py: Verify runtime environment, dependencies, GPU, tools, and configs.

Used directly as CLI and imported by GET /api/system/check.
"""

from __future__ import annotations

import datetime
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# Add nvidia dll directories if present
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
                # Also ensure in PATH for subprocesses or ctypes fallback
                os.environ["PATH"] = str(cdir) + ";" + os.environ.get("PATH", "")
    return added


setup_nvidia_dll_paths()


@dataclass
class CheckResult:
    check: str
    status: str  # PASS, WARN, FAIL
    detail: str
    fix: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def check_python_version() -> CheckResult:
    v = sys.version_info
    ver_str = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) in [(3, 11), (3, 12)]:
        return CheckResult("Python version", "PASS", f"Python {ver_str}")
    return CheckResult(
        "Python version",
        "FAIL",
        f"Python {ver_str} (expected 3.11 or 3.12)",
        "Install Python 3.12 via winget install --id Python.Python.3.12 -e",
    )


def check_disk_space(data_dir: Path, min_free_gb: int = 30) -> CheckResult:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(data_dir)
        free_gb = usage.free / (1024**3)
        if free_gb >= min_free_gb:
            return CheckResult("Disk space", "PASS", f"{free_gb:.1f} GB free on {data_dir.drive or data_dir}")
        elif free_gb >= 10:
            return CheckResult(
                "Disk space",
                "WARN",
                f"{free_gb:.1f} GB free (recommended >= {min_free_gb} GB)",
                f"Free up disk space on {data_dir.drive} or change DATA_DIR in .env",
            )
        else:
            return CheckResult(
                "Disk space",
                "FAIL",
                f"Only {free_gb:.1f} GB free (critical minimum is 10 GB)",
                "Free up disk space immediately or change DATA_DIR in .env",
            )
    except Exception as e:
        return CheckResult("Disk space", "FAIL", f"Cannot determine disk space: {e}")


def check_ffmpeg() -> list[CheckResult]:
    results = []
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")

    if not ffmpeg_path or not ffprobe_path:
        missing = []
        if not ffmpeg_path:
            missing.append("ffmpeg")
        if not ffprobe_path:
            missing.append("ffprobe")
        results.append(
            CheckResult(
                "FFmpeg tools",
                "FAIL",
                f"Missing on PATH: {', '.join(missing)}",
                "Install Gyan.FFmpeg via winget install --id Gyan.FFmpeg -e",
            )
        )
        return results

    # Check ffmpeg version
    try:
        proc = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_creation_flags(),
        )
        first_line = proc.stdout.splitlines()[0] if proc.stdout else "unknown"
        results.append(CheckResult("FFmpeg version", "PASS", first_line))
    except Exception as e:
        results.append(CheckResult("FFmpeg version", "FAIL", f"Failed to run ffmpeg: {e}"))

    # Check NVENC encoder & test encode
    try:
        enc_proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_creation_flags(),
        )
        if "h264_nvenc" in enc_proc.stdout:
            # Run test encode
            test_proc = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=duration=1:size=128x128:rate=30",
                    "-c:v",
                    "h264_nvenc",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=_creation_flags(),
            )
            # Check stderr for encoded frames
            if "frame=" in test_proc.stderr:
                results.append(CheckResult("NVENC hardware encode", "PASS", "h264_nvenc encoder test succeeded"))
            else:
                results.append(
                    CheckResult(
                        "NVENC hardware encode",
                        "FAIL",
                        "h264_nvenc test failed to encode frames",
                        "Update NVIDIA display drivers",
                    )
                )
        else:
            results.append(
                CheckResult(
                    "NVENC hardware encode",
                    "FAIL",
                    "h264_nvenc not present in ffmpeg encoders",
                    "Install Gyan.FFmpeg (full build) and update GPU drivers",
                )
            )
    except Exception as e:
        results.append(CheckResult("NVENC hardware encode", "FAIL", f"Error checking NVENC: {e}"))

    return results


def check_gpu() -> CheckResult:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_creation_flags(),
        )
        if proc.returncode == 0 and proc.stdout.strip():
            gpu_info = proc.stdout.strip().replace("\r", "")
            return CheckResult("NVIDIA GPU", "PASS", gpu_info)
        return CheckResult("NVIDIA GPU", "FAIL", "nvidia-smi returned no output", "Install/reinstall NVIDIA drivers")
    except Exception as e:
        return CheckResult("NVIDIA GPU", "FAIL", f"nvidia-smi not available: {e}", "Ensure NVIDIA driver is installed")


def check_deno() -> CheckResult:
    deno_path = shutil.which("deno")
    if not deno_path:
        # Check user local path if recently installed
        local_deno = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        deno_candidates = list(local_deno.glob("**/deno.exe")) if local_deno.exists() else []
        if deno_candidates:
            deno_path = str(deno_candidates[0])
            os.environ["PATH"] = str(deno_candidates[0].parent) + ";" + os.environ.get("PATH", "")

    if deno_path:
        try:
            proc = subprocess.run(
                [deno_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=_creation_flags(),
            )
            ver = proc.stdout.splitlines()[0] if proc.stdout else "deno found"
            return CheckResult("Deno (yt-dlp JS runtime)", "PASS", ver)
        except Exception as e:
            return CheckResult("Deno (yt-dlp JS runtime)", "WARN", f"deno execution error: {e}")
    return CheckResult(
        "Deno (yt-dlp JS runtime)",
        "WARN",
        "Deno not found on PATH",
        "Install Deno via winget install --id DenoLand.Deno -e",
    )


def check_ytdlp() -> CheckResult:
    try:
        import yt_dlp
        version_str = getattr(yt_dlp.version, "__version__", "unknown")
        # yt-dlp version is typically YYYY.MM.DD or YYYY.MM.DD.xxxx
        parts = version_str.split(".")
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
            rel_date = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
            age_days = (datetime.date.today() - rel_date).days
            if age_days > 60:
                return CheckResult(
                    "yt-dlp package",
                    "WARN",
                    f"yt-dlp {version_str} is {age_days} days old",
                    "Run python scripts/update_ytdlp.py",
                )
            return CheckResult("yt-dlp package", "PASS", f"yt-dlp {version_str} ({age_days}d old)")
        return CheckResult("yt-dlp package", "PASS", f"yt-dlp {version_str}")
    except ImportError:
        return CheckResult("yt-dlp package", "FAIL", "yt-dlp not installed", "pip install yt-dlp")
    except Exception as e:
        return CheckResult("yt-dlp package", "WARN", f"yt-dlp check warning: {e}")


def check_whisper_cuda() -> CheckResult:
    setup_nvidia_dll_paths()
    try:
        import numpy as np
        from faster_whisper import WhisperModel

        # Try loading tiny on CUDA float16
        model = WhisperModel("tiny", device="cuda", compute_type="float16")
        # Transcribe 1s silence (16kHz float32 zero array)
        silence = np.zeros(16000, dtype=np.float32)
        segments, _ = model.transcribe(silence, language="en")
        _ = list(segments)
        del model
        import gc
        gc.collect()
        return CheckResult("faster-whisper CUDA", "PASS", "CUDA float16 tiny model transcribed silence successfully")
    except Exception as e:
        return CheckResult(
            "faster-whisper CUDA",
            "WARN",  # Non-blocking per spec fallback
            f"CUDA transcription failed: {e}",
            "Install nvidia-cublas-cu12 nvidia-cudnn-cu12 or set WHISPER_DEVICE=cpu in .env",
        )


def check_mediapipe(assets_dir: Path) -> CheckResult:
    try:
        import mediapipe
        model_file = assets_dir / "models" / "blaze_face_short_range.tflite"
        if not model_file.exists() or model_file.stat().st_size < 100 * 1024:
            return CheckResult(
                "MediaPipe face detector",
                "FAIL",
                f"Model file missing or too small at {model_file}",
                "Run python scripts/download_models.py --models",
            )
        return CheckResult("MediaPipe face detector", "PASS", f"MediaPipe {mediapipe.__version__} with model present")
    except ImportError:
        return CheckResult("MediaPipe face detector", "FAIL", "mediapipe package not installed", "pip install mediapipe")
    except Exception as e:
        return CheckResult("MediaPipe face detector", "FAIL", f"MediaPipe error: {e}")


def check_opencv() -> CheckResult:
    try:
        import cv2
        if hasattr(cv2, "TrackerCSRT_create"):
            return CheckResult("OpenCV contrib (CSRT)", "PASS", f"OpenCV {cv2.__version__} with CSRT tracker")
        return CheckResult(
            "OpenCV contrib (CSRT)",
            "FAIL",
            f"OpenCV {cv2.__version__} lacks TrackerCSRT_create",
            "pip uninstall opencv-python && pip install opencv-contrib-python",
        )
    except ImportError:
        return CheckResult("OpenCV contrib (CSRT)", "FAIL", "opencv not installed", "pip install opencv-contrib-python")
    except Exception as e:
        return CheckResult("OpenCV contrib (CSRT)", "FAIL", f"OpenCV error: {e}")


def check_pillow_fonts(assets_dir: Path) -> CheckResult:
    try:
        from PIL import ImageFont
        fonts_dir = assets_dir / "fonts"
        required_fonts = ["Anton-Regular.ttf", "Montserrat-ExtraBold.ttf", "NotoColorEmoji.ttf"]
        missing = []
        for f in required_fonts:
            fpath = fonts_dir / f
            if not fpath.exists() or fpath.stat().st_size < 10 * 1024:
                missing.append(f)
            else:
                try:
                    ImageFont.truetype(str(fpath), size=24)
                except Exception as fe:
                    missing.append(f"{f} (load error: {fe})")

        if missing:
            return CheckResult(
                "Pillow fonts",
                "WARN",
                f"Missing or invalid fonts: {', '.join(missing)}",
                "Run python scripts/download_models.py --fonts",
            )
        return CheckResult("Pillow fonts", "PASS", "Anton, Montserrat, and NotoColorEmoji loaded successfully")
    except Exception as e:
        return CheckResult("Pillow fonts", "WARN", f"Font checking error: {e}")


def check_ollama(env_path: Path) -> CheckResult:
    import json
    import urllib.error
    import urllib.request

    host = "127.0.0.1:11434"
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("OLLAMA_HOST="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        host = val

    if not host.startswith("http://") and not host.startswith("https://"):
        url = f"http://{host}/api/tags"
    else:
        url = f"{host}/api/tags"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shorts-engine"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            models_str = ", ".join(models[:4]) if models else "none"
            if not models:
                return CheckResult(
                    "Ollama local LLM",
                    "WARN",
                    f"Ollama running at {host} but no models installed",
                    "Run 'ollama pull qwen3.5:9b'",
                )
            return CheckResult(
                "Ollama local LLM",
                "PASS",
                f"Ollama active with {len(models)} model(s): {models_str}",
            )
    except Exception as e:
        return CheckResult(
            "Ollama local LLM",
            "FAIL",
            f"Cannot reach Ollama at {host}: {e}",
            "In PowerShell: $env:OLLAMA_MODELS = 'D:\\Open_Source_Weights\\ollama'; ollama serve",
        )


def check_gemini(env_path: Path) -> CheckResult:
    # Load .env
    api_key = ""
    model_text = "gemini-2.5-flash"
    model_image = "gemini-2.5-flash-image"
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("GEMINI_MODEL_TEXT="):
                    model_text = line.split("=", 1)[1].strip().strip('"').strip("'") or model_text
                elif line.startswith("GEMINI_MODEL_IMAGE="):
                    model_image = line.split("=", 1)[1].strip().strip('"').strip("'") or model_image

    if not api_key:
        return CheckResult(
            "Gemini API key",
            "PASS",
            "Not set (local Ollama pipeline active)",
        )

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        # List models
        models = [m.name for m in client.models.list()]
        short_names = [m.split("/")[-1] for m in models]
        has_text = any(model_text in name for name in models + short_names)
        has_image = any(model_image in name for name in models + short_names)

        # Quick test generation
        response = client.models.generate_content(
            model=model_text,
            contents="Say 'OK' in one word.",
        )
        reply = (response.text or "").strip()

        details = f"Key valid; test model '{model_text}' returned '{reply}'"
        if not has_text or not has_image:
            avail_flash = [s for s in short_names if "flash" in s]
            return CheckResult(
                "Gemini API key",
                "WARN",
                f"{details}. Configured text/image model may need updating. Available flash models: {avail_flash[:4]}",
                "Check .env GEMINI_MODEL_TEXT and GEMINI_MODEL_IMAGE",
            )
        return CheckResult("Gemini API key", "PASS", details)
    except Exception as e:
        return CheckResult(
            "Gemini API key",
            "FAIL",
            f"Gemini API call failed: {e}",
            "Verify GEMINI_API_KEY in .env and internet access",
        )


def check_ac_power() -> CheckResult:
    try:
        import psutil
        battery = psutil.sensors_battery()
        if battery is None:
            return CheckResult("Power source", "PASS", "Desktop or battery sensor not available")
        if battery.power_plugged:
            return CheckResult("Power source", "PASS", f"AC connected ({battery.percent}% charged)")
        return CheckResult(
            "Power source",
            "WARN",
            f"Running on battery ({battery.percent}%). NVENC and Whisper may throttle.",
            "Connect AC power adapter",
        )
    except Exception as e:
        return CheckResult("Power source", "WARN", f"Could not determine power status: {e}")


def check_port_free(host: str = "127.0.0.1", port: int = 8000, in_process: bool = False) -> CheckResult:
    if in_process:
        return CheckResult("HTTP Port", "PASS", f"{host}:{port} is active (serving current request)")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        sock.close()
        return CheckResult("HTTP Port", "PASS", f"{host}:{port} is free")
    except Exception as e:
        return CheckResult(
            "HTTP Port",
            "FAIL",
            f"Cannot bind to {host}:{port}: {e}",
            f"Ensure no other process is using port {port} or change PORT in .env",
        )


def run_checks(root_dir: Path | None = None, in_process: bool = False) -> list[CheckResult]:
    if root_dir is None:
        root_dir = Path(__file__).resolve().parent.parent
    assets_dir = root_dir / "assets"
    data_dir = root_dir / "data"
    env_path = root_dir / ".env"

    results: list[CheckResult] = []
    results.append(check_python_version())
    results.append(check_disk_space(data_dir))
    results.extend(check_ffmpeg())
    results.append(check_gpu())
    results.append(check_deno())
    results.append(check_ytdlp())
    results.append(check_whisper_cuda())
    results.append(check_mediapipe(assets_dir))
    results.append(check_opencv())
    results.append(check_pillow_fonts(assets_dir))
    results.append(check_ollama(env_path))
    results.append(check_gemini(env_path))
    results.append(check_ac_power())
    results.append(check_port_free(in_process=in_process))
    return results


def print_table(results: list[CheckResult]) -> None:
    headers = ["CHECK", "STATUS", "DETAIL", "FIX"]
    col_w = [25, 8, 45, 30]

    def fmt_row(row: list[str]) -> str:
        return " | ".join(val[: col_w[i]].ljust(col_w[i]) for i, val in enumerate(row))

    separator = "-+-".join("-" * w for w in col_w)

    print(fmt_row(headers))
    print(separator)
    for r in results:
        status_colored = r.status
        print(fmt_row([r.check, status_colored, r.detail, r.fix]))


def main():
    results = run_checks()
    print_table(results)
    any_fail = any(r.status == "FAIL" for r in results)
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
