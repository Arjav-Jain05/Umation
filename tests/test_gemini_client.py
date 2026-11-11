"""Unit tests for LocalLLMClient backward compatibility and local manager delegation."""

from unittest.mock import MagicMock

from pydantic import BaseModel

from app.core.gemini_client import GeminiClient, LocalLLMClient, TokenBucket
from config.settings import Settings


class SampleSchema(BaseModel):
    message: str
    score: int


def test_token_bucket_acquire():
    """Verify TokenBucket acquires tokens."""
    bucket = TokenBucket(rpm=60)
    assert bucket.tokens == 60.0
    bucket.acquire()
    assert bucket.tokens < 60.0


def test_local_llm_client_instantiation():
    """Verify LocalLLMClient instantiates with local settings."""
    settings = Settings()
    client = LocalLLMClient(settings=settings)
    assert client.manager is not None
    assert client.provider is not None


def test_local_llm_client_alias():
    """Verify GeminiClient is an alias for LocalLLMClient."""
    assert GeminiClient is LocalLLMClient


def test_local_llm_generate_json_delegates_to_manager():
    """Verify generate_json delegates directly to LocalModelManager."""
    client = LocalLLMClient()
    mock_mgr = MagicMock()
    mock_mgr.generate_json.return_value = SampleSchema(message="Delegated local success", score=42)
    client.manager = mock_mgr

    res = client.generate_json("Test prompt", SampleSchema, task="test_task")
    assert res.message == "Delegated local success"
    assert res.score == 42
    mock_mgr.generate_json.assert_called_once()
