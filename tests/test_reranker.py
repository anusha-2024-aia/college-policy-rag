"""Tests for reranking services and candidate output limits."""

from app.schemas.retrieval import FusedChunk
from app.services.reranker import MockRerankerService, get_reranker_service


def make_fused_candidate(cid: str, text: str, rrf_score: float = 0.016) -> FusedChunk:
    """Helper creating a test FusedChunk."""
    return FusedChunk(
        chunk_id=cid,
        document_id="doc-1",
        file_name="handbook.pdf",
        title="Handbook",
        page_number=1,
        text=text,
        rrf_score=rrf_score,
        fused_rank=1,
    )


def test_reranker_strictly_limits_top_n():
    """Verify reranker returns exactly top_n candidates when candidate pool is larger."""
    reranker = MockRerankerService()
    candidates = [
        make_fused_candidate(f"c{i}", f"Document text passage number {i} discussing enterprise operations.")
        for i in range(10)
    ]

    reranked = reranker.rerank(query="enterprise operations", candidates=candidates, top_n=3)
    assert len(reranked) == 3

    # Ensure ranks are sequential 1, 2, 3
    assert [r.final_rank for r in reranked] == [1, 2, 3]


def test_reranker_fewer_candidates_than_top_n():
    """Verify reranker returns all candidates when pool is smaller than top_n."""
    reranker = MockRerankerService()
    candidates = [
        make_fused_candidate("c1", "First policy."),
        make_fused_candidate("c2", "Second policy."),
    ]

    reranked = reranker.rerank(query="policy", candidates=candidates, top_n=5)
    assert len(reranked) == 2


def test_reranker_empty_and_zero_top_n():
    """Verify reranker safely handles empty candidate lists or top_n <= 0."""
    reranker = MockRerankerService()

    assert reranker.rerank(query="test", candidates=[], top_n=5) == []

    candidate = make_fused_candidate("c1", "Some text")
    assert reranker.rerank(query="test", candidates=[candidate], top_n=0) == []
    assert reranker.rerank(query="test", candidates=[candidate], top_n=-1) == []


def test_reranker_reorders_by_relevance():
    """Verify that a candidate with matching query terms is promoted to rank #1."""
    reranker = MockRerankerService()

    # Candidate 1 has high prior RRF score but irrelevant text
    c1 = make_fused_candidate(
        "c1",
        text="Facility management guidelines and emergency exit stairwell rules.",
        rrf_score=0.032,
    )

    # Candidate 2 has lower prior RRF score but exact keyword and phrase match
    c2 = make_fused_candidate(
        "c2",
        text="Remote work policy: Employees may work hybrid up to three days per week.",
        rrf_score=0.016,
    )

    reranked = reranker.rerank(query="remote work hybrid policy", candidates=[c1, c2], top_n=2)

    assert len(reranked) == 2
    assert reranked[0].chunk_id == "c2"
    assert reranked[0].final_rank == 1
    assert reranked[1].chunk_id == "c1"
    assert reranked[1].final_rank == 2
    assert reranked[0].rerank_score > reranked[1].rerank_score


def test_get_reranker_service_factory():
    """Verify factory returns MockRerankerService for testing/offline environments."""
    svc = get_reranker_service(force_mock=True)
    assert isinstance(svc, MockRerankerService)


def test_flashrank_reranker_service():
    """Verify FlashRank reranker scores and re-ranks candidates locally on CPU."""
    from app.services.reranker import FlashRankRerankerService
    reranker = FlashRankRerankerService(model="ms-marco-TinyBERT-L-2-v2")
    c1 = make_fused_candidate("c1", "Irrelevant document about deep space astronomical physics.")
    c2 = make_fused_candidate("c2", "College remote work and hybrid attendance policy for staff.")
    results = reranker.rerank(query="remote work attendance", candidates=[c1, c2], top_n=2)
    assert len(results) == 2
    assert results[0].chunk_id == "c2"
    assert results[0].final_rank == 1
    assert results[0].rerank_score > results[1].rerank_score
