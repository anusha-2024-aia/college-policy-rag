"""HTTP Client for communicating with the Document RAG FastAPI backend."""

import sys
from pathlib import Path

# Ensure project root is in sys.path and remove 'ui' directory from sys.path
# to prevent 'ui/app.py' from shadowing the top-level 'app/' package.
_project_root = str(Path(__file__).resolve().parent.parent)
_ui_dir = str(Path(__file__).resolve().parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
while _ui_dir in sys.path:
    sys.path.remove(_ui_dir)

import logging
import os
from typing import Any, Optional
import httpx
from app.schemas.qa import AskResponse

logger = logging.getLogger(__name__)


class APIClientError(Exception):
    """Base exception for UI API client interactions."""
    pass


class BackendConnectionError(APIClientError):
    """Raised when the backend API is unreachable, refused connection, or timed out."""
    pass


class APIValidationError(APIClientError):
    """Raised when the backend rejects parameters with HTTP 422 (e.g. invalid role)."""
    pass


class RateLimitError(APIClientError):
    """Raised when backend provider rate limits are exceeded (HTTP 429)."""
    pass


class ServiceUnavailableError(APIClientError):
    """Raised when backend LLM service is unavailable or misconfigured (HTTP 503)."""
    pass


class GatewayTimeoutError(APIClientError):
    """Raised when backend LLM generation times out (HTTP 504)."""
    pass


def format_conflict_markdown(conf: Any) -> str:
    """Format a PolicyConflict model or dictionary into clean Markdown for UI alerts."""
    if hasattr(conf, "model_dump"):
        data = conf.model_dump()
    elif isinstance(conf, dict):
        data = conf
    else:
        data = {}

    curr_title = data.get("current_title", "Current Policy")
    curr_file = data.get("current_file", "")
    curr_date = data.get("current_effective_date") or "N/A"
    curr_idx = data.get("current_citation_index")
    curr_ref = f"`{curr_file}` [{curr_idx}]" if (curr_file and curr_idx is not None) else f"`{curr_file}`" if curr_file else ""

    sup_title = data.get("superseded_title", "Older Policy")
    sup_file = data.get("superseded_file", "")
    sup_date = data.get("superseded_effective_date") or "N/A"
    sup_idx = data.get("superseded_citation_index")
    sup_ref = f"`{sup_file}` [{sup_idx}]" if (sup_file and sup_idx is not None) else f"`{sup_file}`" if sup_file else ""

    desc = data.get("description") or "A newer version of this policy has superseded the older provision."

    curr_line = f"🟢 **Active Policy**: {curr_title}" + (f" ({curr_ref})" if curr_ref else "") + f" — Effective: {curr_date}"
    sup_line = f"🔴 **Superseded Policy**: {sup_title}" + (f" ({sup_ref})" if sup_ref else "") + f" — Effective: {sup_date}"
    desc_line = f"📌 *{desc}*"

    return f"{curr_line}\n\n{sup_line}\n\n{desc_line}"


def format_citation_header(citation: Any) -> str:
    """Format citation header markdown with evidence index, filename, and page number."""
    if hasattr(citation, "model_dump"):
        data = citation.model_dump()
    elif isinstance(citation, dict):
        data = citation
    else:
        data = {}

    idx = data.get("index", 1)
    file_name = data.get("file_name", "document.pdf")
    page_num = data.get("page_number", 1)
    return f"**[{idx}]** 📄 `{file_name}` — **Page {page_num}**"


def discover_evaluation_reports(results_dir: Optional[Path | str] = None) -> list[Path]:
    """Discover evaluation markdown report files sorted reverse-chronologically."""
    target_dir = Path(results_dir) if results_dir else Path("eval/results")
    if not target_dir.exists() or not target_dir.is_dir():
        return []
    reports = sorted(list(target_dir.glob("eval_report_*.md")), reverse=True)
    return reports


def read_evaluation_report_content(report_path: Path | str) -> str:
    """Read markdown report content safely with UTF-8 encoding."""
    p = Path(report_path)
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"Evaluation report not found: {p}")
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def get_matching_json_export(report_path: Path | str) -> Optional[tuple[str, str, bool]]:
    """Return matching raw JSON export (filename, content, is_valid) for a report path."""
    import json
    p = Path(report_path)
    json_name = p.name.replace("eval_report_", "eval_results_").replace(".md", ".json")
    json_path = p.parent / json_name
    if not json_path.exists() or not json_path.is_file():
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
        json.loads(raw_content)
        return (json_name, raw_content, True)
    except json.JSONDecodeError:
        return (json_name, raw_content, False)
    except Exception:
        return None


def get_database_document_summary(db) -> dict:
    """Query documents catalog in read-only mode and return structured summary metrics."""
    from app.models.document import Document
    docs = db.query(Document).order_by(Document.effective_date.desc()).all()
    total_chunks = sum(d.total_chunks for d in docs)
    total_pages = sum(d.total_pages for d in docs)
    rows = [
        {
            "File Name": d.file_name,
            "Title": d.title,
            "Effective Date": str(d.effective_date),
            "Supersedes": d.supersedes or "—",
            "Allowed Roles": ", ".join(d.allowed_roles) if isinstance(d.allowed_roles, list) else str(d.allowed_roles),
            "Pages": d.total_pages,
            "Chunks": d.total_chunks,
            "Status": d.status,
        }
        for d in docs
    ]
    return {
        "total_docs": len(docs),
        "total_chunks": total_chunks,
        "total_pages": total_pages,
        "rows": rows,
    }


def inspect_pdf_bytes(pdf_bytes: bytes, filename: str) -> dict:
    """Inspect uploaded PDF in-memory without storing or triggering ingestion."""
    import io
    import pypdf
    stream = io.BytesIO(pdf_bytes)
    reader = pypdf.PdfReader(stream)
    num_pages = len(reader.pages)
    file_size_kb = len(pdf_bytes) / 1024.0
    preview_text = ""
    if num_pages > 0:
        preview_text = reader.pages[0].extract_text() or ""
    return {
        "filename": filename,
        "num_pages": num_pages,
        "file_size_kb": file_size_kb,
        "preview_text": preview_text,
    }



class BackendAPIClient:
    """Client for querying the Document RAG FastAPI service."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 45.0,
    ):
        resolved_url = base_url or os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
        self.base_url = resolved_url.rstrip("/")
        self.timeout = timeout

    def ask(
        self,
        question: str,
        role: str = "student",
        top_k: int = 20,
        top_n: int = 5,
        version_aware: bool = True,
        include_diagnostics: bool = False,
        abstention_threshold: Optional[float] = None,
    ) -> AskResponse:
        """Send question to POST /ask and return structured AskResponse."""
        url = f"{self.base_url}/ask"
        payload = {
            "question": question,
            "role": role,
            "top_k": top_k,
            "top_n": top_n,
            "version_aware": version_aware,
            "include_diagnostics": include_diagnostics,
        }
        if abstention_threshold is not None:
            payload["abstention_threshold"] = abstention_threshold

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload)

            if resp.status_code == 200:
                data = resp.json()
                return AskResponse.model_validate(data)

            elif resp.status_code == 422:
                detail = resp.json().get("detail", "Invalid input parameters.")
                raise APIValidationError(f"Request validation failed: {detail}")

            elif resp.status_code == 429:
                detail = resp.json().get("detail", "Rate limit exceeded. Please retry shortly.")
                raise RateLimitError(detail)

            elif resp.status_code == 503:
                detail = resp.json().get("detail", "LLM service configuration error or service unavailable.")
                raise ServiceUnavailableError(detail)

            elif resp.status_code == 504:
                detail = resp.json().get("detail", "Backend service timed out during answer generation.")
                raise GatewayTimeoutError(detail)

            else:
                resp.raise_for_status()
                raise APIClientError(f"Unexpected status code: {resp.status_code}")

        except httpx.ConnectError as exc:
            logger.error("Failed to connect to backend at %s: %s", url, exc)
            raise BackendConnectionError(
                f"Could not connect to Document RAG backend at {self.base_url}. "
                "Please verify the FastAPI server is running."
            ) from exc

        except httpx.TimeoutException as exc:
            logger.error("Request to %s timed out after %.1fs: %s", url, self.timeout, exc)
            raise BackendConnectionError(
                f"Request to backend timed out after {self.timeout}s."
            ) from exc

        except httpx.HTTPError as exc:
            logger.error("HTTP error during request to %s: %s", url, exc)
            raise APIClientError(f"HTTP communication error: {exc}") from exc
