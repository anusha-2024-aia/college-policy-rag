"""Tests for Phase 2: Version-Aware Retrieval, Time Travel, and Deterministic Conflict Detection."""

import pytest
from app.core.database import SessionLocal
from app.services.retrieval import HybridRetrievalService
from app.services.embedding import MockEmbeddingService
from app.services.reranker import FlashRankRerankerService
from app.services.llm import MockLLMService
from app.services.qa import QAService
from app.services.temporal import detect_temporal_intent
from app.services.conflict import detect_deterministic_change_cards
from app.schemas.qa import AskRequest, PassageEvidence


@pytest.fixture
def qa_service():
    """Build QAService wired to test SQLite database with MockEmbeddingService and FlashRank."""
    db = SessionLocal()
    retrieval_service = HybridRetrievalService(
        db_session=db,
        embedding_service=MockEmbeddingService(),
        reranker_service=FlashRankRerankerService(),
    )
    llm_service = MockLLMService()
    return QAService(retrieval_service=retrieval_service, llm_service=llm_service)


def test_minimum_attendance_change_card(qa_service):
    """DONE WHEN Criterion 1: 'minimum attendance' returns 75% with a change card showing 80% -> 75%."""
    request = AskRequest(question="minimum attendance", role="student")
    response = qa_service.answer(request)

    assert not response.abstained
    assert "75%" in response.answer
    assert response.has_policy_conflict is True
    assert len(response.change_cards) > 0

    # Locate minimum attendance change card
    att_card = next((c for c in response.change_cards if "attendance requirement" in c.topic.lower()), None)
    assert att_card is not None
    assert att_card.old.value == "80%"
    assert att_card.new.value == "75%"
    assert "attendance_leave_policy_2023.pdf" in att_card.old.source
    assert "attendance_leave_policy_2025.pdf" in att_card.new.source
    assert att_card.scope == "full"


def test_minimum_attendance_historical_time_travel(qa_service):
    """DONE WHEN Criterion 2: 'Minimum attendance in January 2025' returns 80%, labelled historical."""
    request = AskRequest(question="Minimum attendance in January 2025", role="student")
    response = qa_service.answer(request)

    assert not response.abstained
    assert "80%" in response.answer
    assert response.is_historical is True
    assert response.as_of == "2025-01-15"
    assert "historical rule" in response.answer.lower() or "no longer in force" in response.answer.lower()


def test_unchanged_clause_exam_reporting_no_conflict(qa_service):
    """DONE WHEN Criterion 3: 'How early must I report to the exam hall' returns 30 minutes with NO conflict flag."""
    request = AskRequest(question="How early must I report to the exam hall", role="student")
    response = qa_service.answer(request)

    assert not response.abstained
    assert "30 minutes" in response.answer
    assert response.has_policy_conflict is False
    assert len(response.change_cards) == 0
    assert response.is_historical is False


def test_temporal_intent_detection():
    """Verify temporal intent parser on various time expressions and historical phrases."""
    is_t1, d1, label1 = detect_temporal_intent("minimum attendance in January 2025")
    assert is_t1 is True
    assert d1.year == 2025 and d1.month == 1

    is_t2, d2, label2 = detect_temporal_intent("what was the curfew before July 2025?")
    assert is_t2 is True
    assert d2.year == 2025 and d2.month == 6

    is_t3, d3, label3 = detect_temporal_intent("what was the old rule for exam passing marks?")
    assert is_t3 is True
    assert d3.year < 2025

    is_t4, d4, label4 = detect_temporal_intent("what is the library opening time?")
    assert is_t4 is False


def test_lineage_expansion_toggle(qa_service):
    """Verify that LINEAGE_EXPANSION flag controls sibling expansion."""
    # With lineage expansion disabled, only top_n passages are retrieved without siblings
    req_no_le = AskRequest(question="minimum attendance", role="student", lineage_expansion=False, top_n=1)
    res_no_le = qa_service.answer(req_no_le)
    assert len(res_no_le.passages) == 1

    # With lineage expansion enabled (default), sibling chunk from 2025 is fetched
    req_le = AskRequest(question="minimum attendance", role="student", lineage_expansion=True, top_n=1)
    res_le = qa_service.answer(req_le)
    assert len(res_le.passages) >= 2
    sources = {p.file_name for p in res_le.passages}
    assert "attendance_leave_policy_2025.pdf" in sources
    assert "attendance_leave_policy_2023.pdf" in sources


def test_version_aware_toggle(qa_service):
    """Verify that VERSION_AWARE flag can disable version processing."""
    req_va_off = AskRequest(question="minimum attendance", role="student", version_aware=False)
    res_va_off = qa_service.answer(req_va_off)

    assert res_va_off.has_policy_conflict is False
    assert len(res_va_off.change_cards) == 0
    assert res_va_off.is_historical is False


def test_partial_amendment_conflict_clause_4_2():
    """Verify deterministic change card for partial amendment Clause 4.2."""
    p_circ = PassageEvidence(
        index=1,
        chunk_id="circ-1",
        file_name="exam_rules_amendment_circular_2025.pdf",
        page_number=1,
        text="Amendment to Clause 4.2: the minimum ESE mark required to pass a theory course is reduced from 24 out of 60 to 21 out of 60 (35%).",
        score=0.95,
        clause_ref="Clause 4.2",
        is_superseded=False,
    )
    p_base = PassageEvidence(
        index=2,
        chunk_id="base-1",
        file_name="academic_regulations_examination_assessment_2023.pdf",
        page_number=2,
        text="Clause 4.2. In addition, a student must secure at least 24 marks out of 60 in the ESE.",
        score=0.90,
        clause_ref="Clause 4.2",
        is_superseded=True,
    )
    cards = detect_deterministic_change_cards([p_circ, p_base])
    assert len(cards) >= 1
    card_42 = next((c for c in cards if "4.2" in c.topic), None)
    assert card_42 is not None
    assert card_42.old.value == "24 out of 60"
    assert card_42.new.value == "21 out of 60"
    assert card_42.scope == "partial"


def test_hostel_curfew_conflict():
    """Verify deterministic change cards for hostel regulations (curfew and visitors)."""
    p_2025 = PassageEvidence(
        index=1,
        chunk_id="hostel-25",
        file_name="hostel_rules_2025.pdf",
        page_number=1,
        text="Hostel curfew is 10:30 PM on weekdays. Visitors are allowed in the common room until 7:00 PM.",
        score=0.95,
        is_superseded=False,
    )
    p_2024 = PassageEvidence(
        index=2,
        chunk_id="hostel-24",
        file_name="hostel_rules_2024.pdf",
        page_number=1,
        text="Hostel curfew is 9:30 PM on weekdays. Visitors are allowed in the common room until 6:00 PM.",
        score=0.90,
        is_superseded=True,
    )
    cards = detect_deterministic_change_cards([p_2025, p_2024])
    curfew_card = next((c for c in cards if "Curfew" in c.topic), None)
    visitor_card = next((c for c in cards if "Visitor" in c.topic), None)

    assert curfew_card is not None
    assert curfew_card.old.value == "9:30 PM"
    assert curfew_card.new.value == "10:30 PM"

    assert visitor_card is not None
    assert visitor_card.old.value == "6:00 PM"
    assert visitor_card.new.value == "7:00 PM"

