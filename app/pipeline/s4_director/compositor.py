"""Frame-by-frame video compositor streaming through FFmpeg stdin/stdout raw pipes."""

from __future__ import annotations

import contextlib
import logging
import subprocess
import threading
from pathlib import Path

import numpy as np

from app.pipeline.s4_director.edit_schema import EditList
from app.pipeline.s4_director.effects.base import REGISTRY
from app.utils.ffmpeg import has_encoder

logger = logging.getLogger("app.pipeline.s4_director.compositor")

LAYER_PRIORITY = {
    "zoom_punch": 1,
    "highlight_box": 2,
    "arrow": 3,
    "emoji_pop": 4,
    "hook_card": 5,
    "recap_line": 6,
    "part_label": 7,
    "progress_bar": 8,
}


class FrameReader:
    """Streams decoded raw BGR24 frames from a video file via FFmpeg stdout pipe."""

    def __init__(self, video_path: Path, width: int = 1080, height: int = 1920) -> None:
        self.video_path = video_path
        self.width = width
        self.height = height
        self.frame_bytes = width * height * 3
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> FrameReader:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-i", str(self.video_path),
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-an",
            "-",
        ]
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        startupinfo = None
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=flags,
            startupinfo=startupinfo,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.proc:
            if self.proc.stdout:
                self.proc.stdout.close()
            if self.proc.stderr:
                self.proc.stderr.close()
            self.proc.kill()
            self.proc.wait()

    def read_frame(self) -> np.ndarray | None:
        if not self.proc or not self.proc.stdout:
            return None
        raw = self.proc.stdout.read(self.frame_bytes)
        if len(raw) < self.frame_bytes:
            return None
        return np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3)).copy()


class FrameWriter:
    """Streams processed BGR24 frames into an NVENC/libx264 FFmpeg subprocess."""

    def __init__(
        self,
        out_path: Path,
        fps: float = 30.0,
        width: int = 1080,
        height: int = 1920,
    ) -> None:
        self.out_path = out_path
        self.fps = fps
        self.width = width
        self.height = height
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> FrameWriter:
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        use_nvenc = has_encoder("h264_nvenc")
        v_args = [
            "-c:v", "h264_nvenc",
            "-preset", "p5",
            "-rc", "vbr",
            "-cq", "16",
            "-b:v", "0",
        ] if use_nvenc else [
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "16",
        ]

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{self.width}x{self.height}",
            "-r", str(round(self.fps)),
            "-i", "-",
            *v_args,
            "-pix_fmt", "yuv420p",
            "-an",
            "-y",
            str(self.out_path),
        ]
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        startupinfo = None
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=flags,
            startupinfo=startupinfo,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.proc:
            if self.proc.stdin:
                with contextlib.suppress(Exception):
                    self.proc.stdin.close()
            if self.proc.stderr:
                self.proc.stderr.close()
            self.proc.wait()

    def write_frame(self, frame: np.ndarray) -> None:
        if self.proc and self.proc.stdin:
            self.proc.stdin.write(frame.tobytes())


def render_with_effects(
    framed_path: Path,
    edit_list: EditList,
    out_path: Path,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Composite all active EditList events onto the video frames."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fps = float(edit_list.fps or 30.0)

    # Sort visual events once
    visual_events = [e for e in edit_list.events if e.type in REGISTRY]

    frame_idx = 0
    with FrameReader(framed_path) as reader, FrameWriter(out_path, fps=fps) as writer:
        while True:
            if cancel_event and frame_idx % 30 == 0 and cancel_event.is_set():
                logger.info("Compositor aborted due to cancel signal at frame %d", frame_idx)
                break

            frame = reader.read_frame()
            if frame is None:
                break

            t = frame_idx / fps

            # Find active events at this exact moment
            active = [e for e in visual_events if e.t <= t < (e.t + e.dur)]
            if active:
                # Sort active events by layer priority
                active.sort(key=lambda e: LAYER_PRIORITY.get(e.type, 99))

                for ev in active:
                    renderer = REGISTRY.get(ev.type)
                    if renderer:
                        t_local = t - ev.t
                        frame = renderer.render(
                            frame=frame,
                            t_local=t_local,
                            dur=ev.dur,
                            params=ev.params,
                            canvas_w=1080,
                            canvas_h=1920,
                        )

            writer.write_frame(frame)
            frame_idx += 1

    return out_path
