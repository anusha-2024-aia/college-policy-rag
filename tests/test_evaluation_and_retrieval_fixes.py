"""Regression tests for evaluation metrics separation, keyword retrieval disjunction, abstention threshold, and version awareness."""

import pytest
from sqlalchemy.orm import Session

from eval.schemas import (
    CandidateItem,
    CitationItem,
    ConfigMetrics,
    ExpectedSource,
    GoldenQuestion,
    QuestionEvalResult,
)
from eval.metrics import (
    check_stale_policy_error,
    check_missing_policy_conflict,
    check_abstention,
    classify_failure,
)
from eval.runner import EvaluationRunner
from app.services.retrieval import (
    HybridRetrievalService,
    build_disjunctive_tsquery,
    ScoredChunk,
)
from app.services.embedding import MockEmbeddingService
from app.services.reranker import MockRerankerService
from app.services.llm import MockLLMService
from app.services.qa import QAService
from app.schemas.qa import AskRequest, PassageEvidence
from app.models.document import Document
from app.services.versioning import DocumentVersionService, DocumentVersionStatus
from tests.test_retrieval import setup_ingested_database


# ============================================================================
# 1. Evaluation Metrics Separation Tests
# ============================================================================

def test_stale_citation_vs_missing_conflict_separation():
    """Verify that citing active policy without setting conflict flag is NOT a stale citation error."""
    golden = GoldenQuestion(
        id="Q-VER-1",
        question="What is the remote work policy?",
        is_version_conflict=True,
        expected_sources=[ExpectedSource(file_name="employee_handbook_v2.pdf", page_number=2)],
        superseded_sources=[ExpectedSource(file_name="employee_handbook_v1.pdf", page_number=2)],
    )

    # Case A: Non-version-aware run cites active policy (handbook v2), but has_policy_conflict=False
    res_non_version_aware = QuestionEvalResult(
        question_id="Q-VER-1",
        config_name="hybrid_plus_reranking",
        role="admin",
        question_text="What is the remote work policy?",
        answer="Under the policy, remote work is permitted [1].",
        citations=[CitationItem(index=1, file_name="employee_handbook_v2.pdf", page_number=2)],
        has_policy_conflict=False,
        abstained=False,
    )
    is_stale, _ = check_stale_policy_error(res_non_version_aware, golden)
    is_missing, reason = check_missing_policy_conflict(res_non_version_aware, golden)

    assert is_stale is False, "Active policy was cited; this is NOT a stale citation error!"
    assert is_missing is True, "Conflict flag was False; this IS a missing conflict detection!"
    assert "Failed to detect and flag policy conflict" in reason

    # Case B: Version-aware run cites active policy AND sets has_policy_conflict=True
    res_version_aware = QuestionEvalResult(
        question_id="Q-VER-1",
        config_name="hybrid_plus_reranking_plus_version_awareness",
        role="admin",
        question_text="What is the remote work policy?",
        answer="Current policy permits remote work [1], superseding previous [2].",
        citations=[
            CitationItem(index=1, file_name="employee_handbook_v2.pdf", page_number=2),
            CitationItem(index=2, file_name="employee_handbook_v1.pdf", page_number=2),
        ],
        has_policy_conflict=True,
        abstained=False,
    )
    is_stale_b, _ = check_stale_policy_error(res_version_aware, golden)
    is_missing_b, _ = check_missing_policy_conflict(res_version_aware, golden)

    assert is_stale_b is False
    assert is_missing_b is False


def test_abstention_never_counts_as_stale_citation_error():
    """Verify that an abstention on a version inquiry is never scored as a stale citation error."""
    golden = GoldenQuestion(
        id="Q-VER-2",
        question="What is the mission statement?",
        is_version_conflict=True,
        expected_sources=[ExpectedSource(file_name="handbook_v2.pdf", page_number=1)],
        superseded_sources=[ExpectedSource(file_name="handbook_v1.pdf", page_number=1)],
    )

    res_abstained = QuestionEvalResult(
        question_id="Q-VER-2",
        config_name="vector_only",
        role="admin",
        question_text="What is the mission statement?",
        answer="I do not have sufficient information in the provided documents to answer this question.",
        citations=[],
        has_policy_conflict=False,
        abstained=True,
    )
    is_stale, _ = check_stale_policy_error(res_abstained, golden)
    is_missing, _ = check_missing_policy_conflict(res_abstained, golden)

    assert is_stale is False
    assert is_missing is False


def test_stale_citation_error_triggers_only_when_superseded_relied_on():
    """Verify that check_stale_policy_error triggers when answer cites superseded document without active."""
    golden = GoldenQuestion(
        id="Q-VER-3",
        question="What is the remote work policy?",
        is_version_conflict=True,
        expected_sources=[ExpectedSource(file_name="handbook_v2.pdf", page_number=2)],
        superseded_sources=[ExpectedSource(file_name="handbook_v1.pdf", page_number=2)],
    )

    # Answer citing ONLY the superseded v1 handbook
    res_superseded_only = QuestionEvalResult(
        question_id="Q-VER-3",
        config_name="vector_only",
        role="admin",
        question_text="What is the remote work policy?",
        answer="Remote work is limited to 1 day [1].",
        citations=[CitationItem(index=1, file_name="handbook_v1.pdf", page_number=2)],
        has_policy_conflict=False,
        abstained=False,
    )
    is_stale, reason = check_stale_policy_error(res_superseded_only, golden)
    assert is_stale is True
    assert "cited superseded policy as authoritative" in reason


def test_correct_denominators_and_na_metrics_when_no_eligible_answers():
    """Verify that stale_policy_error_rate is None (N/A) when all version queries abstained."""
    # When both version queries abstained, eligible answers = 0
    q1 = GoldenQuestion(id="Q-1", question="Query 1", is_version_conflict=True)
    q2 = GoldenQuestion(id="Q-2", question="Query 2", is_version_conflict=True)
    r1 = QuestionEvalResult(question_id="Q-1", config_name="test", role="admin", question_text="Q1", abstained=True)
    r2 = QuestionEvalResult(question_id="Q-2", config_name="test", role="admin", question_text="Q2", abstained=True)

    answered_vc = [
        (q, r) for q, r in zip([q1, q2], [r1, r2], strict=False)
        if q.is_version_conflict and not r.abstained
    ]
    assert len(answered_vc) == 0

    # Denominator check: must be None (N/A), not 0.0 or 1.0
    stale_rate = round(sum(1.0 for _, r in answered_vc if r.is_stale_policy_error) / len(answered_vc), 4) if answered_vc else None
    assert stale_rate is None


# ============================================================================
# 2. Keyword Retrieval Disjunction and Ranking Tests
# ============================================================================

def test_build_disjunctive_tsquery_removes_stop_words():
    """Verify that build_disjunctive_tsquery extracts alphanumeric words and strips conversational stop words."""
    query = "What is the remote work policy regarding hybrid schedules and required approvals?"
    ts_str = build_disjunctive_tsquery(query)

    assert ts_str is not None
    tokens = ts_str.split(" | ")
    # Conversational filler words must be stripped
    assert "what" not in tokens
    assert "is" not in tokens
    assert "the" not in tokens
    assert "regarding" not in tokens
    assert "and" not in tokens

    # Meaningful domain terms must be retained
    assert "remote" in tokens
    assert "work" in tokens
    assert "policy" in tokens
    assert "hybrid" in tokens
    assert "schedules" in tokens
    assert "required" in tokens
    assert "approvals" in tokens


def test_build_disjunctive_tsquery_sanitizes_special_characters():
    """Verify that build_disjunctive_tsquery sanitizes punctuation, quotes, and symbols."""
    malicious_query = "What's the policy? (v2.0) [CONFIDENTIAL] - 'admin' OR 1=1; --"
    ts_str = build_disjunctive_tsquery(malicious_query)

    assert ts_str is not None
    tokens = ts_str.split(" | ")
    for t in tokens:
        assert t.isalnum(), f"Token '{t}' contains non-alphanumeric characters!"


def test_keyword_search_with_disjunction_on_sqlite(
    test_db: Session,
    sample_pdf_workspace,
    mock_embedding_service: MockEmbeddingService,
):
    """Verify keyword retrieval executes cleanly with role filter on SQLite."""
    setup_ingested_database(test_db, sample_pdf_workspace, mock_embedding_service)
    retrieval_svc = HybridRetrievalService(
        db_session=test_db,
        embedding_service=mock_embedding_service,
        reranker_service=MockRerankerService(),
    )

    # Search for conversational phrase
    results = retrieval_svc.keyword_search("What is the remote work policy?", k=5, role="student")
    assert isinstance(results, list)
    assert len(results) > 0
    # Check RBAC: student should NOT retrieve admin_salaries
    for r in results:
        assert "admin_salaries" not in r.file_name.lower()


# ============================================================================
# 3. False Abstention and Threshold Calibration Tests
# ============================================================================

def test_abstention_threshold_default_is_calibrated():
    """Verify AskRequest abstention_threshold default is 0.00005."""
    req = AskRequest(question="Test question?", role="student")
    assert req.abstention_threshold == 0.00005


def test_qa_should_abstain_evaluates_evidence_and_answer_signal():
    """Verify should_abstain triggers on empty passages, low score, or explicit abstention sentence."""
    qa_svc = QAService(retrieval_service=None, llm_service=MockLLMService())

    # Empty passages -> True
    assert qa_svc.should_abstain("Answer", [], 0.00005) is True

    # Passage with score below threshold -> True
    low_passage = PassageEvidence(index=1, chunk_id="1", file_name="a.pdf", page_number=1, text="Text", score=0.00001)
    assert qa_svc.should_abstain("Answer", [low_passage], 0.00005) is True

    # Passage with score above threshold -> False
    good_passage = PassageEvidence(index=1, chunk_id="1", file_name="a.pdf", page_number=1, text="Text", score=0.0001)
    assert qa_svc.should_abstain("Answer [1]", [good_passage], 0.00005) is False

    # Explicit abstention sentence in answer -> True regardless of score
    abs_answer = "I do not have sufficient information in the provided documents to answer this question."
    assert qa_svc.should_abstain(abs_answer, [good_passage], 0.00005) is True


# ============================================================================
# 4. Version Awareness Edge Cases Tests
# ============================================================================

def test_version_awareness_detects_conflicts_only_when_both_in_evidence():
    """Verify DocumentVersionService.detect_conflicts behavior across version scenarios."""
    version_svc = DocumentVersionService()

    status_current = DocumentVersionStatus(
        document_id="doc-2",
        file_name="handbook_v2.pdf",
        title="Acme Handbook 2025",
        effective_date="2025-01-01",
        is_superseded=False,
        lineage_root_id="doc-1",
    )
    status_superseded = DocumentVersionStatus(
        document_id="doc-1",
        file_name="handbook_v1.pdf",
        title="Acme Handbook 2024",
        effective_date="2024-01-01",
        is_superseded=True,
        lineage_root_id="doc-1",
    )
    statuses = {"doc-1": status_superseded, "doc-2": status_current}

    # Case 1: Conflicting evidence (both v1 and v2 in evidence)
    p_cur = PassageEvidence(index=1, chunk_id="c2", file_name="handbook_v2.pdf", page_number=1, text="New text", score=0.9)
    p_old = PassageEvidence(index=2, chunk_id="c1", file_name="handbook_v1.pdf", page_number=1, text="Old text", score=0.8)
    has_conf, conflicts = version_svc.detect_conflicts([p_cur, p_old], statuses)
    assert has_conf is True
    assert len(conflicts) == 1
    assert conflicts[0].current_file == "handbook_v2.pdf"
    assert conflicts[0].superseded_file == "handbook_v1.pdf"

    # Case 2: Current-only evidence (only v2 in evidence)
    has_conf_cur, conflicts_cur = version_svc.detect_conflicts([p_cur], statuses)
    assert has_conf_cur is False
    assert len(conflicts_cur) == 0

    # Case 3: Superseded-only evidence (only v1 in evidence)
    has_conf_old, conflicts_old = version_svc.detect_conflicts([p_old], statuses)
    assert has_conf_old is False
    assert len(conflicts_old) == 0

    # Case 4: Missing version metadata (unregistered file)
    p_unreg = PassageEvidence(index=1, chunk_id="cx", file_name="unknown.pdf", page_number=1, text="Text", score=0.9)
    has_conf_unreg, conflicts_unreg = version_svc.detect_conflicts([p_unreg], statuses)
    assert has_conf_unreg is False
    assert len(conflicts_unreg) == 0
