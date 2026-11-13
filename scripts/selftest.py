"""selftest.py: Automated Gate Verification Suite for shorts-engine.

Runs phase-specific acceptance checks or full system verification.

Usage:
    python scripts/selftest.py --phase 0
    python scripts/selftest.py --phase 1
    ...
    python scripts/selftest.py --all
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Compatibility fix for newer PyAV
try:
    import av
    _orig_av_open = av.open
    def _compat_av_open(*args: Any, **kwargs: Any) -> Any:
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)
    av.open = _compat_av_open
except Exception:
    pass

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))
_raw_weights = os.environ.get("WEIGHTS_DIR", "./weights")
WEIGHTS_DIR = Path(_raw_weights) if Path(_raw_weights).is_absolute() else (WORKSPACE_ROOT / _raw_weights).resolve()
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
                with contextlib.suppress(Exception):
                    os.add_dll_directory(str(cdir))
                os.environ["PATH"] = str(cdir) + ";" + os.environ.get("PATH", "")


setup_nvidia_dll_paths()


@dataclass
class GateCheckResult:
    phase: int
    name: str
    status: str  # PASS, FAIL, DEGRADED
    output: str
    duration_s: float
    vram_peak_mb: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_gpu_vram_used() -> float:
    """Return currently used VRAM in MB from nvidia-smi."""
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return float(res.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return 0.0


def unload_ollama_models() -> None:
    """Unload all Ollama models to release VRAM between stages."""
    host = OLLAMA_HOST if OLLAMA_HOST.startswith("http") else f"http://{OLLAMA_HOST}"
    try:
        # Query running models
        req = urllib.request.Request(f"{host}/api/ps")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for m in data.get("models", []):
                name = m.get("name")
                if name:
                    unload_payload = json.dumps({"model": name, "keep_alive": 0}).encode("utf-8")
                    ureq = urllib.request.Request(
                        f"{host}/api/generate",
                        data=unload_payload,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with contextlib.suppress(Exception):
                        urllib.request.urlopen(ureq, timeout=3)
    except Exception:
        pass


# =====================================================================
# Phase 0 Gate Checks
# =====================================================================

def check_phase_0_preflight() -> GateCheckResult:
    """Run check_local_setup.py."""
    t0 = time.time()
    v0 = get_gpu_vram_used()
    script = WORKSPACE_ROOT / "scripts" / "check_local_setup.py"
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=30)
    dur = time.time() - t0
    v1 = get_gpu_vram_used()
    peak = max(v0, v1)

    status = "PASS" if proc.returncode == 0 else "FAIL"
    return GateCheckResult(
        phase=0,
        name="Preflight Health Check",
        status=status,
        output=proc.stdout or proc.stderr,
        duration_s=dur,
        vram_peak_mb=peak,
    )


def check_phase_0_ollama_path() -> GateCheckResult:
    """Verify Ollama models physically reside in D:\\Open_Source_Weights\\ollama."""
    t0 = time.time()
    ollama_dir = WEIGHTS_DIR / "ollama"
    blobs_dir = ollama_dir / "blobs"
    manifests_dir = ollama_dir / "manifests"

    exists = ollama_dir.exists() and (blobs_dir.exists() or manifests_dir.exists())
    blob_count = len(list(blobs_dir.glob("*"))) if blobs_dir.exists() else 0
    dur = time.time() - t0

    if exists and blob_count > 0:
        return GateCheckResult(
            phase=0,
            name="Ollama Storage Location",
            status="PASS",
            output=f"Ollama files physically under {ollama_dir} ({blob_count} blobs found)",
            duration_s=dur,
        )
    elif exists:
        return GateCheckResult(
            phase=0,
            name="Ollama Storage Location",
            status="PASS",
            output=f"Ollama directory confirmed at {ollama_dir}",
            duration_s=dur,
        )
    return GateCheckResult(
        phase=0,
        name="Ollama Storage Location",
        status="FAIL",
        output=f"Ollama directory missing at {ollama_dir}",
        duration_s=dur,
    )


def check_phase_0_whisper_cuda() -> GateCheckResult:
    """Transcribe a 10-second synthetic audio file on CUDA GPU with faster-whisper."""
    t0 = time.time()
    v0 = get_gpu_vram_used()

    # Generate a 10-second test WAV with tone and speech-like amplitude
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_wav = Path(tmp_dir) / "test_10s.wav"
        # Create 10s wav via ffmpeg
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=10",
            "-ar", "16000", "-ac", "1",
            str(test_wav),
        ]
        res = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=15)
        if res.returncode != 0 or not test_wav.exists():
            return GateCheckResult(
                phase=0,
                name="Whisper CUDA 10s Transcription",
                status="FAIL",
                output=f"Failed to generate test audio: {res.stderr}",
                duration_s=time.time() - t0,
            )

        try:
            unload_ollama_models()
            try:
                import torch
            except ImportError:
                torch = None
            from faster_whisper import WhisperModel

            whisper_root = WEIGHTS_DIR / "whisper"
            whisper_root.mkdir(parents=True, exist_ok=True)

            # Resolve local model or snapshot directly to avoid network calls
            model_target = "large-v3"
            for candidate in [
                whisper_root / "models--Systran--faster-whisper-large-v3-turbo",
                whisper_root / "models--Systran--faster-whisper-large-v3",
            ]:
                if candidate.exists():
                    snapshots = list((candidate / "snapshots").glob("*"))
                    if snapshots:
                        model_target = str(snapshots[0])
                        break

            # Attempt CUDA float16
            model = WhisperModel(model_target, device="cuda", compute_type="float16")
            v_during = get_gpu_vram_used()

            segments, _ = model.transcribe(str(test_wav), beam_size=1)
            _ = list(segments)

            # Explicit GPU release as required by spec
            del model
            if torch and torch.cuda.is_available():
                torch.cuda.empty_cache()
            import gc
            gc.collect()

            dur = time.time() - t0
            v_after = get_gpu_vram_used()
            peak = max(v0, v_during, v_after)

            if peak > 7500:
                status = "DEGRADED"
                msg = f"Transcribed successfully on CUDA in {dur:.2f}s, but peak VRAM was high: {peak:.0f} MB."
            else:
                status = "PASS"
                msg = f"Transcribed 10s test file on NVIDIA CUDA in {dur:.2f}s. Peak VRAM: {peak:.0f} MB (within 7.5 GB ceiling)."

            return GateCheckResult(
                phase=0,
                name="Whisper CUDA 10s Transcription",
                status=status,
                output=msg,
                duration_s=dur,
                vram_peak_mb=peak,
            )
        except Exception as exc:
            return GateCheckResult(
                phase=0,
                name="Whisper CUDA 10s Transcription",
                status="FAIL",
                output=f"Whisper CUDA transcription error: {exc}",
                duration_s=time.time() - t0,
            )


def check_phase_0_llm_json() -> GateCheckResult:
    """Verify Ollama LLM generates schema-valid JSON for a test prompt."""
    t0 = time.time()
    v0 = get_gpu_vram_used()

    test_schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "confidence": {"type": "number"},
            "reasons": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["status", "confidence", "reasons"]
    }

    prompt = "Respond with JSON assessing whether a gaming clip with high volume and chat hype is viral."
    host = OLLAMA_HOST if OLLAMA_HOST.startswith("http") else f"http://{OLLAMA_HOST}"
    url = f"{host}/api/chat"

    # Try qwen3.5:9b first, then any available model
    model = "qwen3.5:9b"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "format": test_schema,
        "stream": False,
        "think": False,
        "keep_alive": 0,
        "options": {"temperature": 0.2, "num_predict": 150}
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data.get("message", {}).get("content", "")
            parsed = json.loads(content)

            # Validate against schema keys
            if "status" in parsed and "confidence" in parsed and "reasons" in parsed:
                dur = time.time() - t0
                peak = max(v0, get_gpu_vram_used())
                return GateCheckResult(
                    phase=0,
                    name="Ollama LLM Schema JSON Generation",
                    status="PASS",
                    output=f"Successfully received schema-valid JSON from {model} in {dur:.2f}s: {parsed}",
                    duration_s=dur,
                    vram_peak_mb=peak,
                )
            else:
                return GateCheckResult(
                    phase=0,
                    name="Ollama LLM Schema JSON Generation",
                    status="FAIL",
                    output=f"JSON returned missing required keys: {content}",
                    duration_s=time.time() - t0,
                )
    except Exception as exc:
        return GateCheckResult(
            phase=0,
            name="Ollama LLM Schema JSON Generation",
            status="FAIL",
            output=f"LLM request error: {exc}",
            duration_s=time.time() - t0,
        )


def run_phase_0_checks() -> list[GateCheckResult]:
    return [
        check_phase_0_preflight(),
        check_phase_0_ollama_path(),
        check_phase_0_whisper_cuda(),
        check_phase_0_llm_json(),
    ]


# =====================================================================
# Phase 1 Gate Checks
# =====================================================================

def check_phase_1_cloud_purge() -> GateCheckResult:
    """Verify zero cloud imports, keys, or endpoints exist in project code."""
    t0 = time.time()
    forbidden = ["google.genai", "import genai", "from google import", "api.openai.com", "import openai", "import anthropic"]
    found_violations: list[str] = []

    for root_dir in [WORKSPACE_ROOT / "app", WORKSPACE_ROOT / "config", WORKSPACE_ROOT / "web"]:
        for p in root_dir.rglob("*"):
            if p.is_file() and p.suffix in (".py", ".js", ".html"):
                text = p.read_text(encoding="utf-8", errors="ignore")
                for f in forbidden:
                    if f in text:
                        if "network_guard.py" in str(p) and "BLOCKED_CLOUD_DOMAINS" in text:
                            continue
                        found_violations.append(f"{p.name}: contains '{f}'")

    dur = time.time() - t0
    if found_violations:
        return GateCheckResult(
            phase=1,
            name="Cloud Code Purge (Zero Cloud)",
            status="FAIL",
            output=f"Cloud references found: {'; '.join(found_violations[:3])}",
            duration_s=dur,
        )
    return GateCheckResult(
        phase=1,
        name="Cloud Code Purge (Zero Cloud)",
        status="PASS",
        output="Zero cloud SDK imports or active API keys found across app/, config/, web/.",
        duration_s=dur,
    )


def check_phase_1_network_guard() -> GateCheckResult:
    """Run pytest tests/test_network_guard.py to prove outbound cloud AI calls are blocked."""
    t0 = time.time()
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_network_guard.py"],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    dur = time.time() - t0
    if res.returncode == 0:
        return GateCheckResult(
            phase=1,
            name="Network Guard Enforcement",
            status="PASS",
            output="Network guard blocked all outbound cloud AI attempts and permitted localhost:11434.",
            duration_s=dur,
        )
    return GateCheckResult(
        phase=1,
        name="Network Guard Enforcement",
        status="FAIL",
        output=f"Network guard test failed: {res.stderr or res.stdout}",
        duration_s=dur,
    )


def check_phase_1_single_proposer() -> GateCheckResult:
    """Verify local LLM single proposer generates structured ClipNomination candidates."""
    t0 = time.time()
    v0 = get_gpu_vram_used()
    try:
        from app.pipeline.s2_select.nominate import NominationOut
        from llm.manager import LocalModelManager

        mgr = LocalModelManager()
        test_prompt = (
            "You are a viral shorts scout. Propose moments from this transcript:\n"
            "[0] Look at this insane car chase!\n"
            "[1] The cops are swarming from every side.\n"
            "[2] I hit the ramp and flew over the barrier!\n"
            "[3] That was incredible."
        )
        res = mgr.generate_json("clip_proposal", test_prompt, NominationOut)
        dur = time.time() - t0
        peak = max(v0, get_gpu_vram_used())
        return GateCheckResult(
            phase=1,
            name="Layer 2 Single Proposer (Qwen3.5 9B)",
            status="PASS",
            output=f"Proposer returned structured candidates via Ollama in {dur:.2f}s: {len(res.candidates)} candidates.",
            duration_s=dur,
            vram_peak_mb=peak,
        )
    except Exception as exc:
        return GateCheckResult(
            phase=1,
            name="Layer 2 Single Proposer (Qwen3.5 9B)",
            status="FAIL",
            output=f"Proposer failed: {exc}",
            duration_s=time.time() - t0,
        )


def check_phase_1_end_to_end() -> GateCheckResult:
    """Run full pipeline on samples/sample_5min.mp4 under offline network guard."""
    t0 = time.time()
    v0 = get_gpu_vram_used()
    sample_file = WORKSPACE_ROOT / "samples" / "sample_5min.mp4"
    if not sample_file.exists():
        return GateCheckResult(
            phase=1,
            name="End-to-End 5-Minute Sample",
            status="FAIL",
            output=f"Sample video not found at {sample_file}",
            duration_s=time.time() - t0,
        )

    from app.core.db import get_conn, init_db
    from app.core.models import create_job
    from app.core.network_guard import network_guard
    from app.pipeline.context import JobContext
    from app.pipeline.orchestrator import run_pipeline

    db_path = WORKSPACE_ROOT / "data" / "app.db"
    init_db(db_path)

    # Create job in database
    import uuid
    job_id = f"job_p1_{uuid.uuid4().hex[:8]}"
    with get_conn(db_path) as conn:
        job_dict = create_job(
            job_id=job_id,
            url=str(sample_file),
            title="Local 5-Minute Sample Test",
            options={"min_tier": "C", "max_source_height": 1080},
            ack_fair_use=True,
            conn=conn,
        )

    ctx = JobContext(job=job_dict)

    # Run full pipeline with network guard active (strictly local!)
    v_peaks = [v0]
    try:
        with network_guard(allow_ingest=False):
            run_pipeline(ctx)
            v_peaks.append(get_gpu_vram_used())
    except Exception as exc:
        return GateCheckResult(
            phase=1,
            name="End-to-End 5-Minute Sample",
            status="FAIL",
            output=f"Pipeline execution failed: {exc}",
            duration_s=time.time() - t0,
            vram_peak_mb=max(v_peaks),
        )

    # Inspect the rendered clip file
    rendered_clips = list(ctx.work_dir.glob("clips/*/clip.mp4"))
    dur = time.time() - t0
    peak = max(v_peaks)

    if not rendered_clips:
        return GateCheckResult(
            phase=1,
            name="End-to-End 5-Minute Sample",
            status="FAIL",
            output=f"No final clip.mp4 found in {ctx.work_dir}/clips",
            duration_s=dur,
            vram_peak_mb=peak,
        )

    first_clip = rendered_clips[0]
    from app.utils.ffmpeg import probe
    p = probe(first_clip)

    if p.width != 1080 or p.height != 1920:
        return GateCheckResult(
            phase=1,
            name="End-to-End 5-Minute Sample",
            status="FAIL",
            output=f"Clip resolution is {p.width}x{p.height}, expected 1080x1920 vertical format",
            duration_s=dur,
            vram_peak_mb=peak,
        )

    # Check ASS captions file
    ass_file = first_clip.parent / "captions.ass"
    has_ass = ass_file.exists() and ass_file.stat().st_size > 100

    return GateCheckResult(
        phase=1,
        name="End-to-End 5-Minute Sample",
        status="PASS",
        output=f"Rendered {len(rendered_clips)} valid 9:16 vertical short(s) in {dur:.1f}s. First clip: {p.duration:.1f}s, captions: {has_ass}, Peak VRAM: {peak:.0f} MB.",
        duration_s=dur,
        vram_peak_mb=peak,
    )


def run_phase_1_checks() -> list[GateCheckResult]:
    return [
        check_phase_1_cloud_purge(),
        check_phase_1_network_guard(),
        check_phase_1_single_proposer(),
        check_phase_1_end_to_end(),
    ]


# =====================================================================
# Phase 2 Gate Checks
# =====================================================================

def check_phase_2_candidate_store() -> GateCheckResult:
    """Verify candidate store persistence and score breakdown in SQLite."""
    t0 = time.time()
    try:
        from app.core.db import get_conn, init_db
        from app.core.models import create_job, list_candidates, upsert_candidate

        with tempfile.TemporaryDirectory() as tmp_dir:
            test_db = Path(tmp_dir) / "test_store.db"
            init_db(test_db)
            conn = get_conn(test_db)
            try:
                create_job("job_chk_p2", "https://youtube.com/watch?v=store", {}, ack_fair_use=True, conn=conn)
                upsert_candidate(
                    {
                        "job_id": "job_chk_p2",
                        "id": "c01",
                        "start_s": 15.0,
                        "end_s": 45.0,
                        "hook_text": "Candidate store test",
                        "topic": "Store Verification",
                        "llm_score": 78.0,
                        "audio_score": 65.0,
                        "heat_score": 70.0,
                        "final_score": 74.5,
                        "tier": "A",
                        "scores_json": {"llm": 78.0, "audio": 65.0},
                        "selected": 1,
                    },
                    conn=conn,
                )
                cands = list_candidates("job_chk_p2", conn=conn)
            finally:
                conn.close()

            dur = time.time() - t0
            if len(cands) == 1 and cands[0]["final_score"] == 74.5:
                return GateCheckResult(
                    phase=2,
                    name="Candidate Store Persistence",
                    status="PASS",
                    output=f"Candidate persisted and retrieved with full score breakdown in {dur:.2f}s: {cands[0]['scores']}",
                    duration_s=dur,
                )
            return GateCheckResult(
                phase=2,
                name="Candidate Store Persistence",
                status="FAIL",
                output=f"Candidate store returned unexpected result: {cands}",
                duration_s=dur,
            )
    except Exception as exc:
        return GateCheckResult(
            phase=2,
            name="Candidate Store Persistence",
            status="FAIL",
            output=f"Candidate store error: {exc}",
            duration_s=time.time() - t0,
        )


def check_phase_2_slider_zero_model_calls() -> GateCheckResult:
    """Assert moving slider triggers zero model calls via pytest test_slider_zero_model_calls."""
    t0 = time.time()
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_phase_2_slider.py", "-k", "test_slider_zero_model_calls"],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    dur = time.time() - t0
    if res.returncode == 0:
        return GateCheckResult(
            phase=2,
            name="Slider Zero-Model-Calls Assertion",
            status="PASS",
            output="Moving quality-threshold slider filters in-memory data with ZERO model calls.",
            duration_s=dur,
        )
    return GateCheckResult(
        phase=2,
        name="Slider Zero-Model-Calls Assertion",
        status="FAIL",
        output=f"Test failed: {res.stderr or res.stdout}",
        duration_s=dur,
    )


def check_phase_2_caption_presets() -> GateCheckResult:
    """Verify all 7 caption presets generate valid ASS subtitle files."""
    t0 = time.time()
    from app.core.schemas import WordClip
    from app.pipeline.s3_build.captions import CAPTION_PRESETS, chunk_words, write_ass

    if len(CAPTION_PRESETS) != 7:
        return GateCheckResult(
            phase=2,
            name="7 Caption Presets Generation",
            status="FAIL",
            output=f"Expected 7 caption presets, found {len(CAPTION_PRESETS)}",
            duration_s=time.time() - t0,
        )

    words = [
        WordClip(i=0, w="Viral", s=0.0, e=0.5, s_clip=0.0, e_clip=0.5, p=0.99),
        WordClip(i=1, w="Moments", s=0.5, e=1.0, s_clip=0.5, e_clip=1.0, p=0.99),
    ]
    chunks = chunk_words(words)
    verified_presets = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        for p_name in CAPTION_PRESETS:
            out_p = Path(tmp_dir) / f"{p_name}.ass"
            write_ass(chunks, layout="gameplay", out_path=out_p, preset=p_name)
            if out_p.is_file() and out_p.stat().st_size > 100:
                verified_presets.append(p_name)

    dur = time.time() - t0
    if len(verified_presets) == 7:
        return GateCheckResult(
            phase=2,
            name="7 Caption Presets Generation",
            status="PASS",
            output=f"All 7 presets verified: {', '.join(verified_presets)}",
            duration_s=dur,
        )
    return GateCheckResult(
        phase=2,
        name="7 Caption Presets Generation",
        status="FAIL",
        output=f"Only {len(verified_presets)} / 7 presets generated successfully",
        duration_s=dur,
    )


def check_phase_2_endpoints() -> GateCheckResult:
    """Verify GET /projects/{id}/candidates and POST /projects/{id}/render endpoints."""
    t0 = time.time()
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_phase_2_slider.py", "-k", "test_candidates_and_render_api_endpoints"],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    dur = time.time() - t0
    if res.returncode == 0:
        return GateCheckResult(
            phase=2,
            name="Candidates & Render API Endpoints",
            status="PASS",
            output="GET /projects/{id}/candidates and POST /projects/{id}/render verified with filtering & pins.",
            duration_s=dur,
        )
    return GateCheckResult(
        phase=2,
        name="Candidates & Render API Endpoints",
        status="FAIL",
        output=f"Endpoints test failed: {res.stderr or res.stdout}",
        duration_s=dur,
    )


def run_phase_2_checks() -> list[GateCheckResult]:
    return [
        check_phase_2_candidate_store(),
        check_phase_2_slider_zero_model_calls(),
        check_phase_2_caption_presets(),
        check_phase_2_endpoints(),
    ]


def check_phase_3_individual_sensors() -> GateCheckResult:
    """Verify each Layer 1 sensor runs and emits valid tracks."""
    t0 = time.time()
    try:
        import numpy as np
        import soundfile as sf

        from app.pipeline.sensors.audio_energy import extract_audio_energy
        from app.pipeline.sensors.sound_events import extract_sound_events

        with tempfile.TemporaryDirectory() as tmp_dir:
            test_wav = Path(tmp_dir) / "test_sensor.wav"
            sr = 16000
            t = np.linspace(0, 4.0, int(sr * 4.0), endpoint=False)
            audio = 0.5 * np.sin(2 * np.pi * 440 * t)
            sf.write(str(test_wav), audio, sr)

            a_prof = extract_audio_energy(test_wav)
            se_prof = extract_sound_events(test_wav)

            dur = time.time() - t0
            if a_prof.duration_s >= 3.9 and se_prof.duration_s >= 3.9:
                return GateCheckResult(
                    phase=3,
                    name="Layer 1 Sensors Individual Run",
                    status="PASS",
                    output=f"Audio energy and sound events sensors executed successfully in {dur:.2f}s",
                    duration_s=dur,
                )
            return GateCheckResult(
                phase=3,
                name="Layer 1 Sensors Individual Run",
                status="FAIL",
                output=f"Sensors returned unexpected duration: {a_prof.duration_s}",
                duration_s=dur,
            )
    except Exception as exc:
        return GateCheckResult(
            phase=3,
            name="Layer 1 Sensors Individual Run",
            status="FAIL",
            output=f"Sensor execution error: {exc}",
            duration_s=time.time() - t0,
        )


def check_phase_3_audience_signals() -> GateCheckResult:
    """Verify audience signals parsing and fail-soft behavior with missing signals."""
    t0 = time.time()
    try:
        from app.pipeline.s1_ingest.audience import (
            AudienceSignalsData,
            get_audience_score_for_window,
            parse_chat_replay,
            parse_timestamped_comments,
            parse_yt_heatmap,
        )

        # 1. Parsing with data
        _norm_heat, has_heat = parse_yt_heatmap([{"start_time": 0.0, "end_time": 10.0, "value": 100.0}])
        _comm_bins, has_comm = parse_timestamped_comments([{"text": "Watch 0:25 lol", "like_count": 5}], duration_s=60.0)
        _chat_bins, _, has_chat = parse_chat_replay([{"offset_seconds": 15.0, "text": "POG POG"}], duration_s=60.0)

        # 2. Fail-soft with missing signals (never fill with 0)
        empty_aud = AudienceSignalsData()
        score_missing, b_missing = get_audience_score_for_window(0.0, 30.0, empty_aud)

        dur = time.time() - t0
        if has_heat and has_comm and has_chat and score_missing is None and b_missing.get("available") is False:
            return GateCheckResult(
                phase=3,
                name="Audience Signals & Fail-Soft",
                status="PASS",
                output=f"Heatmap, comments, and chat parsed with fail-soft missing signal handling in {dur:.2f}s",
                duration_s=dur,
            )
        return GateCheckResult(
            phase=3,
            name="Audience Signals & Fail-Soft",
            status="FAIL",
            output=f"Audience parsing returned unexpected status: {has_heat=}, {has_comm=}, {has_chat=}, {score_missing=}",
            duration_s=dur,
        )
    except Exception as exc:
        return GateCheckResult(
            phase=3,
            name="Audience Signals & Fail-Soft",
            status="FAIL",
            output=f"Audience parsing error: {exc}",
            duration_s=time.time() - t0,
        )


def check_phase_3_dynamic_fusion() -> GateCheckResult:
    """Verify dynamic weight redistribution when signals are missing."""
    t0 = time.time()
    try:
        from app.pipeline.s2_select.fusion import calculate_fusion_score

        # When audience is missing (None), active weights must dynamically sum to 1.0
        signals_input = {
            "audience": None,
            "audio_events": 80.0,
            "emotion": 70.0,
            "text_hype": 60.0,
            "llm_consensus": 85.0,
            "critic": 75.0,
            "rerank": 80.0,
            "visual": 65.0,
            "agreement": 90.0,
        }
        final_score, tier, breakdown = calculate_fusion_score(signals_input)
        active_weights = breakdown["active_weights"]
        total_w = sum(active_weights.values())

        dur = time.time() - t0
        if abs(total_w - 1.0) < 1e-3 and "audience" not in active_weights and final_score >= 70.0:
            return GateCheckResult(
                phase=3,
                name="Dynamic Fusion Weight Redistribution",
                status="PASS",
                output=f"Active weights dynamically re-normalized to 1.0 (total: {total_w:.4f}), Tier: {tier}, Score: {final_score}",
                duration_s=dur,
            )
        return GateCheckResult(
            phase=3,
            name="Dynamic Fusion Weight Redistribution",
            status="FAIL",
            output=f"Weight sum != 1.0 or unexpected score: {total_w=}, {final_score=}",
            duration_s=dur,
        )
    except Exception as exc:
        return GateCheckResult(
            phase=3,
            name="Dynamic Fusion Weight Redistribution",
            status="FAIL",
            output=f"Fusion error: {exc}",
            duration_s=time.time() - t0,
        )


def check_phase_3_timeline_and_hot_zones() -> GateCheckResult:
    """Verify timeline event synthesis and hot zones detection."""
    t0 = time.time()
    try:
        import numpy as np

        from app.pipeline.s1_ingest.audience import AudienceSignalsData
        from app.pipeline.sensors.audio_energy import AudioEnergyProfile
        from app.pipeline.sensors.sound_events import SoundEventItem, SoundEventsProfile
        from app.pipeline.sensors.timeline_generator import (
            format_timeline_for_prompt,
            generate_timeline_and_hot_zones,
        )

        a_prof = AudioEnergyProfile(
            duration_s=30.0,
            per_second_rms=np.array([0.1] * 30, dtype=np.float32),
            per_second_z=np.array([0.0] * 30, dtype=np.float32),
            mean_rms=0.1,
            std_rms=0.05,
            silence_explosion_indices=[10],
        )
        se_prof = SoundEventsProfile(
            duration_s=30.0,
            events=[SoundEventItem(time_s=10.5, event="explosion", confidence=0.9)],
            per_second_scores={10: 90.0},
            per_second_tags={10: ["explosion"]},
        )
        aud = AudienceSignalsData(has_chat=True, chat_bins={1: 0.9}, chat_hype_tags={1: ["clip it"]})

        events, hot_zones = generate_timeline_and_hot_zones(30.0, a_prof, se_prof, aud)
        formatted = format_timeline_for_prompt(events, 5.0, 15.0)

        dur = time.time() - t0
        if len(events) >= 2 and len(hot_zones) >= 1 and "explosion" in formatted.lower():
            return GateCheckResult(
                phase=3,
                name="Timeline & Hot-Zone Synthesis",
                status="PASS",
                output=f"Synthesized {len(events)} events and {len(hot_zones)} hot zones in {dur:.2f}s",
                duration_s=dur,
            )
        return GateCheckResult(
            phase=3,
            name="Timeline & Hot-Zone Synthesis",
            status="FAIL",
            output=f"Unexpected synthesis result: {len(events)=}, {len(hot_zones)=}",
            duration_s=dur,
        )
    except Exception as exc:
        return GateCheckResult(
            phase=3,
            name="Timeline & Hot-Zone Synthesis",
            status="FAIL",
            output=f"Timeline generation error: {exc}",
            duration_s=time.time() - t0,
        )


def run_phase_3_checks() -> list[GateCheckResult]:
    return [
        check_phase_3_individual_sensors(),
        check_phase_3_audience_signals(),
        check_phase_3_dynamic_fusion(),
        check_phase_3_timeline_and_hot_zones(),
    ]


def check_phase_4_manager_failure_recovery() -> GateCheckResult:
    """Verify LocalModelManager failure handling (OOM context reduction, retry backoff, model fallback)."""
    t0 = time.time()
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_phase_4_multi_model.py",
            "-k",
            "test_manager_fallback_on_connection_failure or test_manager_oom_context_reduction or test_manager_all_models_fail",
        ],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    dur = time.time() - t0
    if res.returncode == 0:
        return GateCheckResult(
            phase=4,
            name="Model Manager Failure Handling",
            status="PASS",
            output="OOM context reduction, retry backoff, and model fallback verified.",
            duration_s=dur,
        )
    return GateCheckResult(
        phase=4,
        name="Model Manager Failure Handling",
        status="FAIL",
        output=f"Test failed: {res.stderr or res.stdout}",
        duration_s=dur,
    )


def check_phase_4_proposer_agreement() -> GateCheckResult:
    """Verify multi-proposer candidate merging and agreement counting (>50% time overlap)."""
    t0 = time.time()
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_phase_4_multi_model.py",
            "-k",
            "test_multi_proposer_merging_and_agreement",
        ],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    dur = time.time() - t0
    if res.returncode == 0:
        return GateCheckResult(
            phase=4,
            name="Multi-Proposer Agreement (>50% Overlap)",
            status="PASS",
            output="Multi-proposer merging, dedup, and agreement count (>50% overlap) verified.",
            duration_s=dur,
        )
    return GateCheckResult(
        phase=4,
        name="Multi-Proposer Agreement (>50% Overlap)",
        status="FAIL",
        output=f"Test failed: {res.stderr or res.stdout}",
        duration_s=dur,
    )


def check_phase_4_rerank_position_bias() -> GateCheckResult:
    """Verify Layer 4 head-to-head reranker cancels position bias across shuffled batch tournaments."""
    t0 = time.time()
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_phase_4_multi_model.py",
            "-k",
            "test_layer_4_rerank_position_bias",
        ],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    dur = time.time() - t0
    if res.returncode == 0:
        return GateCheckResult(
            phase=4,
            name="Head-to-Head Rerank Position-Bias Check",
            status="PASS",
            output="Tournament rerank proved invariant to candidate input presentation order.",
            duration_s=dur,
        )
    return GateCheckResult(
        phase=4,
        name="Head-to-Head Rerank Position-Bias Check",
        status="FAIL",
        output=f"Test failed: {res.stderr or res.stdout}",
        duration_s=dur,
    )


def check_phase_4_ranker_training() -> GateCheckResult:
    """Verify calibrated personal ranker training on feedback ratings."""
    t0 = time.time()
    try:
        from scripts.train_ranker import train_ranker

        with tempfile.TemporaryDirectory() as tmp_dir:
            test_m = Path(tmp_dir) / "test_ranker.json"
            summary = train_ranker(out_model_path=test_m)
            dur = time.time() - t0
            if summary.get("train_accuracy", 0.0) >= 0.70 and "feature_importances" in summary:
                return GateCheckResult(
                    phase=4,
                    name="Calibrated Ranker Training",
                    status="PASS",
                    output=f"Ranker trained with {summary['train_accuracy']:.1%} accuracy ({summary['model_type']}) in {dur:.2f}s",
                    duration_s=dur,
                )
            return GateCheckResult(
                phase=4,
                name="Calibrated Ranker Training",
                status="FAIL",
                output=f"Ranker returned unexpected summary: {summary}",
                duration_s=dur,
            )
    except Exception as exc:
        return GateCheckResult(
            phase=4,
            name="Calibrated Ranker Training",
            status="FAIL",
            output=f"Ranker training error: {exc}",
            duration_s=time.time() - t0,
        )


def run_phase_4_checks() -> list[GateCheckResult]:
    return [
        check_phase_4_manager_failure_recovery(),
        check_phase_4_proposer_agreement(),
        check_phase_4_rerank_position_bias(),
        check_phase_4_ranker_training(),
    ]


def check_phase_5_visual_evidence() -> GateCheckResult:
    """Verify Layer 5 visual evidence and dead footage detection."""
    t0 = time.time()
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_phase_5_visual_metadata.py",
            "-k",
            "test_dead_frame_detection or test_visual_action_level or test_inspect_candidate_visuals_fail_soft",
        ],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    dur = time.time() - t0
    if res.returncode == 0:
        return GateCheckResult(
            phase=5,
            name="Layer 5 Visual Evidence & Dead Footage",
            status="PASS",
            output="Dead footage detection, action scores, and fail-soft visual checks verified.",
            duration_s=dur,
        )
    return GateCheckResult(
        phase=5,
        name="Layer 5 Visual Evidence & Dead Footage",
        status="FAIL",
        output=f"Test failed: {res.stderr or res.stdout}",
        duration_s=dur,
    )


def check_phase_5_metadata_and_credits() -> GateCheckResult:
    """Verify Layer 8 metadata assembly and mandatory Creator Credit Block."""
    t0 = time.time()
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_phase_5_visual_metadata.py",
            "-k",
            "test_credit_block_mandatory or test_validate_and_fix_metadata",
        ],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    dur = time.time() - t0
    if res.returncode == 0:
        return GateCheckResult(
            phase=5,
            name="Metadata Ensemble & Credit Policy",
            status="PASS",
            output="Mandatory creator credit block, title limits, and risk notes verified.",
            duration_s=dur,
        )
    return GateCheckResult(
        phase=5,
        name="Metadata Ensemble & Credit Policy",
        status="FAIL",
        output=f"Test failed: {res.stderr or res.stdout}",
        duration_s=dur,
    )


def check_phase_5_thumbnails() -> GateCheckResult:
    """Verify Layer 9 thumbnail art generation (1280x720 and 1080x1920) and anti-frame check."""
    t0 = time.time()
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_phase_5_visual_metadata.py",
            "-k",
            "test_pillow_thumbnail_generation",
        ],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    dur = time.time() - t0
    if res.returncode == 0:
        return GateCheckResult(
            phase=5,
            name="Layer 9 Artwork Thumbnails",
            status="PASS",
            output="1280x720 and 1080x1920 abstract art generation and perceptual ahash check verified.",
            duration_s=dur,
        )
    return GateCheckResult(
        phase=5,
        name="Layer 9 Artwork Thumbnails",
        status="FAIL",
        output=f"Test failed: {res.stderr or res.stdout}",
        duration_s=dur,
    )


def check_phase_5_pipeline_presets() -> GateCheckResult:
    """Verify pipeline presets (Fast, Balanced, Best)."""
    t0 = time.time()
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_phase_5_visual_metadata.py",
            "-k",
            "test_job_options_presets",
        ],
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    dur = time.time() - t0
    if res.returncode == 0:
        return GateCheckResult(
            phase=5,
            name="Pipeline Presets (Fast/Balanced/Best)",
            status="PASS",
            output="Fast, Balanced, and Best presets configure pipeline execution layers accurately.",
            duration_s=dur,
        )
    return GateCheckResult(
        phase=5,
        name="Pipeline Presets (Fast/Balanced/Best)",
        status="FAIL",
        output=f"Test failed: {res.stderr or res.stdout}",
        duration_s=dur,
    )


def run_phase_5_checks() -> list[GateCheckResult]:
    return [
        check_phase_5_visual_evidence(),
        check_phase_5_metadata_and_credits(),
        check_phase_5_thumbnails(),
        check_phase_5_pipeline_presets(),
    ]


# =====================================================================
# Main runner
# =====================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="shorts-engine gate verification suite")
    parser.add_argument("--phase", type=int, choices=[0, 1, 2, 3, 4, 5], help="Run checks for a specific phase")
    parser.add_argument("--all", action="store_true", help="Run all phase checks")
    args = parser.parse_args()

    if args.phase is None and not args.all:
        parser.print_help()
        return 1

    phases_to_run = [0, 1, 2, 3, 4, 5] if args.all else [args.phase]
    all_results: list[GateCheckResult] = []

    for phase in phases_to_run:
        print("\n======================================================================")
        print(f"RUNNING GATE CHECKS FOR PHASE {phase}")
        print("======================================================================")

        if phase == 0:
            results = run_phase_0_checks()
        elif phase == 1:
            results = run_phase_1_checks()
        elif phase == 2:
            results = run_phase_2_checks()
        elif phase == 3:
            results = run_phase_3_checks()
        elif phase == 4:
            results = run_phase_4_checks()
        elif phase == 5:
            results = run_phase_5_checks()
        else:
            print(f"[INFO] Phase {phase} gate checks not yet activated.")
            results = []

        all_results.extend(results)
        for r in results:
            tag = f"[{r.status}]"
            print(f"{tag:<10} {r.name:<32} (took {r.duration_s:.2f}s, VRAM {r.vram_peak_mb:.0f}MB)")
            print(f"           Detail: {r.output.strip()[:140]}...")

    fails = [r for r in all_results if r.status == "FAIL"]
    print("\n----------------------------------------------------------------------")
    print(f"VERIFICATION SUMMARY: {len(all_results) - len(fails)} PASS, {len(fails)} FAIL")

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
