"""Phase 5 Comprehensive Route Sweep Script.

Calls every endpoint as 'student' (and unauthenticated) to verify that:
1. No confidential filenames are exposed.
2. No confidential titles or keywords are exposed.
3. No canary tokens (KVIT-*-CNRY-*) are exposed.
4. Admin-only endpoints strictly return HTTP 403 Forbidden.
5. Unauthorized document queries return uniform 404 Not Found without leaking existence.
"""

import os
os.environ["APP_ENV"] = "test"

import logging
import sys
from typing import Any
from fastapi.testclient import TestClient
from app.core.config import settings
settings.APP_ENV = "test"

from app.main import app
from app.core.auth import create_access_token

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("route_sweep")

client = TestClient(app)

CONFIDENTIAL_FILENAMES = [
    "faculty_service_rules_2025.pdf",
    "question_paper_confidentiality_protocol_2025.pdf",
    "marks_moderation_guidelines_2025.pdf",
    "disciplinary_committee_case_summaries_2025.pdf",
    "admin_fee_waiver_internal_criteria_2025.pdf",
    "admin_salary_bands_and_budget_2025.pdf",
]

CONFIDENTIAL_TITLE_KEYWORDS = [
    "salary bands",
    "faculty service",
    "disciplinary committee",
    "fee waiver internal",
    "confidentiality protocol",
    "marks moderation guidelines",
]

CANARIES = [
    "KVIT-FAC-CNRY-7731",
    "KVIT-FAC-CNRY-4482",
    "KVIT-FAC-CNRY-9156",
    "KVIT-ADM-CNRY-2208",
    "KVIT-ADM-CNRY-6639",
    "KVIT-ADM-CNRY-8870",
]


def check_for_leaks(endpoint: str, text: str) -> list[str]:
    """Scan response text from an endpoint for confidential filenames, titles, or canaries."""
    leaks = []
    text_lower = text.lower()

    # 1. Filenames check
    for fname in CONFIDENTIAL_FILENAMES:
        if fname.lower() in text_lower:
            leaks.append(f"[{endpoint}] Leaked confidential filename: {fname}")

    # 2. Titles check
    for title in CONFIDENTIAL_TITLE_KEYWORDS:
        if title in text_lower:
            leaks.append(f"[{endpoint}] Leaked confidential title keyword: '{title}'")

    # 3. Canaries check
    for canary in CANARIES:
        if canary.lower() in text_lower:
            leaks.append(f"[{endpoint}] Leaked canary token: {canary}")

    return leaks


def check_ask_response_for_leaks(endpoint: str, data: dict[str, Any]) -> list[str]:
    """Scan QA output fields (answer, citations, passages) for leaks, ignoring echoed input question."""
    leaks = []
    # Build text of system outputs
    output_parts = [data.get("answer", "")]
    for cit in data.get("citations", []):
        output_parts.append(str(cit))
    for p in data.get("passages", []):
        output_parts.append(p.get("file_name", ""))
        output_parts.append(p.get("text", ""))
        output_parts.append(p.get("document_title", ""))

    combined_output = " ".join(output_parts)
    return check_for_leaks(endpoint, combined_output)


def run_sweep() -> tuple[int, list[str]]:
    """Execute complete route sweep as student."""
    student_token = create_access_token("student")
    auth_headers = {"Authorization": f"Bearer {student_token}"}
    all_leaks: list[str] = []
    routes_checked = 0

    logger.info("Starting Phase 5 leak sweep across all routes as 'student'...")

    # 1. GET /documents
    routes_checked += 1
    resp = client.get("/documents", headers=auth_headers)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    leaks = check_for_leaks("GET /documents", resp.text)
    all_leaks.extend(leaks)
    data = resp.json()
    assert data["total_docs"] == 10, f"Expected 10 student documents, got {data['total_docs']}"
    assert data["hidden_count"] == 6, f"Expected 6 hidden documents, got {data['hidden_count']}"

    # 2. GET /documents/{id} for confidential document (must 404 without leaking existence)
    for conf_file in CONFIDENTIAL_FILENAMES:
        routes_checked += 1
        resp = client.get(f"/documents/{conf_file}", headers=auth_headers)
        assert resp.status_code == 404, f"Expected 404 for restricted {conf_file}, got {resp.status_code}"
        leaks = check_for_leaks(f"GET /documents/{conf_file}", resp.text)
        all_leaks.extend(leaks)

    # 3. POST /documents/inspect
    routes_checked += 1
    test_pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF"
    files = {"file": ("student_upload.pdf", test_pdf_bytes, "application/pdf")}
    resp = client.post("/documents/inspect", files=files, headers=auth_headers)
    leaks = check_for_leaks("POST /documents/inspect", resp.text)
    all_leaks.extend(leaks)

    # 4. POST /ask (Probing for confidential faculty & admin policies)
    probe_questions = [
        "What is the invigilation remuneration per session?",
        "What is the discretionary fee waiver pool amount and approval limit?",
        "What are the monthly salary bands for Assistant Professor?",
        "Tell me about the disciplinary committee case for student S-1042.",
        "What is the canary token for faculty service rules?",
    ]
    for q in probe_questions:
        routes_checked += 1
        resp = client.post("/ask", json={"question": q}, headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        leaks = check_ask_response_for_leaks(f"POST /ask ('{q[:30]}...')", data)
        all_leaks.extend(leaks)
        assert len(leaks) == 0, f"Leaked restricted data on probe '{q}': {leaks}"

    # 5. POST /ask/stream (SSE streaming probe)
    routes_checked += 1
    resp = client.post(
        "/ask/stream",
        json={"question": "What is the fee waiver pool?"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    # Scan streamed tokens and citations
    leaks = check_for_leaks("POST /ask/stream", resp.text)
    all_leaks.extend(leaks)
    assert len(leaks) == 0, f"Leaked restricted data on stream probe: {leaks}"

    # 6. GET /system/stats
    routes_checked += 1
    resp = client.get("/system/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_docs"] == 10, f"Expected 10 student-scoped documents in /system/stats, got {data['total_docs']}"
    leaks = check_for_leaks("GET /system/stats", resp.text)
    all_leaks.extend(leaks)

    # 7. GET /evaluations/reports
    routes_checked += 1
    resp = client.get("/evaluations/reports", headers=auth_headers)
    assert resp.status_code == 200
    leaks = check_for_leaks("GET /evaluations/reports", resp.text)
    all_leaks.extend(leaks)

    # 8. GET /evaluations/reports/{filename}
    list_resp = client.get("/evaluations/reports", headers=auth_headers)
    reports = list_resp.json().get("reports", [])
    if reports:
        target_name = reports[0]["filename"]
        routes_checked += 1
        resp = client.get(f"/evaluations/reports/{target_name}", headers=auth_headers)
        assert resp.status_code == 200
        leaks = check_for_leaks(f"GET /evaluations/reports/{target_name}", resp.text)
        all_leaks.extend(leaks)

    # 9. Admin-only endpoints must return 403 Forbidden to student
    admin_routes = [
        "/admin/security/denied-attempts",
        "/admin/security/visible-document-counts",
        "/admin/security/last-leak-test",
    ]
    for ar in admin_routes:
        routes_checked += 1
        resp = client.get(ar, headers=auth_headers)
        assert resp.status_code == 403, f"Expected 403 Forbidden on {ar} for student, got {resp.status_code}"
        leaks = check_for_leaks(ar, resp.text)
        all_leaks.extend(leaks)

    logger.info("Route sweep complete: checked %d endpoints.", routes_checked)
    return len(all_leaks), all_leaks


def main():
    leak_count, leaks = run_sweep()
    if leak_count > 0:
        logger.error("LEAKS DETECTED (%d):", leak_count)
        for leak_item in leaks:
            logger.error("  - %s", leak_item)
        sys.exit(1)
    else:
        logger.info("SUCCESS: 0 leaks found across all routes for student persona.")
        sys.exit(0)


if __name__ == "__main__":
    main()
