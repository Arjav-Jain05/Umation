"""Reusable stage timer tracking wall-clock time and peak GPU VRAM."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from types import TracebackType

logger = logging.getLogger("app.utils.timer")


def get_vram_mb() -> float:
    """Return currently used GPU VRAM in MB via nvidia-smi."""
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        startupinfo = None
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=flags,
            startupinfo=startupinfo,
        )
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip().split("\n")[0].strip())
    except Exception:
        pass
    return 0.0


@dataclass
class StageTimingResult:
    name: str
    duration_s: float
    start_vram_mb: float
    end_vram_mb: float
    peak_vram_mb: float
    substeps: list[dict[str, float | str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, float | str | list]:
        return {
            "name": self.name,
            "duration_s": round(self.duration_s, 3),
            "start_vram_mb": round(self.start_vram_mb, 1),
            "end_vram_mb": round(self.end_vram_mb, 1),
            "peak_vram_mb": round(self.peak_vram_mb, 1),
            "substeps": self.substeps,
        }

    def summary(self) -> str:
        return (
            f"Stage '{self.name}': {self.duration_s:.2f}s | "
            f"VRAM: start={self.start_vram_mb:.0f}MB, peak={self.peak_vram_mb:.0f}MB, end={self.end_vram_mb:.0f}MB"
        )


class StageTimer:
    """Context manager and tracker for profiling stage wall-clock and VRAM usage."""

    def __init__(self, name: str, sample_interval_s: float = 0.5) -> None:
        self.name = name
        self.sample_interval_s = sample_interval_s
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.start_vram: float = 0.0
        self.end_vram: float = 0.0
        self.peak_vram: float = 0.0
        self.substeps: list[dict[str, float | str]] = []
        self._stop_sampler = threading.Event()
        self._sampler_thread: threading.Thread | None = None
        self._vram_samples: list[float] = []

    def _sample_loop(self) -> None:
        while not self._stop_sampler.is_set():
            v = get_vram_mb()
            if v > 0:
                self._vram_samples.append(v)
            self._stop_sampler.wait(self.sample_interval_s)

    def start(self) -> StageTimer:
        self.start_time = time.perf_counter()
        self.start_vram = get_vram_mb()
        self._vram_samples = [self.start_vram] if self.start_vram > 0 else []
        self._stop_sampler.clear()
        self._sampler_thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._sampler_thread.start()
        return self

    def checkpoint(self, label: str) -> float:
        now = time.perf_counter()
        v = get_vram_mb()
        elapsed = now - self.start_time
        self.substeps.append({
            "label": label,
            "elapsed_s": round(elapsed, 3),
            "vram_mb": round(v, 1),
        })
        if v > self.peak_vram:
            self.peak_vram = v
        return elapsed

    def stop(self) -> StageTimingResult:
        self.end_time = time.perf_counter()
        self._stop_sampler.set()
        if self._sampler_thread and self._sampler_thread.is_alive():
            self._sampler_thread.join(timeout=1.0)

        self.end_vram = get_vram_mb()
        if self.end_vram > 0:
            self._vram_samples.append(self.end_vram)

        all_samples = self._vram_samples or [self.start_vram, self.end_vram]
        self.peak_vram = max(all_samples) if all_samples else max(self.start_vram, self.end_vram)
        dur = self.end_time - self.start_time

        result = StageTimingResult(
            name=self.name,
            duration_s=dur,
            start_vram_mb=self.start_vram,
            end_vram_mb=self.end_vram,
            peak_vram_mb=self.peak_vram,
            substeps=self.substeps,
        )
        logger.info(result.summary())
        return result

    def __enter__(self) -> StageTimer:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop()
