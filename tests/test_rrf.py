"""Tests for Reciprocal Rank Fusion (RRF) algorithm."""

import pytest
from app.schemas.retrieval import ScoredChunk
from app.services.retrieval import HybridRetrievalService


def make_chunk(cid: str, score: float, rank: int, text: str = "sample") -> ScoredChunk:
    """Helper creating a test ScoredChunk."""
    return ScoredChunk(
        chunk_id=cid,
        document_id="doc-1",
        file_name="doc.pdf",
        title="Doc",
        page_number=1,
        text=text,
        score=score,
        rank=rank,
    )


def test_rrf_mathematical_formula():
    """Verify that RRF score matches the exact mathematical definition 1 / (k + rank)."""
    service = HybridRetrievalService(db_session=None, rrf_k=60)

    # 1 item in vector search (rank 1)
    vector_results = [make_chunk("c1", score=0.95, rank=1)]
    keyword_results = []

    fused = service.rrf_fuse(vector_results, keyword_results, k_rrf=60)
    assert len(fused) == 1

    expected_score = 1.0 / (60 + 1)  # 1/61 ~ 0.016393
    assert abs(fused[0].rrf_score - expected_score) < 1e-5
    assert fused[0].fused_rank == 1
    assert fused[0].vector_rank == 1
    assert fused[0].keyword_rank is None


def test_rrf_deduplication_and_dual_match_boost():
    """Verify that a candidate in both vector and keyword search is merged and ranked higher."""
    service = HybridRetrievalService(db_session=None, rrf_k=60)

    # c1 is rank 2 in vector, rank 2 in keyword
    # c2 is rank 1 in vector only
    # c3 is rank 1 in keyword only
    vector_results = [
        make_chunk("c2", score=0.99, rank=1),
        make_chunk("c1", score=0.85, rank=2),
    ]
    keyword_results = [
        make_chunk("c3", score=10.0, rank=1),
        make_chunk("c1", score=5.0, rank=2),
    ]

    fused = service.rrf_fuse(vector_results, keyword_results, k_rrf=60)

    # Must contain exactly 3 unique candidates (c1 deduplicated)
    assert len(fused) == 3
    chunk_ids = [c.chunk_id for c in fused]
    assert len(set(chunk_ids)) == 3

    # c1 received score from BOTH lists: 1/(60+2) + 1/(60+2) = 2/62 ~ 0.032258
    # c2 received score from vector only: 1/(60+1) = 1/61 ~ 0.016393
    # c3 received score from keyword only: 1/(60+1) = 1/61 ~ 0.016393
    # Therefore, c1 must be ranked #1
    assert fused[0].chunk_id == "c1"
    assert fused[0].fused_rank == 1
    assert fused[0].vector_rank == 2
    assert fused[0].keyword_rank == 2

    expected_c1_score = (1.0 / 62) + (1.0 / 62)
    assert abs(fused[0].rrf_score - expected_c1_score) < 1e-5


def test_rrf_empty_inputs():
    """Verify handling when one or both search results are empty."""
    service = HybridRetrievalService(db_session=None, rrf_k=60)

    # Both empty
    assert service.rrf_fuse([], [], k_rrf=60) == []

    # Vector only
    v_results = [make_chunk("c1", 0.9, 1), make_chunk("c2", 0.8, 2)]
    fused_v = service.rrf_fuse(v_results, [], k_rrf=60)
    assert len(fused_v) == 2
    assert fused_v[0].chunk_id == "c1"
    assert fused_v[1].chunk_id == "c2"

    # Keyword only
    k_results = [make_chunk("c3", 5.0, 1)]
    fused_k = service.rrf_fuse([], k_results, k_rrf=60)
    assert len(fused_k) == 1
    assert fused_k[0].chunk_id == "c3"


def test_rrf_custom_k_parameter():
    """Verify that custom k_rrf constant scales scores accordingly."""
    service = HybridRetrievalService(db_session=None)
    v_results = [make_chunk("c1", 0.9, 1)]

    # Custom k=10
    fused = service.rrf_fuse(v_results, [], k_rrf=10)
    expected = 1.0 / (10 + 1)
    assert abs(fused[0].rrf_score - expected) < 1e-5

    with pytest.raises(ValueError, match="k_rrf constant must be positive"):
        service.rrf_fuse(v_results, [], k_rrf=0)
