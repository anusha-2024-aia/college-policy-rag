"""Large Language Model service with OpenAI integration and deterministic mock."""

import abc
import json
import logging
import re
from collections.abc import Generator
from typing import Optional
import httpx
from openai import OpenAI
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Base exception for LLM operations."""
    pass


class LLMAuthenticationError(LLMError):
    """Raised when LLM API key is missing, invalid, or unauthorized."""
    pass


class LLMRateLimitError(LLMError):
    """Raised when LLM provider rate limits are encountered."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when LLM request times out."""
    pass


class BaseLLMService(abc.ABC):
    """Abstract interface for LLM text generation and streaming."""

    @abc.abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate complete answer text from prompt."""
        pass

    @abc.abstractmethod
    def generate_stream(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        """Stream answer text tokens as a generator."""
        pass


class OpenAILLMService(BaseLLMService):
    """Production LLM service using OpenAI chat completions."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 30.0,
    ):
        self._api_key = api_key or settings.LLM_API_KEY
        if not self._api_key:
            raise LLMAuthenticationError(
                "OpenAI API key is missing. Configure LLM_API_KEY in .env before using OpenAILLMService."
            )
        self.model = model or settings.LLM_MODEL
        self.timeout_seconds = timeout_seconds

        try:
            self.client = OpenAI(api_key=self._api_key, timeout=self.timeout_seconds)
        except Exception as exc:
            raise LLMAuthenticationError(f"Failed to initialize OpenAI client: {exc}") from exc

    def _build_messages(self, prompt: str, system_prompt: Optional[str]) -> list[dict[str, str]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = self._build_messages(prompt, system_prompt)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                stream=False,
            )
            content = response.choices[0].message.content
            return content.strip() if content else ""
        except AuthenticationError as exc:
            logger.error("OpenAI authentication failed: %s", exc)
            raise LLMAuthenticationError(f"LLM authentication failed: {exc}") from exc
        except RateLimitError as exc:
            logger.error("OpenAI rate limit exceeded: %s", exc)
            raise LLMRateLimitError(f"LLM rate limit exceeded: {exc}") from exc
        except (APITimeoutError, TimeoutError) as exc:
            logger.error("OpenAI request timed out: %s", exc)
            raise LLMTimeoutError(f"LLM request timed out after {self.timeout_seconds}s") from exc
        except APIConnectionError as exc:
            logger.error("OpenAI connection error: %s", exc)
            raise LLMError(f"LLM connection error: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected error during LLM generation: %s", exc)
            raise LLMError(f"LLM generation failed: {exc}") from exc

    def generate_stream(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        messages = self._build_messages(prompt, system_prompt)
        try:
            response_stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                stream=True,
            )
            for chunk in response_stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except AuthenticationError as exc:
            raise LLMAuthenticationError(f"LLM authentication failed: {exc}") from exc
        except RateLimitError as exc:
            raise LLMRateLimitError(f"LLM rate limit exceeded: {exc}") from exc
        except (APITimeoutError, TimeoutError) as exc:
            raise LLMTimeoutError(f"LLM request timed out: {exc}") from exc
        except Exception as exc:
            raise LLMError(f"LLM streaming failed: {exc}") from exc


class GeminiLLMService(BaseLLMService):
    """Google Gemini API LLM service (free-tier capable) using official Generative Language REST API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-1.5-flash",
        timeout_seconds: float = 30.0,
    ):
        self._api_key = api_key or settings.GEMINI_API_KEY or settings.LLM_API_KEY
        if not self._api_key:
            raise LLMAuthenticationError(
                "Gemini API key is missing. Configure GEMINI_API_KEY or LLM_API_KEY in .env before using GeminiLLMService."
            )
        self.model = model or settings.LLM_MODEL
        if self.model in ("gemini-1.5-flash", "models/gemini-1.5-flash"):
            self._model_path = "models/gemini-2.5-flash"
        elif not self.model.startswith("models/"):
            self._model_path = f"models/{self.model}"
        else:
            self._model_path = self.model
        self.timeout_seconds = timeout_seconds
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def _build_payload(self, prompt: str, system_prompt: Optional[str] = None) -> dict:
        payload: dict = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
            },
        }
        if system_prompt:
            payload["system_instruction"] = {
                "parts": [{"text": system_prompt}]
            }
        return payload

    def _handle_error_response(self, response: httpx.Response) -> None:
        status = response.status_code
        try:
            err_body = response.json()
            err_msg = err_body.get("error", {}).get("message", response.text)
        except Exception:
            err_msg = response.text

        if status in (400, 401, 403):
            logger.error("Gemini authentication/permission error (%d): %s", status, err_msg)
            raise LLMAuthenticationError(f"Gemini API authentication failed: {err_msg}")
        elif status == 429:
            logger.warning("Gemini rate limit exceeded (%d): %s", status, err_msg)
            raise LLMRateLimitError(f"Gemini rate limit exceeded: {err_msg}")
        else:
            logger.error("Gemini API error (%d): %s", status, err_msg)
            raise LLMError(f"Gemini API error ({status}): {err_msg}")

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        payload = self._build_payload(prompt, system_prompt)
        url = f"{self.base_url}/{self._model_path}:generateContent"

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    url,
                    params={"key": self._api_key},
                    json=payload,
                )
                if response.status_code != 200:
                    self._handle_error_response(response)

                data = response.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return ""
                parts = candidates[0].get("content", {}).get("parts", [])
                text_parts = [p.get("text", "") for p in parts if "text" in p]
                return "".join(text_parts).strip()

        except (LLMAuthenticationError, LLMRateLimitError, LLMError):
            raise
        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.error("Gemini request timed out: %s", exc)
            raise LLMTimeoutError(f"Gemini request timed out after {self.timeout_seconds}s") from exc
        except httpx.RequestError as exc:
            logger.error("Gemini connection error: %s", exc)
            raise LLMError(f"Gemini connection error: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected error during Gemini generation: %s", exc)
            raise LLMError(f"Gemini generation failed: {exc}") from exc

    def generate_stream(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        payload = self._build_payload(prompt, system_prompt)
        url = f"{self.base_url}/{self._model_path}:streamGenerateContent"

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                with client.stream(
                    "POST",
                    url,
                    params={"key": self._api_key, "alt": "sse"},
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        response.read()
                        self._handle_error_response(response)

                    for line in response.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        json_str = line[6:].strip()
                        if not json_str:
                            continue
                        try:
                            chunk_data = json.loads(json_str)
                            candidates = chunk_data.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                for part in parts:
                                    if "text" in part and part["text"]:
                                        yield part["text"]
                        except json.JSONDecodeError:
                            continue

        except (LLMAuthenticationError, LLMRateLimitError, LLMError):
            raise
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise LLMTimeoutError(f"Gemini streaming timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LLMError(f"Gemini streaming connection error: {exc}") from exc
        except Exception as exc:
            raise LLMError(f"Gemini streaming failed: {exc}") from exc


class MockLLMService(BaseLLMService):
    """Deterministic, zero-cost mock LLM for testing, CI, and offline operation."""

    ABSTENTION_PHRASE = "I do not have sufficient information in the provided documents to answer this question."

    def __init__(
        self,
        simulate_error: Optional[str] = None,
        custom_response: Optional[str] = None,
    ):
        self.simulate_error = simulate_error
        self.custom_response = custom_response

    def _check_simulated_error(self) -> None:
        if self.simulate_error == "auth":
            raise LLMAuthenticationError("Simulated LLM authentication failure")
        elif self.simulate_error == "rate_limit":
            raise LLMRateLimitError("Simulated LLM rate limit failure")
        elif self.simulate_error == "timeout":
            raise LLMTimeoutError("Simulated LLM timeout")
        elif self.simulate_error == "general":
            raise LLMError("Simulated generic LLM error")

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        self._check_simulated_error()
        if self.custom_response is not None:
            return self.custom_response

        # Check for unanswerable trigger keywords in prompt
        unanswerable_triggers = [
            "mars", "quantum", "warp", "speed of light", "unanswerable", "alien", "jupiter"
        ]
        prompt_lower = prompt.lower()
        if any(trigger in prompt_lower for trigger in unanswerable_triggers):
            return self.ABSTENTION_PHRASE

        # If prompt has no context passages (empty Context Evidence)
        if "Context Evidence:\n\n" in prompt or "Context Evidence:\nNone" in prompt or "[1]" not in prompt:
            return self.ABSTENTION_PHRASE

        # Version-aware prompt handling: check if primary evidence [1] supersedes an older policy in evidence
        superseded_matches = list(re.finditer(
            r"\[(\d+)\]\s+(?:Title:\s*([^|\n]+)\s*\|\s*)?File:[^\n]+\[STATUS:\s*SUPERSEDED\s+by\s+([^-\]]+)\s*-\s*Effective:\s*([^\]]+)\]\n([^\n]+)",
            prompt,
        ))

        primary_current_match = re.search(
            r"\[1\]\s+(?:Title:\s*([^|\n]+)\s*\|\s*)?File:[^\n]+\[STATUS:\s*CURRENT\s*-\s*Effective:\s*([^\]]+)\]\n([^\n]+)",
            prompt,
        )

        if primary_current_match and superseded_matches:
            cur_idx = "1"
            cur_title = (primary_current_match.group(1) or "").strip()
            cur_date = primary_current_match.group(2).strip()
            cur_text = primary_current_match.group(3).strip().rstrip(".")

            for sup_m in superseded_matches:
                old_idx = sup_m.group(1)
                old_sup_by = sup_m.group(3).strip()
                old_date = sup_m.group(4).strip()
                old_text = sup_m.group(5).strip().rstrip(".")

                if cur_title and (cur_title.lower() in old_sup_by.lower() or old_sup_by.lower() in cur_title.lower()):
                    return (
                        f"Under the current policy (effective {cur_date}), {cur_text} [{cur_idx}]. "
                        f"However, this supersedes the previous policy (effective {old_date}), "
                        f"which stated that {old_text} [{old_idx}]."
                    )

        # Standard extraction if no conflict or version tags
        passage_matches = re.findall(r"\[(\d+)\]\s+(?:Title:[^\n]+\|\s*)?File:[^\n]+\n([^\n]+)", prompt)
        if not passage_matches:
            return self.ABSTENTION_PHRASE

        # Synthesize factual response citing [1] and [2]
        facts: list[str] = []
        for idx_str, text_snippet in passage_matches[:2]:
            clean_snippet = text_snippet.strip().rstrip(".")
            facts.append(f"According to the documentation, {clean_snippet} [{idx_str}].")

        return " ".join(facts)

    def generate_stream(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        full_text = self.generate(prompt, system_prompt)
        words = full_text.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")


def get_llm_service(
    force_mock: bool = False,
    simulate_error: Optional[str] = None,
    custom_response: Optional[str] = None,
) -> BaseLLMService:
    """Factory selecting GeminiLLMService, OpenAILLMService, or MockLLMService."""
    provider = (settings.LLM_PROVIDER or "openai").lower()

    if force_mock or settings.APP_ENV == "test" or simulate_error or custom_response:
        logger.info("Using deterministic MockLLMService")
        return MockLLMService(simulate_error=simulate_error, custom_response=custom_response)

    if provider == "gemini":
        gemini_key = settings.GEMINI_API_KEY or settings.LLM_API_KEY
        is_placeholder = not gemini_key or "your_" in gemini_key.lower() or gemini_key in ("test", "dummy")
        if is_placeholder:
            logger.info("Gemini API key not configured or placeholder, using MockLLMService")
            return MockLLMService()
        logger.info("Using GeminiLLMService (model=%s)", settings.LLM_MODEL)
        return GeminiLLMService(api_key=gemini_key, model=settings.LLM_MODEL)

    if provider == "openai":
        key = settings.LLM_API_KEY
        is_placeholder = not key or "your_" in key.lower() or key in ("test", "dummy")
        if is_placeholder:
            logger.info("OpenAI API key not configured or placeholder, using MockLLMService")
            return MockLLMService()
        logger.info("Using OpenAILLMService (model=%s)", settings.LLM_MODEL)
        return OpenAILLMService(api_key=key, model=settings.LLM_MODEL)

    logger.warning("Unrecognized LLM provider '%s', falling back to MockLLMService", provider)
    return MockLLMService()
