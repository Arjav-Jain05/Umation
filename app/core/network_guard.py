"""network_guard.py: Enforce strict offline / localhost-only policy for AI pipeline.

Golden Rule 1: ZERO cloud AI at runtime.
Only localhost:11434 (Ollama) and local sockets are permitted during AI processing.
"""

from __future__ import annotations

import contextlib
import socket
from collections.abc import Generator
from typing import Any

ALLOWED_LOCAL_HOSTS = {
    "127.0.0.1",
    "localhost",
    "::1",
    "0.0.0.0",
}

BLOCKED_CLOUD_DOMAINS = [
    "googleapis.com",
    "openai.com",
    "anthropic.com",
    "huggingface.co",
    "replicate.com",
    "together.xyz",
    "groq.com",
]


class NetworkCallBlockedError(RuntimeError):
    """Raised when an unauthorized outbound network call is attempted."""
    pass


def is_host_allowed(host: str, allow_ingest: bool = False) -> bool:
    """Check whether a target hostname or IP is authorized."""
    host_lower = host.lower().strip()
    if host_lower in ALLOWED_LOCAL_HOSTS:
        return True

    for blocked in BLOCKED_CLOUD_DOMAINS:
        if blocked in host_lower:
            return False

    return bool(allow_ingest)


@contextlib.contextmanager
def network_guard(allow_ingest: bool = False) -> Generator[None, None, None]:
    """Context manager that blocks unauthorized outbound socket connections."""
    orig_connect = socket.socket.connect
    orig_create_connection = socket.create_connection

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) and len(address) > 0 else str(address)
        if not is_host_allowed(host, allow_ingest=allow_ingest):
            raise NetworkCallBlockedError(
                f"ZERO-CLOUD VIOLATION: Outbound network call to '{host}' blocked by network_guard."
            )
        return orig_connect(self, address)

    def guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        host = address[0] if isinstance(address, tuple) and len(address) > 0 else str(address)
        if not is_host_allowed(host, allow_ingest=allow_ingest):
            raise NetworkCallBlockedError(
                f"ZERO-CLOUD VIOLATION: Outbound socket connection to '{host}' blocked by network_guard."
            )
        return orig_create_connection(address, *args, **kwargs)

    socket.socket.connect = guarded_connect  # type: ignore
    socket.create_connection = guarded_create_connection  # type: ignore
    try:
        yield
    finally:
        socket.socket.connect = orig_connect  # type: ignore
        socket.create_connection = orig_create_connection  # type: ignore
