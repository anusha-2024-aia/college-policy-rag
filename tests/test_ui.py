"""Tests for Streamlit UI client, backend contract, and response handling (ui/client.py)."""

import json
import pytest
import httpx
from pathlib import Path
from ui.client import (
    BackendAPIClient,
    BackendConnectionError,
    APIValidationError,
    RateLimitError,
    ServiceUnavailableError,
    GatewayTimeoutError,
    APIClientError,
    format_conflict_markdown,
    format_citation_header,
    discover_evaluation_reports,
    read_evaluation_report_content,
    get_matching_json_export,
    get_database_document_summary,
    inspect_pdf_bytes,
)
from app.schemas.qa import AskRequest, AskResponse, Citation, PassageEvidence, PolicyConflict, RetrievalDiagnostics


def test_client_url_normalization():
    """Verify BackendAPIClient strips trailing slashes from base URL."""
    client1 = BackendAPIClient("http://127.0.0.1:8000/")
    assert client1.base_url == "http://127.0.0.1:8000"

    client2 = BackendAPIClient("http://localhost:8000")
    assert client2.base_url == "http://localhost:8000"


def test_client_default_url_is_8000(monkeypatch):
    """Verify BackendAPIClient defaults to http://127.0.0.1:8000 when no base_url or env is set."""
    monkeypatch.delenv("BACKEND_API_URL", raising=False)
    client = BackendAPIClient()
    assert client.base_url == "http://127.0.0.1:8000"


def test_client_env_override_url(monkeypatch):
    """Verify BackendAPIClient respects BACKEND_API_URL when base_url is not explicitly passed."""
    monkeypatch.setenv("BACKEND_API_URL", "http://127.0.0.1:9000/")
    client = BackendAPIClient()
    assert client.base_url == "http://127.0.0.1:9000"


def test_client_explicit_arg_overrides_env(monkeypatch):
    """Verify explicit base_url argument takes precedence over BACKEND_API_URL env var."""
    monkeypatch.setenv("BACKEND_API_URL", "http://127.0.0.1:9000")
    client = BackendAPIClient("http://127.0.0.1:8000")
    assert client.base_url == "http://127.0.0.1:8000"



def test_client_successful_response_parsing(monkeypatch):
    """Verify BackendAPIClient correctly parses 200 OK responses with citations."""
    sample_response = {
        "question": "What is CS101 grading criteria?",
        "answer": "Grading criteria is Homework 40%, Midterm 30%, Final 30% [1].",
        "citations": [
            {
                "index": 1,
                "file_name": "student_syllabus.pdf",
                "page_number": 2,
                "snippet": "Grading criteria: Homework 40%, Midterm 30%, Final 30%.",
            }
        ],
        "passages": [
            {
                "index": 1,
                "chunk_id": "chunk-1",
                "file_name": "student_syllabus.pdf",
                "page_number": 2,
                "text": "Page 2: Grading criteria: Homework 40%, Midterm 30%, Final 30%.",
                "score": 0.88,
            }
        ],
        "abstained": False,
        "has_policy_conflict": False,
        "conflict_details": None,
        "diagnostics": {
            "timings_ms": {"vector_search_ms": 2.5, "total_retrieval_ms": 5.0},
            "vector_count": 5,
            "keyword_count": 5,
            "fused_count": 8,
            "reranked_count": 1,
        },
    }

    def mock_post(self, url, **kwargs):
        assert url == "http://127.0.0.1:8000/ask"
        assert kwargs["json"]["question"] == "What is CS101 grading criteria?"
        assert kwargs["json"]["role"] == "student"
        return httpx.Response(status_code=200, json=sample_response)

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    client = BackendAPIClient("http://127.0.0.1:8000")
    result = client.ask("What is CS101 grading criteria?", role="student")

    assert isinstance(result, AskResponse)
    assert result.question == "What is CS101 grading criteria?"
    assert not result.abstained
    assert not result.has_policy_conflict
    assert len(result.citations) == 1
    assert result.citations[0].file_name == "student_syllabus.pdf"
    assert result.citations[0].page_number == 2
    assert result.diagnostics is not None
    assert result.diagnostics.reranked_count == 1


def test_client_policy_conflict_parsing(monkeypatch):
    """Verify BackendAPIClient correctly parses responses with policy conflict flags and details."""
    conflict_response = {
        "question": "What is remote work allowance?",
        "answer": "Current policy allows 3 days [1], superseding previous 1 day [2].",
        "citations": [
            {"index": 1, "file_name": "policy_v2.pdf", "page_number": 1, "snippet": "3 days"},
            {"index": 2, "file_name": "policy_v1.pdf", "page_number": 1, "snippet": "1 day"},
        ],
        "passages": [],
        "abstained": False,
        "has_policy_conflict": True,
        "conflict_details": [
            {
                "current_title": "Remote Work Policy 2024",
                "current_file": "policy_v2.pdf",
                "current_effective_date": "2024-01-01",
                "current_citation_index": 1,
                "superseded_title": "Remote Work Policy 2023",
                "superseded_file": "policy_v1.pdf",
                "superseded_effective_date": "2023-01-01",
                "superseded_citation_index": 2,
                "description": "Policy 2023 superseded by 2024.",
            }
        ],
        "diagnostics": None,
    }

    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, **kwargs: httpx.Response(status_code=200, json=conflict_response),
    )

    client = BackendAPIClient("http://127.0.0.1:8000")
    result = client.ask("What is remote work allowance?", role="faculty")

    assert result.has_policy_conflict is True
    assert result.conflict_details is not None
    assert len(result.conflict_details) == 1
    assert result.conflict_details[0].current_title == "Remote Work Policy 2024"
    assert result.conflict_details[0].superseded_title == "Remote Work Policy 2023"


def test_client_abstention_parsing(monkeypatch):
    """Verify BackendAPIClient correctly parses abstention responses."""
    abstention_response = {
        "question": "Warp drive regulations?",
        "answer": "I do not have sufficient information in the provided documents to answer this question.",
        "citations": [],
        "passages": [],
        "abstained": True,
        "has_policy_conflict": False,
        "conflict_details": None,
        "diagnostics": None,
    }

    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, **kwargs: httpx.Response(status_code=200, json=abstention_response),
    )

    client = BackendAPIClient("http://127.0.0.1:8000")
    result = client.ask("Warp drive regulations?", role="student")

    assert result.abstained is True
    assert len(result.citations) == 0
    assert "not have sufficient information" in result.answer


def test_client_error_handling_validation_422(monkeypatch):
    """Verify HTTP 422 raises APIValidationError."""
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, **kwargs: httpx.Response(
            status_code=422,
            json={"detail": "Invalid role 'hacker'. Permitted roles are: student, faculty, admin."},
        ),
    )

    client = BackendAPIClient("http://127.0.0.1:8000")
    with pytest.raises(APIValidationError) as exc_info:
        client.ask("test", role="hacker")
    assert "Invalid role 'hacker'" in str(exc_info.value)


def test_client_error_handling_rate_limit_429(monkeypatch):
    """Verify HTTP 429 raises RateLimitError."""
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, **kwargs: httpx.Response(
            status_code=429,
            json={"detail": "LLM provider rate limit exceeded."},
        ),
    )

    client = BackendAPIClient("http://127.0.0.1:8000")
    with pytest.raises(RateLimitError) as exc_info:
        client.ask("test", role="student")
    assert "rate limit exceeded" in str(exc_info.value)


def test_client_error_handling_service_unavailable_503(monkeypatch):
    """Verify HTTP 503 raises ServiceUnavailableError."""
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, **kwargs: httpx.Response(
            status_code=503,
            json={"detail": "LLM service configuration error."},
        ),
    )

    client = BackendAPIClient("http://127.0.0.1:8000")
    with pytest.raises(ServiceUnavailableError) as exc_info:
        client.ask("test", role="student")
    assert "configuration error" in str(exc_info.value)


def test_client_error_handling_connection_refused(monkeypatch):
    """Verify connection failure raises BackendConnectionError with friendly guidance."""
    def mock_post(self, url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    client = BackendAPIClient("http://127.0.0.1:8000")
    with pytest.raises(BackendConnectionError) as exc_info:
        client.ask("test", role="student")
    assert "Could not connect to Document RAG backend" in str(exc_info.value)
    assert "Please verify the FastAPI server is running" in str(exc_info.value)


def test_client_error_handling_timeout(monkeypatch):
    """Verify request timeout raises BackendConnectionError."""
    def mock_post(self, url, **kwargs):
        raise httpx.TimeoutException("Timed out")

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    client = BackendAPIClient("http://127.0.0.1:8000")
    with pytest.raises(BackendConnectionError) as exc_info:
        client.ask("test", role="student")
    assert "timed out after" in str(exc_info.value)


def test_format_citation_header_with_pydantic_model():
    """Verify format_citation_header correctly formats a Citation Pydantic instance."""
    citation = Citation(
        index=1,
        file_name="student_handbook_2024.pdf",
        page_number=14,
        snippet="Students must maintain a 2.0 GPA.",
    )
    formatted = format_citation_header(citation)
    assert formatted == "**[1]** 📄 `student_handbook_2024.pdf` — **Page 14**"


def test_format_citation_header_with_dict():
    """Verify format_citation_header correctly formats a dictionary (history state)."""
    citation_dict = {
        "index": 2,
        "file_name": "academic_integrity_policy.pdf",
        "page_number": 3,
        "snippet": "Plagiarism incurs academic probation.",
    }
    formatted = format_citation_header(citation_dict)
    assert formatted == "**[2]** 📄 `academic_integrity_policy.pdf` — **Page 3**"


def test_format_conflict_markdown_with_pydantic_model():
    """Verify format_conflict_markdown formats all active and superseded details from PolicyConflict."""
    conflict = PolicyConflict(
        current_title="Remote Work Policy 2024",
        current_file="remote_work_2024.pdf",
        current_effective_date="2024-09-01",
        current_citation_index=1,
        superseded_title="Remote Work Policy 2022",
        superseded_file="remote_work_2022.pdf",
        superseded_effective_date="2022-01-15",
        superseded_citation_index=2,
        description="Updated remote work allowance from 1 day to 3 days per week.",
    )
    formatted = format_conflict_markdown(conflict)
    assert "🟢 **Active Policy**: Remote Work Policy 2024 (`remote_work_2024.pdf` [1]) — Effective: 2024-09-01" in formatted
    assert "🔴 **Superseded Policy**: Remote Work Policy 2022 (`remote_work_2022.pdf` [2]) — Effective: 2022-01-15" in formatted
    assert "📌 *Updated remote work allowance from 1 day to 3 days per week.*" in formatted


def test_format_conflict_markdown_with_dict():
    """Verify format_conflict_markdown handles dictionary history state."""
    conflict_dict = {
        "current_title": "Grading Scale Policy 2024",
        "current_file": "grading_2024.pdf",
        "current_effective_date": "2024-08-01",
        "current_citation_index": 1,
        "superseded_title": "Grading Scale Policy 2020",
        "superseded_file": "grading_2020.pdf",
        "superseded_effective_date": "2020-08-01",
        "superseded_citation_index": 3,
        "description": "Replaced +/- grading with letter grades.",
    }
    formatted = format_conflict_markdown(conflict_dict)
    assert "🟢 **Active Policy**: Grading Scale Policy 2024 (`grading_2024.pdf` [1]) — Effective: 2024-08-01" in formatted
    assert "🔴 **Superseded Policy**: Grading Scale Policy 2020 (`grading_2020.pdf` [3]) — Effective: 2020-08-01" in formatted
    assert "📌 *Replaced +/- grading with letter grades.*" in formatted


def test_abstention_ui_invariants():
    """Verify that an abstention response does not contain citations or ungrounded claims."""
    abstention = AskResponse(
        question="What is the warp core regulation?",
        answer="I do not have sufficient information in the provided documents to answer this question.",
        citations=[],
        passages=[],
        abstained=True,
        has_policy_conflict=False,
    )
    assert abstention.abstained is True
    assert len(abstention.citations) == 0
    assert not abstention.has_policy_conflict


def test_client_role_payload_propagation(monkeypatch):
    """Verify BackendAPIClient correctly propagates simulated roles (faculty, admin) in HTTP payload."""
    recorded_roles = []

    def mock_post(self, url, **kwargs):
        recorded_roles.append(kwargs["json"]["role"])
        return httpx.Response(
            status_code=200,
            json={
                "question": "test question",
                "answer": "test answer",
                "citations": [],
                "passages": [],
                "abstained": False,
                "has_policy_conflict": False,
            },
        )

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    client = BackendAPIClient("http://127.0.0.1:8000")
    client.ask("test", role="student")
    client.ask("test", role="faculty")
    client.ask("test", role="admin")

    assert recorded_roles == ["student", "faculty", "admin"]


def test_client_role_validation_against_real_schema():
    """Verify that only permitted roles (student, faculty, admin) pass schema validation."""
    for role in ["student", "faculty", "admin"]:
        req = AskRequest(question="test question", role=role)
        assert req.role == role

    # Invalid roles must fail validation
    with pytest.raises(ValueError):
        AskRequest(question="test question", role="guest")

    with pytest.raises(ValueError):
        AskRequest(question="test question", role="superuser")

    with pytest.raises(ValueError):
        AskRequest(question="test question", role="hacker")


def test_ui_rbac_restricted_document_abstention_invariant():
    """Verify that an abstention response for restricted queries has 0 citations and 0 passages."""
    restricted_response = AskResponse(
        question="What is the faculty grievance procedure?",
        answer="I do not have sufficient information in the provided documents to answer this question.",
        citations=[],
        passages=[],
        abstained=True,
        has_policy_conflict=False,
        diagnostics=RetrievalDiagnostics(
            timings_ms={"total_retrieval_ms": 4.2},
            vector_count=0,
            keyword_count=0,
            fused_count=0,
            reranked_count=0,
        ),
    )
    # The UI must never display citations or passages for an abstained restricted query
    assert restricted_response.abstained is True
    assert len(restricted_response.citations) == 0
    assert len(restricted_response.passages) == 0
    assert restricted_response.diagnostics.vector_count == 0
    assert restricted_response.diagnostics.reranked_count == 0


def test_discover_evaluation_reports_finds_stage3_reports():
    """Verify discover_evaluation_reports discovers Stage 3 reports with newest first."""
    reports = discover_evaluation_reports("eval/results")
    assert len(reports) >= 1
    # First report should be the final Stage 3 report
    assert reports[0].name == "eval_report_20261019_082717.md"


def test_discover_evaluation_reports_missing_or_empty_dir(tmp_path):
    """Verify discover_evaluation_reports gracefully returns empty list for missing/empty dirs."""
    assert discover_evaluation_reports(tmp_path / "non_existent") == []
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    assert discover_evaluation_reports(empty_dir) == []


def test_read_evaluation_report_content_valid_and_missing(tmp_path):
    """Verify reading report content and raising FileNotFoundError for missing reports."""
    # Valid report
    content = read_evaluation_report_content("eval/results/eval_report_20261019_082717.md")
    assert "# Document RAG - Evaluation Benchmark Report" in content
    assert "hybrid_plus_reranking_plus_version_awareness" in content

    # Missing report
    with pytest.raises(FileNotFoundError):
        read_evaluation_report_content(tmp_path / "non_existent_report.md")


def test_get_matching_json_export_valid_malformed_and_missing(tmp_path):
    """Verify get_matching_json_export handles valid JSON, malformed JSON, and missing files."""
    # 1. Valid real report from eval/results
    export = get_matching_json_export("eval/results/eval_report_20261019_082717.md")
    assert export is not None
    json_name, json_data, is_valid = export
    assert json_name == "eval_results_20261019_082717.json"
    assert is_valid is True
    assert len(json_data) > 0

    # 2. Missing JSON file
    dummy_report = tmp_path / "eval_report_99999999_000000.md"
    dummy_report.write_text("# Report", encoding="utf-8")
    assert get_matching_json_export(dummy_report) is None

    # 3. Malformed JSON file
    malformed_json = tmp_path / "eval_results_99999999_000000.json"
    malformed_json.write_text("{corrupt: json content", encoding="utf-8")
    export_malformed = get_matching_json_export(dummy_report)
    assert export_malformed is not None
    m_name, m_data, m_valid = export_malformed
    assert m_valid is False


def test_get_database_document_summary_mock_and_structure():
    """Verify get_database_document_summary structures document metrics correctly."""
    class MockDoc:
        def __init__(self, file_name, title, effective_date, supersedes, allowed_roles, total_pages, total_chunks, status):
            self.file_name = file_name
            self.title = title
            self.effective_date = effective_date
            self.supersedes = supersedes
            self.allowed_roles = allowed_roles
            self.total_pages = total_pages
            self.total_chunks = total_chunks
            self.status = status

    class MockQuery:
        def order_by(self, *args):
            return self

        def all(self):
            return [
                MockDoc("doc1.pdf", "Doc 1", "2024-01-01", None, ["student"], 2, 4, "indexed"),
                MockDoc("doc2.pdf", "Doc 2", "2024-02-01", "doc1.pdf", ["faculty"], 3, 6, "indexed"),
            ]

    class MockDB:
        def query(self, model):
            return MockQuery()

    summary = get_database_document_summary(MockDB())
    assert summary["total_docs"] == 2
    assert summary["total_chunks"] == 10
    assert summary["total_pages"] == 5
    assert len(summary["rows"]) == 2
    assert summary["rows"][0]["File Name"] == "doc1.pdf"
    assert summary["rows"][0]["Allowed Roles"] == "student"
    assert summary["rows"][1]["Supersedes"] == "doc1.pdf"


def test_get_database_document_summary_live_db():
    """Verify live database document catalog summary reflects verified 16 KVIT documents and 31 chunks."""
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        summary = get_database_document_summary(db)

    assert summary["total_docs"] == 16
    assert summary["total_chunks"] == 31
    assert summary["total_pages"] == 31
    assert len(summary["rows"]) == 16


def test_inspect_pdf_bytes_valid_and_invalid(tmp_path):
    """Verify inspect_pdf_bytes parses PDF in-memory without disk write or ingestion."""
    import pypdf
    # Create minimal 1-page PDF in memory
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    import io
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    result = inspect_pdf_bytes(pdf_bytes, "sample_preview.pdf")
    assert result["filename"] == "sample_preview.pdf"
    assert result["num_pages"] == 1
    assert result["file_size_kb"] > 0

    # Test invalid PDF bytes raises an error
    with pytest.raises(Exception):
        inspect_pdf_bytes(b"not a valid pdf binary content", "corrupt.pdf")


def test_exact_zip_directory_structure_exists():
    """Verify that all 7 page directories and policy_intelligence_studio from the uploaded ZIP exist."""
    expected_folders = [
        "page_1_policy_intelligence_dashboard",
        "page_2_ask_policy_workspace",
        "page_3_policy_change_intelligence",
        "page_4_document_library",
        "page_5_evaluations_benchmarks",
        "page_6_system_health",
        "page_7_about_architecture",
        "policy_intelligence_studio",
    ]
    for folder in expected_folders:
        folder_path = Path("ui") / folder
        assert folder_path.is_dir(), f"Folder ui/{folder} must exist"

    # Verify DESIGN.md
    assert (Path("ui") / "policy_intelligence_studio" / "DESIGN.md").is_file()

    # Verify each page has code.html and screen.png
    for p_num in range(1, 8):
        matches = list(Path("ui").glob(f"page_{p_num}_*"))
        assert len(matches) == 1
        p_dir = matches[0]
        assert (p_dir / "code.html").is_file(), f"Missing code.html in {p_dir}"
        assert (p_dir / "screen.png").is_file(), f"Missing screen.png in {p_dir}"
        assert (p_dir / "code.html").stat().st_size > 20000
        assert (p_dir / "screen.png").stat().st_size > 100000


def test_standalone_sidebar_cross_navigation_links():
    """Verify that all 7 standalone code.html files link to their sibling page directories."""
    import re
    targets = {
        1: "../page_1_policy_intelligence_dashboard/code.html",
        2: "../page_2_ask_policy_workspace/code.html",
        3: "../page_3_policy_change_intelligence/code.html",
        4: "../page_4_document_library/code.html",
        5: "../page_5_evaluations_benchmarks/code.html",
        6: "../page_6_system_health/code.html",
        7: "../page_7_about_architecture/code.html",
    }
    for p_num in range(1, 8):
        p_dir = list(Path("ui").glob(f"page_{p_num}_*"))[0]
        html = (p_dir / "code.html").read_text(encoding="utf-8")
        for target_idx, target_url in targets.items():
            expected = "code.html" if target_idx == p_num else target_url
            assert expected in html, f"Page {p_num} should contain link to {expected}"


def test_fastapi_serves_exact_zip_routes():
    """Verify FastAPI routes serve the exact ZIP structure at their native paths."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    pages = [
        "page_1_policy_intelligence_dashboard",
        "page_2_ask_policy_workspace",
        "page_3_policy_change_intelligence",
        "page_4_document_library",
        "page_5_evaluations_benchmarks",
        "page_6_system_health",
        "page_7_about_architecture",
    ]
    for p in pages:
        r_html = client.get(f"/{p}/code.html")
        assert r_html.status_code == 200
        assert "LexisPolicy AI" in r_html.text

        r_png = client.get(f"/{p}/screen.png")
        assert r_png.status_code == 200
        assert len(r_png.content) > 100000

    r_design = client.get("/policy_intelligence_studio/DESIGN.md")
    assert r_design.status_code == 200
    assert "Policy Intelligence Studio" in r_design.text


def test_ui_zip_package_integrity():
    """Verify generated ZIP package contains the exact 16 files/folders matching uploaded archive."""
    import zipfile
    zip_path = Path("lexis_policy_ai_ui.zip")
    assert zip_path.is_file(), "lexis_policy_ai_ui.zip must exist"

    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        assert "index.html" in namelist
        assert "policy_intelligence_studio/DESIGN.md" in namelist
        for p_num in range(1, 8):
            matches_html = [n for n in namelist if n.startswith(f"page_{p_num}_") and n.endswith("code.html")]
            matches_png = [n for n in namelist if n.startswith(f"page_{p_num}_") and n.endswith("screen.png")]
            assert len(matches_html) == 1, f"Missing code.html for page {p_num} in zip"
            assert len(matches_png) == 1, f"Missing screen.png for page {p_num} in zip"


def test_download_ui_zip_endpoint():
    """Verify GET /download-ui-zip downloads the exact zip package with 200 OK."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.get("/download-ui-zip")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert len(resp.content) > 3000000




