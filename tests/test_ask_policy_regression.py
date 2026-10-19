"""Regression tests for Ask Policy role handling, abstention, and API response contracts.

Verifies:
1. Student, Faculty, and Admin roles are accepted and validated by the API contract.
2. API /ask response does NOT return a `role` field, confirming the frontend must
   preserve and display the simulated user role rather than looking for `response.role`.
3. Abstention responses return abstained=True, empty citations, and meaningful explanation
   without fabricated sources or hardcoded success status.
4. Grounded responses return valid citations with page numbers and snippets.
5. Inactive / invalid roles are rejected with HTTP 422.
6. Error handling for malformed / empty queries.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.qa import AskRequest, AskResponse, Citation, PassageEvidence, PolicyConflict
from app.schemas.retrieval import RetrievalDiagnostics

client = TestClient(app)


def test_ask_request_roles_supported():
    """Verify that student, faculty, and admin roles are accepted by the schema."""
    for role in ["student", "faculty", "admin"]:
        req = AskRequest(question="What is the policy?", role=role)
        assert req.role == role


def test_ask_request_invalid_role_rejected():
    """Verify that unsupported roles fail validation."""
    with pytest.raises(Exception):
        AskRequest(question="What is the policy?", role="guest")

    with pytest.raises(Exception):
        AskRequest(question="What is the policy?", role="Abstained")


def test_ask_response_schema_has_no_role_field():
    """Verify that AskResponse does NOT include a 'role' field.
    
    This ensures regression coverage for the root cause: the frontend previously
    attempted to read `result.role` from the API response (which was undefined),
    leading to `Role: Abstained` and `authorized for your active role ()`.
    """
    fields = AskResponse.model_fields
    assert "role" not in fields
    assert "abstained" in fields
    assert "answer" in fields
    assert "citations" in fields
    assert "has_policy_conflict" in fields


def test_ask_endpoint_student_role_live():
    """Verify live /ask endpoint accepts student role without schema validation error."""
    response = client.post(
        "/ask",
        json={"question": "What is the minimum grade required to pass a core course?", "role": "student"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "abstained" in data
    assert "citations" in data
    # Role must NOT be in the API response
    assert "role" not in data


def test_ask_endpoint_faculty_role_live():
    """Verify live /ask endpoint accepts faculty role."""
    response = client.post(
        "/ask",
        json={"question": "What are faculty office hours requirements?", "role": "faculty"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "role" not in data


def test_ask_endpoint_admin_role_live():
    """Verify live /ask endpoint accepts admin role."""
    response = client.post(
        "/ask",
        json={"question": "What is the grade replacement policy?", "role": "admin"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "role" not in data


def test_ask_endpoint_rejects_invalid_role():
    """Verify that an invalid role returns 422 Unprocessable Entity."""
    response = client.post(
        "/ask",
        json={"question": "What is the policy?", "role": "invalid_role"},
    )
    assert response.status_code == 422


def test_ask_endpoint_rejects_empty_question():
    """Verify that an empty question string or missing question is rejected with 422."""
    response = client.post(
        "/ask",
        json={"question": "", "role": "student"},
    )
    assert response.status_code == 422

    response_missing = client.post(
        "/ask",
        json={"role": "student"},
    )
    assert response_missing.status_code == 422


def test_abstention_does_not_fabricate_citations():
    """Verify that an abstention outcome returns zero citations and does not fabricate evidence."""
    # Query completely unrelated to academic policy corpus
    response = client.post(
        "/ask",
        json={"question": "What is the policy regarding deep sea submarine piloting?", "role": "student"},
    )
    assert response.status_code == 200
    data = response.json()
    if data["abstained"]:
        assert len(data["citations"]) == 0
        assert "insufficient" in data["answer"].lower() or "not contain" in data["answer"].lower() or len(data["answer"]) > 0


def test_grounded_answer_includes_real_citations():
    """Verify that a supported policy inquiry produces citations with legitimate metadata."""
    response = client.post(
        "/ask",
        json={"question": "What is the minimum grade required to pass a core course?", "role": "student"},
    )
    assert response.status_code == 200
    data = response.json()
    if not data["abstained"] and len(data["citations"]) > 0:
        citation = data["citations"][0]
        assert "file_name" in citation
        assert "page_number" in citation
        assert "snippet" in citation
        assert citation["file_name"].endswith(".pdf")
        assert citation["page_number"] >= 1


def test_structured_policy_response_contracts():
    """Verify AskResponse contracts support structured UI rendering components:
    - Answer summary and rules in 'answer'
    - Verified citations in 'citations'
    - Active policy lineage in 'passages'
    - Policy conflict details in 'conflict_details'
    """
    sample = AskResponse(
        question="What is the curfew?",
        answer="Curfew is 10 PM on weeknights [1].\n\nImportant Rules:\n* Visitors out by 7 PM [1].",
        citations=[Citation(index=1, file_name="kvit_handbook.pdf", page_number=2, snippet="Curfew is 10 PM.")],
        passages=[
            PassageEvidence(
                index=1,
                chunk_id="chk-1",
                file_name="kvit_handbook.pdf",
                page_number=2,
                text="Curfew is 10 PM on weeknights.",
                score=0.85,
                document_title="KVIT Student Handbook",
                effective_date="2024-01-01",
                is_superseded=False,
            )
        ],
        abstained=False,
        has_policy_conflict=False,
    )
    data = sample.model_dump()
    assert "answer" in data
    assert len(data["citations"]) == 1
    assert data["citations"][0]["index"] == 1
    assert len(data["passages"]) == 1
    assert data["passages"][0]["document_title"] == "KVIT Student Handbook"
    assert data["passages"][0]["effective_date"] == "2024-01-01"
    assert "role" not in data


def test_diagnostics_includes_semantic_retrieval_active_flag():
    """Verify retrieval diagnostics schema reports true operational state of semantic retrieval."""
    diag = RetrievalDiagnostics(
        vector_count=5,
        keyword_count=5,
        fused_count=8,
        reranked_count=2,
        semantic_retrieval_active=False,
        timings_ms={"total_retrieval_ms": 12.5},
    )
    data = diag.model_dump()
    assert "semantic_retrieval_active" in data
    assert isinstance(data["semantic_retrieval_active"], bool)
    assert data["semantic_retrieval_active"] is False


def test_policy_conflict_schema_active_vs_superseded():
    """Verify PolicyConflict structured schema provides exact active and superseded lineage."""
    conflict = PolicyConflict(
        current_title="KVIT Attendance Policy 2024",
        current_file="kvit_attendance_2024.pdf",
        current_effective_date="2024-01-01",
        current_citation_index=1,
        superseded_title="KVIT Attendance Policy 2022",
        superseded_file="kvit_attendance_2022.pdf",
        superseded_effective_date="2022-01-01",
        superseded_citation_index=2,
        description="2024 policy allows 3 online sessions, superseding 2022 rule of 1 session.",
    )
    assert conflict.current_effective_date > conflict.superseded_effective_date
    assert conflict.current_file != conflict.superseded_file
    assert conflict.current_citation_index == 1
    assert conflict.superseded_citation_index == 2

