"""Tests for Phase 3 Question Answering (POST /ask, POST /ask/stream, citations, abstention, error handling)."""

from collections.abc import Generator
from pathlib import Path
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import get_db
from app.api.routes.ask import get_qa_service
from app.schemas.qa import AskRequest, AskResponse, Citation, PassageEvidence
from app.services.embedding import MockEmbeddingService
from app.services.reranker import MockRerankerService
from app.services.retrieval import HybridRetrievalService
from app.services.llm import (
    MockLLMService,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMError,
)
from app.services.qa import QAService
from tests.test_retrieval import setup_ingested_database


@pytest.fixture(autouse=True)
def cleanup_overrides():
    """Ensure FastAPI dependency overrides are cleanly restored after each test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def qa_test_setup(test_db: Session, sample_pdf_workspace: Path, mock_embedding_service: MockEmbeddingService):
    """Populate test database with sample documents and provide configured retrieval service."""
    setup_ingested_database(test_db, sample_pdf_workspace, mock_embedding_service)
    retrieval_service = HybridRetrievalService(
        db_session=test_db,
        embedding_service=mock_embedding_service,
        reranker_service=MockRerankerService(),
    )
    return {
        "db": test_db,
        "retrieval": retrieval_service,
    }


def test_ask_valid_question_returns_grounded_answer_and_citations(
    client: TestClient, qa_test_setup: dict
):
    """Verify POST /ask answers valid question with citations mapped to real documents and pages."""
    app.dependency_overrides[get_db] = lambda: qa_test_setup["db"]

    payload = {
        "question": "What is the corporate architecture and mission?",
        "top_k": 10,
        "top_n": 3,
        "include_diagnostics": True,
    }

    response = client.post("/ask", json=payload)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["question"] == payload["question"]
    assert not data["abstained"]
    assert "[1]" in data["answer"]
    assert len(data["citations"]) >= 1

    # Verify citation fields point to actual ingested file and page
    top_citation = data["citations"][0]
    assert top_citation["index"] == 1
    assert top_citation["file_name"] == "valid_doc.pdf"
    assert top_citation["page_number"] == 1
    assert len(top_citation["snippet"]) > 0

    # Verify passages match
    assert len(data["passages"]) <= 3
    assert data["passages"][0]["index"] == 1
    assert data["passages"][0]["file_name"] == "valid_doc.pdf"
    assert data["passages"][0]["page_number"] == 1

    # Verify diagnostics are populated
    assert data["diagnostics"] is not None
    assert "vector_search_ms" in data["diagnostics"]["timings_ms"]
    assert "reranking_ms" in data["diagnostics"]["timings_ms"]
    assert data["diagnostics"]["reranked_count"] == len(data["passages"])


def test_citation_validator_rejects_hallucinated_citations(qa_test_setup: dict):
    """Verify that hallucinated citation indices like [99] are strictly excluded from citations list.

    The model must never invent a source file or page number.
    """
    retrieval_service = qa_test_setup["retrieval"]

    # Provide a mock response that cites real passage [1] and hallucinated passage [99]
    hallucinating_llm = MockLLMService(
        custom_response=(
            "According to the official documentation, corporate architecture is established [1]. "
            "However, unverified rumours suggest secret protocols [99] and extra policies [42]."
        )
    )
    qa_service = QAService(retrieval_service=retrieval_service, llm_service=hallucinating_llm)

    request = AskRequest(
        question="What is corporate architecture?",
        top_k=5,
        top_n=2,
    )
    response = qa_service.answer(request)

    assert not response.abstained
    assert "[1]" in response.answer
    assert "[99]" in response.answer

    # Assert only [1] is recorded as a valid citation; [99] and [42] are omitted
    citation_indices = [c.index for c in response.citations]
    assert 1 in citation_indices
    assert 99 not in citation_indices
    assert 42 not in citation_indices

    # All citations must correspond to an actual passage in response.passages
    valid_passage_indices = {p.index for p in response.passages}
    for cit in response.citations:
        assert cit.index in valid_passage_indices
        assert cit.file_name in ("valid_doc.pdf", "policy_v2.pdf")
        assert cit.page_number in (1, 2, 3)


def test_abstention_on_unanswerable_question(client: TestClient, qa_test_setup: dict):
    """Verify that questions containing concepts absent from documents trigger abstention."""
    app.dependency_overrides[get_db] = lambda: qa_test_setup["db"]

    payload = {
        "question": "What is the warp drive engine speed limit on Mars?",
        "top_k": 5,
        "top_n": 3,
    }

    response = client.post("/ask", json=payload)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["abstained"] is True
    assert data["answer"] == QAService.ABSTENTION_SENTENCE
    assert data["citations"] == []


def test_abstention_on_empty_corpus(client: TestClient, test_db: Session):
    """Verify system abstains gracefully when database has zero documents."""
    app.dependency_overrides[get_db] = lambda: test_db

    payload = {
        "question": "What is the corporate architecture?",
    }

    response = client.post("/ask", json=payload)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["abstained"] is True
    assert data["answer"] == QAService.ABSTENTION_SENTENCE
    assert data["citations"] == []
    assert data["passages"] == []


def test_early_abstention_when_scores_below_threshold(qa_test_setup: dict):
    """Verify early abstention occurs when evidence reranker score is below configured threshold."""
    retrieval_service = qa_test_setup["retrieval"]
    llm = MockLLMService()
    qa_service = QAService(retrieval_service=retrieval_service, llm_service=llm)

    # Set threshold above top rerank score
    request = AskRequest(
        question="What is corporate architecture?",
        abstention_threshold=0.99,
    )
    response = qa_service.answer(request)

    assert response.abstained is True
    assert response.answer == QAService.ABSTENTION_SENTENCE
    assert response.citations == []


def test_error_handling_authentication_failure(client: TestClient, qa_test_setup: dict):
    """Verify missing/invalid LLM credentials return HTTP 503 Service Unavailable."""
    app.dependency_overrides[get_db] = lambda: qa_test_setup["db"]
    error_llm = MockLLMService(simulate_error="auth")
    app.dependency_overrides[get_qa_service] = lambda: QAService(
        retrieval_service=qa_test_setup["retrieval"],
        llm_service=error_llm,
    )

    response = client.post("/ask", json={"question": "What is corporate policy?"})
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "configuration error or missing API credentials" in response.json()["detail"]


def test_error_handling_rate_limit(client: TestClient, qa_test_setup: dict):
    """Verify LLM provider rate limits return HTTP 429 Too Many Requests."""
    app.dependency_overrides[get_db] = lambda: qa_test_setup["db"]
    error_llm = MockLLMService(simulate_error="rate_limit")
    app.dependency_overrides[get_qa_service] = lambda: QAService(
        retrieval_service=qa_test_setup["retrieval"],
        llm_service=error_llm,
    )

    response = client.post("/ask", json={"question": "What is corporate policy?"})
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert "rate limit exceeded" in response.json()["detail"]


def test_error_handling_timeout(client: TestClient, qa_test_setup: dict):
    """Verify LLM provider timeouts return HTTP 504 Gateway Timeout."""
    app.dependency_overrides[get_db] = lambda: qa_test_setup["db"]
    error_llm = MockLLMService(simulate_error="timeout")
    app.dependency_overrides[get_qa_service] = lambda: QAService(
        retrieval_service=qa_test_setup["retrieval"],
        llm_service=error_llm,
    )

    response = client.post("/ask", json={"question": "What is corporate policy?"})
    assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT
    assert "timed out" in response.json()["detail"]


def test_streaming_endpoint_returns_sse_events(client: TestClient, qa_test_setup: dict):
    """Verify POST /ask/stream returns SSE stream with metadata, token, citations, and done events."""
    app.dependency_overrides[get_db] = lambda: qa_test_setup["db"]

    payload = {
        "question": "Where are the standard operating procedures located?",
        "include_diagnostics": True,
    }

    response = client.post("/ask/stream", json=payload)
    assert response.status_code == status.HTTP_200_OK
    assert "text/event-stream" in response.headers["content-type"]

    body = response.text
    assert "event: metadata" in body
    assert "event: token" in body
    assert "event: citations" in body
    assert "event: done" in body
    assert '"abstained": false' in body
    assert "valid_doc.pdf" in body


def test_streaming_endpoint_abstention(client: TestClient, qa_test_setup: dict):
    """Verify POST /ask/stream streams abstention sentence when question is unanswerable."""
    app.dependency_overrides[get_db] = lambda: qa_test_setup["db"]

    payload = {
        "question": "What is the warp drive speed limit on Mars?",
    }

    response = client.post("/ask/stream", json=payload)
    assert response.status_code == status.HTTP_200_OK

    body = response.text
    assert "event: metadata" in body
    assert "event: token" in body
    assert "event: citations" in body
    assert "event: done" in body
    assert '"abstained": true' in body

    # Reconstruct streamed tokens from SSE data lines
    import json
    streamed_tokens = [
        json.loads(line[6:])["token"]
        for line in body.splitlines()
        if line.startswith("data: ") and '"token"' in line
    ]
    reconstructed_answer = "".join(streamed_tokens)
    assert reconstructed_answer == QAService.ABSTENTION_SENTENCE
