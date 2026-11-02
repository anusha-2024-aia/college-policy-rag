"""Database Backup and Restore Disaster Recovery Verification Drill.

Executes a complete, verifiable backup and restore drill into an empty database,
asserting table schemas, exact row count invariants, and query synthesis.
"""

from __future__ import annotations

import os
import sys
import time
import shutil
import sqlite3
import tempfile
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models.document import Document
from app.models.chunk import Chunk
from app.models.chunk_semantic import ChunkSemantic
from app.models.lineage import DocumentLineage
from app.models.user import User
from app.models.index_metadata import EmbeddingIndexMetadata


def run_drill() -> dict[str, any]:
    """Execute backup, restore into empty database, and verify integrity."""
    source_db_path = PROJECT_ROOT / "data" / "test_kvit.db"
    if not source_db_path.exists():
        raise FileNotFoundError(f"Source database not found: {source_db_path}")

    start_time = time.perf_counter()
    drill_dir = Path(tempfile.mkdtemp(prefix="kvit_drill_"))
    backup_file = drill_dir / "kvit_backup_drill.dump"
    restored_db_path = drill_dir / "restored_drill.db"

    print("=" * 80)
    print(" KVIT POLICY INTELLIGENCE - DISASTER RECOVERY & BACKUP/RESTORE DRILL")
    print("=" * 80)
    print(f" Source Database:  {source_db_path} ({source_db_path.stat().st_size} bytes)")
    print(f" Drill Target Dir: {drill_dir}")
    print("-" * 80)

    # 1. Capture Source Database Table Row Counts
    src_conn = sqlite3.connect(str(source_db_path))
    src_cur = src_conn.cursor()
    tables = [
        "documents",
        "chunks",
        "chunks_semantic",
        "document_lineage",
        "users",
        "embedding_index_metadata",
    ]
    source_counts = {}
    for tbl in tables:
        src_cur.execute(f"SELECT count(*) FROM {tbl}")
        source_counts[tbl] = src_cur.fetchone()[0]
    src_conn.close()

    print("\n[STEP 1] Generating Atomic Database Backup Archive...")
    t0_backup = time.perf_counter()
    # Execute sqlite backup API (produces 100% consistent transactional copy)
    src_conn = sqlite3.connect(str(source_db_path))
    bck_conn = sqlite3.connect(str(backup_file))
    src_conn.backup(bck_conn)
    bck_conn.close()
    src_conn.close()
    backup_duration = time.perf_counter() - t0_backup
    print(f" [OK] Backup created: {backup_file} ({backup_file.stat().st_size} bytes in {backup_duration*1000:.1f}ms)")

    print("\n[STEP 2] Initializing Clean Target Database and Restoring Archive...")
    t0_restore = time.perf_counter()
    bck_conn = sqlite3.connect(str(backup_file))
    target_conn = sqlite3.connect(str(restored_db_path))
    bck_conn.backup(target_conn)
    target_conn.close()
    bck_conn.close()
    restore_duration = time.perf_counter() - t0_restore
    print(f" [OK] Restore completed into: {restored_db_path} in {restore_duration*1000:.1f}ms")

    print("\n[STEP 3] Verifying Restored Database Invariants & Row Counts...")
    engine = create_engine(f"sqlite:///{restored_db_path}")
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    restored_counts = {}
    mismatches = []
    print(f" {'Table Name':<30} | {'Source Count':<14} | {'Restored Count':<14} | {'Status'}")
    print(f" {'-'*30} | {'-'*14} | {'-'*14} | {'-'*8}")
    for tbl in tables:
        with engine.connect() as conn:
            cnt = conn.execute(text(f"SELECT count(*) FROM {tbl}")).scalar()
            restored_counts[tbl] = cnt
            src_cnt = source_counts[tbl]
            is_match = (cnt == src_cnt)
            status_str = "MATCH" if is_match else "MISMATCH"
            print(f" {tbl:<30} | {src_cnt:<14} | {cnt:<14} | {status_str}")
            if not is_match:
                mismatches.append(f"{tbl}: expected {src_cnt}, got {cnt}")

    print("\n[STEP 4] Executing Sample Retrieval Query Against Restored Database...")
    sample_doc = session.query(Document).filter_by(file_name="academic_regulations_2024.pdf").first()
    assert sample_doc is not None, "academic_regulations_2024.pdf must exist in restored database"
    sample_chunk = session.query(Chunk).filter_by(document_id=sample_doc.id).first()
    assert sample_chunk is not None, "Chunks must exist for restored document"
    sample_semantic = session.query(ChunkSemantic).filter_by(chunk_id=sample_chunk.id).first()
    assert sample_semantic is not None, "Dense embeddings must exist in restored database"
    assert len(sample_semantic.embedding) == 384, "ONNX embedding vector dimension must be 384"

    print(f" [OK] Document verified: '{sample_doc.title}' (Version: {sample_doc.doc_version})")
    print(f" [OK] Chunk sample (p.{sample_chunk.page_number}): \"{sample_chunk.text[:80]}...\"")
    print(f" [OK] Semantic vector verified: model='{sample_semantic.model_name}', dim={len(sample_semantic.embedding)}")

    session.close()
    engine.dispose()

    # Cleanup temporary drill folder
    shutil.rmtree(drill_dir, ignore_errors=True)

    total_duration = time.perf_counter() - start_time
    print("-" * 80)
    print(f" DRILL STATUS: {'SUCCESS' if not mismatches else 'FAILED'}")
    print(f" Total Drill Time: {total_duration*1000:.1f}ms")
    print("=" * 80)

    if mismatches:
        raise RuntimeError(f"Disaster Recovery Drill failed with mismatches: {mismatches}")

    return {
        "status": "SUCCESS",
        "total_duration_ms": round(total_duration * 1000, 2),
        "backup_duration_ms": round(backup_duration * 1000, 2),
        "restore_duration_ms": round(restore_duration * 1000, 2),
        "table_counts": restored_counts,
        "sample_document": sample_doc.title,
    }


if __name__ == "__main__":
    run_drill()

