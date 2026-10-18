"""Pytest configuration, shared fixtures, and database setup."""

import tempfile
from collections.abc import Generator
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker, Session
from fastapi.testclient import TestClient
from app.main import app
from app.models import Base
from app.core.config import settings
from app.services.embedding import MockEmbeddingService
from tests.helpers import write_test_pdf

# Ensure unit/integration test isolation
settings.APP_ENV = "test"


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    """Provide a TestClient instance for API tests."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="function")
def test_db() -> Generator[Session, None, None]:
    """Provide an isolated in-memory SQLite database session for unit tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def mock_embedding_service() -> MockEmbeddingService:
    """Provide deterministic mock embedding service for tests."""
    return MockEmbeddingService(dimension=1536)


@pytest.fixture(scope="function")
def sample_pdf_workspace() -> Generator[Path, None, None]:
    """Create a temporary directory with valid, multi-page, empty, and corrupted PDFs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        raw_dir = base / "raw_pdfs"
        raw_dir.mkdir(parents=True, exist_ok=True)

        # 1. Valid multi-page document
        write_test_pdf(
            raw_dir / "valid_doc.pdf",
            [
                "Page 1: Overview of corporate architecture and mission.",
                "Page 2: Standard operating procedures and safety regulations.",
                "Page 3: Guidelines on confidential data retention and encryption.",
            ],
        )

        # 2. Document with superseding metadata
        write_test_pdf(
            raw_dir / "policy_v2.pdf",
            [
                "Page 1: Policy v2 superseding 2023 regulations with updated AI usage guidelines.",
                "Page 2: Enforcement mechanisms and escalation paths.",
            ],
        )

        # 3. Corrupted PDF
        corrupt_path = raw_dir / "corrupted.pdf"
        with open(corrupt_path, "wb") as f:
            f.write(b"%PDF-1.4\nCorrupted binary data that cannot be parsed as a PDF\n%%EOF")

        # 4. Zero-byte empty file
        empty_path = raw_dir / "empty.pdf"
        empty_path.touch()

        # 5. Manifest CSV
        manifest_path = base / "documents_manifest.csv"
        manifest_content = (
            "file,title,effective_date,supersedes,allowed_roles\n"
            "raw_pdfs/valid_doc.pdf,Corporate Architecture,2025-01-15,,engineering;admin;student;faculty\n"
            "raw_pdfs/policy_v2.pdf,Policy V2,2025-06-01,Policy V1,legal;security;executive;student;faculty;admin\n"
        )
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(manifest_content)

        yield base
