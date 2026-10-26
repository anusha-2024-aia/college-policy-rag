"""Tests for Phase 6: Comprehensive Security & Version Test Suite.

Verifies:
1. 30 adversarial queries across student and faculty roles (60 evaluations): zero leaks.
2. Negative control (security enforcement disabled): leaks > 0.
3. Token attacks (alg=none, tampered signature, expired token, missing token).
4. Role-scoped cache isolation (admin confidential query followed by identical student query).
5. Authorized access verification on golden set queries R11-R15.
6. Version tests on unchanged clauses (S14, S15): has_policy_conflict=False, change_cards=[].
7. Formatted console output prints: "leaks: 0 / N" and "negative control leaks: M / N".
"""

import json
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.auth import (
    create_access_token,
    verify_access_token,
    AuthenticationError,
    _base64url_encode,
)
from app.core.cache import query_cache
from eval.run_phase6_tests import check_response_for_leaks, run_phase6_suite

client = TestClient(app)

CANARIES_PATH = Path("eval/canaries.json")
ADVERSARIAL_PATH = Path("eval/adversarial_queries.jsonl")
GOLDEN_PATH = Path("eval/golden.jsonl")


@pytest.fixture(scope="module")
def adversarial_data():
    with open(ADVERSARIAL_PATH, "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f if line.strip()]
    with open(CANARIES_PATH, "r", encoding="utf-8") as f:
        canaries = json.load(f)
    return queries, canaries


def test_adversarial_queries_student_zero_leaks(adversarial_data):
    """Verify that all 30 adversarial queries evaluated as student result in zero leaks."""
    queries, canaries_data = adversarial_data
    student_token = create_access_token("student")
    student_forbidden_files = list(canaries_data.keys())
    student_forbidden_canaries = [info["canary"] for info in canaries_data.values()]

    leaks = 0
    leak_details = []

    for q in queries:
        query_cache.clear()
        resp = client.post(
            "/ask",
            json={"question": q["query"]},
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()

        is_leak, reasons = check_response_for_leaks(
            data,
            forbidden_files=student_forbidden_files,
            forbidden_canaries=student_forbidden_canaries,
            canaries_data=canaries_data,
        )
        if is_leak:
            leaks += 1
            leak_details.append((q["id"], reasons))

    assert leaks == 0, f"Detected {leaks} leaks for student: {leak_details}"


def test_adversarial_queries_faculty_zero_leaks(adversarial_data):
    """Verify that all 30 adversarial queries evaluated as faculty do not leak admin files or canaries."""
    queries, canaries_data = adversarial_data
    faculty_token = create_access_token("faculty")

    admin_files = [
        "disciplinary_committee_case_summaries_2025.pdf",
        "admin_fee_waiver_internal_criteria_2025.pdf",
        "admin_salary_bands_and_budget_2025.pdf",
    ]
    faculty_forbidden_files = admin_files
    faculty_forbidden_canaries = [canaries_data[f]["canary"] for f in admin_files if f in canaries_data]

    leaks = 0
    leak_details = []

    for q in queries:
        query_cache.clear()
        resp = client.post(
            "/ask",
            json={"question": q["query"]},
            headers={"Authorization": f"Bearer {faculty_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()

        is_leak, reasons = check_response_for_leaks(
            data,
            forbidden_files=faculty_forbidden_files,
            forbidden_canaries=faculty_forbidden_canaries,
            canaries_data=canaries_data,
        )
        if is_leak:
            leaks += 1
            leak_details.append((q["id"], reasons))

    assert leaks == 0, f"Detected {leaks} leaks for faculty: {leak_details}"


def test_negative_control_detects_leaks(adversarial_data):
    """Verify negative control: disabling security enforcement allows leaks to be detected (> 0)."""
    queries, canaries_data = adversarial_data
    student_token = create_access_token("student")
    student_forbidden_files = list(canaries_data.keys())
    student_forbidden_canaries = [info["canary"] for info in canaries_data.values()]

    settings.SECURITY_ENFORCEMENT_ENABLED = False
    neg_leaks = 0

    try:
        for q in queries:
            query_cache.clear()
            resp = client.post(
                "/ask",
                json={"question": q["query"]},
                headers={"Authorization": f"Bearer {student_token}"},
            )
            data = resp.json()
            is_leak, _ = check_response_for_leaks(
                data,
                forbidden_files=q.get("forbidden_files", student_forbidden_files),
                forbidden_canaries=q.get("forbidden_canaries", student_forbidden_canaries),
                canaries_data=canaries_data,
            )
            if is_leak:
                neg_leaks += 1
    finally:
        settings.SECURITY_ENFORCEMENT_ENABLED = True

    assert neg_leaks > 0, "Negative control failed: disabling security did not produce any leaks!"
    assert neg_leaks in (15, 17), f"Expected 15 or 17 negative control leaks, got {neg_leaks}"


def test_token_attacks_alg_none_tampered_expired_missing():
    """Verify cryptographic rejection of malformed, tampered, expired, and missing tokens."""
    # 1. alg=none attack
    h_none = _base64url_encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    p_none = _base64url_encode(json.dumps({"role": "admin", "sub": "admin", "exp": int(time.time()) + 3600}).encode())
    resp_none = client.post(
        "/ask",
        json={"question": "salary bands"},
        headers={"Authorization": f"Bearer {h_none}.{p_none}."},
    )
    assert resp_none.status_code == 401

    # 2. Tampered signature / edited role claim attack
    valid_token = create_access_token("student")
    parts = valid_token.split(".")
    tampered_p = _base64url_encode(json.dumps({"role": "admin", "sub": "admin", "exp": int(time.time()) + 3600}).encode())
    resp_tampered = client.post(
        "/ask",
        json={"question": "salary bands"},
        headers={"Authorization": f"Bearer {parts[0]}.{tampered_p}.{parts[2]}"},
    )
    assert resp_tampered.status_code == 401

    # 3. Expired token attack
    expired_token = create_access_token("admin", expires_in_seconds=-60)
    resp_expired = client.post(
        "/ask",
        json={"question": "salary bands"},
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp_expired.status_code == 401

    # 4. Missing token on privileged admin route
    resp_missing = client.get("/admin/security/visible-document-counts")
    assert resp_missing.status_code == 403


def test_cache_isolation_admin_student():
    """Verify cache isolation prevents student from accessing cached admin responses."""
    query_cache.clear()
    confidential_q = "What are the administrative executive salary bands?"

    admin_token = create_access_token("admin")
    student_token = create_access_token("student")

    # Admin asks confidential question
    admin_resp = client.post(
        "/ask",
        json={"question": confidential_q},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_resp.status_code == 200

    # Student asks exact same question
    student_resp = client.post(
        "/ask",
        json={"question": confidential_q},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert student_resp.status_code == 200
    st_data = student_resp.json()

    assert st_data.get("abstained") is True
    assert st_data.get("citations") == []
    assert "KVIT-ADM-CNRY-8870" not in student_resp.text
    assert "Rs. 60,000" not in student_resp.text


def test_golden_authorized_access_r11_to_r15():
    """Verify authorized users (faculty, admin) successfully access documents in R11-R15."""
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        golden_set = [json.loads(line) for line in f if line.strip()]

    r_queries = [item for item in golden_set if item.get("id") in ["R11", "R12", "R13", "R14", "R15"]]
    admin_token = create_access_token("admin")
    faculty_token = create_access_token("faculty")

    for item in r_queries:
        query_cache.clear()
        tok = admin_token if item["role"] == "admin" else faculty_token
        resp = client.post(
            "/ask",
            json={"question": item["question"]},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("abstained") is False, f"Query {item['id']} abstained unexpectedly!"
        assert len(data.get("citations", [])) > 0, f"Query {item['id']} had empty citations!"


def test_unchanged_clause_version_tests():
    """Verify unchanged clause queries S14 and S15 produce no conflict flag."""
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        golden_set = [json.loads(line) for line in f if line.strip()]

    student_token = create_access_token("student")
    unchanged_queries = [item for item in golden_set if item.get("id") in ["S14", "S15"]]

    for item in unchanged_queries:
        query_cache.clear()
        resp = client.post(
            "/ask",
            json={"question": item["question"]},
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("has_policy_conflict") is False, f"Unchanged query {item['id']} flagged conflict!"
        assert len(data.get("change_cards", [])) == 0, f"Unchanged query {item['id']} returned change cards!"


def test_phase6_suite_summary_metrics(capsys):
    """Verify Phase 6 summary metrics output format."""
    summary = run_phase6_suite()
    captured = capsys.readouterr()

    assert summary["protected_leaks"] == 0
    assert summary["negative_control_leaks"] > 0
    assert "leaks: 0 / 60" in captured.out
    assert f"negative control leaks: {summary['negative_control_leaks']} / 30" in captured.out

