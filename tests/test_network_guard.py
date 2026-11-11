"""test_network_guard.py: Verify network guard blocks all cloud AI outbound requests."""

import socket

import pytest

from app.core.network_guard import NetworkCallBlockedError, is_host_allowed, network_guard


def test_is_host_allowed():
    assert is_host_allowed("127.0.0.1") is True
    assert is_host_allowed("localhost") is True
    assert is_host_allowed("::1") is True

    # Cloud AI domains must always be blocked
    assert is_host_allowed("generativelanguage.googleapis.com") is False
    assert is_host_allowed("api.openai.com") is False
    assert is_host_allowed("api.anthropic.com") is False
    assert is_host_allowed("api-inference.huggingface.co") is False

    # External domains blocked when allow_ingest=False
    assert is_host_allowed("youtube.com", allow_ingest=False) is False

    # Ingest allows video domains but STILL blocks cloud AI
    assert is_host_allowed("youtube.com", allow_ingest=True) is True
    assert is_host_allowed("generativelanguage.googleapis.com", allow_ingest=True) is False


def test_network_guard_blocks_socket_connect():
    with network_guard(allow_ingest=False):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with pytest.raises(NetworkCallBlockedError, match="ZERO-CLOUD VIOLATION"):
            s.connect(("generativelanguage.googleapis.com", 443))
        s.close()


def test_network_guard_allows_localhost():
    with network_guard(allow_ingest=False):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Attempt connecting to localhost:11434 - should NOT raise NetworkCallBlockedError
        # (It may succeed or raise standard ConnectionRefusedError if port closed, but not NetworkCallBlockedError)
        try:
            s.connect(("127.0.0.1", 11434))
        except (ConnectionRefusedError, TimeoutError, OSError) as exc:
            assert not isinstance(exc, NetworkCallBlockedError)
        finally:
            s.close()
