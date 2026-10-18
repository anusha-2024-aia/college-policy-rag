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


class BackendAPIClient:
    """Client for querying the Document RAG FastAPI service."""

    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: float = 45.0):
        self.base_url = base_url.rstrip("/")
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
