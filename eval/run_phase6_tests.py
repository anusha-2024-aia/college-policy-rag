"""Phase 6 Comprehensive Test Suite and Verification Runner.

Executes and verifies:
1. 30 adversarial queries across student and faculty roles (60 evaluations): zero leaks.
2. Negative control with security enforcement disabled: leaks > 0.
3. Token attacks (alg=none, tampered signature, expired token, missing token).
4. Route sweep across all 20 API endpoints as student: zero leaks.
5. Role-scoped cache isolation: admin query followed by student identical query.
6. Authorized access verification on R11-R15 from golden set.
7. Version-aware unchanged clause verification on S14 and S15: has_policy_conflict=False, change_cards=[].
8. Prints required metrics: "leaks: 0 / N" and "negative control leaks: M / N".
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Ensure test environment points to local test database
os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.core.auth import (
    create_access_token,
    _base64url_encode,
)
from app.core.cache import query_cache
from eval.route_sweep import run_sweep

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("phase6_runner")

CANARIES_PATH = Path("eval/canaries.json")
ADVERSARIAL_PATH = Path("eval/adversarial_queries.jsonl")
GOLDEN_PATH = Path("eval/golden.jsonl")
RESULTS_DIR = Path("eval/results")


def check_response_for_leaks(
    data: dict[str, Any],
    forbidden_files: list[str],
    forbidden_canaries: list[str],
    canaries_data: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Inspect ask response system outputs (passages, citations, answer) for unauthorized leaks."""
    leak_reasons: list[str] = []

    # 1. Inspect retrieved passages
    passages = data.get("passages", [])
    for p in passages:
        p_file = p.get("file_name", "")
        if p_file in forbidden_files:
            leak_reasons.append(f"Passage contains forbidden file '{p_file}'")

    # 2. Inspect citations
    citations = data.get("citations", [])
    passages_by_idx = {p.get("index"): p.get("file_name") for p in passages}
    for c in citations:
        c_idx = c.get("index")
        c_file = passages_by_idx.get(c_idx)
        if c_file in forbidden_files:
            leak_reasons.append(f"Citation [{c_idx}] cites forbidden file '{c_file}'")

    # 3. Inspect generated answer for canaries and confidential facts
    answer = data.get("answer", "")
    ans_lower = answer.lower()

    for cnry in forbidden_canaries:
        if cnry.lower() in ans_lower:
            leak_reasons.append(f"Answer contains forbidden canary token '{cnry}'")

    for f_file in forbidden_files:
        doc_info = canaries_data.get(f_file, {})
        for fact in doc_info.get("facts", []):
            clean_fact = fact.strip().lower()
            if len(clean_fact) > 20 and clean_fact in ans_lower:
                leak_reasons.append(f"Answer contains verbatim confidential fact from '{f_file}': '{clean_fact[:50]}...'")

    return (len(leak_reasons) > 0, leak_reasons)


def run_phase6_suite() -> dict[str, Any]:
    """Execute all Phase 6 verification tests and return structured summary metrics."""
    client = TestClient(app)

    with open(ADVERSARIAL_PATH, "r", encoding="utf-8") as f:
        adversarial_queries = [json.loads(line) for line in f if line.strip()]

    with open(CANARIES_PATH, "r", encoding="utf-8") as f:
        canaries_data = json.load(f)

    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        golden_set = [json.loads(line) for line in f if line.strip()]

    # Collect forbidden files and canaries per role
    student_forbidden_files = list(canaries_data.keys())
    student_forbidden_canaries = [info["canary"] for info in canaries_data.values()]

    admin_files = [
        "disciplinary_committee_case_summaries_2025.pdf",
        "admin_fee_waiver_internal_criteria_2025.pdf",
        "admin_salary_bands_and_budget_2025.pdf",
    ]
    faculty_forbidden_files = admin_files
    faculty_forbidden_canaries = [canaries_data[f]["canary"] for f in admin_files if f in canaries_data]

    student_token = create_access_token("student")
    faculty_token = create_access_token("faculty")
    admin_token = create_access_token("admin")

    # --------------------------------------------------------------------------
    # 1. 30 Adversarial Queries × Roles (Zero Leaks Verification)
    # --------------------------------------------------------------------------
    logger.info("Executing 30 adversarial queries across student and faculty roles...")
    total_adversarial_evaluations = 0
    protected_leaks = 0
    detailed_leak_reports = []

    # Student role against all 30 queries
    for q in adversarial_queries:
        query_cache.clear()
        total_adversarial_evaluations += 1
        resp = client.post(
            "/ask",
            json={"question": q["query"]},
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200, f"Query {q['id']} failed with status {resp.status_code}"
        data = resp.json()

        is_leak, reasons = check_response_for_leaks(
            data,
            forbidden_files=student_forbidden_files,
            forbidden_canaries=student_forbidden_canaries,
            canaries_data=canaries_data,
        )
        if is_leak:
            protected_leaks += 1
            detailed_leak_reports.append({"id": q["id"], "role": "student", "reasons": reasons})

    # Faculty role against all 30 queries (must not leak admin files/canaries)
    for q in adversarial_queries:
        query_cache.clear()
        total_adversarial_evaluations += 1
        resp = client.post(
            "/ask",
            json={"question": q["query"]},
            headers={"Authorization": f"Bearer {faculty_token}"},
        )
        assert resp.status_code == 200, f"Query {q['id']} failed with status {resp.status_code}"
        data = resp.json()

        is_leak, reasons = check_response_for_leaks(
            data,
            forbidden_files=faculty_forbidden_files,
            forbidden_canaries=faculty_forbidden_canaries,
            canaries_data=canaries_data,
        )
        if is_leak:
            protected_leaks += 1
            detailed_leak_reports.append({"id": q["id"], "role": "faculty", "reasons": reasons})

    # --------------------------------------------------------------------------
    # 2. Negative Control (Security Enforcement Disabled -> Leaks > 0)
    # --------------------------------------------------------------------------
    logger.info("Executing negative control with SECURITY_ENFORCEMENT_ENABLED = False...")
    settings.SECURITY_ENFORCEMENT_ENABLED = False
    neg_control_evaluations = len(adversarial_queries)
    neg_control_leaks = 0

    try:
        for q in adversarial_queries:
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
                neg_control_leaks += 1
    finally:
        settings.SECURITY_ENFORCEMENT_ENABLED = True

    # --------------------------------------------------------------------------
    # 3. Token Attacks Verification
    # --------------------------------------------------------------------------
    logger.info("Executing token attacks (alg=none, tampered, expired, missing)...")
    token_attacks_passed = True

    # alg=none
    h_none = _base64url_encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    p_none = _base64url_encode(json.dumps({"role": "admin", "sub": "admin", "exp": int(time.time()) + 3600}).encode())
    resp_none = client.post("/ask", json={"question": "salary bands"}, headers={"Authorization": f"Bearer {h_none}.{p_none}."})
    assert resp_none.status_code == 401

    # tampered signature
    valid_parts = student_token.split(".")
    tampered_p = _base64url_encode(json.dumps({"role": "admin", "sub": "admin", "exp": int(time.time()) + 3600}).encode())
    resp_tamp = client.post("/ask", json={"question": "salary bands"}, headers={"Authorization": f"Bearer {valid_parts[0]}.{tampered_p}.{valid_parts[2]}"})
    assert resp_tamp.status_code == 401

    # expired token
    expired_tok = create_access_token("admin", expires_in_seconds=-60)
    resp_exp = client.post("/ask", json={"question": "salary bands"}, headers={"Authorization": f"Bearer {expired_tok}"})
    assert resp_exp.status_code == 401

    # missing token on admin-only route (Phase 2 strict requirement: missing token -> 401)
    resp_missing = client.get("/admin/security/visible-document-counts")
    assert resp_missing.status_code == 401

    # insufficient role (student on admin-only route -> 403)
    resp_forbidden = client.get(
        "/admin/security/visible-document-counts",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp_forbidden.status_code == 403

    # --------------------------------------------------------------------------
    # 4. Route Sweep Verification
    # --------------------------------------------------------------------------
    logger.info("Executing Phase 5 route sweep across 20 endpoints as student...")
    route_leaks, sweep_results = run_sweep()
    assert route_leaks == 0, f"Route sweep detected {route_leaks} leaks: {sweep_results}"

    # --------------------------------------------------------------------------
    # 5. Role-Scoped Cache Isolation Verification
    # --------------------------------------------------------------------------
    logger.info("Executing cache isolation test...")
    query_cache.clear()
    probe_query = "What are the administrative executive salary bands?"

    # Admin asks
    admin_resp = client.post("/ask", json={"question": probe_query}, headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_resp.status_code == 200

    # Student asks same question
    student_resp = client.post("/ask", json={"question": probe_query}, headers={"Authorization": f"Bearer {student_token}"})
    assert student_resp.status_code == 200
    st_data = student_resp.json()
    assert st_data.get("abstained") is True
    assert st_data.get("citations") == []
    assert "KVIT-ADM-CNRY-8870" not in student_resp.text
    assert "Rs. 60,000" not in student_resp.text

    # --------------------------------------------------------------------------
    # 6. Authorized Access Verification (R11-R15)
    # --------------------------------------------------------------------------
    logger.info("Executing authorized access tests for R11-R15...")
    r_queries = [item for item in golden_set if item.get("id") in ["R11", "R12", "R13", "R14", "R15"]]
    authorized_passed = 0

    for item in r_queries:
        query_cache.clear()
        tok = admin_token if item["role"] == "admin" else faculty_token
        resp = client.post("/ask", json={"question": item["question"]}, headers={"Authorization": f"Bearer {tok}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("abstained") is False, f"Authorized query {item['id']} abstained unexpectedly!"
        assert len(data.get("citations", [])) > 0, f"Authorized query {item['id']} has no citations!"
        authorized_passed += 1

    # --------------------------------------------------------------------------
    # 7. Version Tests: Unchanged Clause Verification (S14, S15)
    # --------------------------------------------------------------------------
    logger.info("Executing version tests for unchanged clauses (S14, S15)...")
    unchanged_queries = [item for item in golden_set if item.get("id") in ["S14", "S15"]]
    unchanged_passed = 0

    for item in unchanged_queries:
        query_cache.clear()
        resp = client.post(
            "/ask",
            json={"question": item["question"]},
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("has_policy_conflict") is False, f"Unchanged query {item['id']} falsely flagged policy conflict!"
        assert len(data.get("change_cards", [])) == 0, f"Unchanged query {item['id']} returned false change cards!"
        unchanged_passed += 1

    # --------------------------------------------------------------------------
    # 8. Summary Output and Report Serialization
    # --------------------------------------------------------------------------
    summary = {
        "status": "passed" if protected_leaks == 0 and neg_control_leaks > 0 else "failed",
        "adversarial_evaluations": total_adversarial_evaluations,
        "protected_leaks": protected_leaks,
        "negative_control_evaluations": neg_control_evaluations,
        "negative_control_leaks": neg_control_leaks,
        "token_attacks_passed": token_attacks_passed,
        "route_sweep_leaks": route_leaks,
        "cache_isolation_passed": True,
        "authorized_access_passed": f"{authorized_passed}/{len(r_queries)}",
        "unchanged_clauses_passed": f"{unchanged_passed}/{len(unchanged_queries)}",
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = RESULTS_DIR / "phase6_test_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Required output format
    print(f"leaks: {protected_leaks} / {total_adversarial_evaluations}")
    print(f"negative control leaks: {neg_control_leaks} / {neg_control_evaluations}")

    return summary


if __name__ == "__main__":
    run_phase6_suite()

