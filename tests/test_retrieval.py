"""Integration and benchmark tests for hybrid retrieval service."""

from pathlib import Path
from sqlalchemy.orm import Session
from app.services.ingestion import IngestionService
from app.services.manifest import ManifestService
from app.services.retrieval import HybridRetrievalService
from app.services.embedding import MockEmbeddingService
from app.services.reranker import MockRerankerService


def setup_ingested_database(test_db: Session, sample_pdf_workspace: Path, mock_embedding_service: MockEmbeddingService):
    """Helper to populate test database with sample documents."""
    manifest_service = ManifestService(base_dir=sample_pdf_workspace)
    ingestion_service = IngestionService(
        db_session=test_db,
        manifest_service=manifest_service,
        embedding_service=mock_embedding_service,
    )
    manifest_path = sample_pdf_workspace / "documents_manifest.csv"
    ingestion_service.ingest_manifest(manifest_path=manifest_path)


def test_vector_search_alone(test_db: Session, sample_pdf_workspace: Path, mock_embedding_service: MockEmbeddingService):
    """Verify vector_search returns semantically ranked results with 1-based ranks."""
    setup_ingested_database(test_db, sample_pdf_workspace, mock_embedding_service)

    service = HybridRetrievalService(
        db_session=test_db,
        embedding_service=mock_embedding_service,
    )

    results = service.vector_search("corporate architecture and guidelines", k=5)
    assert len(results) > 0
    assert results[0].rank == 1
    assert all(r.score >= 0.0 for r in results)
    assert all(r.page_number in (1, 2, 3) for r in results)


def test_keyword_search_alone(test_db: Session, sample_pdf_workspace: Path, mock_embedding_service: MockEmbeddingService):
    """Verify keyword_search retrieves chunks containing exact matching tokens."""
    setup_ingested_database(test_db, sample_pdf_workspace, mock_embedding_service)

    service = HybridRetrievalService(
        db_session=test_db,
        embedding_service=mock_embedding_service,
    )

    results = service.keyword_search("encryption", k=5)
    assert len(results) > 0
    # The chunk on encryption must be retrieved
    assert any("encryption" in r.text.lower() for r in results)


def test_full_retrieve_pipeline_diagnostics(test_db: Session, sample_pdf_workspace: Path, mock_embedding_service: MockEmbeddingService):
    """Verify retrieve() returns all stage outputs and diagnostic timings."""
    setup_ingested_database(test_db, sample_pdf_workspace, mock_embedding_service)

    service = HybridRetrievalService(
        db_session=test_db,
        embedding_service=mock_embedding_service,
        reranker_service=MockRerankerService(),
    )

    response = service.retrieve("regulations safety", top_k=10, top_n=3)

    assert response.query == "regulations safety"
    assert len(response.vector_results) > 0
    assert len(response.keyword_results) > 0
    assert len(response.fused_results) > 0
    assert len(response.reranked_results) <= 3

    # Check diagnostic timings
    diag = response.diagnostics
    assert "vector_search_ms" in diag.timings_ms
    assert "keyword_search_ms" in diag.timings_ms
    assert "rrf_fusion_ms" in diag.timings_ms
    assert "reranking_ms" in diag.timings_ms
    assert "total_retrieval_ms" in diag.timings_ms
    assert diag.vector_count == len(response.vector_results)
    assert diag.reranked_count == len(response.reranked_results)


def test_manual_questions_benchmark(test_db: Session, sample_pdf_workspace: Path, mock_embedding_service: MockEmbeddingService):
    """Evaluate a manually verified set of questions against ingested documents.

    Asserts that the expected document and page number are retrieved at rank #1.
    """
    setup_ingested_database(test_db, sample_pdf_workspace, mock_embedding_service)

    service = HybridRetrievalService(
        db_session=test_db,
        embedding_service=mock_embedding_service,
        reranker_service=MockRerankerService(),
    )

    test_queries = [
        {
            "query": "What are the rules on confidential data retention and encryption?",
            "expected_file": "valid_doc.pdf",
            "expected_page": 3,
        },
        {
            "query": "Where are the standard operating procedures and safety regulations located?",
            "expected_file": "valid_doc.pdf",
            "expected_page": 2,
        },
        {
            "query": "What are the enforcement mechanisms and escalation paths in policy v2?",
            "expected_file": "policy_v2.pdf",
            "expected_page": 2,
        },
        {
            "query": "What is the corporate architecture and mission?",
            "expected_file": "valid_doc.pdf",
            "expected_page": 1,
        },
    ]

    for item in test_queries:
        response = service.retrieve(item["query"], top_k=10, top_n=3)
        assert len(response.reranked_results) > 0, f"No results for query: {item['query']}"

        top_hit = response.reranked_results[0]
        # Assert top hit matches expected file and page
        assert top_hit.file_name == item["expected_file"], (
            f"Query '{item['query']}' retrieved file '{top_hit.file_name}' instead of '{item['expected_file']}'"
        )
        assert top_hit.page_number == item["expected_page"], (
            f"Query '{item['query']}' retrieved page {top_hit.page_number} instead of page {item['expected_page']}"
        )
