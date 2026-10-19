"""Deterministic Semantic Embedding Backfill Script for Phase 5.2B.

Generates 384-dimensional dense semantic vectors using the local ONNX all-MiniLM-L6-v2
embedding model and writes them into `chunks_semantic`.

SAFEGUARDS:
- Model checksum verification before inference.
- Embeddings for all eligible chunks computed and validated in memory before opening write transaction.
- Single atomic transaction: inserts full set and validates row count before commit.
- Immediate rollback on any exception; zero partial rows persisted.
- Detects unexpected partial pre-existing rows and halts safely without overwriting.
- Strictly read-only on `documents` and `chunks`; never modifies `chunks.embedding`.
- No automatic table drops or deletions.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

# Ensure project root is in sys.path for direct CLI invocation
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine
from app.models.chunk import Chunk
from app.models.chunk_semantic import ChunkSemantic
from app.services.embedding_onnx import ONNXEmbeddingService

logger = logging.getLogger("backfill_semantic")

EXPECTED_ONNX_SHA256 = "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452"
DEFAULT_MODEL_PATH = Path("models/embeddings/all-MiniLM-L6-v2/model.onnx")
EXPECTED_DIMENSION = 384


class BackfillError(Exception):
    """Base exception for backfill errors."""


class ChecksumMismatchError(BackfillError):
    """Raised when ONNX model file fails integrity checksum verification."""


class BackfillValidationError(BackfillError):
    """Raised when computed embeddings fail shape, finiteness, or chunk_id validation."""


class BackfillStateError(BackfillError):
    """Raised when unexpected pre-existing rows or uncertain state is detected."""


def verify_model_checksum(
    model_path: Path = DEFAULT_MODEL_PATH,
    expected_sha: str = EXPECTED_ONNX_SHA256,
) -> bool:
    """Verify SHA-256 hash of the local ONNX model file.

    Args:
        model_path: Path to model.onnx.
        expected_sha: Expected SHA-256 hexadecimal string.

    Returns:
        True if checksum matches.

    Raises:
        FileNotFoundError: If model_path does not exist.
        ChecksumMismatchError: If checksum does not match expected_sha.
    """
    if not model_path.exists():
        raise FileNotFoundError(f"ONNX model file not found at {model_path}")

    h = hashlib.sha256()
    with open(model_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    actual_sha = h.hexdigest()

    if actual_sha != expected_sha:
        raise ChecksumMismatchError(
            f"Model SHA256 checksum mismatch! Expected: {expected_sha}, Got: {actual_sha}"
        )
    logger.info("Model SHA-256 verified successfully: %s", actual_sha)
    return True


def validate_embedding_vector(vector: Sequence[float], chunk_id: str) -> None:
    """Validate vector dimensionality and finiteness.

    Args:
        vector: List or sequence of floats representing the embedding vector.
        chunk_id: Chunk identifier for diagnostic reporting.

    Raises:
        BackfillValidationError: If length != 384 or non-finite values are present.
    """
    if len(vector) != EXPECTED_DIMENSION:
        raise BackfillValidationError(
            f"Chunk '{chunk_id}' produced embedding of dimension {len(vector)}, expected {EXPECTED_DIMENSION}."
        )
    arr = np.array(vector, dtype=float)
    if not np.all(np.isfinite(arr)):
        raise BackfillValidationError(
            f"Chunk '{chunk_id}' produced non-finite (NaN/Inf) embedding values."
        )


def prepare_semantic_records(
    chunks: Sequence[Chunk],
    embedding_service: ONNXEmbeddingService,
) -> list[ChunkSemantic]:
    """Compute and validate embeddings in memory for all candidate chunks.

    Guarantees no DB writes occur during inference or vector validation.

    Args:
        chunks: Sequence of Chunk records requiring semantic embeddings.
        embedding_service: Initialized ONNX embedding service.

    Returns:
        List of uncommitted ChunkSemantic model instances.

    Raises:
        BackfillValidationError: On duplicates, dimension mismatch, or non-finite values.
    """
    if not chunks:
        return []

    # Guard against duplicate chunk_ids in the candidate sequence
    seen_ids: set[str] = set()
    for c in chunks:
        if c.id in seen_ids:
            raise BackfillValidationError(
                f"Duplicate chunk_id encountered in input set: '{c.id}'"
            )
        seen_ids.add(c.id)

    texts = [c.text for c in chunks]
    raw_embeddings = embedding_service.embed_texts(texts)

    if len(raw_embeddings) != len(chunks):
        raise BackfillValidationError(
            f"Embedding service returned {len(raw_embeddings)} vectors for {len(chunks)} chunks."
        )

    records: list[ChunkSemantic] = []
    for chunk, emb in zip(chunks, raw_embeddings):
        validate_embedding_vector(emb, chunk.id)
        records.append(
            ChunkSemantic(
                chunk_id=chunk.id,
                embedding=emb,
                model_name="all-MiniLM-L6-v2",
            )
        )

    return records


def validate_existing_semantic_records(
    session: Session,
    all_chunks: Sequence[Chunk],
) -> None:
    """Validate integrity, consistency, dimensions, and model names of existing semantic records.

    Raises:
        BackfillStateError: If existing rows have duplicate chunk IDs, orphan references,
                            mismatched model names, null embeddings, or non-finite/wrong-dimension vectors.
    """
    all_chunk_ids = {c.id for c in all_chunks}
    existing_rows = session.query(ChunkSemantic).all()
    if not existing_rows:
        return

    seen_chunk_ids: set[str] = set()
    for row in existing_rows:
        # Check duplicate chunk_id
        if row.chunk_id in seen_chunk_ids:
            raise BackfillStateError(
                f"Duplicate chunk_id '{row.chunk_id}' detected in existing chunks_semantic rows."
            )
        seen_chunk_ids.add(row.chunk_id)

        # Check orphan chunk_id
        if row.chunk_id not in all_chunk_ids:
            raise BackfillStateError(
                f"Orphan semantic record detected: chunk_id '{row.chunk_id}' does not exist in chunks table."
            )

        # Check model_name
        if row.model_name != "all-MiniLM-L6-v2":
            raise BackfillStateError(
                f"Existing semantic record '{row.id}' has unexpected model_name '{row.model_name}', expected 'all-MiniLM-L6-v2'."
            )

        # Check embedding dimension and finiteness
        if row.embedding is None:
            raise BackfillStateError(
                f"Existing semantic record '{row.id}' has NULL embedding."
            )
        try:
            validate_embedding_vector(row.embedding, row.chunk_id)
        except BackfillValidationError as exc:
            raise BackfillStateError(
                f"Existing semantic record '{row.id}' failed vector validation: {exc}"
            ) from exc


def reconcile_database_state(session: Session) -> dict:
    """Perform read-only reconciliation of chunks and chunks_semantic.

    Returns:
        Diagnostic dictionary detailing chunk and semantic row counts.
    """
    all_chunks = session.query(Chunk.id, Chunk.document_id, Chunk.chunk_index).all()
    total_chunks = len(all_chunks)
    all_chunk_ids = {c.id for c in all_chunks}

    semantic_rows = session.query(ChunkSemantic).all()
    total_semantic = len(semantic_rows)
    semantic_chunk_ids = {s.chunk_id for s in semantic_rows}

    missing_chunk_ids = list(all_chunk_ids - semantic_chunk_ids)
    orphan_chunk_ids = list(semantic_chunk_ids - all_chunk_ids)

    # Check for duplicate chunk_ids and vector validity in chunks_semantic
    duplicate_chunk_ids: list[str] = []
    seen = set()
    invalid_model_names: list[str] = []
    invalid_dimensions: list[str] = []
    non_finite_vectors: list[str] = []

    for s in semantic_rows:
        if s.chunk_id in seen:
            duplicate_chunk_ids.append(s.chunk_id)
        seen.add(s.chunk_id)

        if s.model_name != "all-MiniLM-L6-v2":
            invalid_model_names.append(s.id)

        if s.embedding is None or len(s.embedding) != EXPECTED_DIMENSION:
            invalid_dimensions.append(s.id)
        elif not np.all(np.isfinite(np.array(s.embedding, dtype=float))):
            non_finite_vectors.append(s.id)

    diagnostics = {
        "total_chunks": total_chunks,
        "total_semantic_rows": total_semantic,
        "missing_semantic_count": len(missing_chunk_ids),
        "orphan_semantic_count": len(orphan_chunk_ids),
        "duplicate_semantic_count": len(duplicate_chunk_ids),
        "invalid_model_names_count": len(invalid_model_names),
        "invalid_dimension_count": len(invalid_dimensions),
        "non_finite_vector_count": len(non_finite_vectors),
        "missing_chunk_ids": missing_chunk_ids,
        "orphan_chunk_ids": orphan_chunk_ids,
        "duplicate_chunk_ids": duplicate_chunk_ids,
    }
    return diagnostics


def execute_backfill(
    session: Session,
    embedding_service: Optional[ONNXEmbeddingService] = None,
    verify_checksum: bool = True,
    model_path: Path = DEFAULT_MODEL_PATH,
    allow_resume: bool = False,
) -> dict:
    """Execute deterministic backfill of semantic embeddings.

    Args:
        session: Active SQLAlchemy database session.
        embedding_service: Optional initialized service (uses local ONNX service if None).
        verify_checksum: Whether to verify ONNX model file checksum before inference.
        model_path: Path to model.onnx.
        allow_resume: If True, allows resuming an interrupted partial backfill.
                      If False, halts on unexpected pre-existing rows to require reconciliation.

    Returns:
        Summary dict containing status, rows inserted, and total semantic count.

    Raises:
        ChecksumMismatchError: If model checksum is invalid.
        BackfillStateError: If unexpected partial state is detected without allow_resume.
        BackfillValidationError: If vector generation or pre-commit verification fails.
    """
    # 1. Verify model checksum
    if verify_checksum:
        verify_model_checksum(model_path)

    # 2. Inspect current database state (Read-Only)
    all_chunks = (
        session.query(Chunk)
        .order_by(Chunk.document_id, Chunk.chunk_index)
        .all()
    )
    total_chunks = len(all_chunks)
    existing_semantic_count = session.query(ChunkSemantic).count()

    logger.info(
        "Current DB state: total_chunks=%d, existing_semantic_rows=%d",
        total_chunks,
        existing_semantic_count,
    )

    # Anomaly check: more semantic rows than total chunks
    if existing_semantic_count > total_chunks:
        raise BackfillStateError(
            f"Database anomaly detected: {existing_semantic_count} semantic rows exist for {total_chunks} total chunks. "
            f"Run read-only reconciliation (`--reconcile`) to investigate duplicate or orphan records."
        )

    # Idempotent no-op check: already fully backfilled
    if total_chunks > 0 and existing_semantic_count == total_chunks:
        validate_existing_semantic_records(session, all_chunks)
        logger.info("All %d chunks already have valid semantic embeddings. Backfill is already complete.", total_chunks)
        return {
            "status": "already_complete",
            "total_chunks": total_chunks,
            "rows_inserted": 0,
            "final_semantic_count": existing_semantic_count,
        }

    # Unexpected partial state check
    if 0 < existing_semantic_count < total_chunks:
        if not allow_resume:
            raise BackfillStateError(
                f"Unexpected partial state detected: {existing_semantic_count}/{total_chunks} chunks have "
                f"semantic embeddings. To prevent unintended overwrites or race conditions, backfill is halted. "
                f"Run read-only reconciliation (`--reconcile`) and verify database consistency before resuming "
                f"with `--allow-resume`."
            )
        # Pre-validate all existing rows for integrity, dimensions, and model name consistency
        logger.info("Validating %d pre-existing semantic rows before resuming...", existing_semantic_count)
        validate_existing_semantic_records(session, all_chunks)

        # Filter only missing chunks for resume
        existing_chunk_ids = {r.chunk_id for r in session.query(ChunkSemantic.chunk_id).all()}
        eligible_chunks = [c for c in all_chunks if c.id not in existing_chunk_ids]
    else:
        eligible_chunks = all_chunks

    if not eligible_chunks:
        logger.info("No eligible chunks found for backfill.")
        return {
            "status": "no_eligible_chunks",
            "total_chunks": total_chunks,
            "rows_inserted": 0,
            "final_semantic_count": existing_semantic_count,
        }

    # 3. Compute and validate all embeddings in memory BEFORE opening transaction
    service = embedding_service or ONNXEmbeddingService(model_dir=model_path.parent)
    logger.info("Computing embeddings in memory for %d eligible chunks...", len(eligible_chunks))
    records = prepare_semantic_records(eligible_chunks, service)

    # 4. Open Single Atomic Transaction for Insertion
    logger.info("Opening atomic transaction to insert %d records...", len(records))
    try:
        for record in records:
            session.add(record)
        session.flush()

        # In-transaction row count verification before commit
        in_tx_count = session.query(ChunkSemantic).count()
        expected_total = existing_semantic_count + len(records)
        if in_tx_count != expected_total:
            raise BackfillValidationError(
                f"Pre-commit count mismatch! Expected {expected_total} rows in transaction, found {in_tx_count}."
            )

        session.commit()
        logger.info("Transaction committed successfully. %d rows inserted.", len(records))
    except Exception as exc:
        session.rollback()
        logger.error("Transaction failed and was rolled back cleanly: %s", exc)
        raise

    final_count = session.query(ChunkSemantic).count()
    return {
        "status": "success",
        "total_chunks": total_chunks,
        "rows_inserted": len(records),
        "final_semantic_count": final_count,
    }


def main():
    """CLI entrypoint for semantic embedding backfill and reconciliation."""
    parser = argparse.ArgumentParser(
        description="Deterministic Semantic Embedding Backfill for Phase 5.2B"
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Run read-only reconciliation audit between chunks and chunks_semantic without modifying data.",
    )
    parser.add_argument(
        "--allow-resume",
        action="store_true",
        help="Allow resuming a partially backfilled database after reconciliation verification.",
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=DEFAULT_MODEL_PATH,
        help="Path to local ONNX model file.",
    )
    parser.add_argument(
        "--skip-checksum",
        action="store_true",
        help="Skip model SHA256 checksum verification (not recommended for production).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    with SessionLocal() as session:
        if args.reconcile:
            logger.info("Running read-only reconciliation audit...")
            diag = reconcile_database_state(session)
            print("--- RECONCILIATION AUDIT ---")
            print(f"Total Chunks:           {diag['total_chunks']}")
            print(f"Total Semantic Rows:    {diag['total_semantic_rows']}")
            print(f"Missing Semantic Rows:  {diag['missing_semantic_count']}")
            print(f"Orphan Semantic Rows:   {diag['orphan_semantic_count']}")
            print(f"Duplicate Chunk IDs:    {diag['duplicate_semantic_count']}")
            if diag["missing_chunk_ids"]:
                print(f"Sample Missing Chunk IDs: {diag['missing_chunk_ids'][:5]}")
            return

        result = execute_backfill(
            session=session,
            verify_checksum=not args.skip_checksum,
            model_path=args.model_path,
            allow_resume=args.allow_resume,
        )
        print(f"Backfill Result: {result}")


if __name__ == "__main__":
    main()
