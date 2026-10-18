"""Tests for Phase 4: Version-Aware Answers, Graph Validation, Conflict Detection, and Invariant Preservation."""

import datetime
import tempfile
from pathlib import Path
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import get_db
from app.models.document import Document
from app.models.chunk import Chunk
from app.services.versioning import (
    DocumentVersionService,
    DocumentVersionStatus,
    MissingSupersedesTargetError,
    CircularVersionError,
    TemporalOrderError,
)
from app.services.manifest import ManifestService
from app.services.ingestion import IngestionService
from app.services.embedding import MockEmbeddingService
from tests.helpers import write_test_pdf


@pytest.fixture(autouse=True)
def cleanup_overrides():
    """Ensure FastAPI dependency overrides are cleanly restored after each test."""
    yield
    app.dependency_overrides.clear()


# ============================================================================
# 1. Unit Tests for Version Graph Validation & Cycle Detection
# ============================================================================

def test_version_graph_valid_multi_version_lineage():
    """Verify building version graph correctly establishes successor, predecessor, and rank."""
    service = DocumentVersionService()
    docs = [
        Document(
            id="doc-1",
            file_name="policy_v1.pdf",
            title="Remote Work Policy 2023",
            effective_date=datetime.date(2023, 1, 1),
            supersedes=None,
        ),
        Document(
            id="doc-2",
            file_name="policy_v2.pdf",
            title="Remote Work Policy 2024",
            effective_date=datetime.date(2024, 1, 1),
            supersedes="Remote Work Policy 2023",
        ),
        Document(
            id="doc-3",
            file_name="policy_v3.pdf",
            title="Remote Work Policy 2025",
            effective_date=datetime.date(2025, 1, 1),
            supersedes="Remote Work Policy 2024",
        ),
    ]

    statuses = service.build_version_graph(docs, strict_validation=True)

    # v1 is superseded by v2
    assert statuses["doc-1"].is_superseded is True
    assert statuses["doc-1"].superseded_by_title == "Remote Work Policy 2024"
    assert statuses["doc-1"].version_rank == 1

    # v2 is superseded by v3
    assert statuses["doc-2"].is_superseded is True
    assert statuses["doc-2"].superseded_by_title == "Remote Work Policy 2025"
    assert statuses["doc-2"].version_rank == 2

    # v3 is the current terminal version
    assert statuses["doc-3"].is_superseded is False
    assert statuses["doc-3"].superseded_by_title is None
    assert statuses["doc-3"].version_rank == 3


def test_version_graph_detects_missing_supersedes_target():
    """Verify strict validation raises MissingSupersedesTargetError when target document is absent."""
    service = DocumentVersionService()
    docs = [
        Document(
            id="doc-1",
            file_name="policy_v2.pdf",
            title="Remote Work Policy 2024",
            effective_date=datetime.date(2024, 1, 1),
            supersedes="NonExistentPolicy2020",
        )
    ]

    with pytest.raises(MissingSupersedesTargetError) as exc_info:
        service.build_version_graph(docs, strict_validation=True)
    assert "does not exist in the collection" in str(exc_info.value)


def test_version_graph_detects_circular_version_dependency():
    """Verify strict validation raises CircularVersionError on cyclic supersedes relationships."""
    service = DocumentVersionService()
    docs = [
        Document(
            id="doc-a",
            file_name="doc_a.pdf",
            title="Policy Alpha",
            effective_date=datetime.date(2024, 1, 1),
            supersedes="Policy Beta",
        ),
        Document(
            id="doc-b",
            file_name="doc_b.pdf",
            title="Policy Beta",
            effective_date=datetime.date(2024, 1, 1),
            supersedes="Policy Alpha",
        ),
    ]

    with pytest.raises(CircularVersionError) as exc_info:
        service.build_version_graph(docs, strict_validation=True)
    assert "Circular document version relationship detected" in str(exc_info.value)


def test_version_graph_detects_temporal_order_violation():
    """Verify strict validation raises TemporalOrderError if older document claims to supersede newer."""
    service = DocumentVersionService()
    docs = [
        Document(
            id="doc-new",
            file_name="new_policy.pdf",
            title="Security Guidelines 2025",
            effective_date=datetime.date(2025, 6, 1),
            supersedes=None,
        ),
        Document(
            id="doc-old",
            file_name="old_policy.pdf",
            title="Security Guidelines 2023",
            effective_date=datetime.date(2023, 1, 1),
            supersedes="Security Guidelines 2025",
        ),
    ]

    with pytest.raises(TemporalOrderError) as exc_info:
        service.build_version_graph(docs, strict_validation=True)
    assert "Temporal violation" in str(exc_info.value)


# ============================================================================
# 2. Integration Tests with Synthetic Documents & Manifest
# ============================================================================

@pytest.fixture
def synthetic_policy_corpus(test_db: Session, mock_embedding_service: MockEmbeddingService):
    """Create a temporary directory with synthetic policy documents and ingest into test_db."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        raw_dir = base / "raw_pdfs"
        raw_dir.mkdir(parents=True, exist_ok=True)

        # 1. Old Remote Work Policy v1 (1 day per week)
        write_test_pdf(
            raw_dir / "remote_work_policy_v1.pdf",
            [
                "Page 1: Remote Work Policy 2023. Employees are permitted to work remotely 1 day per week. Core office hours are 9am to 5pm.",
            ],
        )

        # 2. Amended Remote Work Policy v2 (3 days per week, supersedes v1)
        write_test_pdf(
            raw_dir / "remote_work_policy_v2.pdf",
            [
                "Page 1: Remote Work Policy 2024. Employees are permitted to work remotely 3 days per week. Remote work equipment stipend is $500.",
            ],
        )

        # 3. Unrelated newer policy: Travel Expense Policy 2025 ($75 meal allowance)
        write_test_pdf(
            raw_dir / "travel_expense_policy.pdf",
            [
                "Page 1: Travel Expense Policy 2025. Standard meal allowance during business travel is $75 per day.",
            ],
        )

        # 4. Unrelated older policy: Corporate Core Values (eff 2022, missing supersedes metadata)
        write_test_pdf(
            raw_dir / "core_values_guide.pdf",
            [
                "Page 1: Corporate Core Values. Our core values are integrity, innovation, and customer dedication.",
            ],
        )

        # Manifest defining explicit version relationships
        manifest_path = base / "documents_manifest.csv"
        manifest_content = (
            "file,title,effective_date,supersedes,allowed_roles\n"
            "raw_pdfs/remote_work_policy_v1.pdf,Remote Work Policy 2023,2023-01-01,,all\n"
            "raw_pdfs/remote_work_policy_v2.pdf,Remote Work Policy 2024,2024-01-01,Remote Work Policy 2023,all\n"
            "raw_pdfs/travel_expense_policy.pdf,Travel Expense Policy 2025,2025-05-01,,all\n"
            "raw_pdfs/core_values_guide.pdf,Corporate Core Values,2022-01-01,,all\n"
        )
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(manifest_content)

        manifest_service = ManifestService(base_dir=base)
        ingestion_service = IngestionService(
            db_session=test_db,
            manifest_service=manifest_service,
            embedding_service=mock_embedding_service,
        )
        ingestion_service.ingest_manifest(manifest_path=manifest_path)

        yield {
            "db": test_db,
            "base_dir": base,
        }


def test_amended_policy_explains_current_first_and_identifies_superseded(
    client: TestClient, synthetic_policy_corpus: dict
):
    """Verify that a question about an amended policy returns current value first and identifies superseded policy."""
    app.dependency_overrides[get_db] = lambda: synthetic_policy_corpus["db"]

    payload = {
        "question": "How many days per week are employees permitted to work remotely?",
        "top_k": 10,
        "top_n": 4,
        "version_aware": True,
    }

    response = client.post("/ask", json=payload)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert not data["abstained"]
    assert data["has_policy_conflict"] is True
    assert data["conflict_details"] is not None
    assert len(data["conflict_details"]) == 1

    conflict = data["conflict_details"][0]
    assert conflict["current_title"] == "Remote Work Policy 2024"
    assert conflict["current_effective_date"] == "2024-01-01"
    assert conflict["current_file"] == "remote_work_policy_v2.pdf"
    assert conflict["superseded_title"] == "Remote Work Policy 2023"
    assert conflict["superseded_effective_date"] == "2023-01-01"
    assert conflict["superseded_file"] == "remote_work_policy_v1.pdf"

    # Answer must explain current policy first and identify superseded policy second
    answer = data["answer"]
    assert "Under the current policy (effective 2024-01-01)" in answer
    assert "3 days per week" in answer
    assert "[1]" in answer
    assert "supersedes the previous policy (effective 2023-01-01)" in answer
    assert "1 day per week" in answer
    assert "[2]" in answer

    # Citations must link to both documents with page 1
    cited_files = {c["file_name"] for c in data["citations"]}
    assert "remote_work_policy_v2.pdf" in cited_files
    assert "remote_work_policy_v1.pdf" in cited_files
    for c in data["citations"]:
        assert c["page_number"] == 1


def test_unrelated_newer_document_does_not_supersede_older_document(
    client: TestClient, synthetic_policy_corpus: dict
):
    """Verify that a newer document (Travel Expense 2025) does NOT globally supersede unrelated older docs (Core Values 2022)."""
    app.dependency_overrides[get_db] = lambda: synthetic_policy_corpus["db"]

    payload = {
        "question": "What are the core values of the corporation?",
        "top_k": 10,
        "top_n": 3,
        "version_aware": True,
    }

    response = client.post("/ask", json=payload)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert not data["abstained"]
    # No conflict: Core values is not superseded by anything
    assert data["has_policy_conflict"] is False
    assert data["conflict_details"] is None

    # The response must cite core_values_guide.pdf
    assert any(c["file_name"] == "core_values_guide.pdf" for c in data["citations"])
    assert "integrity" in data["answer"].lower()
    # Must NOT claim that Travel Expense Policy supersedes core values
    assert "supersedes" not in data["answer"].lower()


def test_unrelated_newer_policy_cited_without_false_superseding(
    client: TestClient, synthetic_policy_corpus: dict
):
    """Verify query about Travel Expense Policy returns the $75 allowance without conflict."""
    app.dependency_overrides[get_db] = lambda: synthetic_policy_corpus["db"]

    payload = {
        "question": "What is the standard meal allowance during business travel?",
        "top_k": 5,
        "top_n": 2,
        "version_aware": True,
    }

    response = client.post("/ask", json=payload)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert not data["abstained"]
    assert data["has_policy_conflict"] is False
    assert data["conflict_details"] is None

    assert any(c["file_name"] == "travel_expense_policy.pdf" for c in data["citations"])
    assert "$75" in data["answer"]


def test_version_aware_toggle_ablation(
    client: TestClient, synthetic_policy_corpus: dict
):
    """Verify toggling version_aware=False suppresses conflict detection, while version_aware=True enables it."""
    app.dependency_overrides[get_db] = lambda: synthetic_policy_corpus["db"]

    question = "How many days per week are employees permitted to work remotely?"

    # 1. Ablation: version_aware disabled
    resp_disabled = client.post(
        "/ask",
        json={"question": question, "top_k": 10, "top_n": 4, "version_aware": False},
    )
    assert resp_disabled.status_code == status.HTTP_200_OK
    data_disabled = resp_disabled.json()
    assert data_disabled["has_policy_conflict"] is False
    assert data_disabled["conflict_details"] is None

    # 2. Evaluation: version_aware enabled
    resp_enabled = client.post(
        "/ask",
        json={"question": question, "top_k": 10, "top_n": 4, "version_aware": True},
    )
    assert resp_enabled.status_code == status.HTTP_200_OK
    data_enabled = resp_enabled.json()
    assert data_enabled["has_policy_conflict"] is True
    assert data_enabled["conflict_details"] is not None


def test_historical_content_and_citations_preserved(
    synthetic_policy_corpus: dict
):
    """Verify superseded documents and their chunks remain in the database without deletion."""
    db: Session = synthetic_policy_corpus["db"]

    v1_doc = db.query(Document).filter(Document.file_name == "remote_work_policy_v1.pdf").first()
    assert v1_doc is not None
    assert v1_doc.title == "Remote Work Policy 2023"

    v1_chunks = db.query(Chunk).filter(Chunk.document_id == v1_doc.id).all()
    assert len(v1_chunks) > 0
    assert "1 day per week" in v1_chunks[0].text
