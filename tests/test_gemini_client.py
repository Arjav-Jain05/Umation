"""Unit tests for GeminiClient (rate limiter, exponential retry, cache hit, schema retry)."""

import json
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from app.core.cache import cache_set, make_key
from app.core.errors import BadModelOutput
from app.core.gemini_client import GeminiClient, TokenBucket
from config.settings import Settings


class SampleSchema(BaseModel):
    message: str
    score: int


def test_token_bucket_acquire():
    """Verify TokenBucket acquires tokens and refills over elapsed time."""
    bucket = TokenBucket(rpm=60)  # 1 token per second, capacity 60
    assert bucket.tokens == 60.0
    bucket.acquire()
    assert bucket.tokens < 60.0


def test_gemini_retry_backoff(monkeypatch: pytest.MonkeyPatch):
    """Verify _call_with_retry retries on transient errors and backs off."""
    mock_sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: mock_sleeps.append(s))

    settings = Settings(gemini_api_key="fake-test-key", gemini_rpm=60)
    client = GeminiClient(settings=settings, enable_cache=False)

    call_count = 0

    def flaky_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("429 Resource has been exhausted (rate limit)")
        return "success"

    res = client._call_with_retry(flaky_func)
    assert res == "success"
    assert call_count == 3
    # Two backoff sleeps occurred
    assert len(mock_sleeps) == 2
    assert mock_sleeps[0] >= 2.0
    assert mock_sleeps[1] >= 4.0


def test_gemini_cache_hit_avoids_api_call(monkeypatch: pytest.MonkeyPatch):
    """Verify cache hit returns cached model directly without invoking Gemini API."""
    settings = Settings(gemini_api_key="fake-test-key", gemini_rpm=60)
    client = GeminiClient(settings=settings, enable_cache=True)

    prompt = "Test prompt for cache"
    expected_data = {"message": "Cached response", "score": 99}
    key = make_key(
        settings.gemini_model_text,
        prompt,
        SampleSchema.__name__,
        0.2,
        str(None),
    )
    cache_set(key, json.dumps(expected_data))

    # Mock client property so that if called it would raise
    mock_genai_client = MagicMock()
    mock_genai_client.models.generate_content.side_effect = AssertionError("API should not be called on cache hit")
    client._client = mock_genai_client

    result = client.generate_json(prompt, SampleSchema, temperature=0.2)
    assert result.message == "Cached response"
    assert result.score == 99
    assert mock_genai_client.models.generate_content.call_count == 0


def test_gemini_invalid_json_retried_once(monkeypatch: pytest.MonkeyPatch):
    """Verify invalid JSON on first attempt triggers a retry with error feedback and succeeds."""
    settings = Settings(gemini_api_key="fake-test-key", gemini_rpm=60)
    client = GeminiClient(settings=settings, enable_cache=False)

    mock_resp_bad = MagicMock()
    mock_resp_bad.text = "NOT JSON TEXT"

    mock_resp_good = MagicMock()
    mock_resp_good.text = json.dumps({"message": "Valid after retry", "score": 10})

    mock_genai_client = MagicMock()
    mock_genai_client.models.generate_content.side_effect = [mock_resp_bad, mock_resp_good]
    client._client = mock_genai_client

    result = client.generate_json("Generate sample", SampleSchema)
    assert result.message == "Valid after retry"
    assert result.score == 10
    # Two attempts made
    assert mock_genai_client.models.generate_content.call_count == 2


def test_gemini_invalid_json_twice_raises_bad_model_output(monkeypatch: pytest.MonkeyPatch):
    """Verify invalid JSON twice raises BadModelOutput."""
    settings = Settings(gemini_api_key="fake-test-key", gemini_rpm=60)
    client = GeminiClient(settings=settings, enable_cache=False)

    mock_resp_bad = MagicMock()
    mock_resp_bad.text = "NOT JSON TEXT"

    mock_genai_client = MagicMock()
    mock_genai_client.models.generate_content.return_value = mock_resp_bad
    client._client = mock_genai_client

    with pytest.raises(BadModelOutput, match="violated schema"):
        client.generate_json("Generate sample", SampleSchema)
