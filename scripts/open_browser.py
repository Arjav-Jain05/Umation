"""open_browser.py: Poll localhost:8000 until responsive, then open default web browser."""

from __future__ import annotations

import contextlib
import socket
import time
import webbrowser


def open_when_ready(host: str = "127.0.0.1", port: int = 8000, max_wait_s: float = 15.0) -> bool:
    """Poll the HTTP port and launch the browser once the server accepts connections."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_wait_s:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            res = s.connect_ex((host, port))
            if res == 0:
                s.close()
                time.sleep(0.3)
                webbrowser.open(f"http://{host}:{port}")
                return True
        except Exception:
            pass
        finally:
            with contextlib.suppress(Exception):
                s.close()
        time.sleep(0.4)

    # Fallback: open anyway if timeout reached
    webbrowser.open(f"http://{host}:{port}")
    return False


if __name__ == "__main__":
    open_when_ready()
