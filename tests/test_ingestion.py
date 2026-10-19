"""End-to-end ingestion pipeline tests and idempotency verification."""

from pathlib import Path
from sqlalchemy.orm import Session
from app.models.document import Document
from app.models.chunk import Chunk
from app.services.ingestion import IngestionService
from app.services.manifest import ManifestService
from app.services.embedding import MockEmbeddingService


def test_end_to_end_ingestion(test_db: Session, sample_pdf_workspace: Path, mock_embedding_service: MockEmbeddingService):
    """Verify complete ingestion pipeline: manifest parsing, PDF extraction, chunking, and database storage."""
    manifest_service = ManifestService(base_dir=sample_pdf_workspace)
    ingestion_service = IngestionService(
        db_session=test_db,
        manifest_service=manifest_service,
        embedding_service=mock_embedding_service,
    )

    manifest_path = sample_pdf_workspace / "documents_manifest.csv"
    report = ingestion_service.ingest_manifest(manifest_path=manifest_path)

    # 1. Verify Report
    assert report.total_documents == 2
    assert report.ingested_count == 2
    assert report.skipped_count == 0
    assert report.failed_count == 0
    assert report.total_chunks_created > 0

    # 2. Verify Document Records
    docs = test_db.query(Document).order_by(Document.file_name).all()
    assert len(docs) == 2

    policy_doc = next(d for d in docs if d.file_name == "policy_v2.pdf")
    assert policy_doc.title == "Policy V2"
    assert policy_doc.supersedes == "Policy V1"
    assert "legal" in policy_doc.allowed_roles
    assert policy_doc.status == "ingested"
    assert policy_doc.total_pages == 2

    valid_doc = next(d for d in docs if d.file_name == "valid_doc.pdf")
    assert valid_doc.title == "Corporate Architecture"
    assert valid_doc.supersedes is None
    assert "engineering" in valid_doc.allowed_roles
    assert valid_doc.total_pages == 3

    # 3. Verify Chunk Records and Manual Chunk Inspection
    chunks = test_db.query(Chunk).filter(Chunk.document_id == valid_doc.id).order_by(Chunk.chunk_index).all()
    assert len(chunks) == valid_doc.total_chunks
    assert len(chunks) >= 3

    # Manually inspect chunks: verify 1-based page numbers, vector dimension, text
    seen_pages = set()
    for chunk in chunks:
        assert chunk.page_number in (1, 2, 3)
        assert chunk.token_count > 0
        assert len(chunk.embedding) == 1536
        assert chunk.text.strip() != ""
        seen_pages.add(chunk.page_number)

    # Ensure all 3 pages are represented
    assert seen_pages == {1, 2, 3}


def test_repeated_ingestion_is_idempotent(test_db: Session, sample_pdf_workspace: Path, mock_embedding_service: MockEmbeddingService):
    """CRITICAL TEST: Verify that running ingestion repeatedly creates NO duplicate records."""
    manifest_service = ManifestService(base_dir=sample_pdf_workspace)
    ingestion_service = IngestionService(
        db_session=test_db,
        manifest_service=manifest_service,
        embedding_service=mock_embedding_service,
    )
    manifest_path = sample_pdf_workspace / "documents_manifest.csv"

    # Pass 1: Initial ingestion
    report_pass1 = ingestion_service.ingest_manifest(manifest_path=manifest_path)
    assert report_pass1.ingested_count == 2
    initial_doc_count = test_db.query(Document).count()
    initial_chunk_count = test_db.query(Chunk).count()

    assert initial_doc_count == 2
    assert initial_chunk_count > 0

    # Pass 2: Repeated ingestion with identical files and manifest
    report_pass2 = ingestion_service.ingest_manifest(manifest_path=manifest_path, force=False)
    assert report_pass2.skipped_count == 2
    assert report_pass2.ingested_count == 0

    # Verify database counts are STRICTLY IDENTICAL (no duplicate documents or chunks)
    after_doc_count = test_db.query(Document).count()
    after_chunk_count = test_db.query(Chunk).count()

    assert after_doc_count == initial_doc_count, "Duplicate document records detected after repeated ingestion!"
    assert after_chunk_count == initial_chunk_count, "Duplicate chunk records detected after repeated ingestion!"


def test_forced_reingestion_replaces_chunks_without_duplicates(test_db: Session, sample_pdf_workspace: Path, mock_embedding_service: MockEmbeddingService):
    """Verify that force=True re-chunks and replaces existing chunks cleanly without creating duplicates."""
    manifest_service = ManifestService(base_dir=sample_pdf_workspace)
    ingestion_service = IngestionService(
        db_session=test_db,
        manifest_service=manifest_service,
        embedding_service=mock_embedding_service,
    )
    manifest_path = sample_pdf_workspace / "documents_manifest.csv"

    # Pass 1: Normal ingestion
    ingestion_service.ingest_manifest(manifest_path=manifest_path)
    initial_chunks = test_db.query(Chunk).count()

    # Pass 2: Forced re-ingestion
    report_forced = ingestion_service.ingest_manifest(manifest_path=manifest_path, force=True)
    assert report_forced.ingested_count == 2

    # Chunk count should still match exactly (old chunks deleted, new chunks inserted)
    after_forced_chunks = test_db.query(Chunk).count()
    assert after_forced_chunks == initial_chunks


def test_ingestion_with_corrupt_pdf_fails_gracefully(test_db: Session, sample_pdf_workspace: Path, mock_embedding_service: MockEmbeddingService):
    """Verify that corrupt or empty PDFs are logged and marked as failed without halting valid documents."""
    manifest_service = ManifestService(base_dir=sample_pdf_workspace)
    ingestion_service = IngestionService(
        db_session=test_db,
        manifest_service=manifest_service,
        embedding_service=mock_embedding_service,
    )

    # Append corrupt and empty PDFs to manifest
    manifest_path = sample_pdf_workspace / "mixed_manifest.csv"
    manifest_content = (
        "file,title,effective_date,supersedes,allowed_roles\n"
        "raw_pdfs/valid_doc.pdf,Valid Document,2025-01-01,,all\n"
        "raw_pdfs/corrupted.pdf,Corrupt File,2025-01-02,,admin\n"
        "raw_pdfs/empty.pdf,Empty File,2025-01-03,,admin\n"
    )
    manifest_path.write_text(manifest_content, encoding="utf-8")

    report = ingestion_service.ingest_manifest(manifest_path=manifest_path)

    assert report.total_documents == 3
    assert report.ingested_count == 1
    assert report.failed_count == 2
    assert len(report.errors) == 2

    # Ensure the valid document was still ingested properly despite the failures
    valid_doc = test_db.query(Document).filter_by(file_name="valid_doc.pdf").first()
    assert valid_doc is not None
    assert valid_doc.status == "ingested"


def test_gemini_embedding_service(monkeypatch):
    """Verify GeminiEmbeddingService formats payload and parses 768-dim embeddings."""
    from unittest.mock import MagicMock
    import httpx
    from app.services.embedding import GeminiEmbeddingService

    fake_response = MagicMock(spec=httpx.Response)
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "embeddings": [
            {"values": [0.1] * 768},
            {"values": [0.2] * 768},
        ]
    }

    mock_client = MagicMock()
    mock_client.post.return_value = fake_response
    mock_client.__enter__.return_value = mock_client
    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    gemini_emb = GeminiEmbeddingService(
        api_key="test-gemini-key",
        model="text-embedding-004",
        dimension=768,
    )
    assert gemini_emb.dimension == 768

    results = gemini_emb.embed_texts(["Text passage one", "Text passage two"])
    assert len(results) == 2
    assert len(results[0]) == 768
    assert results[0][0] == 0.1
    assert mock_client.post.called


def test_ingestion_with_semantic_embeddings(test_db: Session, sample_pdf_workspace: Path, mock_embedding_service: MockEmbeddingService):
    """Verify IngestionService automatically writes to chunks_semantic when semantic embedder is supplied."""
    from unittest.mock import MagicMock
    from app.models.chunk_semantic import ChunkSemantic

    mock_sem = MagicMock()
    mock_sem.embed_texts.side_effect = lambda texts: [[0.05] * 384 for _ in texts]

    manifest_service = ManifestService(base_dir=sample_pdf_workspace)
    ingestion_service = IngestionService(
        db_session=test_db,
        manifest_service=manifest_service,
        embedding_service=mock_embedding_service,
        semantic_embedding_service=mock_sem,
    )

    manifest_path = sample_pdf_workspace / "documents_manifest.csv"
    report = ingestion_service.ingest_manifest(manifest_path=manifest_path)

    assert report.ingested_count == 2
    chunks = test_db.query(Chunk).all()
    assert len(chunks) > 0

    sem_rows = test_db.query(ChunkSemantic).all()
    assert len(sem_rows) == len(chunks)
    assert all(len(s.embedding) == 384 for s in sem_rows)
    assert all(s.model_name == "all-MiniLM-L6-v2" for s in sem_rows)
    # Verify FK constraint integrity
    chunk_ids = {c.id for c in chunks}
    sem_chunk_ids = {s.chunk_id for s in sem_rows}
    assert sem_chunk_ids == chunk_ids
