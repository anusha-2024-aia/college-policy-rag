"""Output Canary and Restricted Content Scanner for Defence-in-Depth Layer 4 (L4).

Scans generated answers and citations against canary tokens in eval/canaries.json
and confidential verbatim facts. If an unauthorized role's output contains restricted
canary identifiers or verbatim confidential statements, the scan intercepts and blocks
the response, logging a security alert and returning the canonical abstention response.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional, Any
from app.core.config import settings

logger = logging.getLogger(__name__)

CANARIES_FILE_PATH = Path("eval/canaries.json")


class SecurityScanner:
    """Defence-in-Depth Layer 4 Output Scanner."""

    CANARY_REGEX = re.compile(r"\bKVIT-[A-Z]{3}-CNRY-\d{4}\b", re.IGNORECASE)

    def __init__(self, canaries_path: Optional[Path] = None):
        self.canaries_path = canaries_path or CANARIES_FILE_PATH
        self._canary_data: Optional[dict[str, Any]] = None

    @property
    def canary_data(self) -> dict[str, Any]:
        """Lazy load and cache canary specifications from eval/canaries.json."""
        if self._canary_data is None:
            if self.canaries_path.exists():
                try:
                    with open(self.canaries_path, "r", encoding="utf-8") as f:
                        self._canary_data = json.load(f)
                except Exception as exc:
                    logger.error("Failed to load canaries file %s: %s", self.canaries_path, exc)
                    self._canary_data = {}
            else:
                logger.warning("Canaries file %s not found.", self.canaries_path)
                self._canary_data = {}
        return self._canary_data

    def scan_output(self, text: str, caller_role: str) -> tuple[bool, Optional[str]]:
        """Scan text output for canaries and restricted confidential facts.

        Args:
            text: Model-generated answer or text to verify.
            caller_role: Verified role of the caller ('student', 'faculty', 'admin').

        Returns:
            Tuple of (leak_detected: bool, leak_reason: Optional[str]).
        """
        if not text or not text.strip():
            return False, None

        if not getattr(settings, "L4_OUTPUT_SCAN_ENABLED", True) or not getattr(settings, "SECURITY_ENFORCEMENT_ENABLED", True):
            return False, None

        clean_role = (caller_role or "").strip().lower()

        # 1. Regex search for any canary token pattern
        found_tokens = self.CANARY_REGEX.findall(text)
        token_set = {t.upper() for t in found_tokens}

        for doc_name, doc_info in self.canary_data.items():
            allowed = [r.lower() for r in doc_info.get("allowed_roles", [])]
            doc_canary = str(doc_info.get("canary", "")).upper()

            # If caller is NOT authorized for this document's role tier
            if clean_role not in allowed and "all" not in allowed:
                # Check for explicit canary token match
                if doc_canary in token_set or doc_canary.lower() in text.lower():
                    reason = f"Canary token '{doc_canary}' from restricted document '{doc_name}' detected in response."
                    logger.critical("SECURITY VIOLATION (L4): %s (Caller: %s)", reason, clean_role)
                    return True, reason

                # Check for verbatim facts from unauthorized documents
                facts = doc_info.get("facts", [])
                for fact in facts:
                    # Clean punctuation for robust matching
                    norm_fact = re.sub(r"\s+", " ", fact).strip()
                    if not norm_fact:
                        continue

                    # Exact substring match
                    if norm_fact.lower() in text.lower():
                        reason = f"Verbatim confidential statement from '{doc_name}' detected: '{norm_fact[:60]}...'"
                        logger.critical("SECURITY VIOLATION (L4): %s (Caller: %s)", reason, clean_role)
                        return True, reason

                    # Significant signature fragments (n-grams > 6 words)
                    words = norm_fact.split()
                    if len(words) >= 8:
                        fragment = " ".join(words[:7]).lower()
                        if fragment in text.lower():
                            reason = f"Confidential text fragment from '{doc_name}' detected: '{fragment}...'"
                            logger.critical("SECURITY VIOLATION (L4): %s (Caller: %s)", reason, clean_role)
                            return True, reason

        return False, None

