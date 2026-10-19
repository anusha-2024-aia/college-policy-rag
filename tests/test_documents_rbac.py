"""Tests for Document Library server-side RBAC and lineage enforcement.

Verifies:
1. Server-side role enforcement: student role must NEVER see confidential faculty/admin titles.
2. Hidden documents return only an aggregate count ('6 hidden for your role').
3. Library status and lineage derived accurately from manifest (Active, Superseded, Partially amended).
4. Invalid roles are rejected with HTTP 400 Bad Request.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# Sensitive documents that MUST NEVER be visible to students
CONFIDENTIAL_DOC_FILENAMES = {
    "faculty_service_rules_2025.pdf",
    "question_paper_confidentiality_protocol_2025.pdf",
    "marks_moderation_guidelines_2025.pdf",
    "disciplinary_committee_case_summaries_2025.pdf",
    "admin_fee_waiver_internal_criteria_2025.pdf",
    "admin_salary_bands_and_budget_2025.pdf",
}

# Confidential title keywords that MUST NOT appear in student response
CONFIDENTIAL_TITLE_KEYWORDS = [
    "Salary Bands",
    "Faculty Service",
    "Disciplinary Committee",
    "Fee Waiver",
    "Confidentiality Protocol",
    "Marks Moderation",
]


def test_student_must_not_see_restricted_titles():
    """Verify item 1: student role receives only authorized documents and an accurate hidden count."""
    response = client.get("/documents?role=student")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()

    assert "total_docs" in data
    assert "hidden_count" in data
    assert "documents" in data

    # Live DB contains 16 policies: 10 student, 3 faculty+admin, 3 admin-only
    assert data["total_docs"] == 10, f"Expected 10 student documents, got {data['total_docs']}"
    assert data["hidden_count"] == 6, f"Expected 6 hidden documents for student, got {data['hidden_count']}"

    # Crucial security assertion: verify NO restricted filenames are exposed
    returned_filenames = {d["file_name"] for d in data["documents"]}
    leaked_files = returned_filenames.intersection(CONFIDENTIAL_DOC_FILENAMES)
    assert not leaked_files, f"Security Violation: Student was exposed to restricted files: {leaked_files}"

    # Verify NO restricted titles or title keywords appear anywhere in the student response
    for doc in data["documents"]:
        title = doc["title"]
        for keyword in CONFIDENTIAL_TITLE_KEYWORDS:
            assert keyword.lower() not in title.lower(), (
                f"Security Violation: Student response exposed restricted title keyword '{keyword}' in '{title}'"
            )
        # Every document returned to student must include 'student' in allowed_roles
        assert any("student" in r.lower() for r in doc["allowed_roles"]), (
            f"Document {doc['file_name']} without student role exposed to student"
        )


def test_faculty_role_document_filtering():
    """Verify faculty sees student + faculty policies, with 3 admin policies hidden."""
    response = client.get("/documents?role=faculty")
    assert response.status_code == 200
    data = response.json()

    assert data["total_docs"] == 13
    assert data["hidden_count"] == 3

    returned_filenames = {d["file_name"] for d in data["documents"]}
    # Faculty can see faculty_service_rules
    assert "faculty_service_rules_2025.pdf" in returned_filenames

    # Faculty must NOT see admin-only documents
    admin_only = {
        "disciplinary_committee_case_summaries_2025.pdf",
        "admin_fee_waiver_internal_criteria_2025.pdf",
        "admin_salary_bands_and_budget_2025.pdf",
    }
    leaked_admin = returned_filenames.intersection(admin_only)
    assert not leaked_admin, f"Security Violation: Faculty saw admin-only files: {leaked_admin}"


def test_admin_role_document_filtering():
    """Verify admin role has complete visibility across all 16 corpus documents."""
    response = client.get("/documents?role=admin")
    assert response.status_code == 200
    data = response.json()

    assert data["total_docs"] == 16
    assert data["hidden_count"] == 0
    returned_filenames = {d["file_name"] for d in data["documents"]}
    assert "admin_salary_bands_and_budget_2025.pdf" in returned_filenames


def test_document_manifest_status_and_lineage():
    """Verify item 3: Library status and lineage reflect manifest relationships."""
    response = client.get("/documents?role=admin")
    assert response.status_code == 200
    data = response.json()
    docs_by_name = {d["file_name"]: d for d in data["documents"]}

    # 1. attendance_leave_policy_2023.pdf is superseded by attendance_leave_policy_2025.pdf
    doc_2023 = docs_by_name.get("attendance_leave_policy_2023.pdf")
    assert doc_2023 is not None
    assert doc_2023["status"] == "Superseded"
    assert "superseded by" in (doc_2023["superseded_by_title"] or "").lower()

    # 2. examination_assessment_rules_2023.pdf is partially amended
    doc_exam = docs_by_name.get("examination_assessment_rules_2023.pdf")
    assert doc_exam is not None
    assert doc_exam["status"] == "Partially amended"
    assert "amended by" in (doc_exam["superseded_by_title"] or "").lower()

    # 3. hostel_rules_2024.pdf is superseded by hostel_rules_2025.pdf
    doc_hostel = docs_by_name.get("hostel_rules_2024.pdf")
    assert doc_hostel is not None
    assert doc_hostel["status"] == "Superseded"

    # 4. Standard active policy
    doc_active = docs_by_name.get("academic_regulations_2024.pdf")
    assert doc_active is not None
    assert doc_active["status"] == "Active"


def test_invalid_role_rejected_with_400():
    """Verify unauthorized or malformed role requests receive HTTP 400 Bad Request."""
    response = client.get("/documents?role=hacker_role")
    assert response.status_code == 400
    assert "invalid role" in response.text.lower()
