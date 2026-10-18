"""Tests for LLM service interfaces, mock behavior, and exception hierarchies."""

import pytest
from app.services.llm import (
    MockLLMService,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMError,
    get_llm_service,
)


def test_mock_llm_generates_factual_answer_with_citations():
    """Verify MockLLM parses context evidence and produces factual response with [N] citations."""
    llm = MockLLMService()
    prompt = (
        "Context Evidence:\n"
        "[1] File: handbook.pdf (Page 2)\n"
        "Remote work policy: Employees may work hybrid up to three days per week.\n\n"
        "User Question: What is the remote work policy?"
    )

    answer = llm.generate(prompt)
    assert "[1]" in answer
    assert "Remote work policy" in answer
    assert not answer.startswith("I do not have sufficient information")


def test_mock_llm_abstains_on_unanswerable_triggers():
    """Verify MockLLM returns standard abstention sentence when query contains unknown concepts."""
    llm = MockLLMService()
    prompt = (
        "Context Evidence:\n"
        "[1] File: handbook.pdf (Page 2)\n"
        "Office hours are 9am to 5pm.\n\n"
        "User Question: What is the warp drive engine speed on Mars?"
    )

    answer = llm.generate(prompt)
    assert answer == MockLLMService.ABSTENTION_PHRASE


def test_mock_llm_abstains_on_empty_evidence():
    """Verify MockLLM returns abstention sentence when evidence is absent."""
    llm = MockLLMService()
    prompt = "Context Evidence:\nNone\n\nUser Question: What are the office hours?"

    answer = llm.generate(prompt)
    assert answer == MockLLMService.ABSTENTION_PHRASE


def test_mock_llm_streaming():
    """Verify MockLLM streaming yields word tokens correctly."""
    llm = MockLLMService(custom_response="Hello world test citation [1].")
    tokens = list(llm.generate_stream("prompt"))

    assert len(tokens) == 5
    assert "".join(tokens) == "Hello world test citation [1]."


def test_mock_llm_simulates_auth_error():
    """Verify MockLLM raises LLMAuthenticationError when requested."""
    llm = MockLLMService(simulate_error="auth")
    with pytest.raises(LLMAuthenticationError):
        llm.generate("test")


def test_mock_llm_simulates_rate_limit_error():
    """Verify MockLLM raises LLMRateLimitError when requested."""
    llm = MockLLMService(simulate_error="rate_limit")
    with pytest.raises(LLMRateLimitError):
        llm.generate("test")


def test_mock_llm_simulates_timeout_error():
    """Verify MockLLM raises LLMTimeoutError when requested."""
    llm = MockLLMService(simulate_error="timeout")
    with pytest.raises(LLMTimeoutError):
        llm.generate("test")


def test_get_llm_service_factory():
    """Verify factory returns MockLLMService during testing."""
    svc = get_llm_service(force_mock=True)
    assert isinstance(svc, MockLLMService)


def test_gemini_llm_service_generate_success(monkeypatch):
    """Verify GeminiLLMService parses candidates and returns synthesized text."""
    from unittest.mock import MagicMock
    import httpx
    from app.services.llm import GeminiLLMService

    fake_response = MagicMock(spec=httpx.Response)
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "According to the handbook, employees can work remotely [1]."}]
                }
            }
        ]
    }

    mock_client = MagicMock()
    mock_client.post.return_value = fake_response
    mock_client.__enter__.return_value = mock_client
    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    gemini = GeminiLLMService(api_key="test-gemini-key", model="gemini-1.5-flash")
    result = gemini.generate("What is the remote work policy?", system_prompt="Answer based on context.")

    assert result == "According to the handbook, employees can work remotely [1]."
    assert mock_client.post.called


def test_gemini_llm_service_auth_error(monkeypatch):
    """Verify GeminiLLMService maps HTTP 400/403 to LLMAuthenticationError."""
    from unittest.mock import MagicMock
    import httpx
    from app.services.llm import GeminiLLMService

    fake_response = MagicMock(spec=httpx.Response)
    fake_response.status_code = 400
    fake_response.text = '{"error": {"message": "API key not valid. Please pass a valid API key."}}'
    fake_response.json.return_value = {"error": {"message": "API key not valid."}}

    mock_client = MagicMock()
    mock_client.post.return_value = fake_response
    mock_client.__enter__.return_value = mock_client
    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    gemini = GeminiLLMService(api_key="invalid-key")
    with pytest.raises(LLMAuthenticationError):
        gemini.generate("hello")


def test_gemini_llm_service_rate_limit(monkeypatch):
    """Verify GeminiLLMService maps HTTP 429 to LLMRateLimitError."""
    from unittest.mock import MagicMock
    import httpx
    from app.services.llm import GeminiLLMService

    fake_response = MagicMock(spec=httpx.Response)
    fake_response.status_code = 429
    fake_response.text = '{"error": {"message": "Resource exhausted / quota exceeded"}}'
    fake_response.json.return_value = {"error": {"message": "Quota exceeded"}}

    mock_client = MagicMock()
    mock_client.post.return_value = fake_response
    mock_client.__enter__.return_value = mock_client
    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    gemini = GeminiLLMService(api_key="test-key")
    with pytest.raises(LLMRateLimitError):
        gemini.generate("hello")


def test_gemini_llm_service_timeout(monkeypatch):
    """Verify GeminiLLMService maps TimeoutException to LLMTimeoutError."""
    from unittest.mock import MagicMock
    import httpx
    from app.services.llm import GeminiLLMService

    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.TimeoutException("Read timeout")
    mock_client.__enter__.return_value = mock_client
    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    gemini = GeminiLLMService(api_key="test-key")
    with pytest.raises(LLMTimeoutError):
        gemini.generate("hello")

