"""Regression tests for partial amendments, version graph validation, and targeted conflict detection."""

import datetime
import pytest
from app.models.document import Document
from app.schemas.qa import PassageEvidence
from app.services.versioning import DocumentVersionService, DocumentVersionStatus
from app.services.qa import QAService
from app.services.llm import MockLLMService


def _get_exam_docs():
    return [
        Document(
            id="doc-rules-2023",
            file_name="examination_assessment_rules_2023.pdf",
            title="Examination and Assessment Rules",
            effective_date=datetime.date(2023, 8, 1),
            supersedes=None,
        ),
        Document(
            id="doc-amend-2025",
            file_name="exam_rules_amendment_circular_2025.pdf",
            title="Circular No. KVIT/ACAD/2025/014: Amendment to Examination and Assessment Rules",
            effective_date=datetime.date(2025, 7, 1),
            supersedes="partial: Clause 4.2 and Clause 6.1 only:examination_assessment_rules_2023.pdf",
        ),
    ]


def test_partial_amendment_version_graph():
    """Verify that a partial amendment marks predecessor as partially amended, NOT wholly superseded."""
    docs = _get_exam_docs()
    service = DocumentVersionService()
    status_map = service.build_version_graph(docs, strict_validation=True)

    status_2023 = status_map["doc-rules-2023"]
    status_2025 = status_map["doc-amend-2025"]

    # Predecessor 2023 rules must NOT be marked superseded
    assert status_2023.is_superseded is False, "2023 rules should remain active, not wholly superseded"
    assert status_2023.is_partially_amended is True
    assert status_2023.amendment_scope == "Clause 4.2 and Clause 6.1 only"
    assert status_2023.amended_by_file == "exam_rules_amendment_circular_2025.pdf"

    # Successor 2025 circular is active amendment
    assert status_2025.is_superseded is False
    assert status_2025.is_amendment is True
    assert status_2025.amends_file == "examination_assessment_rules_2023.pdf"
    assert status_2025.amendment_scope == "Clause 4.2 and Clause 6.1 only"


def test_amended_clause_4_2_flagged_as_conflict():
    """Verify that evidence from amended Clause 4.2 (passing mark 24 -> 21) IS flagged as a conflict."""
    docs = _get_exam_docs()
    service = DocumentVersionService()
    status_map = service.build_version_graph(docs, strict_validation=True)

    passages = [
        PassageEvidence(
            index=1,
            chunk_id="chk-amend-1",
            file_name="exam_rules_amendment_circular_2025.pdf",
            page_number=1,
            text="Amendment to Clause 4.2: the minimum ESE mark required to pass a theory course is reduced from 24 out of 60 to 21 out of 60 (35%).",
            score=0.95,
            effective_date="2025-07-01",
            is_superseded=False,
        ),
        PassageEvidence(
            index=2,
            chunk_id="chk-rules-4.2",
            file_name="examination_assessment_rules_2023.pdf",
            page_number=2,
            text="Clause 4.2. In theory courses, a student must secure a minimum of 24 marks out of 60 in the End Semester Examination to pass.",
            score=0.89,
            effective_date="2023-08-01",
            is_superseded=False,
            is_partially_amended=True,
            amendment_scope="Clause 4.2 and Clause 6.1 only",
        ),
    ]

    has_conflict, conflicts = service.detect_conflicts(passages, status_map)
    assert has_conflict is True, "Amended Clause 4.2 MUST trigger a policy conflict"
    assert len(conflicts) == 1
    assert "amended" in conflicts[0].description.lower()
    assert conflicts[0].current_file == "exam_rules_amendment_circular_2025.pdf"
    assert conflicts[0].superseded_file == "examination_assessment_rules_2023.pdf"


def test_amended_clause_6_1_flagged_as_conflict():
    """Verify that evidence from amended Clause 6.1 (re-evaluation window/fee) IS flagged as a conflict."""
    docs = _get_exam_docs()
    service = DocumentVersionService()
    status_map = service.build_version_graph(docs, strict_validation=True)

    passages = [
        PassageEvidence(
            index=1,
            chunk_id="chk-amend-6.1",
            file_name="exam_rules_amendment_circular_2025.pdf",
            page_number=1,
            text="Amendment to Clause 6.1: the re-evaluation application window is extended from 5 working days to 7 working days after the publication of results, and the fee is reduced from Rs. 800 to Rs. 600.",
            score=0.94,
            effective_date="2025-07-01",
            is_superseded=False,
        ),
        PassageEvidence(
            index=2,
            chunk_id="chk-rules-6.1",
            file_name="examination_assessment_rules_2023.pdf",
            page_number=3,
            text="Clause 6.1. A student may apply for re-evaluation within 5 working days of publication of results upon payment of Rs. 800 per paper.",
            score=0.90,
            effective_date="2023-08-01",
            is_superseded=False,
            is_partially_amended=True,
            amendment_scope="Clause 4.2 and Clause 6.1 only",
        ),
    ]

    has_conflict, conflicts = service.detect_conflicts(passages, status_map)
    assert has_conflict is True, "Amended Clause 6.1 MUST trigger a policy conflict"
    assert len(conflicts) == 1
    assert conflicts[0].current_file == "exam_rules_amendment_circular_2025.pdf"
    assert conflicts[0].superseded_file == "examination_assessment_rules_2023.pdf"


def test_unchanged_clause_4_1_not_flagged_as_conflict():
    """Verify that evidence from an unchanged clause (Clause 4.1 aggregate mark 40/100) is NOT flagged as a conflict."""
    docs = _get_exam_docs()
    service = DocumentVersionService()
    status_map = service.build_version_graph(docs, strict_validation=True)

    passages = [
        PassageEvidence(
            index=1,
            chunk_id="chk-amend-1",
            file_name="exam_rules_amendment_circular_2025.pdf",
            page_number=1,
            text="Amendment to Clause 4.2: the minimum ESE mark is 21 out of 60. The aggregate requirement of 40 out of 100 under Clause 4.1 is unchanged.",
            score=0.92,
            effective_date="2025-07-01",
            is_superseded=False,
        ),
        PassageEvidence(
            index=2,
            chunk_id="chk-rules-4.1",
            file_name="examination_assessment_rules_2023.pdf",
            page_number=2,
            text="Clause 4.1. To pass a theory course a student must secure at least 40 marks out of 100 in aggregate (CIA plus ESE).",
            score=0.88,
            effective_date="2023-08-01",
            is_superseded=False,
            is_partially_amended=True,
            amendment_scope="Clause 4.2 and Clause 6.1 only",
        ),
    ]

    has_conflict, conflicts = service.detect_conflicts(passages, status_map)
    assert has_conflict is False, "Unchanged Clause 4.1 must NOT trigger a conflict flag"
    assert len(conflicts) == 0


def test_unchanged_clause_3_1_not_flagged_as_conflict():
    """Verify that evidence from unchanged Clause 3.1 (reporting time 30 mins) is NOT flagged as a conflict."""
    docs = _get_exam_docs()
    service = DocumentVersionService()
    status_map = service.build_version_graph(docs, strict_validation=True)

    passages = [
        PassageEvidence(
            index=1,
            chunk_id="chk-rules-3.1",
            file_name="examination_assessment_rules_2023.pdf",
            page_number=1,
            text="Clause 3.1. Students must report to the examination hall 30 minutes before the scheduled start time.",
            score=0.87,
            effective_date="2023-08-01",
            is_superseded=False,
            is_partially_amended=True,
            amendment_scope="Clause 4.2 and Clause 6.1 only",
        ),
        PassageEvidence(
            index=2,
            chunk_id="chk-amend-general",
            file_name="exam_rules_amendment_circular_2025.pdf",
            page_number=1,
            text="All other clauses of the Examination and Assessment Rules dated 1 August 2023 remain in force without change.",
            score=0.82,
            effective_date="2025-07-01",
            is_superseded=False,
        ),
    ]

    has_conflict, conflicts = service.detect_conflicts(passages, status_map)
    assert has_conflict is False, "Unchanged Clause 3.1 must NOT trigger a conflict flag"
    assert len(conflicts) == 0


def test_mixed_query_amended_and_unchanged_clauses():
    """Verify that when context includes both unchanged (3.1) and amended (4.2) clauses, only the amended clause triggers a conflict."""
    docs = _get_exam_docs()
    service = DocumentVersionService()
    status_map = service.build_version_graph(docs, strict_validation=True)

    passages = [
        PassageEvidence(
            index=1,
            chunk_id="chk-amend-4.2",
            file_name="exam_rules_amendment_circular_2025.pdf",
            page_number=1,
            text="Amendment to Clause 4.2: the minimum ESE mark is reduced to 21 out of 60.",
            score=0.96,
            effective_date="2025-07-01",
            is_superseded=False,
        ),
        PassageEvidence(
            index=2,
            chunk_id="chk-rules-3.1",
            file_name="examination_assessment_rules_2023.pdf",
            page_number=1,
            text="Clause 3.1. Students must report to the examination hall 30 minutes before the scheduled start time.",
            score=0.91,
            effective_date="2023-08-01",
            is_superseded=False,
            is_partially_amended=True,
            amendment_scope="Clause 4.2 and Clause 6.1 only",
        ),
        PassageEvidence(
            index=3,
            chunk_id="chk-rules-4.2",
            file_name="examination_assessment_rules_2023.pdf",
            page_number=2,
            text="Clause 4.2. In theory courses, a student must secure a minimum of 24 marks out of 60.",
            score=0.88,
            effective_date="2023-08-01",
            is_superseded=False,
            is_partially_amended=True,
            amendment_scope="Clause 4.2 and Clause 6.1 only",
        ),
    ]

    has_conflict, conflicts = service.detect_conflicts(passages, status_map)
    assert has_conflict is True, "Mixed query with amended Clause 4.2 present must detect the amendment conflict"
    assert len(conflicts) == 1, "Exactly one conflict should be declared for the document pair"


def test_multiple_passages_same_document_deduplication():
    """Verify that multiple retrieved passages from the same document do NOT create duplicate redundant conflicts."""
    docs = _get_exam_docs()
    service = DocumentVersionService()
    status_map = service.build_version_graph(docs, strict_validation=True)

    passages = [
        PassageEvidence(
            index=1,
            chunk_id="chk-amend-1",
            file_name="exam_rules_amendment_circular_2025.pdf",
            page_number=1,
            text="Amendment to Clause 4.2 and Clause 6.1: official notification.",
            score=0.97,
            effective_date="2025-07-01",
            is_superseded=False,
        ),
        PassageEvidence(
            index=2,
            chunk_id="chk-rules-p1",
            file_name="examination_assessment_rules_2023.pdf",
            page_number=1,
            text="Section on examination conduct Clause 4.2 details.",
            score=0.92,
            effective_date="2023-08-01",
            is_superseded=False,
            is_partially_amended=True,
            amendment_scope="Clause 4.2 and Clause 6.1 only",
        ),
        PassageEvidence(
            index=3,
            chunk_id="chk-rules-p2",
            file_name="examination_assessment_rules_2023.pdf",
            page_number=2,
            text="Further elaboration of Clause 4.2 passing thresholds.",
            score=0.89,
            effective_date="2023-08-01",
            is_superseded=False,
            is_partially_amended=True,
            amendment_scope="Clause 4.2 and Clause 6.1 only",
        ),
        PassageEvidence(
            index=4,
            chunk_id="chk-rules-p3",
            file_name="examination_assessment_rules_2023.pdf",
            page_number=3,
            text="Clause 6.1 re-evaluation provisions.",
            score=0.85,
            effective_date="2023-08-01",
            is_superseded=False,
            is_partially_amended=True,
            amendment_scope="Clause 4.2 and Clause 6.1 only",
        ),
    ]

    has_conflict, conflicts = service.detect_conflicts(passages, status_map)
    assert has_conflict is True
    # Deduplication ensures only 1 conflict entry per (amender, amended) document pair
    assert len(conflicts) == 1, "Duplicate conflicts for the same document pair must be deduplicated"


def test_clause_formatting_variations():
    """Verify that clause number matching robustly recognizes varied realistic formatting styles."""
    docs = _get_exam_docs()
    service = DocumentVersionService()
    status_map = service.build_version_graph(docs, strict_validation=True)

    variations = [
        "Clause 4.2. In theory courses minimum mark is 24.",
        "clause 4.2: students must score at least 24.",
        "Section 4.2 defines the minimum passing mark.",
        "sec. 4.2 passing criteria.",
        "cl. 4.2 passing score.",
        "Clause-4.2 passing rule.",
        "Under 4.2 the requirement is 24 marks.",
    ]

    for var_text in variations:
        passages = [
            PassageEvidence(
                index=1,
                chunk_id="chk-amend",
                file_name="exam_rules_amendment_circular_2025.pdf",
                page_number=1,
                text="Amendment to Clause 4.2 reduces mark to 21.",
                score=0.95,
                effective_date="2025-07-01",
                is_superseded=False,
            ),
            PassageEvidence(
                index=2,
                chunk_id="chk-rules-var",
                file_name="examination_assessment_rules_2023.pdf",
                page_number=2,
                text=var_text,
                score=0.90,
                effective_date="2023-08-01",
                is_superseded=False,
                is_partially_amended=True,
                amendment_scope="Clause 4.2 and Clause 6.1 only",
            ),
        ]
        has_conflict, conflicts = service.detect_conflicts(passages, status_map)
        assert has_conflict is True, f"Failed to match clause formatting: '{var_text}'"


def test_full_replacement_attendance_and_hostel():
    """Verify that full replacements (attendance and hostel policies) continue to mark predecessors as wholly superseded."""
    docs = [
        # Attendance full replacement
        Document(
            id="doc-att-2023",
            file_name="attendance_leave_policy_2023.pdf",
            title="Attendance and Leave Policy",
            effective_date=datetime.date(2023, 8, 1),
            supersedes=None,
        ),
        Document(
            id="doc-att-2025",
            file_name="attendance_leave_policy_2025.pdf",
            title="Attendance and Leave Policy",
            effective_date=datetime.date(2025, 7, 1),
            supersedes="attendance_leave_policy_2023.pdf",
        ),
        # Hostel full replacement
        Document(
            id="doc-hostel-2024",
            file_name="hostel_rules_2024.pdf",
            title="Hostel Rules",
            effective_date=datetime.date(2024, 7, 1),
            supersedes=None,
        ),
        Document(
            id="doc-hostel-2025",
            file_name="hostel_rules_2025.pdf",
            title="Hostel Rules",
            effective_date=datetime.date(2025, 7, 1),
            supersedes="hostel_rules_2024.pdf",
        ),
    ]

    service = DocumentVersionService()
    status_map = service.build_version_graph(docs, strict_validation=True)

    # Attendance: 2023 is wholly superseded by 2025
    assert status_map["doc-att-2023"].is_superseded is True
    assert status_map["doc-att-2023"].is_partially_amended is False
    assert status_map["doc-att-2023"].superseded_by_file == "attendance_leave_policy_2025.pdf"
    assert status_map["doc-att-2025"].is_superseded is False

    # Hostel: 2024 is wholly superseded by 2025
    assert status_map["doc-hostel-2024"].is_superseded is True
    assert status_map["doc-hostel-2024"].is_partially_amended is False
    assert status_map["doc-hostel-2024"].superseded_by_file == "hostel_rules_2025.pdf"
    assert status_map["doc-hostel-2025"].is_superseded is False

    # Full replacement conflict check
    att_passages = [
        PassageEvidence(
            index=1,
            chunk_id="att-2025-p1",
            file_name="attendance_leave_policy_2025.pdf",
            page_number=1,
            text="Minimum attendance is 75%.",
            score=0.95,
            effective_date="2025-07-01",
            is_superseded=False,
        ),
        PassageEvidence(
            index=2,
            chunk_id="att-2023-p1",
            file_name="attendance_leave_policy_2023.pdf",
            page_number=1,
            text="Minimum attendance is 80%.",
            score=0.90,
            effective_date="2023-08-01",
            is_superseded=True,
            superseded_by="Attendance and Leave Policy 2025",
        ),
    ]
    has_conflict, conflicts = service.detect_conflicts(att_passages, status_map)
    assert has_conflict is True, "Full replacement of attendance policy MUST flag conflict"
    assert len(conflicts) == 1
    assert "has been superseded by" in conflicts[0].description


def test_evidence_prompt_status_tagging():
    """Verify that build_evidence_prompt correctly tags partially amended vs wholly superseded documents."""
    qa_service = QAService(retrieval_service=None, llm_service=MockLLMService())

    passages = [
        PassageEvidence(
            index=1,
            chunk_id="chk-1",
            file_name="exam_rules_amendment_circular_2025.pdf",
            page_number=1,
            text="Circular text.",
            score=0.9,
            effective_date="2025-07-01",
            is_superseded=False,
        ),
        PassageEvidence(
            index=2,
            chunk_id="chk-2",
            file_name="examination_assessment_rules_2023.pdf",
            page_number=1,
            text="Clause 3.1 reporting time.",
            score=0.85,
            effective_date="2023-08-01",
            is_superseded=False,
            is_partially_amended=True,
            amendment_scope="Clause 4.2 and Clause 6.1 only",
        ),
        PassageEvidence(
            index=3,
            chunk_id="chk-3",
            file_name="attendance_leave_policy_2023.pdf",
            page_number=1,
            text="Old 80% attendance rule.",
            score=0.8,
            effective_date="2023-08-01",
            is_superseded=True,
            superseded_by="Attendance and Leave Policy 2025",
        ),
    ]

    prompt = qa_service.build_evidence_prompt(passages, version_aware=True)

    # 1. Amendment circular is CURRENT
    assert "[STATUS: CURRENT - Effective: 2025-07-01]" in prompt
    # 2. Partially amended document is CURRENT (Partially amended ...) NOT SUPERSEDED
    assert "[STATUS: CURRENT (Partially amended (Clause 4.2 and Clause 6.1 only)) - Effective: 2023-08-01]" in prompt
    # 3. Wholly superseded document is SUPERSEDED
    assert "[STATUS: SUPERSEDED by Attendance and Leave Policy 2025 - Effective: 2023-08-01]" in prompt
