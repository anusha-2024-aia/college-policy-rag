"""Tests for Phase 5.1A Strengthened Semantic Retrieval Evaluation (eval/semantic_benchmark.py)."""

import pytest
import math
from pathlib import Path
from eval.semantic_benchmark import (
    compute_cosine_similarity,
    rank_passages,
    compute_retrieval_ranking_metrics,
    build_pooled_corpus,
    evaluate_retrieval_benchmark,
    run_phase_5_1a_audit,
    SYNTHETIC_BENCHMARK_ITEMS,
    CANDIDATE_MODEL_CATALOG,
    MockEmbeddingService,
)


# ---------------------------------------------------------------------------
# 1. Cosine Similarity Mathematical Properties
# ---------------------------------------------------------------------------

def test_cosine_similarity_math():
    """Verify mathematical axioms of cosine similarity."""
    v1 = [1.0, 2.0, 3.0]
    assert pytest.approx(compute_cosine_similarity(v1, v1), rel=1e-5) == 1.0

    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    assert pytest.approx(compute_cosine_similarity(v2, v3), abs=1e-5) == 0.0

    v4 = [1.0, 1.0]
    v5 = [-1.0, -1.0]
    assert pytest.approx(compute_cosine_similarity(v4, v5), rel=1e-5) == -1.0

    v_zero = [0.0, 0.0, 0.0]
    assert compute_cosine_similarity(v1, v_zero) == 0.0

    with pytest.raises(ValueError) as exc:
        compute_cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])
    assert "Vector dimensions do not match" in str(exc.value)


# ---------------------------------------------------------------------------
# 2. Hand-Verifiable Ranking & Retrieval Metrics Tests (Ties, Missing, Multi)
# ---------------------------------------------------------------------------

def test_rank_passages_hand_verifiable_and_deterministic_ties():
    """Verify rank_passages orders by similarity descending and breaks ties by ID ascending."""
    query_vec = [1.0, 0.0]
    candidates = [
        [0.0, 1.0],  # sim = 0.0 (P-C)
        [1.0, 0.0],  # sim = 1.0 (P-A)
        [0.5, 0.5],  # sim = ~0.707 (P-B)
    ]
    candidate_ids = ["P-C", "P-A", "P-B"]

    ranked = rank_passages(query_vec, candidates, candidate_ids)
    assert ranked[0][0] == "P-A"
    assert pytest.approx(ranked[0][1], rel=1e-4) == 1.0
    assert ranked[1][0] == "P-B"
    assert ranked[2][0] == "P-C"

    # Test deterministic tie-breaking (identical similarity: 0.5, 0.5)
    tie_candidates = [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]
    tie_ids = ["ID-Z", "ID-A", "ID-M"]
    ranked_ties = rank_passages(query_vec, tie_candidates, tie_ids)
    # Secondary sort must be alphabetical by ID
    assert [r[0] for r in ranked_ties] == ["ID-A", "ID-M", "ID-Z"]


def test_retrieval_metrics_hand_verifiable_scenarios():
    """Verify compute_retrieval_ranking_metrics against hand-calculated cases."""
    # Dummy ranked results with 6 passages
    ranked = [
        ("P1", 0.95),
        ("P2", 0.85),
        ("P3", 0.75),
        ("P4", 0.65),
        ("P5", 0.55),
        ("P6", 0.45),
    ]

    # Scenario 1: Target at Rank 1
    m1 = compute_retrieval_ranking_metrics(ranked, ["P1"])
    assert m1["first_relevant_rank"] == 1
    assert m1["reciprocal_rank"] == 1.0
    assert m1["hit_at_k"] == {1: 1, 3: 1, 5: 1}
    assert m1["recall_at_k"] == {1: 1.0, 3: 1.0, 5: 1.0}

    # Scenario 2: Target at Rank 2
    m2 = compute_retrieval_ranking_metrics(ranked, ["P2"])
    assert m2["first_relevant_rank"] == 2
    assert m2["reciprocal_rank"] == 0.5
    assert m2["hit_at_k"] == {1: 0, 3: 1, 5: 1}
    assert m2["recall_at_k"] == {1: 0.0, 3: 1.0, 5: 1.0}

    # Scenario 3: Target at Rank 4
    m3 = compute_retrieval_ranking_metrics(ranked, ["P4"])
    assert m3["first_relevant_rank"] == 4
    assert m3["reciprocal_rank"] == 0.25
    assert m3["hit_at_k"] == {1: 0, 3: 0, 5: 1}
    assert m3["recall_at_k"] == {1: 0.0, 3: 0.0, 5: 1.0}

    # Scenario 4: Target at Rank 6 (outside top 5)
    m4 = compute_retrieval_ranking_metrics(ranked, ["P6"])
    assert m4["first_relevant_rank"] == 6
    assert pytest.approx(m4["reciprocal_rank"], rel=1e-4) == 1.0 / 6.0
    assert m4["hit_at_k"] == {1: 0, 3: 0, 5: 0}
    assert m4["recall_at_k"] == {1: 0.0, 3: 0.0, 5: 0.0}

    # Scenario 5: Missing target (not found in corpus)
    m5 = compute_retrieval_ranking_metrics(ranked, ["P_MISSING"])
    assert m5["first_relevant_rank"] is None
    assert m5["reciprocal_rank"] == 0.0
    assert m5["hit_at_k"] == {1: 0, 3: 0, 5: 0}
    assert m5["recall_at_k"] == {1: 0.0, 3: 0.0, 5: 0.0}

    # Scenario 6: Multiple relevant targets (P1 and P4)
    m6 = compute_retrieval_ranking_metrics(ranked, ["P1", "P4"])
    assert m6["first_relevant_rank"] == 1
    assert m6["reciprocal_rank"] == 1.0
    # At k=1: only P1 found -> hit=1, recall=0.5
    # At k=3: only P1 found -> hit=1, recall=0.5
    # At k=5: P1 and P4 found -> hit=1, recall=1.0
    assert m6["hit_at_k"] == {1: 1, 3: 1, 5: 1}
    assert m6["recall_at_k"] == {1: 0.5, 3: 0.5, 5: 1.0}


# ---------------------------------------------------------------------------
# 3. Expanded Dataset & Corpus Integrity
# ---------------------------------------------------------------------------

def test_expanded_synthetic_benchmark_dataset_integrity():
    """Verify structure, diversity, and non-emptiness of the expanded 15-item dataset."""
    assert len(SYNTHETIC_BENCHMARK_ITEMS) == 15

    required_keys = {
        "id", "topic", "query",
        "relevant_passage_id", "relevant_passage",
        "hard_negative_id", "hard_negative_passage",
        "soft_distractor_id", "soft_distractor_passage",
        "notes"
    }

    seen_item_ids = set()
    seen_passage_ids = set()

    for item in SYNTHETIC_BENCHMARK_ITEMS:
        assert required_keys.issubset(item.keys())
        assert item["id"] not in seen_item_ids
        seen_item_ids.add(item["id"])

        # Check passage IDs are distinct
        for p_key in ["relevant_passage_id", "hard_negative_id", "soft_distractor_id"]:
            pid = item[p_key]
            assert pid not in seen_passage_ids
            seen_passage_ids.add(pid)

        # Confirm non-trivial lengths
        assert len(item["query"].strip()) >= 15
        assert len(item["relevant_passage"].strip()) >= 50
        assert len(item["hard_negative_passage"].strip()) >= 50
        assert len(item["soft_distractor_passage"].strip()) >= 50


def test_build_pooled_corpus_structure():
    """Verify pooled corpus compiles exactly 45 unique passages across 3 types."""
    corpus = build_pooled_corpus(SYNTHETIC_BENCHMARK_ITEMS)
    assert len(corpus) == 45

    types = [p.passage_type for p in corpus]
    assert types.count("relevant") == 15
    assert types.count("hard_negative") == 15
    assert types.count("soft_distractor") == 15

    unique_ids = {p.id for p in corpus}
    assert len(unique_ids) == 45


# ---------------------------------------------------------------------------
# 4. Empirical Mock Embedding Retrieval Quality & Separation Failure
# ---------------------------------------------------------------------------

def test_mock_embedding_empirical_retrieval_and_separation():
    """Empirically evaluate MockEmbeddingService across 15 queries and 45 pooled passages."""
    mock_service = MockEmbeddingService(dimension=1536)
    report = evaluate_retrieval_benchmark(
        service=mock_service,
        model_name="deterministic-mock-sha256",
        is_mock=True,
        items=SYNTHETIC_BENCHMARK_ITEMS,
    )

    assert report.total_queries == 15
    assert report.corpus_size == 45
    assert report.dimension == 1536
    assert report.is_mock is True

    # 1. Cosine similarity diagnostics:
    # Deterministic SHA-256 hash vectors have near-zero semantic correlation.
    # Mean separation delta vs hard negatives and distractors remains small (|delta| < 0.15).
    assert abs(report.mean_delta_hard_negative) < 0.15
    assert abs(report.mean_delta_soft_distractor) < 0.15

    # 2. Corpus retrieval ranking metrics:
    # In a corpus of 45 passages, random hash ranking produces poor Recall@1 and low MRR.
    # Confirm Recall@1 does not exhibit genuine retrieval performance (Recall@1 <= 0.35).
    assert report.recall_at_1 <= 0.35
    assert report.mrr <= 0.35


# ---------------------------------------------------------------------------
# 5. Candidate Catalog & Audit Execution
# ---------------------------------------------------------------------------

def test_candidate_model_catalog_audit_specs():
    """Verify all 5 candidate models are cataloged with dimension and status."""
    assert len(CANDIDATE_MODEL_CATALOG) == 5
    catalog_map = {m.name: m for m in CANDIDATE_MODEL_CATALOG}

    assert catalog_map["deterministic-mock-sha256"].dimension == 1536
    assert catalog_map["deterministic-mock-sha256"].current_status == "ACTIVE (Baseline / Mock)"

    assert catalog_map["text-embedding-3-small"].dimension == 1536
    assert "BLOCKED" in catalog_map["text-embedding-3-small"].current_status

    assert catalog_map["text-embedding-004"].dimension == 768
    assert "INCOMPATIBLE" in catalog_map["text-embedding-004"].storage_compatibility
    assert "BLOCKED" in catalog_map["text-embedding-004"].current_status

    assert catalog_map["all-MiniLM-L6-v2"].dimension == 384
    assert catalog_map["bge-small-en-v1.5"].dimension == 384


def test_run_phase_5_1a_audit_output(tmp_path):
    """Verify run_phase_5_1a_audit generates valid structured JSON artifact."""
    result = run_phase_5_1a_audit(output_dir=str(tmp_path))

    assert result["audit_name"] == "Phase 5.1A: Strengthened Semantic Retrieval Evaluation & Dimension Strategy"
    assert result["dataset_metadata"]["total_queries"] == 15
    assert result["dataset_metadata"]["total_corpus_passages"] == 45
    assert result["real_models_status"]["status"] == "BLOCKED"
    assert result["real_models_status"]["fabricated_results"] is None

    written_files = list(tmp_path.glob("semantic_retrieval_benchmark_*.json"))
    assert len(written_files) == 1

    import json
    data = json.loads(written_files[0].read_text(encoding="utf-8"))
    assert data["mock_embedding_evaluation"]["total_queries"] == 15
    assert "empirical_conclusions" in data


# ---------------------------------------------------------------------------
# 6. Safety & Offline Guarantee
# ---------------------------------------------------------------------------

def test_offline_execution_no_network_or_db(monkeypatch):
    """Confirm Phase 5.1A execution makes zero network calls."""
    def forbidden_network(*args, **kwargs):
        raise RuntimeError("Network call attempted during Phase 5.1A offline execution!")

    import socket
    monkeypatch.setattr(socket, "create_connection", forbidden_network)

    mock_service = MockEmbeddingService(dimension=1536)
    report = evaluate_retrieval_benchmark(mock_service, "offline_test", is_mock=True)
    assert report.total_queries == 15
    assert report.corpus_size == 45
