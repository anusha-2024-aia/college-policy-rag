"""Tests for Phase 6 Evaluation Framework (eval/schemas.py, eval/metrics.py, eval/runner.py)."""

import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from eval.schemas import (
    ExpectedSource,
    GoldenQuestion,
    CandidateItem,
    CitationItem,
    QuestionEvalResult,
    ConfigMetrics,
    EvaluationSummaryReport,
)
from eval.metrics import (
    matches_expected_source,
    calculate_hit_at_k,
    calculate_reciprocal_rank,
    check_unsupported_answer,
    check_stale_policy_error,
    check_missing_policy_conflict,
    check_information_leak,
    check_abstention,
    classify_failure,
    compute_ragas_metrics,
)
from eval.runner import EvaluationRunner, SUPPORTED_CONFIGS
from app.services.embedding import MockEmbeddingService
from app.services.reranker import MockRerankerService
from app.services.retrieval import HybridRetrievalService
from app.services.llm import MockLLMService
from app.services.qa import QAService
from tests.test_retrieval import setup_ingested_database


# ============================================================================
# 1. Schema Validation Tests
# ============================================================================

def test_expected_source_alias_normalization():
    """Verify ExpectedSource accepts 'file' and 'page' aliases and normalizes paths."""
    src1 = ExpectedSource.model_validate({"file": "data/raw_pdfs/policy.pdf", "page": 3})
    assert src1.file_name == "policy.pdf"
    assert src1.page_number == 3

    src2 = ExpectedSource.model_validate({"file_name": "handbook.pdf", "page_number": 1})
    assert src2.file_name == "handbook.pdf"
    assert src2.page_number == 1


def test_golden_question_validation_success():
    """Verify GoldenQuestion validates standard fields and normalizes roles."""
    data = {
        "id": "Q-001",
        "question": "What is the policy on remote work?",
        "role": "STUDENT",
        "expected_answer": "Employees may work remotely 3 days per week.",
        "expected_sources": [{"file": "policy_v2.pdf", "page": 1}],
        "should_abstain": False,
        "is_version_conflict": True,
        "superseded_sources": [{"file": "policy_v1.pdf", "page": 1}],
    }
    q = GoldenQuestion.model_validate(data)
    assert q.id == "Q-001"
    assert q.role == "student"
    assert len(q.expected_sources) == 1
    assert q.expected_sources[0].file_name == "policy_v2.pdf"
    assert q.is_version_conflict is True


def test_golden_question_rejects_invalid_role():
    """Verify GoldenQuestion rejects unpermitted roles with ValidationError."""
    with pytest.raises(ValidationError):
        GoldenQuestion.model_validate({
            "id": "Q-BAD",
            "question": "Test question?",
            "role": "hacker",
        })


# ============================================================================
# 2. Retrieval Metric Tests (Hit Rate@5 and MRR)
# ============================================================================

def test_calculate_hit_at_k():
    """Verify Hit@5 calculation for rank 1, rank 5, rank 6 (miss), and page mismatch."""
    expected = [ExpectedSource(file_name="handbook.pdf", page_number=2)]

    # Hit at rank 1
    cands_rank1 = [
        CandidateItem(file_name="handbook.pdf", page_number=2, rank=1, score=0.9),
        CandidateItem(file_name="other.pdf", page_number=1, rank=2, score=0.8),
    ]
    assert calculate_hit_at_k(cands_rank1, expected, k=5) is True

    # Hit at rank 5
    cands_rank5 = [
        CandidateItem(file_name="other1.pdf", page_number=1, rank=1, score=0.9),
        CandidateItem(file_name="other2.pdf", page_number=1, rank=2, score=0.8),
        CandidateItem(file_name="other3.pdf", page_number=1, rank=3, score=0.7),
        CandidateItem(file_name="other4.pdf", page_number=1, rank=4, score=0.6),
        CandidateItem(file_name="handbook.pdf", page_number=2, rank=5, score=0.5),
    ]
    assert calculate_hit_at_k(cands_rank5, expected, k=5) is True

    # Miss at rank 6 (outside top 5)
    cands_rank6 = cands_rank5 + [
        CandidateItem(file_name="handbook.pdf", page_number=2, rank=6, score=0.4)
    ]
    # Replace rank 5 with other
    cands_rank6[4] = CandidateItem(file_name="other5.pdf", page_number=1, rank=5, score=0.5)
    assert calculate_hit_at_k(cands_rank6, expected, k=5) is False

    # Miss on page mismatch
    cands_wrong_page = [
        CandidateItem(file_name="handbook.pdf", page_number=99, rank=1, score=0.9)
    ]
    assert calculate_hit_at_k(cands_wrong_page, expected, k=5) is False

    # Empty inputs
    assert calculate_hit_at_k([], expected, k=5) is False
    assert calculate_hit_at_k(cands_rank1, [], k=5) is False


def test_calculate_reciprocal_rank():
    """Verify MRR calculation across various ranks and multiple matches."""
    expected = [
        ExpectedSource(file_name="handbook.pdf", page_number=2),
        ExpectedSource(file_name="policy.pdf", page_number=1),
    ]

    # Rank 1 match -> RR = 1.0
    cands1 = [CandidateItem(file_name="handbook.pdf", page_number=2, rank=1, score=0.9)]
    assert calculate_reciprocal_rank(cands1, expected) == 1.0

    # Rank 2 match -> RR = 0.5
    cands2 = [
        CandidateItem(file_name="unrelated.pdf", page_number=1, rank=1, score=0.9),
        CandidateItem(file_name="handbook.pdf", page_number=2, rank=2, score=0.8),
    ]
    assert calculate_reciprocal_rank(cands2, expected) == 0.5

    # Rank 4 match -> RR = 0.25
    cands4 = [
        CandidateItem(file_name="u1.pdf", page_number=1, rank=1, score=0.9),
        CandidateItem(file_name="u2.pdf", page_number=1, rank=2, score=0.8),
        CandidateItem(file_name="u3.pdf", page_number=1, rank=3, score=0.7),
        CandidateItem(file_name="policy.pdf", page_number=1, rank=4, score=0.6),
    ]
    assert calculate_reciprocal_rank(cands4, expected) == 0.25

    # Multiple matches: selects first match (rank 2, not rank 4)
    cands_multi = [
        CandidateItem(file_name="u1.pdf", page_number=1, rank=1, score=0.9),
        CandidateItem(file_name="policy.pdf", page_number=1, rank=2, score=0.8),
        CandidateItem(file_name="u3.pdf", page_number=1, rank=3, score=0.7),
        CandidateItem(file_name="handbook.pdf", page_number=2, rank=4, score=0.6),
    ]
    assert calculate_reciprocal_rank(cands_multi, expected) == 0.5

    # No match in candidate list -> RR = 0.0
    cands_miss = [CandidateItem(file_name="u1.pdf", page_number=1, rank=1, score=0.9)]
    assert calculate_reciprocal_rank(cands_miss, expected) == 0.0


# ============================================================================
# 3. Custom Domain Metrics Tests
# ============================================================================

def test_check_unsupported_answer():
    """Verify detection of answers without citations or with hallucinated indices."""
    golden = GoldenQuestion(id="Q-1", question="What is policy?", expected_sources=[ExpectedSource(file_name="a.pdf", page_number=1)])

    # Valid supported answer
    res_valid = QuestionEvalResult(
        question_id="Q-1",
        config_name="hybrid",
        role="student",
        question_text="What is policy?",
        answer="The policy is clear [1].",
        citations=[CitationItem(index=1, file_name="a.pdf", page_number=1)],
        abstained=False,
    )
    is_unsupp, _ = check_unsupported_answer(res_valid, golden)
    assert is_unsupp is False

    # Unsupported: non-abstained but zero citations
    res_no_cite = QuestionEvalResult(
        question_id="Q-1",
        config_name="hybrid",
        role="student",
        question_text="What is policy?",
        answer="The policy is clear without proof.",
        citations=[],
        abstained=False,
    )
    is_unsupp, reason = check_unsupported_answer(res_no_cite, golden)
    assert is_unsupp is True
    assert "without any verifiable citations" in reason

    # Unsupported: hallucinated citation bracket [99]
    res_hallucinated = QuestionEvalResult(
        question_id="Q-1",
        config_name="hybrid",
        role="student",
        question_text="What is policy?",
        answer="The policy is stated here [1] and secret facts [99].",
        citations=[CitationItem(index=1, file_name="a.pdf", page_number=1)],
        abstained=False,
    )
    is_unsupp, reason = check_unsupported_answer(res_hallucinated, golden)
    assert is_unsupp is True
    assert "99" in reason


def test_check_stale_policy_error():
    """Verify detection of stale-policy errors on version conflict queries."""
    golden = GoldenQuestion(
        id="Q-VER",
        question="What is the remote work allowance?",
        is_version_conflict=True,
        expected_sources=[ExpectedSource(file_name="policy_v2.pdf", page_number=1)],
        superseded_sources=[ExpectedSource(file_name="policy_v1.pdf", page_number=1)],
    )

    # Valid current-first response with conflict flag
    res_good = QuestionEvalResult(
        question_id="Q-VER",
        config_name="version_aware",
        role="student",
        question_text="What is the allowance?",
        answer="Current policy allows 3 days [1], superseding previous 1 day [2].",
        citations=[
            CitationItem(index=1, file_name="policy_v2.pdf", page_number=1),
            CitationItem(index=2, file_name="policy_v1.pdf", page_number=1),
        ],
        has_policy_conflict=True,
        abstained=False,
    )
    is_stale, _ = check_stale_policy_error(res_good, golden)
    assert is_stale is False

    # Answer cites active policy: no stale error even without conflict flag
    res_no_conflict_flag = QuestionEvalResult(
        question_id="Q-VER",
        config_name="version_aware",
        role="student",
        question_text="What is the allowance?",
        answer="Current policy allows 3 days [1].",
        citations=[CitationItem(index=1, file_name="policy_v2.pdf", page_number=1)],
        has_policy_conflict=False,
        abstained=False,
    )
    is_stale, _ = check_stale_policy_error(res_no_conflict_flag, golden)
    assert is_stale is False  # Corrected: active policy was cited!
    is_missing, reason = check_missing_policy_conflict(res_no_conflict_flag, golden)
    assert is_missing is True
    assert "Failed to detect and flag policy conflict" in reason

    # Stale error: cited only superseded document
    res_cited_only_old = QuestionEvalResult(
        question_id="Q-VER",
        config_name="version_aware",
        role="student",
        question_text="What is the allowance?",
        answer="Policy allows 1 day [1].",
        citations=[CitationItem(index=1, file_name="policy_v1.pdf", page_number=1)],
        has_policy_conflict=True,
        abstained=False,
    )
    is_stale, reason = check_stale_policy_error(res_cited_only_old, golden)
    assert is_stale is True
    assert "cited superseded policy as authoritative" in reason

    # Abstention on version conflict is NOT a stale policy citation error
    res_abstained = QuestionEvalResult(
        question_id="Q-VER",
        config_name="version_aware",
        role="student",
        question_text="What is the allowance?",
        answer="I do not have sufficient information in the provided documents to answer this question.",
        citations=[],
        has_policy_conflict=False,
        abstained=True,
    )
    is_stale_abs, _ = check_stale_policy_error(res_abstained, golden)
    assert is_stale_abs is False
    is_missing_abs, _ = check_missing_policy_conflict(res_abstained, golden)
    assert is_missing_abs is False


def test_check_information_leak():
    """Verify unauthorized information leak detection."""
    golden = GoldenQuestion(
        id="Q-SEC",
        question="What is executive compensation?",
        role="student",
        expected_sources=[ExpectedSource(file_name="admin_salaries.pdf", page_number=1)],
        restricted_for_roles=["student"],
    )

    # Clean: student abstained with 0 chunks
    res_clean = QuestionEvalResult(
        question_id="Q-SEC",
        config_name="hybrid",
        role="student",
        question_text="What is compensation?",
        retrieved_candidates=[],
        citations=[],
        abstained=True,
    )
    is_leak, _ = check_information_leak(res_clean, golden)
    assert is_leak is False

    # Leak: restricted chunk was retrieved for student
    res_leak = QuestionEvalResult(
        question_id="Q-SEC",
        config_name="hybrid",
        role="student",
        question_text="What is compensation?",
        retrieved_candidates=[
            CandidateItem(file_name="admin_salaries.pdf", page_number=1, rank=1, score=0.9)
        ],
        citations=[CitationItem(index=1, file_name="admin_salaries.pdf", page_number=1)],
        abstained=False,
    )
    is_leak, reason = check_information_leak(res_leak, golden)
    assert is_leak is True
    assert "admin_salaries.pdf" in reason


def test_classify_failure_taxonomy():
    """Verify failure classification maps correctly to taxonomy categories."""
    golden = GoldenQuestion(
        id="Q-1",
        question="Test query?",
        expected_sources=[ExpectedSource(file_name="doc.pdf", page_number=1)],
        should_abstain=False,
    )

    # 1. Retrieval Miss: candidate pool has none of the expected sources
    res_retrieval_miss = QuestionEvalResult(
        question_id="Q-1",
        config_name="vector_only",
        role="student",
        question_text="Test query?",
        retrieved_candidates=[CandidateItem(file_name="wrong.pdf", page_number=1, rank=1, score=0.5)],
        hit_at_5=False,
    )
    cat, _ = classify_failure(res_retrieval_miss, golden)
    assert cat == "retrieval_miss"

    # 2. Ranking Miss: candidate pool has target, but ranked > 5
    res_ranking_miss = QuestionEvalResult(
        question_id="Q-1",
        config_name="vector_only",
        role="student",
        question_text="Test query?",
        retrieved_candidates=[
            CandidateItem(file_name="wrong.pdf", page_number=1, rank=1, score=0.5),
            CandidateItem(file_name="doc.pdf", page_number=1, rank=7, score=0.3),
        ],
        hit_at_5=False,
    )
    cat, _ = classify_failure(res_ranking_miss, golden)
    assert cat == "ranking_miss"

    # 3. Abstention Error: should_abstain is True but system answered
    golden_abs = GoldenQuestion(id="Q-2", question="Mars?", should_abstain=True)
    res_failed_abs = QuestionEvalResult(
        question_id="Q-2",
        config_name="hybrid",
        role="student",
        question_text="Mars?",
        abstained=False,
    )
    cat, _ = classify_failure(res_failed_abs, golden_abs)
    assert cat == "abstention_error"


def test_compute_ragas_metrics_distinguishes_unavailable_from_zero():
    """Verify compute_ragas_metrics returns (None, None) when package or provider is absent, never 0.00."""
    faith, relev = compute_ragas_metrics([])
    # In test environment without ragas or active OpenAI key, metrics must be None
    assert faith is None
    assert relev is None


# ============================================================================
# 4. End-to-End Multi-Configuration Runner Test (Synthetic Smoke Benchmark)
# ============================================================================

def test_evaluation_runner_all_5_configurations(
    test_db: Session,
    sample_pdf_workspace: Path,
    mock_embedding_service: MockEmbeddingService,
):
    """Execute all 5 benchmark configurations on a verified 5-question mini golden set."""
    setup_ingested_database(test_db, sample_pdf_workspace, mock_embedding_service)

    retrieval_svc = HybridRetrievalService(
        db_session=test_db,
        embedding_service=mock_embedding_service,
        reranker_service=MockRerankerService(),
    )
    qa_svc = QAService(
        retrieval_service=retrieval_svc,
        llm_service=MockLLMService(),
    )

    runner = EvaluationRunner(
        db_session=test_db,
        retrieval_service=retrieval_svc,
        qa_service=qa_svc,
        top_k=10,
        top_n=3,
    )

    # 5-question representative mini golden set
    golden_set = [
        # 1. Answerable standard question (valid_doc.pdf, page 1)
        GoldenQuestion(
            id="Q-001",
            question="What is the corporate architecture and mission?",
            role="student",
            expected_sources=[ExpectedSource(file_name="valid_doc.pdf", page_number=1)],
            should_abstain=False,
        ),
        # 2. Answerable standard question (valid_doc.pdf, page 3)
        GoldenQuestion(
            id="Q-002",
            question="What are the guidelines on confidential data retention and encryption?",
            role="student",
            expected_sources=[ExpectedSource(file_name="valid_doc.pdf", page_number=3)],
            should_abstain=False,
        ),
        # 3. Version conflict question (policy_v2.pdf superseding policy_v1)
        GoldenQuestion(
            id="Q-003",
            question="What is Policy V2 and its updated guidelines?",
            role="faculty",
            expected_sources=[ExpectedSource(file_name="policy_v2.pdf", page_number=1)],
            is_version_conflict=False,  # in sample workspace policy_v1 is not present so not a dual-conflict
            should_abstain=False,
        ),
        # 4. Unanswerable question expecting safe abstention
        GoldenQuestion(
            id="Q-004",
            question="What are the warp drive speed of light regulations on mars?",
            role="student",
            should_abstain=True,
            expected_sources=[],
        ),
        # 5. Role restricted query with student role
        GoldenQuestion(
            id="Q-005",
            question="What is corporate architecture?",
            role="student",
            should_abstain=False,
            expected_sources=[ExpectedSource(file_name="valid_doc.pdf", page_number=1)],
        ),
    ]

    for cfg in SUPPORTED_CONFIGS:
        metrics, results = runner.evaluate_configuration(cfg, golden_set)

        # Assertions across every configuration
        assert metrics.config_name == cfg
        assert metrics.total_queries == 5
        assert metrics.eval_retrieval_queries == 4  # 4 answerable queries with expected sources
        assert metrics.hit_rate_at_5 >= 0.0
        assert metrics.mean_reciprocal_rank >= 0.0
        assert metrics.information_leak_rate == 0.0  # ZERO leaks permitted
        assert metrics.average_latency_ms >= 0.0
        assert len(results) == 5

        # Verify unavailable metrics are properly represented as None, not 0.0
        assert metrics.faithfulness is None
        assert metrics.answer_relevance is None

        # Verify safe abstention on unanswerable Q-004
        q4_res = next(r for r in results if r.question_id == "Q-004")
        assert q4_res.abstained is True
        assert q4_res.is_correct_abstention is True
