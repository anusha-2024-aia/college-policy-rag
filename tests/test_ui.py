"""Tests for Streamlit UI client, backend contract, and response handling (ui/client.py)."""

import json
import pytest
import httpx
from ui.client import (
    BackendAPIClient,
    BackendConnectionError,
    APIValidationError,
    RateLimitError,
    ServiceUnavailableError,
    GatewayTimeoutError,
    APIClientError,
)
from app.schemas.qa import AskResponse, Citation, PassageEvidence, PolicyConflict, RetrievalDiagnostics


def test_client_url_normalization():
    """Verify BackendAPIClient strips trailing slashes from base URL."""
    client1 = BackendAPIClient("http://127.0.0.1:8000/")
    assert client1.base_url == "http://127.0.0.1:8000"

    client2 = BackendAPIClient("http://localhost:8000")
    assert client2.base_url == "http://localhost:8000"


def test_client_successful_response_parsing(monkeypatch):
    """Verify BackendAPIClient correctly parses 200 OK responses with citations."""
    sample_response = {
        "question": "What is CS101 grading criteria?",
        "answer": "Grading criteria is Homework 40%, Midterm 30%, Final 30% [1].",
        "citations": [
            {
                "index": 1,
                "file_name": "student_syllabus.pdf",
                "page_number": 2,
                "snippet": "Grading criteria: Homework 40%, Midterm 30%, Final 30%.",
            }
        ],
        "passages": [
            {
                "index": 1,
                "chunk_id": "chunk-1",
                "file_name": "student_syllabus.pdf",
                "page_number": 2,
                "text": "Page 2: Grading criteria: Homework 40%, Midterm 30%, Final 30%.",
                "score": 0.88,
            }
        ],
        "abstained": False,
        "has_policy_conflict": False,
        "conflict_details": None,
        "diagnostics": {
            "timings_ms": {"vector_search_ms": 2.5, "total_retrieval_ms": 5.0},
            "vector_count": 5,
            "keyword_count": 5,
            "fused_count": 8,
            "reranked_count": 1,
        },
    }

    def mock_post(self, url, **kwargs):
        assert url == "http://127.0.0.1:8000/ask"
        assert kwargs["json"]["question"] == "What is CS101 grading criteria?"
        assert kwargs["json"]["role"] == "student"
        return httpx.Response(status_code=200, json=sample_response)

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    client = BackendAPIClient("http://127.0.0.1:8000")
    result = client.ask("What is CS101 grading criteria?", role="student")

    assert isinstance(result, AskResponse)
    assert result.question == "What is CS101 grading criteria?"
    assert not result.abstained
    assert not result.has_policy_conflict
    assert len(result.citations) == 1
    assert result.citations[0].file_name == "student_syllabus.pdf"
    assert result.citations[0].page_number == 2
    assert result.diagnostics is not None
    assert result.diagnostics.reranked_count == 1


def test_client_policy_conflict_parsing(monkeypatch):
    """Verify BackendAPIClient correctly parses responses with policy conflict flags and details."""
    conflict_response = {
        "question": "What is remote work allowance?",
        "answer": "Current policy allows 3 days [1], superseding previous 1 day [2].",
        "citations": [
            {"index": 1, "file_name": "policy_v2.pdf", "page_number": 1, "snippet": "3 days"},
            {"index": 2, "file_name": "policy_v1.pdf", "page_number": 1, "snippet": "1 day"},
        ],
        "passages": [],
        "abstained": False,
        "has_policy_conflict": True,
        "conflict_details": [
            {
                "current_title": "Remote Work Policy 2024",
                "current_file": "policy_v2.pdf",
                "current_effective_date": "2024-01-01",
                "current_citation_index": 1,
                "superseded_title": "Remote Work Policy 2023",
                "superseded_file": "policy_v1.pdf",
                "superseded_effective_date": "2023-01-01",
                "superseded_citation_index": 2,
                "description": "Policy 2023 superseded by 2024.",
            }
        ],
        "diagnostics": None,
    }

    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, **kwargs: httpx.Response(status_code=200, json=conflict_response),
    )

    client = BackendAPIClient("http://127.0.0.1:8000")
    result = client.ask("What is remote work allowance?", role="faculty")

    assert result.has_policy_conflict is True
    assert result.conflict_details is not None
    assert len(result.conflict_details) == 1
    assert result.conflict_details[0].current_title == "Remote Work Policy 2024"
    assert result.conflict_details[0].superseded_title == "Remote Work Policy 2023"


def test_client_abstention_parsing(monkeypatch):
    """Verify BackendAPIClient correctly parses abstention responses."""
    abstention_response = {
        "question": "Warp drive regulations?",
        "answer": "I do not have sufficient information in the provided documents to answer this question.",
        "citations": [],
        "passages": [],
        "abstained": True,
        "has_policy_conflict": False,
        "conflict_details": None,
        "diagnostics": None,
    }

    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, **kwargs: httpx.Response(status_code=200, json=abstention_response),
    )

    client = BackendAPIClient("http://127.0.0.1:8000")
    result = client.ask("Warp drive regulations?", role="student")

    assert result.abstained is True
    assert len(result.citations) == 0
    assert "not have sufficient information" in result.answer


def test_client_error_handling_validation_422(monkeypatch):
    """Verify HTTP 422 raises APIValidationError."""
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, **kwargs: httpx.Response(
            status_code=422,
            json={"detail": "Invalid role 'hacker'. Permitted roles are: student, faculty, admin."},
        ),
    )

    client = BackendAPIClient("http://127.0.0.1:8000")
    with pytest.raises(APIValidationError) as exc_info:
        client.ask("test", role="hacker")
    assert "Invalid role 'hacker'" in str(exc_info.value)


def test_client_error_handling_rate_limit_429(monkeypatch):
    """Verify HTTP 429 raises RateLimitError."""
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, **kwargs: httpx.Response(
            status_code=429,
            json={"detail": "LLM provider rate limit exceeded."},
        ),
    )

    client = BackendAPIClient("http://127.0.0.1:8000")
    with pytest.raises(RateLimitError) as exc_info:
        client.ask("test", role="student")
    assert "rate limit exceeded" in str(exc_info.value)


def test_client_error_handling_service_unavailable_503(monkeypatch):
    """Verify HTTP 503 raises ServiceUnavailableError."""
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, **kwargs: httpx.Response(
            status_code=503,
            json={"detail": "LLM service configuration error."},
        ),
    )

    client = BackendAPIClient("http://127.0.0.1:8000")
    with pytest.raises(ServiceUnavailableError) as exc_info:
        client.ask("test", role="student")
    assert "configuration error" in str(exc_info.value)


def test_client_error_handling_connection_refused(monkeypatch):
    """Verify connection failure raises BackendConnectionError with friendly guidance."""
    def mock_post(self, url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    client = BackendAPIClient("http://127.0.0.1:8000")
    with pytest.raises(BackendConnectionError) as exc_info:
        client.ask("test", role="student")
    assert "Could not connect to Document RAG backend" in str(exc_info.value)
    assert "Please verify the FastAPI server is running" in str(exc_info.value)


def test_client_error_handling_timeout(monkeypatch):
    """Verify request timeout raises BackendConnectionError."""
    def mock_post(self, url, **kwargs):
        raise httpx.TimeoutException("Timed out")

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    client = BackendAPIClient("http://127.0.0.1:8000")
    with pytest.raises(BackendConnectionError) as exc_info:
        client.ask("test", role="student")
    assert "timed out after" in str(exc_info.value)
