"""Role-Scoped Query Cache with cryptographic corpus versioning and request parameters.

Enforces Phase 5 and Phase 6 cache isolation specification:
- Cache key strictly includes: caller role + corpus version + query hash + versioning flags.
- An admin query cached in memory can NEVER be accessed by a student caller,
  even for identical query strings.
- Distinct request configurations (e.g. version_aware on vs off, diagnostics) occupy distinct cache slots.
"""

import hashlib
import time
from typing import Optional, Any
from app.core.config import settings
from app.schemas.qa import AskResponse


class QueryCache:
    """In-memory role-isolated query cache."""

    def __init__(self, default_ttl_seconds: int = 3600):
        self.default_ttl = default_ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def compute_cache_key(
        self,
        query: str,
        role: str,
        corpus_version: Optional[str] = None,
        version_aware: Optional[bool] = None,
        lineage_expansion: Optional[bool] = None,
        as_of: Optional[str] = None,
        top_n: Optional[int] = 5,
        include_diagnostics: Optional[bool] = False,
    ) -> str:
        """Compute isolated cache key incorporating role, corpus version, and query parameters.

        Format:
        sha256("{role}:{corpus_version}:{normalized_query}:va={version_aware}:le={lineage_expansion}:as_of={as_of}:top_n={top_n}:diag={include_diagnostics}")
        """
        clean_role = (role or "student").strip().lower()
        c_ver = (corpus_version or settings.CORPUS_VERSION).strip()
        norm_query = (query or "").strip().lower()

        raw_key = (
            f"{clean_role}:{c_ver}:{norm_query}:va={version_aware}:"
            f"le={lineage_expansion}:as_of={as_of}:top_n={top_n}:diag={include_diagnostics}"
        )
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def get(
        self,
        query: str,
        role: str,
        version_aware: Optional[bool] = None,
        lineage_expansion: Optional[bool] = None,
        as_of: Optional[str] = None,
        top_n: Optional[int] = 5,
        include_diagnostics: Optional[bool] = False,
    ) -> Optional[AskResponse]:
        """Retrieve cached AskResponse if valid and unexpired for the specific role and parameters."""
        if not getattr(settings, "QUERY_CACHE_ENABLED", True):
            return None

        key = self.compute_cache_key(
            query,
            role,
            version_aware=version_aware,
            lineage_expansion=lineage_expansion,
            as_of=as_of,
            top_n=top_n,
            include_diagnostics=include_diagnostics,
        )
        item = self._store.get(key)
        if not item:
            return None

        expires_at, response_data = item
        if time.time() > expires_at:
            # Expired
            self._store.pop(key, None)
            return None

        return AskResponse.model_validate(response_data)

    def set(
        self,
        query: str,
        role: str,
        response: AskResponse,
        version_aware: Optional[bool] = None,
        lineage_expansion: Optional[bool] = None,
        as_of: Optional[str] = None,
        top_n: Optional[int] = 5,
        include_diagnostics: Optional[bool] = False,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Store AskResponse under role-isolated cache key."""
        if not getattr(settings, "QUERY_CACHE_ENABLED", True):
            return

        key = self.compute_cache_key(
            query,
            role,
            version_aware=version_aware,
            lineage_expansion=lineage_expansion,
            as_of=as_of,
            top_n=top_n,
            include_diagnostics=include_diagnostics,
        )
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        expires_at = time.time() + ttl

        self._store[key] = (expires_at, response.model_dump())

    def clear(self) -> None:
        """Evict all cache entries."""
        self._store.clear()


# Global query cache singleton
query_cache = QueryCache()
