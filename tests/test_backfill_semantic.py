"""Unit tests for the semantic embedding backfill script (Phase 5.2B).

These tests run strictly in an isolated in-memory SQLite database or mock environment.
Under no circumstances do they modify the live PostgreSQL database.
"""

import datetime as dt
import math
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.chunk import Chunk
from app.models.chunk_semantic import ChunkSemantic
from scripts.backfill_semantic_embeddings import (
    verify_model_checksum,
    validate_embedding_vector,
    prepare_semantic_records,
    reconcile_database_state,
    execute_backfill,
    ChecksumMismatchError,
    BackfillValidationError,
    BackfillStateError,
    EXPECTED_DIMENSION,
    EXPECTED_ONNX_SHA256,
)


class Mock384EmbeddingService:
    """Mock service returning deterministic 384-dimensional unit-norm vectors."""

    def __init__(self, dimension: int = 384, inject_nan: bool = False):
        self.dimension = dimension
        self.inject_nan = inject_nan

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for i, text in enumerate(texts):
            if self.inject_nan:
                vec = [float("nan")] * self.dimension
            else:
                # Deterministic normalized dummy floats
                raw = [(float(hash(text + str(idx)) % 1000) / 1000.0) for idx in range(self.dimension)]
                norm = math.sqrt(sum(x * x for x in raw)) or 1.0
                vec = [round(x / norm, 6) for x in raw]
            embeddings.append(vec)
        return embeddings


def create_dummy_doc_and_chunks(db: Session, num_chunks: int = 3) -> tuple[Document, list[Chunk]]:
    """Helper to seed dummy document and chunks in test database."""
    doc = Document(
        id="doc-test-1",
        file_name="test_policy.pdf",
        file_hash="hash_123",
        title="Test Policy",
        effective_date=dt.date(2025, 1, 1),
        allowed_roles=["student", "faculty"],
        total_pages=1,
        total_chunks=num_chunks,
    )
    db.add(doc)
    db.flush()

    chunks = []
    for i in range(num_chunks):
        chk = Chunk(
            id=f"chunk-test-{i+1}",
            document_id=doc.id,
            chunk_index=i,
            page_number=1,
            text=f"Test clause section {i+1} policy text content.",
            token_count=10,
            embedding=[0.0] * 1536,
        )
        db.add(chk)
        chunks.append(chk)
    db.commit()
    return doc, chunks


# =========================================================================
# 1. Model Checksum Verification Tests
# =========================================================================

def test_verify_model_checksum_valid(tmp_path: Path):
    """Verify checksum passes when file content matches expected SHA-256."""
    dummy_file = tmp_path / "model.onnx"
    dummy_content = b"model binary payload"
    dummy_file.write_bytes(dummy_content)

    import hashlib
    expected_sha = hashlib.sha256(dummy_content).hexdigest()

    assert verify_model_checksum(dummy_file, expected_sha=expected_sha) is True


def test_verify_model_checksum_mismatch(tmp_path: Path):
    """Verify ChecksumMismatchError is raised if SHA-256 does not match."""
    dummy_file = tmp_path / "model.onnx"
    dummy_file.write_bytes(b"corrupted model content")

    with pytest.raises(ChecksumMismatchError, match="Model SHA256 checksum mismatch"):
        verify_model_checksum(dummy_file, expected_sha=EXPECTED_ONNX_SHA256)


def test_verify_model_checksum_missing_file(tmp_path: Path):
    """Verify FileNotFoundError is raised if model file is missing."""
    missing_file = tmp_path / "non_existent.onnx"
    with pytest.raises(FileNotFoundError, match="ONNX model file not found"):
        verify_model_checksum(missing_file)


# =========================================================================
# 2. Vector Validation Tests
# =========================================================================

def test_validate_embedding_vector_valid():
    """Verify valid 384-dimensional finite vector passes validation."""
    valid_vec = [0.05] * EXPECTED_DIMENSION
    validate_embedding_vector(valid_vec, "chunk-1")  # Should not raise


@pytest.mark.parametrize("wrong_dim", [1536, 128, 0, 383, 385])
def test_validate_embedding_vector_dimension_mismatch(wrong_dim: int):
    """Verify BackfillValidationError is raised on dimension mismatch."""
    vec = [0.1] * wrong_dim
    with pytest.raises(BackfillValidationError, match="produced embedding of dimension"):
        validate_embedding_vector(vec, "chunk-1")


def test_validate_embedding_vector_non_finite():
    """Verify BackfillValidationError is raised when NaN or Inf is present."""
    nan_vec = [0.1] * (EXPECTED_DIMENSION - 1) + [float("nan")]
    with pytest.raises(BackfillValidationError, match="produced non-finite"):
        validate_embedding_vector(nan_vec, "chunk-nan")

    inf_vec = [0.1] * (EXPECTED_DIMENSION - 1) + [float("inf")]
    with pytest.raises(BackfillValidationError, match="produced non-finite"):
        validate_embedding_vector(inf_vec, "chunk-inf")


# =========================================================================
# 3. Candidate Preparation Tests
# =========================================================================

def test_prepare_semantic_records_duplicate_chunk_id():
    """Verify duplicate chunk IDs in candidate set are rejected immediately."""
    chk1 = Chunk(id="chunk-same", text="Passage 1", token_count=5, page_number=1, chunk_index=0)
    chk2 = Chunk(id="chunk-same", text="Passage 2", token_count=5, page_number=1, chunk_index=1)

    service = Mock384EmbeddingService()
    with pytest.raises(BackfillValidationError, match="Duplicate chunk_id encountered"):
        prepare_semantic_records([chk1, chk2], service)


def test_prepare_semantic_records_success():
    """Verify candidate preparation correctly builds valid ChunkSemantic records."""
    chk1 = Chunk(id="chk-1", text="Clause A", token_count=5, page_number=1, chunk_index=0)
    chk2 = Chunk(id="chk-2", text="Clause B", token_count=5, page_number=1, chunk_index=1)

    service = Mock384EmbeddingService()
    records = prepare_semantic_records([chk1, chk2], service)

    assert len(records) == 2
    assert records[0].chunk_id == "chk-1"
    assert len(records[0].embedding) == 384
    assert records[0].model_name == "all-MiniLM-L6-v2"
    assert records[1].chunk_id == "chk-2"


# =========================================================================
# 4. Read-Only Reconciliation Tests
# =========================================================================

def test_reconcile_database_state(test_db: Session):
    """Verify read-only reconciliation reports accurate counts and diagnostic diffs."""
    doc, chunks = create_dummy_doc_and_chunks(test_db, num_chunks=3)

    # Initially 0 semantic rows
    diag = reconcile_database_state(test_db)
    assert diag["total_chunks"] == 3
    assert diag["total_semantic_rows"] == 0
    assert diag["missing_semantic_count"] == 3
    assert diag["orphan_semantic_count"] == 0

    # Add 1 semantic row
    sem1 = ChunkSemantic(
        id="sem-1",
        chunk_id=chunks[0].id,
        embedding=[0.1] * 384,
        model_name="all-MiniLM-L6-v2",
    )
    test_db.add(sem1)
    test_db.commit()

    diag2 = reconcile_database_state(test_db)
    assert diag2["total_semantic_rows"] == 1
    assert diag2["missing_semantic_count"] == 2
    assert chunks[0].id not in diag2["missing_chunk_ids"]
    assert chunks[1].id in diag2["missing_chunk_ids"]


# =========================================================================
# 5. Execution, Idempotency, and Failure Recovery Tests
# =========================================================================

def test_execute_backfill_clean_success(test_db: Session):
    """Verify clean full backfill inserts expected records into test_db."""
    doc, chunks = create_dummy_doc_and_chunks(test_db, num_chunks=3)
    service = Mock384EmbeddingService()

    result = execute_backfill(
        session=test_db,
        embedding_service=service,
        verify_checksum=False,
    )

    assert result["status"] == "success"
    assert result["rows_inserted"] == 3
    assert result["final_semantic_count"] == 3

    # Verify rows in DB
    stored = test_db.query(ChunkSemantic).all()
    assert len(stored) == 3
    assert {s.chunk_id for s in stored} == {c.id for c in chunks}


def test_execute_backfill_already_complete_idempotent(test_db: Session):
    """Verify executing backfill on already fully backfilled DB is a safe no-op."""
    doc, chunks = create_dummy_doc_and_chunks(test_db, num_chunks=2)
    service = Mock384EmbeddingService()

    # Initial backfill
    execute_backfill(test_db, embedding_service=service, verify_checksum=False)

    # Re-run
    rerun_result = execute_backfill(test_db, embedding_service=service, verify_checksum=False)
    assert rerun_result["status"] == "already_complete"
    assert rerun_result["rows_inserted"] == 0
    assert rerun_result["final_semantic_count"] == 2


def test_execute_backfill_unexpected_partial_rows_halts_safely(test_db: Session):
    """Verify partial pre-existing rows raise BackfillStateError without allow_resume."""
    doc, chunks = create_dummy_doc_and_chunks(test_db, num_chunks=3)

    # Insert 1 pre-existing row
    test_db.add(ChunkSemantic(
        id="sem-existing",
        chunk_id=chunks[0].id,
        embedding=[0.1] * 384,
        model_name="all-MiniLM-L6-v2",
    ))
    test_db.commit()

    service = Mock384EmbeddingService()
    with pytest.raises(BackfillStateError, match="Unexpected partial state detected: 1/3 chunks"):
        execute_backfill(test_db, embedding_service=service, verify_checksum=False, allow_resume=False)

    # Confirm existing row was not touched or deleted
    assert test_db.query(ChunkSemantic).count() == 1


def test_execute_backfill_allow_resume_succeeds(test_db: Session):
    """Verify backfill resumes safely when allow_resume=True."""
    doc, chunks = create_dummy_doc_and_chunks(test_db, num_chunks=3)

    test_db.add(ChunkSemantic(
        id="sem-existing",
        chunk_id=chunks[0].id,
        embedding=[0.1] * 384,
        model_name="all-MiniLM-L6-v2",
    ))
    test_db.commit()

    service = Mock384EmbeddingService()
    result = execute_backfill(
        test_db,
        embedding_service=service,
        verify_checksum=False,
        allow_resume=True,
    )

    assert result["status"] == "success"
    assert result["rows_inserted"] == 2
    assert result["final_semantic_count"] == 3


def test_execute_backfill_transaction_failure_triggers_clean_rollback(test_db: Session):
    """Verify any exception inside the transaction cleanly rolls back all staged inserts."""
    doc, chunks = create_dummy_doc_and_chunks(test_db, num_chunks=3)
    service = Mock384EmbeddingService()

    # We simulate a failure in pre-commit verification by patching session.query
    original_query = test_db.query

    def failing_query(entity, *args, **kwargs):
        if entity is ChunkSemantic:
            # First query is in inspect state, second in in-transaction count verification
            # Let it fail during pre-commit count verification
            mock_q = original_query(entity, *args, **kwargs)
            return mock_q
        return original_query(entity, *args, **kwargs)

    # Simulate an error by forcing a commit failure via a mock flush error
    with patch.object(test_db, "commit", side_effect=RuntimeError("Simulated DB commit error")):
        with pytest.raises(RuntimeError, match="Simulated DB commit error"):
            execute_backfill(test_db, embedding_service=service, verify_checksum=False)

    # After rollback, chunks_semantic must have 0 rows
    assert test_db.query(ChunkSemantic).count() == 0
    # Original chunks and document must remain intact
    assert test_db.query(Chunk).count() == 3
    assert test_db.query(Document).count() == 1


# =========================================================================
# 6. Pre-Existing Row Validation & Resume Safeguard Tests
# =========================================================================

def test_resume_mode_rejects_corrupted_model_name(test_db: Session):
    """Verify resume mode halts if an existing row has an unexpected model name."""
    doc, chunks = create_dummy_doc_and_chunks(test_db, num_chunks=3)

    test_db.add(ChunkSemantic(
        id="sem-bad-model",
        chunk_id=chunks[0].id,
        embedding=[0.1] * 384,
        model_name="wrong-model-v1",
    ))
    test_db.commit()

    service = Mock384EmbeddingService()
    with pytest.raises(BackfillStateError, match="unexpected model_name 'wrong-model-v1'"):
        execute_backfill(test_db, embedding_service=service, verify_checksum=False, allow_resume=True)


def test_resume_mode_rejects_corrupted_dimension(test_db: Session):
    """Verify resume mode halts if an existing row has an incorrect vector dimension."""
    doc, chunks = create_dummy_doc_and_chunks(test_db, num_chunks=3)

    test_db.add(ChunkSemantic(
        id="sem-bad-dim",
        chunk_id=chunks[0].id,
        embedding=[0.1] * 128,  # invalid dimension
        model_name="all-MiniLM-L6-v2",
    ))
    test_db.commit()

    service = Mock384EmbeddingService()
    with pytest.raises(BackfillStateError, match="failed vector validation"):
        execute_backfill(test_db, embedding_service=service, verify_checksum=False, allow_resume=True)


def test_resume_mode_rejects_orphan_semantic_row(test_db: Session):
    """Verify resume mode halts if an existing row references a non-existent chunk."""
    doc, chunks = create_dummy_doc_and_chunks(test_db, num_chunks=2)

    test_db.add(ChunkSemantic(
        id="sem-orphan",
        chunk_id="chunk-non-existent-999",
        embedding=[0.1] * 384,
        model_name="all-MiniLM-L6-v2",
    ))
    test_db.commit()

    service = Mock384EmbeddingService()
    with pytest.raises(BackfillStateError, match="Orphan semantic record detected"):
        execute_backfill(test_db, embedding_service=service, verify_checksum=False, allow_resume=True)


def test_execute_backfill_rejects_semantic_row_count_exceeding_chunks(test_db: Session):
    """Verify anomaly detection when semantic rows exceed total chunks."""
    doc, chunks = create_dummy_doc_and_chunks(test_db, num_chunks=1)

    test_db.add(ChunkSemantic(id="sem-1", chunk_id=chunks[0].id, embedding=[0.1] * 384))
    test_db.add(ChunkSemantic(id="sem-extra", chunk_id="orphan-id", embedding=[0.1] * 384))
    test_db.commit()

    service = Mock384EmbeddingService()
    with pytest.raises(BackfillStateError, match="Database anomaly detected"):
        execute_backfill(test_db, embedding_service=service, verify_checksum=False)
