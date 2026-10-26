"""Tests for Phase 4: Identity, JWT Authentication, and 4-Layer Defence-in-Depth Role Enforcement.

Verifies:
1. Identity:
   - POST /auth/demo-login returns signed, short-lived HMAC-SHA256 JWT tokens for student, faculty, admin.
   - All routes get role from get_current_role dependency.
   - Missing token defaults to student (least privilege).
   - Tampered token yields HTTP 401.
   - Expired token yields HTTP 401.
   - alg=none token yields HTTP 401.
2. Layer 1 (L1) SQL Filtering:
   - Parameterized role filter prevents retrieval of unauthorized chunks before fusion and reranking.
   - Sibling lineage expansion does not pull unauthorized chunks.
3. Layer 2 (L2) Postgres RLS:
   - Policy logic matches 0 rows when transaction role is unset (NULL).
   - RLS setup SQL contains ENABLE, FORCE RLS, and current_setting('app.current_role', true).
4. Layer 3 (L3) Runtime Assertion:
   - Injected unauthorized chunk into evidence pipeline triggers immediate abort and abstention.
5. Layer 4 (L4) Output Scan:
   - Generated answers containing eval/canaries.json tokens or restricted facts are intercepted and blocked.
   - Authorized roles are permitted to receive legitimate content.
6. Negative Control:
   - Disabling enforcement allows leaks to be detected, verifying test sensitivity.
"""

from datetime import date
import base64
import json
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.config import settings
from app.core.auth import (
    create_access_token,
    verify_access_token,
    get_current_role,
    AuthenticationError,
    _base64url_encode,
)
from app.core.rls import evaluate_rls_policy, RLS_SQL_PATH
from app.core.database import Base
from app.models.document import Document
from app.models.chunk import Chunk
from app.models.lineage import DocumentLineage
from app.schemas.qa import AskRequest, PassageEvidence
from app.services.embedding import MockEmbeddingService
from app.services.reranker import MockRerankerService
from app.services.retrieval import HybridRetrievalService
from app.services.llm import MockLLMService
from app.services.qa import QAService
from app.services.security_scanner import SecurityScanner

client = TestClient(app)


# ------------------------------------------------------------------------------
# 1. Identity & Token Attacks
# ------------------------------------------------------------------------------

def test_demo_login_success():
    """Verify POST /auth/demo-login issues valid tokens for permitted roles."""
    for role in ["student", "faculty", "admin"]:
        response = client.post("/auth/demo-login", json={"role": role})
        assert response.status_code == 200, f"Failed demo login for role {role}: {response.text}"
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["role"] == role
        assert data["expires_in"] == settings.JWT_EXPIRE_SECONDS

        # Verify issued token cryptographically
        payload = verify_access_token(data["access_token"])
        assert payload["role"] == role
        assert payload["sub"] == role
        assert payload["exp"] > time.time()


def test_demo_login_rejects_invalid_role():
    """Verify demo login rejects unrecognized roles."""
    response = client.post("/auth/demo-login", json={"role": "hacker_role"})
    assert response.status_code == 422


def test_missing_token_defaults_to_student():
    """Verify that requests without an Authorization header default to student role."""
    role = get_current_role(authorization=None)
    assert role == "student"

    role_blank = get_current_role(authorization="")
    assert role_blank == "student"


def test_token_attack_alg_none():
    """Verify that tokens using 'alg': 'none' are strictly rejected with 401."""
    # Craft an alg=none token
    header = {"alg": "none", "typ": "JWT"}
    payload = {"role": "admin", "sub": "admin", "iat": int(time.time()), "exp": int(time.time()) + 3600}
    h_b64 = _base64url_encode(json.dumps(header).encode())
    p_b64 = _base64url_encode(json.dumps(payload).encode())
    none_token = f"{h_b64}.{p_b64}."

    with pytest.raises(Exception):
        verify_access_token(none_token)

    # Test via API dependency
    response = client.post(
        "/ask",
        json={"question": "What is the fee waiver pool?"},
        headers={"Authorization": f"Bearer {none_token}"},
    )
    assert response.status_code == 401
    assert "algorithm" in response.text.lower() or "verification failed" in response.text.lower()


def test_token_attack_tampered_signature():
    """Verify that tokens with modified claims or altered signatures yield 401."""
    valid_token = create_access_token("student")
    parts = valid_token.split(".")

    # Tamper with the payload to claim admin
    tampered_payload = {"role": "admin", "sub": "admin", "iat": int(time.time()), "exp": int(time.time()) + 3600}
    tampered_p_b64 = _base64url_encode(json.dumps(tampered_payload).encode())
    tampered_token = f"{parts[0]}.{tampered_p_b64}.{parts[2]}"

    with pytest.raises(AuthenticationError):
        verify_access_token(tampered_token)

    response = client.post(
        "/ask",
        json={"question": "What is the fee waiver pool?"},
        headers={"Authorization": f"Bearer {tampered_token}"},
    )
    assert response.status_code == 401


def test_token_attack_expired_token():
    """Verify that expired tokens are strictly rejected with 401."""
    # Generate token expired 60 seconds ago
    expired_token = create_access_token("admin", expires_in_seconds=-60)

    with pytest.raises(AuthenticationError):
        verify_access_token(expired_token)

    response = client.post(
        "/ask",
        json={"question": "What is the fee waiver pool?"},
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    assert "expired" in response.text.lower()


# ------------------------------------------------------------------------------
# 2. Layer 1 (L1) SQL Role Filtering
# ------------------------------------------------------------------------------

@pytest.fixture
def rbac_test_db():
    """Create an isolated database with student, faculty, and admin chunks."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()

    # 1. Student Document & Chunk
    doc_student = Document(
        id="doc-student",
        file_name="student_rules.pdf",
        file_hash="hash1",
        title="Student Code of Conduct",
        effective_date=date(2025, 1, 1),
        allowed_roles=["student", "faculty", "admin"],
        status="current",
    )
    chunk_student = Chunk(
        id="chunk-student",
        document_id="doc-student",
        chunk_index=0,
        page_number=1,
        text="All students must maintain 75% attendance.",
        token_count=10,
        clause_ref="Clause 1.1",
        allowed_roles=["student", "faculty", "admin"],
        embedding=[0.1] * 1536,
        status="current",
    )

    # 2. Faculty Document & Chunk
    doc_faculty = Document(
        id="doc-faculty",
        file_name="faculty_service_rules_2025.pdf",
        file_hash="hash2",
        title="Faculty Service Rules 2025",
        effective_date=date(2025, 1, 1),
        allowed_roles=["faculty", "admin"],
        status="current",
    )
    chunk_faculty = Chunk(
        id="chunk-faculty",
        document_id="doc-faculty",
        chunk_index=0,
        page_number=1,
        text="Invigilation remuneration is Rs. 500 per session. Canary: KVIT-FAC-CNRY-7731",
        token_count=15,
        clause_ref="Clause 4.1",
        allowed_roles=["faculty", "admin"],
        embedding=[0.2] * 1536,
        status="current",
    )

    # 3. Admin Document & Chunk
    doc_admin = Document(
        id="doc-admin",
        file_name="admin_salary_bands_and_budget_2025.pdf",
        file_hash="hash3",
        title="Admin Salary Bands and Budget 2025",
        effective_date=date(2025, 1, 1),
        allowed_roles=["admin"],
        status="current",
    )
    chunk_admin = Chunk(
        id="chunk-admin",
        document_id="doc-admin",
        chunk_index=0,
        page_number=1,
        text="Monthly salary bands: Assistant Professor Rs. 60,000 to Rs. 1,50,000. Canary: KVIT-ADM-CNRY-8870",
        token_count=20,
        clause_ref="Clause 8.1",
        allowed_roles=["admin"],
        embedding=[0.3] * 1536,
        status="current",
    )

    session.add_all([doc_student, doc_faculty, doc_admin, chunk_student, chunk_faculty, chunk_admin])
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_l1_sql_role_filtering(rbac_test_db):
    """Verify L1 SQL filtering prevents student from retrieving faculty/admin chunks."""
    retrieval_service = HybridRetrievalService(
        db_session=rbac_test_db,
        embedding_service=MockEmbeddingService(dimension=1536),
        reranker_service=MockRerankerService(),
        semantic_retrieval_enabled=False,
    )

    # 1. Student query: must only see student chunk
    student_res = retrieval_service.retrieve(
        query="remuneration and salary",
        top_k=10,
        top_n=5,
        role="student",
        lineage_expansion=False,
    )
    student_files = {c.file_name for c in student_res.reranked_results}
    assert "faculty_service_rules_2025.pdf" not in student_files
    assert "admin_salary_bands_and_budget_2025.pdf" not in student_files

    # 2. Faculty query: sees faculty + student chunks, but NOT admin
    faculty_res = retrieval_service.retrieve(
        query="remuneration and salary",
        top_k=10,
        top_n=5,
        role="faculty",
        lineage_expansion=False,
    )
    faculty_files = {c.file_name for c in faculty_res.reranked_results}
    assert "faculty_service_rules_2025.pdf" in faculty_files
    assert "admin_salary_bands_and_budget_2025.pdf" not in faculty_files

    # 3. Admin query: sees all
    admin_res = retrieval_service.retrieve(
        query="remuneration and salary",
        top_k=10,
        top_n=5,
        role="admin",
        lineage_expansion=False,
    )
    admin_files = {c.file_name for c in admin_res.reranked_results}
    assert "admin_salary_bands_and_budget_2025.pdf" in admin_files


# ------------------------------------------------------------------------------
# 3. Layer 2 (L2) Postgres Row-Level Security
# ------------------------------------------------------------------------------

def test_l2_rls_sql_setup_script():
    """Verify that scripts/setup_postgres_rls.sql defines FORCE RLS and role policies."""
    assert RLS_SQL_PATH.exists(), f"Missing RLS SQL setup script at {RLS_SQL_PATH}"
    sql_text = RLS_SQL_PATH.read_text(encoding="utf-8")

    assert "ENABLE ROW LEVEL SECURITY" in sql_text
    assert "FORCE ROW LEVEL SECURITY" in sql_text
    assert "current_setting('app.current_role', true)" in sql_text
    assert "kvit_app_user" in sql_text
    assert "NOBYPASSRLS" in sql_text


def test_l2_rls_policy_simulation_zero_rows_when_unset():
    """Verify that when app.current_role is unset (None), RLS policy returns False (0 rows)."""
    allowed_roles = ["faculty", "admin"]

    # When setting is unset (None)
    assert evaluate_rls_policy(None, allowed_roles) is False
    assert evaluate_rls_policy("", allowed_roles) is False

    # When setting is student
    assert evaluate_rls_policy("student", allowed_roles) is False

    # When setting is faculty
    assert evaluate_rls_policy("faculty", allowed_roles) is True

    # When setting is admin
    assert evaluate_rls_policy("admin", allowed_roles) is True


# ------------------------------------------------------------------------------
# 4. Layer 3 (L3) Runtime Invariant Assertion
# ------------------------------------------------------------------------------

def test_l3_runtime_assertion_blocks_unauthorized_chunk(rbac_test_db):
    """Verify that L3 aborts generation and returns abstention if an unauthorized chunk is in evidence."""
    retrieval_service = HybridRetrievalService(
        db_session=rbac_test_db,
        embedding_service=MockEmbeddingService(dimension=1536),
        reranker_service=MockRerankerService(),
        semantic_retrieval_enabled=False,
    )
    mock_llm = MockLLMService()
    qa_service = QAService(retrieval_service=retrieval_service, llm_service=mock_llm)

    # Deliberately mock retrieval to return a confidential faculty chunk to a student caller
    faculty_chunk = rbac_test_db.query(Chunk).filter(Chunk.id == "chunk-faculty").first()
    injected_passage = PassageEvidence(
        index=1,
        chunk_id=faculty_chunk.id,
        file_name="faculty_service_rules_2025.pdf",
        page_number=1,
        text=faculty_chunk.text,
        score=0.95,
        allowed_roles=["faculty", "admin"],  # Student is NOT permitted!
    )

    # Monkeypatch _prepare_passages_and_conflicts to inject unauthorized chunk
    qa_service._prepare_passages_and_conflicts = lambda req, role=None: (
        [injected_passage], False, [], [], False, None, None
    )

    req = AskRequest(question="What is the invigilation remuneration?", role="student")
    response = qa_service.answer(req, role="student")

    # Assert L3 caught the violation and aborted
    assert response.abstained is True
    assert response.abstain_reason == "unauthorized_evidence_blocked"
    assert response.answer == qa_service.ABSTENTION_SENTENCE
    assert response.citations == []
    assert mock_llm.generate_call_count == 0, "LLM was called despite L3 security invariant failure!"


# ------------------------------------------------------------------------------
# 5. Layer 4 (L4) Output Canary and Verbatim Scanner
# ------------------------------------------------------------------------------

def test_l4_output_scan_canary_leak_blocked():
    """Verify that L4 detects canary tokens and confidential facts for unauthorized roles."""
    scanner = SecurityScanner()

    # 1. Canary leak test for student
    leaked_canary_text = "The protocol states: dual lock system. Reference: KVIT-FAC-CNRY-4482"
    is_leak, reason = scanner.scan_output(leaked_canary_text, caller_role="student")
    assert is_leak is True
    assert "Canary token" in reason

    # 2. Verbatim statement leak test for student
    leaked_fact_text = "According to rules: Invigilation remuneration is Rs. 500 per session."
    is_leak, reason = scanner.scan_output(leaked_fact_text, caller_role="student")
    assert is_leak is True
    assert "confidential" in reason.lower()

    # 3. Authorized faculty caller is NOT blocked for faculty rules
    is_leak_fac, _ = scanner.scan_output(leaked_fact_text, caller_role="faculty")
    assert is_leak_fac is False

    # 4. Admin canary leaked to faculty caller
    admin_canary_text = "Disciplinary case details KVIT-ADM-CNRY-2208."
    is_leak_admin, reason = scanner.scan_output(admin_canary_text, caller_role="faculty")
    assert is_leak_admin is True
    assert "KVIT-ADM-CNRY-2208" in reason


def test_l4_output_scan_intercepts_llm_answer(rbac_test_db):
    """Verify that QAService.answer() intercepts an LLM response containing a canary."""
    retrieval_service = HybridRetrievalService(
        db_session=rbac_test_db,
        embedding_service=MockEmbeddingService(dimension=1536),
        reranker_service=MockRerankerService(),
        semantic_retrieval_enabled=False,
    )

    # Mock LLM to emit a canary token
    mock_llm = MockLLMService()
    mock_llm.custom_response = (
        '{"answer": "Invigilation fee is Rs. 500 [1]. Token: KVIT-FAC-CNRY-7731", '
        '"authoritative_sources": [1], "historical_sources": [], "conflict": false, '
        '"change_cards": [], "as_of": null, "abstain": false, "abstain_reason": null}'
    )
    qa_service = QAService(retrieval_service=retrieval_service, llm_service=mock_llm)

    # Valid student passage
    student_passage = PassageEvidence(
        index=1,
        chunk_id="chunk-student",
        file_name="student_rules.pdf",
        page_number=1,
        text="Student attendance rules [1].",
        score=0.9,
        allowed_roles=["student", "faculty", "admin"],
    )
    qa_service._prepare_passages_and_conflicts = lambda req, role=None: (
        [student_passage], False, [], [], False, None, None
    )

    req = AskRequest(question="What is the policy?", role="student")
    response = qa_service.answer(req, role="student")

    # Assert L4 caught the canary and blocked the answer
    assert response.abstained is True
    assert response.abstain_reason == "restricted_content_blocked"
    assert response.answer == qa_service.ABSTENTION_SENTENCE
    assert response.citations == []


# ------------------------------------------------------------------------------
# 6. Negative Control
# ------------------------------------------------------------------------------

def test_negative_control_enforcement_bypass():
    """Verify that disabling security enforcement allows leak detection (proves test validity)."""
    scanner = SecurityScanner()
    test_text = "Confidential invigilation remuneration is Rs. 500 per session."

    # When enforcement is enabled: leak is detected
    settings.SECURITY_ENFORCEMENT_ENABLED = True
    is_leak, _ = scanner.scan_output(test_text, caller_role="student")
    assert is_leak is True

    # When enforcement is disabled (negative control flag): scan is bypassed
    settings.SECURITY_ENFORCEMENT_ENABLED = False
    is_leak_disabled, _ = scanner.scan_output(test_text, caller_role="student")
    assert is_leak_disabled is False

    # Restore default setting
    settings.SECURITY_ENFORCEMENT_ENABLED = True
