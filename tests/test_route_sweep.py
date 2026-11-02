"""Tests for Phase 5: Leak Surface Elimination, Route Sweep, Cache Isolation, and Admin Security API."""

from fastapi.testclient import TestClient
from app.main import app
from app.core.auth import create_access_token
from app.core.cache import query_cache
from eval.route_sweep import run_sweep

client = TestClient(app)


def test_phase5_route_sweep_zero_leaks():
    """Verify that calling all endpoints as student persona yields zero leaks across 20 routes."""
    leak_count, leaks = run_sweep()
    assert leak_count == 0, f"Route sweep detected leaks: {leaks}"


def test_cache_isolation_admin_then_student():
    """Verify Phase 5 cache isolation: admin asks a confidential question, then student asks same question.

    Security Requirement:
    Cache key must include role and corpus version. The student query must NEVER retrieve
    or leak the admin's cached response.
    """
    query_cache.clear()
    question = "What are the administrative executive salary bands?"

    # 1. Admin asks the question
    admin_token = create_access_token("admin")
    admin_resp = client.post(
        "/ask",
        json={"question": question},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_resp.status_code == 200
    admin_data = admin_resp.json()

    # Admin response is cached under admin role key
    admin_cache_key = query_cache.compute_cache_key(question, "admin")
    assert admin_cache_key in query_cache._store

    # 2. Student asks the exact same question
    student_token = create_access_token("student")
    student_resp = client.post(
        "/ask",
        json={"question": question},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert student_resp.status_code == 200
    student_data = student_resp.json()

    # Crucial security assertions:
    # Student must abstain, citations must be empty, and no confidential salary facts or canaries appear
    assert student_data["abstained"] is True
    assert student_data["answer"] == "I do not have sufficient information in the provided documents to answer this question."
    assert student_data["citations"] == []
    assert "KVIT-ADM-CNRY-8870" not in student_resp.text
    assert "Rs. 60,000" not in student_resp.text


def test_uniform_404_prevents_existence_oracle():
    """Verify requesting a restricted document returns the exact same 404 response as a nonexistent document."""
    student_token = create_access_token("student")
    auth_headers = {"Authorization": f"Bearer {student_token}"}

    # 1. Nonexistent document
    resp_fake = client.get("/documents/completely_fake_document_9999.pdf", headers=auth_headers)
    assert resp_fake.status_code == 404
    fake_body = resp_fake.json()

    # 2. Existing but confidential admin document
    resp_conf = client.get("/documents/admin_salary_bands_and_budget_2025.pdf", headers=auth_headers)
    assert resp_conf.status_code == 404
    conf_body = resp_conf.json()

    # Both must be identical: detail == "Document not found."
    assert fake_body["detail"] == conf_body["detail"] == "Document not found."


def test_admin_security_api_authorization():
    """Verify /admin/security endpoints are strictly restricted to admin role."""
    student_token = create_access_token("student")
    admin_token = create_access_token("admin")

    # 1. Student access is rejected with 403 Forbidden
    resp_student = client.get(
        "/admin/security/visible-document-counts",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp_student.status_code == 403

    # 2. Admin access is permitted with 200 OK
    resp_admin = client.get(
        "/admin/security/visible-document-counts",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_admin.status_code == 200
    data = resp_admin.json()
    assert "counts_by_role" in data
    assert data["counts_by_role"]["student"] == 10
    assert data["counts_by_role"]["faculty"] == 13
    assert data["counts_by_role"]["admin"] == 16


def test_access_audit_stores_hash_never_raw_text():
    """Verify access audit logs query hash rather than raw query text."""
    admin_token = create_access_token("admin")
    resp = client.get(
        "/admin/security/denied-attempts",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "attempts" in data

    for attempt in data["attempts"]:
        assert "query_hash" in attempt
        assert len(attempt["query_hash"]) == 64  # SHA-256 hex string
        # Confirm query text field does NOT exist on the model schema
        assert "query" not in attempt
        assert "text" not in attempt

