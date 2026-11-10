"""Power state management: keep system awake during pipeline runs and detect battery."""

from __future__ import annotations

import ctypes
import logging
import sys
from collections.abc import Generator
from contextlib import contextmanager

logger = logging.getLogger("app.core.power")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def on_battery() -> bool:
    """Check if system is running on battery power."""
    try:
        import psutil

        battery = psutil.sensors_battery()
        if battery is None:
            return False
        return not battery.power_plugged
    except Exception as e:
        logger.debug("Could not inspect battery state: %s", e)
        return False


@contextmanager
def keep_awake() -> Generator[None, None, None]:
    """Context manager preventing Windows sleep mode during active jobs."""
    is_windows = sys.platform == "win32" and hasattr(ctypes, "windll")
    if is_windows:
        try:
            # Set continuous system execution state
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            logger.debug("Windows power execution state set: keep awake enabled")
        except Exception as e:
            logger.warning("Failed to set thread execution state: %s", e)

    try:
        yield
    finally:
        if is_windows:
            try:
                # Clear system requirement
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
                logger.debug("Windows power execution state cleared: sleep permitted")
            except Exception as e:
                logger.warning("Failed to reset thread execution state: %s", e)
