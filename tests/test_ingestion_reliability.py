"""Comprehensive database reliability and ingestion behavior tests.

Tests verify:
1. Idempotent re-ingestion: re-ingesting documents produces zero duplicate rows.
2. Version replacement and lineage: older document chunks are marked superseded (valid_to set),
   never deleted, and lineage records link predecessor to successor.
3. Transactional atomic rollback: failure during ingestion rolls back completely, leaving
   zero orphaned documents or dangling chunks.
"""

import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, Chunk, DocumentLineage
from app.services.ingestion import IngestionService
from app.services.chunker import ChunkerService
from app.services.manifest import ManifestService
from app.services.embedding import MockEmbeddingService
from app.services.pdf_parser import PDFParserService, ParsedPDF, PageData
from pathlib import Path


@pytest.fixture
def clean_db() -> Session:
    """Create an isolated in-memory SQLite database session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionMaker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionMaker()
    try:
        yield session
    finally:
        session.close()


class MockPDFParser(PDFParserService):
    """Mock parser that returns controlled parsed PDF structures."""

    def __init__(self, pages_text: list[str], file_hash: str = "hash_v1"):
        super().__init__()
        self.pages_text = pages_text
        self.file_hash = file_hash

    def parse_pdf(self, path) -> ParsedPDF:
        pages = [
            PageData(page_number=i + 1, text=t, char_count=len(t))
            for i, t in enumerate(self.pages_text)
        ]
        p = Path(path)
        return ParsedPDF(
            file_name=p.name,
            file_path=p,
            file_hash=self.file_hash,
            total_pages=len(pages),
            pages=pages,
        )


class MockFailingEmbedder(MockEmbeddingService):
    """Mock embedder that simulates an unexpected failure."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Simulated embedding service outage or connection reset")


def test_idempotent_reingestion_produces_no_duplicate_chunks(clean_db: Session, tmp_path):
    """Verify that running ingestion on identical file twice produces zero duplicates."""
    pdf_file = tmp_path / "academic_regulations_2024.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 mock content")

    manifest_file = tmp_path / "manifest.csv"
    manifest_file.write_text(
        "file,title,effective_date,supersedes,allowed_roles\n"
        f"{pdf_file.name},KVIT Academic Regulations,2024-07-01,,all\n",
        encoding="utf-8",
    )

    parser = MockPDFParser(
        pages_text=["Clause 1.0 General rules for B.Tech.", "Clause 2.0 Attendance requirement is 80%."],
        file_hash="hash_2024_abc",
    )
    manifest_service = ManifestService(base_dir=tmp_path)
    chunker = ChunkerService(chunk_size_tokens=100, chunk_overlap_tokens=0)
    embedder = MockEmbeddingService(dimension=1536)

    service = IngestionService(
        db_session=clean_db,
        manifest_service=manifest_service,
        pdf_parser=parser,
        chunker=chunker,
        embedding_service=embedder,
    )

    # 1. First ingestion run
    report1 = service.ingest_manifest(manifest_file)
    assert report1.ingested_count == 1
    assert report1.skipped_count == 0
    assert report1.total_chunks_created == 2

    assert clean_db.query(Document).count() == 1
    assert clean_db.query(Chunk).count() == 2

    # 2. Second ingestion run (idempotency check)
    report2 = service.ingest_manifest(manifest_file)
    assert report2.ingested_count == 0
    assert report2.skipped_count == 1
    assert report2.failed_count == 0

    # Counts must remain identical
    assert clean_db.query(Document).count() == 1
    assert clean_db.query(Chunk).count() == 2


def test_version_replacement_preserves_lineage_and_supersedes_chunks(clean_db: Session, tmp_path):
    """Verify that replacing a document marks predecessor superseded without deleting old chunks."""
    # Create two versions of policy PDF
    pdf_v1 = tmp_path / "attendance_rules_2024.pdf"
    pdf_v1.write_bytes(b"%PDF-1.4 v1 content")
    pdf_v2 = tmp_path / "attendance_rules_2025.pdf"
    pdf_v2.write_bytes(b"%PDF-1.4 v2 content")

    manifest_file = tmp_path / "manifest.csv"
    manifest_file.write_text(
        "file,title,effective_date,supersedes,allowed_roles\n"
        f"{pdf_v1.name},Attendance Policy 2024,2024-07-01,,student;faculty;admin\n"
        f"{pdf_v2.name},Attendance Policy 2025,2025-07-01,Attendance Policy 2024,student;faculty;admin\n",
        encoding="utf-8",
    )

    lineage_file = tmp_path / "supersession_register.csv"
    lineage_file.write_text(
        "old_file,new_file,scope,effective_date,evidence_page,evidence_text\n"
        f"{pdf_v1.name},{pdf_v2.name},full,2025-07-01,1,This policy fully replaces Attendance Policy 2024\n",
        encoding="utf-8",
    )

    manifest_service = ManifestService(base_dir=tmp_path)
    chunker = ChunkerService(chunk_size_tokens=100, chunk_overlap_tokens=0)
    embedder = MockEmbeddingService(dimension=1536)

    # Ingest v1
    parser_v1 = MockPDFParser(["Clause 4.1 Minimum attendance is 80%."], file_hash="hash_v1")
    service1 = IngestionService(
        db_session=clean_db,
        manifest_service=manifest_service,
        pdf_parser=parser_v1,
        chunker=chunker,
        embedding_service=embedder,
    )
    service1.ingest_manifest(manifest_file)

    # Ingest v2 + supersession register
    parser_v2 = MockPDFParser(["Clause 4.1 Minimum attendance revised to 75%."], file_hash="hash_v2")
    service2 = IngestionService(
        db_session=clean_db,
        manifest_service=manifest_service,
        pdf_parser=parser_v2,
        chunker=chunker,
        embedding_service=embedder,
    )
    service2.ingest_manifest(manifest_file, lineage_path=lineage_file)

    # Invariants Verification:
    # 1. Total documents is 2 (both preserved)
    assert clean_db.query(Document).count() == 2

    doc_v1 = clean_db.query(Document).filter(Document.file_name == pdf_v1.name).first()
    doc_v2 = clean_db.query(Document).filter(Document.file_name == pdf_v2.name).first()

    assert doc_v1.status == "superseded"
    assert doc_v1.expires_date == date(2025, 7, 1)

    assert doc_v2.status == "current"
    assert doc_v2.supersedes_doc_id == doc_v1.id

    # 2. Total chunks is 2 (old chunks preserved, not deleted)
    assert clean_db.query(Chunk).count() == 2

    chunk_v1 = clean_db.query(Chunk).filter(Chunk.document_id == doc_v1.id).first()
    chunk_v2 = clean_db.query(Chunk).filter(Chunk.document_id == doc_v2.id).first()

    assert chunk_v1.status == "superseded"
    assert chunk_v1.valid_to == date(2025, 7, 1)

    assert chunk_v2.status == "current"
    assert chunk_v2.valid_from == date(2025, 7, 1)
    assert chunk_v2.valid_to is None

    # 3. Lineage record exists
    lineage = clean_db.query(DocumentLineage).first()
    assert lineage is not None
    assert lineage.old_doc_id == doc_v1.id
    assert lineage.new_doc_id == doc_v2.id
    assert lineage.scope == "full"


def test_failed_ingestion_rolls_back_atomically(clean_db: Session, tmp_path):
    """Verify that a failure during ingestion rolls back completely, leaving zero orphaned records."""
    pdf_file = tmp_path / "corrupted_policy.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 broken content")

    manifest_file = tmp_path / "manifest.csv"
    manifest_file.write_text(
        "file,title,effective_date,supersedes,allowed_roles\n"
        f"{pdf_file.name},Corrupted Document,2025-01-01,,all\n",
        encoding="utf-8",
    )

    manifest_service = ManifestService(base_dir=tmp_path)
    chunker = ChunkerService(chunk_size_tokens=100, chunk_overlap_tokens=0)
    parser = MockPDFParser(["Some text before crash"], file_hash="crash_hash")
    failing_embedder = MockFailingEmbedder()

    service = IngestionService(
        db_session=clean_db,
        manifest_service=manifest_service,
        pdf_parser=parser,
        chunker=chunker,
        embedding_service=failing_embedder,
    )

    report = service.ingest_manifest(manifest_file)
    assert report.failed_count == 1
    assert report.ingested_count == 0

    # Verify zero orphaned documents, chunks, or lineage
    assert clean_db.query(Document).count() == 0
    assert clean_db.query(Chunk).count() == 0
    assert clean_db.query(DocumentLineage).count() == 0
