"""Phase 7 Test Suite: Clause-Level Change Intelligence and Evidence Verification.

Verifies:
1. Deterministic diff across the three KVIT lineages:
   - Attendance: 80% -> 75%, fee Rs. 500 -> Rs. 300, floor 70% -> 65%.
   - Hostel: curfew 9:30 PM -> 10:30 PM, visitors 6:00 PM -> 7:00 PM, added late-pass clause.
   - Exam rules: only Clauses 4.2 and 6.1 changed; all other clauses classified as unchanged.
2. Unchanged clause precision: 'how early must I report to the exam hall' produces NO conflict flag.
3. False-flag rate on 5 unchanged clause questions in eval/golden_extended.jsonl is exactly 0.00%.
4. REST endpoint GET /policies/{lineage_id}/diff with 4-layer role governance.
5. Strict verbatim evidence verification and temporal in-force check before answer delivery.
6. Enriched answer contract schema (current_rule, effective_date, previous_rule, etc.).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db, get_test_session
from app.core.auth import create_access_token
from app.schemas.qa import AskRequest, Citation, PassageEvidence
from app.services.clause_diff import ClauseDiffService
from app.services.retrieval import HybridRetrievalService
from app.services.embedding import MockEmbeddingService
from app.services.reranker import MockRerankerService
from app.services.llm import MockLLMService
from app.services.qa import QAService

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def db_session():
    return get_test_session()


@pytest.fixture
def diff_service(db_session):
    return ClauseDiffService(db_session)


@pytest.fixture
def qa_service(db_session):
    embedder = MockEmbeddingService(dimension=1536)
    reranker = MockRerankerService()
    llm = MockLLMService()
    retrieval = HybridRetrievalService(db_session, embedder, reranker)
    return QAService(retrieval, llm)


@pytest.fixture
def test_client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def student_auth_headers():
    token = create_access_token(role="student", subject="demo_student")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_auth_headers():
    token = create_access_token(role="admin", subject="demo_admin")
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# 1. Deterministic Lineage Diff Tests
# ==============================================================================
class TestDeterministicLineageDiff:
    """Verifies deterministic clause extraction and diffing for KVIT policy lineages."""

    def test_attendance_lineage_diff(self, diff_service):
        """Attendance policy: 80% -> 75%, fee Rs. 500 -> Rs. 300, floor 70% -> 65%."""
        lineage = diff_service.get_lineage_by_identifier("attendance")
        assert lineage is not None, "Attendance lineage must exist"

        diff = diff_service.diff_lineage(lineage)
        assert diff.scope == "full"
        assert "attendance_leave_policy_2023.pdf" in diff.predecessor_file
        assert "attendance_leave_policy_2025.pdf" in diff.successor_file

        topics = {c.topic: (c.old.value, c.new.value) for c in diff.change_cards}
        assert "Minimum Course Attendance Requirement" in topics
        assert topics["Minimum Course Attendance Requirement"] == ("80%", "75%")

        assert "Attendance Condonation Fee" in topics
        assert topics["Attendance Condonation Fee"] == ("Rs. 500", "Rs. 300")

        assert "Minimum Attendance for Condonation Eligibility" in topics
        assert topics["Minimum Attendance for Condonation Eligibility"] == ("70%", "65%")

        assert "Leave Application Submission Window" in topics
        assert topics["Leave Application Submission Window"] == ("3 days", "5 days")

    def test_hostel_lineage_diff(self, diff_service):
        """Hostel policy: curfew 9:30 PM -> 10:30 PM, visitors 6:00 PM -> 7:00 PM, added late-pass clause."""
        lineage = diff_service.get_lineage_by_identifier("hostel")
        assert lineage is not None, "Hostel lineage must exist"

        diff = diff_service.diff_lineage(lineage)
        assert diff.scope == "full"
        assert "hostel_rules_2024.pdf" in diff.predecessor_file
        assert "hostel_rules_2025.pdf" in diff.successor_file

        topics = {c.topic: (c.old.value, c.new.value) for c in diff.change_cards}
        assert "Hostel Curfew Timing" in topics
        assert topics["Hostel Curfew Timing"] == ("9:30 PM", "10:30 PM")

        assert "Hostel Visitor Hours Deadline" in topics
        assert topics["Hostel Visitor Hours Deadline"] == ("6:00 PM", "7:00 PM")

        # Verify added late pass clause
        added_deltas = [d for d in diff.clause_deltas if d.status == "added"]
        assert len(added_deltas) >= 1
        assert any("late pass" in d.topic.lower() or "late pass" in (d.new_value or "").lower() for d in added_deltas)

        # Verify unchanged parameters exist (security deposit Rs. 10,000)
        unchanged_deltas = [d for d in diff.clause_deltas if d.status == "unchanged"]
        assert len(unchanged_deltas) >= 1

    def test_examination_rules_partial_amendment_diff(self, diff_service):
        """Examination rules: only Clauses 4.2 and 6.1 changed; all other clauses unchanged."""
        lineage = diff_service.get_lineage_by_identifier("exam")
        assert lineage is not None, "Examination lineage must exist"

        diff = diff_service.diff_lineage(lineage)
        assert diff.scope == "partial"
        assert set(diff.amended_clauses) == {"Clause 4.2", "Clause 6.1"}

        # Clauses 4.2 and 6.1 metrics
        changed_deltas = [d for d in diff.clause_deltas if d.status == "changed"]
        changed_refs = {d.clause_ref for d in changed_deltas}
        assert "Clause 4.2" in changed_refs
        assert "Clause 6.1" in changed_refs

        topics = {c.topic: (c.old.value, c.new.value) for c in diff.change_cards}
        assert "Clause 4.2: End-Semester Exam Minimum Passing Mark" in topics
        assert topics["Clause 4.2: End-Semester Exam Minimum Passing Mark"] == ("24 out of 60", "21 out of 60")

        assert "Clause 6.1: Re-Evaluation Application Window" in topics
        assert topics["Clause 6.1: Re-Evaluation Application Window"] == ("5 working days", "7 working days")

        assert "Clause 6.1: Re-Evaluation Fee per Paper" in topics
        assert topics["Clause 6.1: Re-Evaluation Fee per Paper"] == ("Rs. 800", "Rs. 600")

        # Verify that all other clauses are strictly classified as UNCHANGED
        unchanged_deltas = [d for d in diff.clause_deltas if d.status == "unchanged"]
        unchanged_refs = {d.clause_ref for d in unchanged_deltas}

        # Check key unchanged clauses
        assert "Clause 1" in unchanged_refs
        assert "Clause 2" in unchanged_refs
        assert "Clause 3.1" in unchanged_refs  # Reporting time
        assert "Clause 4.1" in unchanged_refs  # Theory course aggregate pass mark
        assert "Clause 5" in unchanged_refs


# ==============================================================================
# 2. Unchanged Clause Precision & False-Flag Rate
# ==============================================================================
class TestUnchangedClausePrecision:
    """Verifies that queries on unchanged clauses produce NO false conflict flags."""

    def test_exam_hall_reporting_time_produces_no_conflict(self, qa_service):
        """Query: 'how early must I report to the exam hall' -> has_policy_conflict == False."""
        req = AskRequest(
            question="how early must I report to the exam hall",
            role="student",
            version_aware=True,
            top_k=20,
            top_n=5,
        )
        resp = qa_service.answer(req, role="student")
        assert resp.abstained is False
        assert resp.has_policy_conflict is False, "Reporting time (Clause 3.1) must produce NO conflict flag"
        assert len(resp.change_cards) == 0, "Reporting time must emit 0 change cards"
        assert any("30 minutes" in p.text.lower() for p in resp.passages)

    def test_theory_aggregate_mark_produces_no_conflict(self, qa_service):
        """Query: 'Did the circular change the aggregate pass mark of 40 out of 100?' -> False."""
        req = AskRequest(
            question="Did the 2025 circular change the aggregate pass mark of 40 out of 100 for theory courses?",
            role="student",
            version_aware=True,
            top_k=20,
            top_n=5,
        )
        resp = qa_service.answer(req, role="student")
        assert resp.has_policy_conflict is False
        assert len(resp.change_cards) == 0

    def test_extended_unchanged_clause_questions_zero_false_flags(self, qa_service):
        """Verify false-flag rate on all 5 unchanged clause questions in eval/golden_extended.jsonl."""
        extended_file = PROJECT_ROOT / "eval" / "golden_extended.jsonl"
        assert extended_file.exists()

        unchanged_questions = []
        with open(extended_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    if rec.get("type") == "unchanged_clause":
                        unchanged_questions.append(rec)

        assert len(unchanged_questions) == 5, f"Expected 5 unchanged clause questions, found {len(unchanged_questions)}"

        false_flag_count = 0
        for q in unchanged_questions:
            req = AskRequest(
                question=q["question"],
                role=q.get("role", "student"),
                version_aware=True,
                top_k=20,
                top_n=5,
            )
            resp = qa_service.answer(req, role=q.get("role", "student"))
            if resp.has_policy_conflict or len(resp.change_cards) > 0:
                false_flag_count += 1

        false_flag_rate = false_flag_count / len(unchanged_questions)
        print(f"\n[EVALUATION] Unchanged Clause False-Flag Rate: {false_flag_rate:.2%} ({false_flag_count}/{len(unchanged_questions)})")
        assert false_flag_rate == 0.0, f"False-flag rate on unchanged clauses must be 0.00%, got {false_flag_rate:.2%}"


# ==============================================================================
# 3. REST API Endpoint: GET /policies/{lineage_id}/diff
# ==============================================================================
class TestPolicyDiffEndpoint:
    """Verifies REST diff endpoint and 4-layer role security governance."""

    def test_get_attendance_diff_endpoint(self, test_client, student_auth_headers):
        response = test_client.get("/policies/attendance/diff", headers=student_auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["scope"] == "full"
        assert len(data["change_cards"]) >= 3
        assert "attendance_leave_policy_2025.pdf" in data["successor_file"]

    def test_get_exam_diff_endpoint(self, test_client, student_auth_headers):
        response = test_client.get("/policies/exam/diff", headers=student_auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["scope"] == "partial"
        assert set(data["amended_clauses"]) == {"Clause 4.2", "Clause 6.1"}
        assert len(data["change_cards"]) == 3
        assert data["total_unchanged"] >= 10

    def test_get_hostel_diff_endpoint(self, test_client, student_auth_headers):
        response = test_client.get("/policies/hostel/diff", headers=student_auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["scope"] == "full"
        assert len(data["change_cards"]) >= 2
        assert data["total_added"] >= 1

    def test_nonexistent_lineage_returns_404(self, test_client, student_auth_headers):
        response = test_client.get("/policies/nonexistent_xyz_123/diff", headers=student_auth_headers)
        assert response.status_code == 404

    def test_unauthenticated_request_returns_401(self, test_client):
        response = test_client.get("/policies/attendance/diff")
        assert response.status_code == 401


# ==============================================================================
# 4. Strict Verbatim Evidence Verification & Answer Contract
# ==============================================================================
class TestEvidenceVerificationAndAnswerContract:
    """Verifies strict verbatim snippet checking and enriched AnswerContract fields."""

    def test_fabricated_citation_is_dropped(self, qa_service):
        """A citation whose snippet does not exist verbatim on the cited page must be pruned."""
        citation = Citation(
            index=1,
            file_name="attendance_leave_policy_2025.pdf",
            page_number=1,
            snippet="Every student receives a free MacBook Pro upon enrollment at KVIT.",
        )
        passage = PassageEvidence(
            index=1,
            chunk_id="chk_fake",
            file_name="attendance_leave_policy_2025.pdf",
            page_number=1,
            text="A student must have a minimum attendance of 75% in each course.",
            score=0.9,
        )
        # Should fail verification
        is_valid = qa_service.verify_citation_evidence(citation, passage)
        assert is_valid is False, "Fabricated snippet must fail evidence verification"

    def test_valid_verbatim_citation_passes(self, qa_service, db_session):
        """A genuine verbatim snippet from the document page passes verification."""
        from app.models.chunk import Chunk
        db_chunk = db_session.query(Chunk).filter(Chunk.text.like("%75%%")).first()
        assert db_chunk is not None

        citation = Citation(
            index=1,
            file_name=db_chunk.document.file_name,
            page_number=db_chunk.page_number,
            snippet="minimum attendance of 75% in each course",
        )
        passage = PassageEvidence(
            index=1,
            chunk_id=db_chunk.id,
            file_name=db_chunk.document.file_name,
            page_number=db_chunk.page_number,
            text=db_chunk.text,
            score=0.9,
        )
        is_valid = qa_service.verify_citation_evidence(citation, passage)
        assert is_valid is True, "Authentic verbatim citation must pass verification"

    def test_answer_contract_enriched_fields(self, qa_service):
        """Verifies current_rule, effective_date, previous_rule, and previous_source fields."""
        req = AskRequest(
            question="What is the minimum course attendance requirement at KVIT?",
            role="student",
            version_aware=True,
            top_k=20,
            top_n=5,
        )
        resp = qa_service.answer(req, role="student")
        assert resp.abstained is False
        assert resp.effective_date is not None
        assert resp.supporting_passages is not None
        assert len(resp.supporting_passages) > 0
        if resp.change_cards:
            assert resp.current_rule is not None
            assert resp.previous_rule is not None
            assert resp.previous_source is not None
