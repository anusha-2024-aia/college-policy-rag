"""Targeted regression tests for Stage 3 verification fixes.

Covers:
- KVIT-014 partial amendment retrieval of circular alongside base clause 4.2
- RBAC exclusion and clean abstention for student/faculty on restricted documents
- Out-of-corpus clean abstention without unsupported hallucinations
- Ensuring legitimate answerable queries still receive supported answers
"""

import pytest
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.schemas.qa import AskRequest
from app.services.retrieval import HybridRetrievalService
from app.services.embedding import get_embedding_service
from app.services.reranker import get_reranker_service
from app.services.llm import get_llm_service
from app.services.qa import QAService


@pytest.fixture(scope="module")
def live_qa_service():
    """Create QA service bound to live test database with mock embeddings and deterministic mock LLM."""
    db: Session = SessionLocal()
    embedding_svc = get_embedding_service(force_mock=True)
    reranker_svc = get_reranker_service()
    llm_svc = get_llm_service(force_mock=True)
    retrieval_svc = HybridRetrievalService(
        db_session=db,
        embedding_service=embedding_svc,
        reranker_service=reranker_svc,
    )
    qa_svc = QAService(retrieval_service=retrieval_svc, llm_service=llm_svc)
    yield qa_svc
    db.close()


def test_kvit014_partial_amendment_retrieves_circular_and_base_clause(live_qa_service: QAService):
    """KVIT-014: Ensure query about amended Clause 4.2 retrieves 2025 circular alongside base 2023 clause."""
    req = AskRequest(
        question="What is the minimum End-Semester Examination mark required to pass a theory course under Clause 4.2?",
        role="student",
        version_aware=True,
        abstention_threshold=0.00005,
    )
    resp = live_qa_service.answer(req)

    assert resp.abstained is False
    assert resp.has_policy_conflict is True

    # Both the 2025 amendment circular and the 2023 base document must be in citations
    cited_files = {c.file_name for c in resp.citations}
    assert "exam_rules_amendment_circular_2025.pdf" in cited_files
    assert "examination_assessment_rules_2023.pdf" in cited_files

    # Active amendment must be cited as index 1
    assert resp.citations[0].file_name == "exam_rules_amendment_circular_2025.pdf"
    assert "[1]" in resp.answer
    assert "[2]" in resp.answer


def test_student_restricted_faculty_query_abstains_cleanly(live_qa_service: QAService):
    """KVIT-019 / KVIT-022: Student querying faculty-only policies receives clean abstention and zero leaks."""
    req = AskRequest(
        question="What is the weekly teaching load for an Assistant Professor and the invigilation remuneration per session under faculty service rules?",
        role="student",
        version_aware=True,
        abstention_threshold=0.00005,
    )
    resp = live_qa_service.answer(req)

    assert resp.abstained is True
    assert resp.answer == live_qa_service.ABSTENTION_SENTENCE
    assert resp.citations == []
    # Zero restricted chunks in response passages
    assert not any(p.file_name == "faculty_service_rules_2025.pdf" for p in resp.passages)


def test_student_restricted_admin_salary_query_abstains_cleanly(live_qa_service: QAService):
    """KVIT-025: Student querying admin-only salary bands receives clean abstention and zero leaks."""
    req = AskRequest(
        question="What is the approved annual operating budget for 2025-26, and what is the monthly salary band for a Professor?",
        role="student",
        version_aware=True,
        abstention_threshold=0.00005,
    )
    resp = live_qa_service.answer(req)

    assert resp.abstained is True
    assert resp.answer == live_qa_service.ABSTENTION_SENTENCE
    assert resp.citations == []
    assert not any("admin_salary" in p.file_name for p in resp.passages)


def test_faculty_restricted_admin_budget_query_abstains_cleanly(live_qa_service: QAService):
    """KVIT-024: Faculty querying admin-only budget receives clean abstention."""
    req = AskRequest(
        question="What is the approved annual operating budget for 2025-26, and what is the monthly salary band for a Professor?",
        role="faculty",
        version_aware=True,
        abstention_threshold=0.00005,
    )
    resp = live_qa_service.answer(req)

    assert resp.abstained is True
    assert resp.answer == live_qa_service.ABSTENTION_SENTENCE
    assert resp.citations == []


def test_admin_authorized_salary_query_succeeds(live_qa_service: QAService):
    """KVIT-023: Admin querying admin-only salary bands receives supported answer and citations."""
    req = AskRequest(
        question="What is the approved annual operating budget for 2025-26, and what is the monthly salary band for a Professor?",
        role="admin",
        version_aware=True,
        abstention_threshold=0.00005,
    )
    resp = live_qa_service.answer(req)

    assert resp.abstained is False
    cited_files = {c.file_name for c in resp.citations}
    assert "admin_salary_bands_and_budget_2025.pdf" in cited_files


def test_out_of_corpus_questions_abstain_without_hallucinations(live_qa_service: QAService):
    """KVIT-031 / KVIT-032 / KVIT-033: Unanswerable out-of-corpus queries must abstain with zero citations."""
    queries = [
        "What are the rules and safety requirements for operating autonomous flying drones on the KVIT cricket ground?",
        "What is the procedure for students to obtain scuba diving equipment certification from the university sports complex?",
        "How much annual research funding does KVIT receive from international aerospace agencies for Martian soil exploration?",
    ]
    for q in queries:
        req = AskRequest(
            question=q,
            role="student",
            version_aware=True,
            abstention_threshold=0.00005,
        )
        resp = live_qa_service.answer(req)
        assert resp.abstained is True, f"Failed to abstain on out-of-corpus query: {q}"
        assert resp.answer == live_qa_service.ABSTENTION_SENTENCE
        assert resp.citations == []


def test_legitimate_answerable_question_receives_answer(live_qa_service: QAService):
    """Ensure legitimate questions are NOT falsely abstained."""
    req = AskRequest(
        question="What is the fee for replacing a lost student ID card, and what are the campus gate hours?",
        role="student",
        version_aware=True,
        abstention_threshold=0.00005,
    )
    resp = live_qa_service.answer(req)

    assert resp.abstained is False
    assert len(resp.citations) > 0
    assert resp.citations[0].file_name == "student_handbook_2025.pdf"
