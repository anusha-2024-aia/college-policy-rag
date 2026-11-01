"""Atomic and idempotent CLI reindexing tool for Document RAG embeddings."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
import sys
import time
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings
from app.core.database import Base, SessionLocal, get_test_session
from app.models.chunk import Chunk
from app.models.chunk_semantic import ChunkSemantic
from app.models.index_metadata import EmbeddingIndexMetadata
from app.services.embedding import (
    EmbeddingProvider,
    get_embedding_provider,
    MockEmbeddingService,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reindex")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reindex document chunk embeddings atomically and update index metadata."
    )
    parser.add_argument(
        "--model",
        type=str,
        default="all-MiniLM-L6-v2",
        help="Embedding model identifier to index (e.g. 'all-MiniLM-L6-v2', 'mock-sha256', 'openai', 'gemini').",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Batch size for generating embeddings (default: 32).",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Optional database connection URL override.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reindexing even if index metadata already matches.",
    )
    return parser.parse_args()


def reindex_corpus(
    model_id: str = "all-MiniLM-L6-v2",
    batch_size: int = 32,
    db: Optional[Session] = None,
    force: bool = False,
) -> EmbeddingIndexMetadata:
    """Atomically builds and swaps in new embeddings for all chunks in the database.

    Guarantees:
    - Atomicity: Embeddings are generated in memory; the database swap occurs in a single transaction.
    - Idempotency: Re-running with the same model produces the exact same valid state without duplicates.
    - Consistency: EmbeddingIndexMetadata is updated within the same transaction.
    """
    close_db_on_exit = False
    if db is None:
        db = SessionLocal()
        close_db_on_exit = True

    try:
        # 1. Resolve embedding provider
        force_mock = model_id.lower() in ("mock", "mock-sha256")
        provider = get_embedding_provider(model_id=model_id, force_mock=force_mock)
        logger.info(
            "Resolved embedding provider: model_id='%s', dim=%d, normalized=%s, is_mock=%s",
            provider.model_id,
            provider.dim,
            provider.normalized,
            provider.is_mock,
        )

        # 2. Check if reindexing is already complete
        meta = db.query(EmbeddingIndexMetadata).filter_by(id="default").first()
        chunks = db.query(Chunk).order_by(Chunk.chunk_index).all()
        total_chunks = len(chunks)

        if total_chunks == 0:
            logger.warning("No chunks found in database to reindex.")
            return meta

        if (
            not force
            and meta is not None
            and meta.model_id == provider.model_id
            and meta.dim == provider.dim
            and meta.chunk_count == total_chunks
        ):
            # For 384d ONNX, also check that chunks_semantic has the matching rows
            if provider.dim == 384:
                sem_count = db.query(ChunkSemantic).filter_by(model_name=provider.model_id).count()
                if sem_count == total_chunks:
                    logger.info("Corpus is already indexed with '%s' (%d chunks). Use --force to rebuild.", provider.model_id, sem_count)
                    return meta

        logger.info("Starting embedding generation for %d chunks in batches of %d...", total_chunks, batch_size)
        start_time = time.perf_counter()

        # 3. Compute embeddings in memory
        chunk_texts = [c.text for c in chunks]
        embeddings: list[list[float]] = []

        for i in range(0, total_chunks, batch_size):
            batch_texts = chunk_texts[i : i + batch_size]
            batch_vectors = provider.embed_documents(batch_texts)
            embeddings.extend(batch_vectors)

        # Validation
        if len(embeddings) != total_chunks:
            raise ValueError(f"Embedding count mismatch: expected {total_chunks}, got {len(embeddings)}")
        for idx, vec in enumerate(embeddings):
            if len(vec) != provider.dim:
                raise ValueError(
                    f"Vector dimension mismatch at chunk {idx}: expected {provider.dim}, got {len(vec)}"
                )

        # 4. Atomic transaction swap
        logger.info("Swapping in embeddings atomically within a single database transaction...")
        try:
            if provider.dim == 384 or provider.model_id == "all-MiniLM-L6-v2":
                # Clear existing semantic rows and insert fresh records
                db.query(ChunkSemantic).delete()
                for chunk, vec in zip(chunks, embeddings, strict=True):
                    sem_row = ChunkSemantic(
                        chunk_id=chunk.id,
                        embedding=vec,
                        model_name=provider.model_id,
                    )
                    db.add(sem_row)
            elif provider.dim == 1536:
                # Update chunks.embedding
                for chunk, vec in zip(chunks, embeddings, strict=True):
                    chunk.embedding = vec

            # Update index metadata
            if meta is None:
                meta = EmbeddingIndexMetadata(id="default")
                db.add(meta)

            meta.model_id = provider.model_id
            meta.dim = provider.dim
            meta.normalized = provider.normalized
            meta.is_mock = provider.is_mock
            meta.chunk_count = total_chunks
            meta.updated_at = datetime.now(timezone.utc)

            db.commit()
            elapsed = time.perf_counter() - start_time
            logger.info(
                "[SUCCESS] Reindexed %d chunks with model '%s' (dim=%d, normalized=%s, is_mock=%s) in %.2f seconds.",
                total_chunks,
                provider.model_id,
                provider.dim,
                provider.normalized,
                provider.is_mock,
                elapsed,
            )
            return meta
        except Exception as exc:
            db.rollback()
            logger.error("Transaction failed during reindexing, rolled back completely: %s", exc)
            raise

    finally:
        if close_db_on_exit:
            db.close()


def get_reindex_db(db_url: Optional[str] = None) -> Session:
    """Resolve database session with fallback to offline test SQLite database."""
    if db_url:
        custom_engine = create_engine(db_url)
        Base.metadata.create_all(bind=custom_engine)
        CustomSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=custom_engine)
        return CustomSessionLocal()

    if settings.APP_ENV == "test":
        return get_test_session()

    try:
        session = SessionLocal()
        session.execute(text("SELECT 1"))
        return session
    except Exception as exc:
        logger.warning(
            "Primary database connection failed (%s); falling back to offline SQLite 'data/test_kvit.db'...",
            exc,
        )
        if Path("data/test_kvit.db").exists():
            return get_test_session()
        raise


def main():
    args = parse_args()
    db = get_reindex_db(args.db_url)

    try:
        reindex_corpus(
            model_id=args.model,
            batch_size=args.batch_size,
            db=db,
            force=args.force,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
