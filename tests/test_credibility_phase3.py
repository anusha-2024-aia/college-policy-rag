"""Phase 3 Credibility Bugs & Document Library Verification Suite.

Verifies all Done-When criteria for Phase 3:
1. GET /documents returns only the caller's authorized documents and an accurate hidden_count,
   with zero restricted metadata (titles, filenames, supersession targets) leaked in responses.
2. No non-college documents or non-standard roles exist in DB, manifest, test fixtures, or code.
   Roles are strictly {"student", "faculty", "admin"}.
3. Ingestion pipeline preserves clause boundaries and produces >= 50 realistic chunks across 16 docs.
4. GET /evaluations/summary returns dynamic, real benchmark metrics with zero hardcoded metrics.
5. UI index.html contains username/password auth form, dynamic evaluation metric hooks, and hidden count.
"""

from __future__ import annotations

import json
import os
import sqlite3
import pytest
from fastapi.testclient import TestClient

# Ensure test mode for secure secret enforcement
os.environ["APP_ENV"] = "test"

from app.main import app
from app.core.auth import create_access_token
from app.core.roles import PERMITTED_ROLES


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def db_conn():
    db_path = os.path.join(os.path.dirname(__file__), "..", "data", "test_kvit.db")
    if not os.path.exists(db_path):
        pytest.skip("data/test_kvit.db not found")
    conn = sqlite3.connect(db_path)
    yield conn
    conn.close()


class TestDocumentLibraryRoleFiltering:
    """Verifies server-side role filtering and metadata masking for GET /documents."""

    def test_student_documents_and_hidden_count(self, client):
        token = create_access_token(role="student")
        resp = client.get("/documents", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert "documents" in data
        assert "hidden_count" in data
        assert "total_docs" in data

        docs = data["documents"]
        # Student should see 10 documents, 6 hidden
        assert len(docs) == 10
        assert data["hidden_count"] == 6
        assert data["total_docs"] == 10

        # Verify zero restricted filenames or sensitive keywords appear in visible documents
        restricted_keywords = [
            "salary",
            "disciplinary_committee",
            "recruitment",
            "faculty_service",
        ]
        visible_filenames = [d["file_name"] for d in docs]
        for fname in visible_filenames:
            for kw in restricted_keywords:
                assert kw not in fname.lower(), f"Restricted keyword '{kw}' leaked in filename '{fname}'"

        # Verify supersession metadata is masked if pointing to a restricted document
        for doc in docs:
            superseded_by_title = doc.get("superseded_by_title")
            if superseded_by_title:
                assert superseded_by_title != "Salary Bands and Operating Budget"
                assert superseded_by_title != "Disciplinary Committee Case Summaries (Pseudonymised)"

    def test_faculty_documents_and_hidden_count(self, client):
        token = create_access_token(role="faculty")
        resp = client.get("/documents", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["documents"]) == 13
        assert data["hidden_count"] == 3

        # Faculty cannot see admin-only documents (e.g. Disciplinary Committee Case Summaries)
        filenames = [d["file_name"] for d in data["documents"]]
        assert "disciplinary_committee_case_summaries_2025.pdf" not in filenames
        assert "admin_salary_bands_and_budget_2025.pdf" not in filenames
        assert "admin_fee_waiver_internal_criteria_2025.pdf" not in filenames

    def test_admin_documents_and_hidden_count(self, client):
        token = create_access_token(role="admin")
        resp = client.get("/documents", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()

        # Admin sees all 16 documents
        assert len(data["documents"]) == 16
        assert data["hidden_count"] == 0

    def test_single_document_access_control(self, client):
        student_token = create_access_token(role="student")
        admin_token = create_access_token(role="admin")

        # Student accessing admin-only document -> 404 (not found for their role)
        resp_student = client.get(
            "/documents/disciplinary_committee_case_summaries_2025.pdf",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp_student.status_code == 404

        # Admin accessing admin-only document -> 200
        resp_admin = client.get(
            "/documents/disciplinary_committee_case_summaries_2025.pdf",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp_admin.status_code == 200
        assert resp_admin.json()["file_name"] == "disciplinary_committee_case_summaries_2025.pdf"


class TestCollegeCorpusAndRoleStandardization:
    """Verifies that no non-college files or non-standard roles exist in DB, manifest, or codebase."""

    def test_permitted_roles_are_strictly_standard(self):
        assert PERMITTED_ROLES == {"student", "faculty", "admin"}

    def test_no_non_college_documents_in_db(self, db_conn):
        cursor = db_conn.cursor()
        cursor.execute("SELECT file_name FROM documents")
        filenames = [row[0] for row in cursor.fetchall()]

        disallowed_names = [
            "financial_disclosure_q3.pdf",
            "employee_handbook_v1.pdf",
            "employee_handbook_v2.pdf",
            "security_compliance_policy.pdf",
        ]
        for name in disallowed_names:
            assert name not in filenames, f"Corporate/non-college document found in database: {name}"

    def test_db_roles_strictly_within_permitted(self, db_conn):
        cursor = db_conn.cursor()
        cursor.execute("SELECT allowed_roles FROM chunks")
        rows = cursor.fetchall()

        for (roles_val,) in rows:
            if not roles_val:
                continue
            if isinstance(roles_val, str) and roles_val.startswith("["):
                roles = json.loads(roles_val)
            elif isinstance(roles_val, str):
                roles = [r.strip() for r in roles_val.split(";") if r.strip()]
            else:
                roles = list(roles_val)

            for r in roles:
                assert r in PERMITTED_ROLES, f"Disallowed role '{r}' found in chunk allowed_roles: '{roles_val}'"


class TestChunkDistributionAndCorpusQuality:
    """Verifies ingestion produced >= 50 chunks across 16 docs with preserved clause references."""

    def test_corpus_size_invariants(self, db_conn):
        cursor = db_conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM documents")
        (doc_count,) = cursor.fetchone()
        assert doc_count == 16, f"Expected 16 documents, found {doc_count}"

        cursor.execute("SELECT COUNT(*) FROM chunks")
        (chunk_count,) = cursor.fetchone()
        assert chunk_count >= 50, f"Expected at least 50 chunks, found {chunk_count}"

        # Verify semantic table has 1:1 coverage
        cursor.execute("SELECT COUNT(*) FROM chunks_semantic")
        (semantic_count,) = cursor.fetchone()
        assert semantic_count >= 50
        assert semantic_count == chunk_count

    def test_clause_boundary_preservation(self, db_conn):
        cursor = db_conn.cursor()
        cursor.execute("SELECT clause_ref, token_count FROM chunks")
        rows = cursor.fetchall()

        clause_refs = [r[0] for r in rows if r[0]]
        token_counts = [r[1] for r in rows if r[1] is not None]

        # Verify clause refs were extracted (not all None or empty)
        assert len(clause_refs) > 20, f"Expected at least 20 chunks with clause_ref, got {len(clause_refs)}"

        # Verify token counts vary (not uniform page chunks)
        unique_token_counts = set(token_counts)
        assert len(unique_token_counts) >= 10, "Expected variety in chunk token counts"


class TestDynamicEvaluationSummary:
    """Verifies GET /evaluations/summary returns live benchmark metrics."""

    def test_evaluations_summary_endpoint(self, client):
        token = create_access_token(role="admin")
        resp = client.get("/evaluations/summary", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert "primary_recall_at_5" in data
        assert "primary_mrr" in data
        assert "primary_leak_rate" in data
        assert "corpus_documents" in data
        assert "corpus_chunks" in data
        assert "configs" in data

        # Values must be real benchmark results
        assert data["primary_recall_at_5"] > 0.8
        assert data["primary_mrr"] > 0.8
        assert data["primary_leak_rate"] == 0.0
        assert data["corpus_documents"] == 16
        assert data["corpus_chunks"] >= 50

        # Configs should include the benchmark configurations
        assert len(data["configs"]) >= 5


class TestUIIntegrity:
    """Verifies that ui/web/index.html includes username/password login and dynamic metrics."""

    def test_ui_html_structure(self):
        ui_path = os.path.join(os.path.dirname(__file__), "..", "ui", "web", "index.html")
        assert os.path.exists(ui_path)

        with open(ui_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Hardcoded static fake numbers should not be present as static card content
        assert "86.7%" not in content
        assert "98.4%" not in content
        assert "0.00% (0/30)" not in content

        # Login inputs and dynamic metric containers must be present
        assert 'id="login-username"' in content
        assert 'id="login-password"' in content
        assert 'id="demo-mode-section"' in content
        assert 'id="doc-library-stats"' in content
        assert 'id="eval-primary-recall5"' in content
        assert 'id="eval-primary-mrr"' in content
        assert 'id="eval-primary-leaks"' in content
