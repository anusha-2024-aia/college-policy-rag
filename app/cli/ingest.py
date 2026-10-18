"""Command-line ingestion script for Document RAG."""

import argparse
import logging
import sys
import time
from pathlib import Path
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.services.chunker import ChunkerService
from app.services.embedding import get_embedding_service
from app.services.ingestion import IngestionService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cli.ingest")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Ingest PDF documents into PostgreSQL + pgvector according to documents_manifest.csv."
    )
    parser.add_argument(
        "--manifest",
        type=str,
        default=settings.MANIFEST_PATH,
        help=f"Path to manifest CSV (default: {settings.MANIFEST_PATH})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-chunking and re-embedding even if document hash is unchanged",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=settings.CHUNK_SIZE_TOKENS,
        help=f"Target tokens per chunk (default: {settings.CHUNK_SIZE_TOKENS})",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=settings.CHUNK_OVERLAP_TOKENS,
        help=f"Token overlap between adjacent chunks (default: {settings.CHUNK_OVERLAP_TOKENS})",
    )
    parser.add_argument(
        "--mock-embeddings",
        action="store_true",
        help="Force use of deterministic mock embeddings (useful for testing and offline runs)",
    )
    return parser.parse_args()


def main() -> None:
    """Main CLI execution routine."""
    args = parse_args()
    manifest_path = Path(args.manifest)

    print("=" * 70)
    print(" Document RAG - PDF Ingestion Pipeline")
    print("=" * 70)
    print(f" Manifest:     {manifest_path}")
    print(f" Chunk Size:   {args.chunk_size} tokens")
    print(f" Overlap:      {args.chunk_overlap} tokens")
    print(f" Force:        {args.force}")
    print(f" Mock Vectors: {args.mock_embeddings}")
    print("=" * 70)

    # 1. Initialize database schema
    print("\n[1/3] Initializing database schema...")
    try:
        init_db()
        print(" -> Database schema ready.")
    except Exception as exc:
        logger.error("Failed to connect or initialize database: %s", exc)
        print(f" [ERROR] Database connection failed: {exc}")
        sys.exit(1)

    # 2. Configure services
    print("\n[2/3] Initializing ingestion services...")
    chunker = ChunkerService(
        chunk_size_tokens=args.chunk_size,
        chunk_overlap_tokens=args.chunk_overlap,
    )
    embedding_svc = get_embedding_service(force_mock=args.mock_embeddings)

    db = SessionLocal()
    start_time = time.time()

    try:
        ingestion_svc = IngestionService(
            db_session=db,
            chunker=chunker,
            embedding_service=embedding_svc,
        )

        print("\n[3/3] Running ingestion pipeline...")
        report = ingestion_svc.ingest_manifest(manifest_path=manifest_path, force=args.force)

    finally:
        db.close()

    elapsed = time.time() - start_time

    # 3. Print Results Summary
    print("\n" + "=" * 70)
    print(" Ingestion Summary")
    print("=" * 70)
    print(f" Total Documents:  {report.total_documents}")
    print(f" Ingested:        {report.ingested_count}")
    print(f" Skipped:         {report.skipped_count}")
    print(f" Failed:          {report.failed_count}")
    print(f" Chunks Created:  {report.total_chunks_created}")
    print(f" Elapsed Time:    {elapsed:.2f}s")
    print("-" * 70)

    if report.document_results:
        print(f" {'File Name':<32} | {'Status':<10} | {'Pages':<6} | {'Chunks':<6}")
        print("-" * 70)
        for doc in report.document_results:
            print(f" {doc.file_name:<32} | {doc.status:<10} | {doc.total_pages:<6} | {doc.total_chunks:<6}")

    if report.errors:
        print("\nErrors encountered:")
        for err in report.errors:
            print(f" [!] {err}")
        sys.exit(1)

    print("\nIngestion completed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
