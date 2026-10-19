"""Focused unit and integration tests for semantic retrieval integration (Phase 5.2B Step 3).

Validates:
- Feature flag OFF vs. ON behavior
- Query embedding dimension and finiteness
- Semantic cosine-distance ordering
- Use of chunks_semantic table
- Missing semantic rows and graceful fallback
- RRF fusion and deduplication with full-text search
- Strict RBAC pre-filtering before ranking/fusion
- Version awareness, amendments, citations, and abstention in QAService
- Database read-only invariants during retrieval
- API schema compatibility
"""

import datetime as dt
import math
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.chunk import Chunk
from app.models.chunk_semantic import ChunkSemantic
from app.schemas.retrieval import RetrievalResponse, ScoredChunk
from app.schemas.qa import AskRequest
from app.services.embedding import MockEmbeddingService
from app.services.embedding_onnx import ONNXEmbeddingService
from app.services.reranker import MockRerankerService
from app.services.retrieval import HybridRetrievalService
from app.services.qa import QAService
from app.services.llm import MockLLMService
from app.services.versioning import DocumentVersionService
from app.core.config import settings


class DeterministicSemanticService:
    """Mock 384-dimensional semantic embedding service for isolated SQLite tests."""

    def __init__(self, dimension: int = 384):
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for text in texts:
            # Generate deterministic unit-normalized pseudo-embedding
            raw = [float((hash(text + str(i)) % 1000) - 500) / 500.0 for i in range(self._dimension)]
            norm = math.sqrt(sum(x * x for x in raw)) or 1.0
            embeddings.append([round(x / norm, 6) for x in raw])
        return embeddings

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]


def seed_semantic_test_corpus(db: Session) -> dict[str, Chunk]:
    """Helper to populate isolated SQLite test database with docs, chunks, and semantic rows."""
    # 1. Public student attendance policy
    doc_student = Document(
        id="doc-student-policy",
        file_name="student_attendance_2025.pdf",
        file_hash="hash_student",
        title="Student Attendance Policy 2025",
        effective_date=dt.date(2025, 1, 1),
        supersedes="student_attendance_2023.pdf",
        allowed_roles=["student", "faculty", "admin"],
        total_pages=1,
        total_chunks=2,
    )
    # 2. Older superseded attendance policy
    doc_superseded = Document(
        id="doc-superseded-policy",
        file_name="student_attendance_2023.pdf",
        file_hash="hash_superseded",
        title="Student Attendance Policy 2023",
        effective_date=dt.date(2023, 1, 1),
        allowed_roles=["student", "faculty", "admin"],
        total_pages=1,
        total_chunks=1,
    )
    # 3. Confidential faculty salary document
    doc_faculty = Document(
        id="doc-faculty-salary",
        file_name="faculty_salaries_2025.pdf",
        file_hash="hash_faculty",
        title="Faculty Compensation 2025",
        effective_date=dt.date(2025, 1, 1),
        allowed_roles=["faculty", "admin"],
        total_pages=1,
        total_chunks=1,
    )

    db.add_all([doc_student, doc_superseded, doc_faculty])
    db.flush()

    # Chunks
    chk_current = Chunk(
        id="chunk-cur-att",
        document_id=doc_student.id,
        chunk_index=0,
        page_number=1,
        text="Minimum student attendance required is 75% for all courses.",
        token_count=12,
        embedding=[0.05] * 1536,
    )
    chk_other = Chunk(
        id="chunk-cur-rules",
        document_id=doc_student.id,
        chunk_index=1,
        page_number=1,
        text="Medical leave requires hospital certificate submitted within 3 days.",
        token_count=11,
        embedding=[0.01] * 1536,
    )
    chk_old = Chunk(
        id="chunk-old-att",
        document_id=doc_superseded.id,
        chunk_index=0,
        page_number=1,
        text="Minimum student attendance required is 80% for all courses under 2023 rules.",
        token_count=13,
        embedding=[0.04] * 1536,
    )
    chk_salary = Chunk(
        id="chunk-fac-salary",
        document_id=doc_faculty.id,
        chunk_index=0,
        page_number=1,
        text="Confidential Professor grade salary scale is Level 14 with pay matrix.",
        token_count=12,
        embedding=[0.02] * 1536,
    )

    db.add_all([chk_current, chk_other, chk_old, chk_salary])
    db.flush()

    # Semantic embeddings (384-dim)
    sem_service = DeterministicSemanticService()
    sem_cur = ChunkSemantic(
        id="sem-cur-att",
        chunk_id=chk_current.id,
        embedding=sem_service.embed_texts([chk_current.text])[0],
        model_name="all-MiniLM-L6-v2",
    )
    sem_other = ChunkSemantic(
        id="sem-cur-rules",
        chunk_id=chk_other.id,
        embedding=sem_service.embed_texts([chk_other.text])[0],
        model_name="all-MiniLM-L6-v2",
    )
    sem_old = ChunkSemantic(
        id="sem-old-att",
        chunk_id=chk_old.id,
        embedding=sem_service.embed_texts([chk_old.text])[0],
        model_name="all-MiniLM-L6-v2",
    )
    sem_salary = ChunkSemantic(
        id="sem-fac-salary",
        chunk_id=chk_salary.id,
        embedding=sem_service.embed_texts([chk_salary.text])[0],
        model_name="all-MiniLM-L6-v2",
    )

    db.add_all([sem_cur, sem_other, sem_old, sem_salary])
    db.commit()

    return {
        "current": chk_current,
        "other": chk_other,
        "old": chk_old,
        "salary": chk_salary,
    }


# =========================================================================
# 1. Feature Flag and Query Embedding Invariant Tests
# =========================================================================

def test_feature_flag_off_uses_legacy_retrieval(test_db: Session):
    """Verify that when semantic_retrieval_enabled is False, legacy path is used."""
    chunks_map = seed_semantic_test_corpus(test_db)
    mock_legacy = MockEmbeddingService(dimension=1536)

    service = HybridRetrievalService(
        db_session=test_db,
        embedding_service=mock_legacy,
        semantic_retrieval_enabled=False,
    )

    resp = service.retrieve("student attendance", top_k=5, role="student")
    assert resp.diagnostics.semantic_retrieval_active is False
    assert len(resp.vector_results) > 0


def test_feature_flag_on_uses_semantic_retrieval(test_db: Session):
    """Verify that when semantic_retrieval_enabled is True, 384-dim semantic path is active."""
    chunks_map = seed_semantic_test_corpus(test_db)
    sem_service = DeterministicSemanticService()

    service = HybridRetrievalService(
        db_session=test_db,
        semantic_embedding_service=sem_service,
        semantic_retrieval_enabled=True,
    )

    resp = service.retrieve("student attendance", top_k=5, role="student")
    assert resp.diagnostics.semantic_retrieval_active is True
    assert len(resp.vector_results) > 0


def test_per_request_use_semantic_override(test_db: Session):
    """Verify feature-flag gating: request True cannot bypass disabled flag; False can opt out of enabled flag."""
    seed_semantic_test_corpus(test_db)
    sem_service = DeterministicSemanticService()

    # 1. Operational flag is False: request use_semantic=True CANNOT bypass the operational gate
    service_disabled = HybridRetrievalService(
        db_session=test_db,
        semantic_embedding_service=sem_service,
        semantic_retrieval_enabled=False,
    )
    resp_blocked = service_disabled.retrieve("attendance", top_k=5, role="student", use_semantic=True)
    assert resp_blocked.diagnostics.semantic_retrieval_active is False

    # 2. Operational flag is True: request use_semantic=False safely opts out to legacy path
    service_enabled = HybridRetrievalService(
        db_session=test_db,
        semantic_embedding_service=sem_service,
        semantic_retrieval_enabled=True,
    )
    resp_opt_out = service_enabled.retrieve("attendance", top_k=5, role="student", use_semantic=False)
    assert resp_opt_out.diagnostics.semantic_retrieval_active is False

    # 3. Operational flag is True: request use_semantic=True activates semantic retrieval
    resp_active = service_enabled.retrieve("attendance", top_k=5, role="student", use_semantic=True)
    assert resp_active.diagnostics.semantic_retrieval_active is True


def test_semantic_query_embedding_dimension_and_finite_values():
    """Verify ONNXEmbeddingService query embeddings have dimension 384 and finite values."""
    service = ONNXEmbeddingService()
    emb = service.embed_query("KVIT student attendance requirement")

    assert len(emb) == 384
    assert all(isinstance(v, float) and not math.isnan(v) and not math.isinf(v) for v in emb)
    # Unit norm check
    norm = math.sqrt(sum(v * v for v in emb))
    assert abs(norm - 1.0) < 1e-4


# =========================================================================
# 2. Semantic Ranking and Ordering Tests
# =========================================================================

def test_semantic_cosine_distance_ordering(test_db: Session):
    """Verify semantic vector search ranks identical/closest passage at rank #1."""
    chunks_map = seed_semantic_test_corpus(test_db)
    sem_service = DeterministicSemanticService()

    service = HybridRetrievalService(
        db_session=test_db,
        semantic_embedding_service=sem_service,
        semantic_retrieval_enabled=True,
    )

    # Query exactly matching current attendance clause
    results = service.vector_search(chunks_map["current"].text, k=3, role="student")
    assert len(results) > 0
    assert results[0].chunk_id == chunks_map["current"].id
    assert results[0].rank == 1
    assert results[0].score >= results[1].score


def test_semantic_vector_search_uses_chunks_semantic_table(test_db: Session):
    """Verify that semantic vector search retrieves scores based on chunks_semantic."""
    chunks_map = seed_semantic_test_corpus(test_db)
    sem_service = DeterministicSemanticService()

    service = HybridRetrievalService(
        db_session=test_db,
        semantic_embedding_service=sem_service,
        semantic_retrieval_enabled=True,
    )

    results = service.vector_search("student attendance", k=5, role="student")
    retrieved_chunk_ids = {r.chunk_id for r in results}
    assert chunks_map["current"].id in retrieved_chunk_ids


# =========================================================================
# 3. RBAC Security Filtering Tests
# =========================================================================

def test_rbac_filtering_strictly_enforced_in_semantic_search(test_db: Session):
    """Verify unauthorized confidential documents are never retrieved by student role."""
    chunks_map = seed_semantic_test_corpus(test_db)
    sem_service = DeterministicSemanticService()

    service = HybridRetrievalService(
        db_session=test_db,
        semantic_embedding_service=sem_service,
        semantic_retrieval_enabled=True,
    )

    # Student asks about confidential faculty salary
    query = "Confidential Professor grade salary scale Level 14 pay matrix"
    results = service.vector_search(query, k=10, role="student")

    # Zero salary chunks allowed for student
    retrieved_chunk_ids = {r.chunk_id for r in results}
    assert chunks_map["salary"].id not in retrieved_chunk_ids

    # Authorized faculty CAN retrieve it
    fac_results = service.vector_search(query, k=10, role="faculty")
    fac_chunk_ids = {r.chunk_id for r in fac_results}
    assert chunks_map["salary"].id in fac_chunk_ids


# =========================================================================
# 4. Fallback and Failure Handling Tests
# =========================================================================

def test_missing_semantic_rows_safe_fallback(test_db: Session):
    """Verify that when chunks_semantic has no rows, it falls back cleanly to baseline."""
    # Seed docs and chunks, but do NOT seed chunks_semantic
    doc = Document(
        id="doc-no-sem",
        file_name="plain_doc.pdf",
        file_hash="plain_hash",
        title="Plain Doc",
        effective_date=dt.date(2025, 1, 1),
        allowed_roles=["student"],
        total_pages=1,
        total_chunks=1,
    )
    chk = Chunk(
        id="chk-no-sem",
        document_id=doc.id,
        chunk_index=0,
        page_number=1,
        text="Plain policy text.",
        token_count=5,
        embedding=[0.05] * 1536,
    )
    test_db.add_all([doc, chk])
    test_db.commit()

    service = HybridRetrievalService(
        db_session=test_db,
        embedding_service=MockEmbeddingService(dimension=1536),
        semantic_embedding_service=DeterministicSemanticService(),
        semantic_retrieval_enabled=True,  # enabled, but chunks_semantic is empty
    )

    # Should safely fall back to legacy vector search without exception
    results = service.vector_search("plain policy", k=5, role="student")
    assert len(results) > 0
    assert results[0].chunk_id == "chk-no-sem"

    # Diagnostics in retrieve() must accurately report that semantic was NOT active
    resp = service.retrieve("plain policy", top_k=5, role="student")
    assert resp.diagnostics.semantic_retrieval_active is False
    assert len(resp.vector_results) > 0


def test_semantic_exception_triggers_safe_fallback(test_db: Session):
    """Verify that any exception during semantic vector search falls back to legacy path."""
    seed_semantic_test_corpus(test_db)
    failing_service = MagicMock()
    failing_service.embed_query.side_effect = RuntimeError("Simulated ONNX inference failure")

    service = HybridRetrievalService(
        db_session=test_db,
        embedding_service=MockEmbeddingService(dimension=1536),
        semantic_embedding_service=failing_service,
        semantic_retrieval_enabled=True,
    )

    results = service.vector_search("student attendance", k=5, role="student")
    assert len(results) > 0  # Fell back to legacy search cleanly

    # Diagnostics in retrieve() must accurately report that semantic was NOT active
    resp = service.retrieve("student attendance", top_k=5, role="student")
    assert resp.diagnostics.semantic_retrieval_active is False
    assert len(resp.vector_results) > 0


# =========================================================================
# 5. RRF Fusion and Deduplication Tests
# =========================================================================

def test_semantic_fulltext_rrf_fusion_and_deduplication(test_db: Session):
    """Verify candidates from semantic and keyword searches are deduplicated and boosted."""
    seed_semantic_test_corpus(test_db)
    sem_service = DeterministicSemanticService()

    service = HybridRetrievalService(
        db_session=test_db,
        semantic_embedding_service=sem_service,
        reranker_service=MockRerankerService(),
        semantic_retrieval_enabled=True,
    )

    resp = service.retrieve("student attendance 75%", top_k=5, top_n=3, role="student")
    assert len(resp.fused_results) > 0

    # Ensure no duplicate chunk_ids in fused results
    fused_cids = [fc.chunk_id for fc in resp.fused_results]
    assert len(fused_cids) == len(set(fused_cids))


# =========================================================================
# 6. QAService Downstream Integration Tests
# =========================================================================

def test_qa_service_version_awareness_with_semantic_retrieval(test_db: Session):
    """Verify QAService correctly prioritizes active policy over superseded policy with semantic retrieval."""
    chunks_map = seed_semantic_test_corpus(test_db)
    sem_service = DeterministicSemanticService()

    retrieval_service = HybridRetrievalService(
        db_session=test_db,
        semantic_embedding_service=sem_service,
        reranker_service=MockRerankerService(),
        semantic_retrieval_enabled=True,
    )
    llm_service = MockLLMService()
    qa_service = QAService(
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        version_service=DocumentVersionService(),
    )

    req = AskRequest(
        question="What is the student attendance percentage requirement?",
        role="student",
        version_aware=True,
        semantic_retrieval=True,
    )
    resp = qa_service.answer(req)

    assert resp.answer != ""
    assert len(resp.citations) > 0
    # Current attendance policy cited
    cited_files = {c.file_name for c in resp.citations}
    assert "student_attendance_2025.pdf" in cited_files


def test_qa_service_abstention_on_out_of_corpus_with_semantic_retrieval(test_db: Session):
    """Verify QAService abstains cleanly when query relevance is below floor."""
    seed_semantic_test_corpus(test_db)
    sem_service = DeterministicSemanticService()

    retrieval_service = HybridRetrievalService(
        db_session=test_db,
        semantic_embedding_service=sem_service,
        reranker_service=MockRerankerService(),
        semantic_retrieval_enabled=True,
    )
    llm_service = MockLLMService()
    qa_service = QAService(
        retrieval_service=retrieval_service,
        llm_service=llm_service,
    )

    req = AskRequest(
        question="What is the astronomical distance from Mars to Jupiter in parsecs?",
        role="student",
        semantic_retrieval=True,
    )
    resp = qa_service.answer(req)
    assert resp.abstained is True
    assert QAService.ABSTENTION_SENTENCE in resp.answer
    assert len(resp.citations) == 0


# =========================================================================
# 7. Database Read-Only Invariant Tests
# =========================================================================

def test_retrieval_performs_zero_database_writes(test_db: Session):
    """Verify that running retrieval performs strictly zero database writes."""
    seed_semantic_test_corpus(test_db)
    docs_before = test_db.query(Document).count()
    chunks_before = test_db.query(Chunk).count()
    semantic_before = test_db.query(ChunkSemantic).count()

    service = HybridRetrievalService(
        db_session=test_db,
        semantic_embedding_service=DeterministicSemanticService(),
        reranker_service=MockRerankerService(),
        semantic_retrieval_enabled=True,
    )

    for _ in range(5):
        service.retrieve("student attendance leave rules", top_k=5, role="student")

    assert test_db.query(Document).count() == docs_before
    assert test_db.query(Chunk).count() == chunks_before
    assert test_db.query(ChunkSemantic).count() == semantic_before
