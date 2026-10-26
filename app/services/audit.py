"""Audit service for logging access decisions and security events without leaking restricted text."""

import hashlib
import logging
from typing import Optional
from sqlalchemy.orm import Session
from app.models.audit import AccessAudit

logger = logging.getLogger(__name__)


def record_access_audit(
    db: Session,
    role: str,
    query: str,
    decision: str,
    blocked_candidates: int = 0,
    request_id: Optional[str] = None,
) -> Optional[AccessAudit]:
    """Record an access decision into the access_audit table.

    CRITICAL PRIVACY RULE:
    Never store raw user query text or restricted document content in the database.
    Stores strictly a one-way SHA-256 hash of the query.

    Args:
        db: Active SQLAlchemy Session.
        role: Validated caller role ('student', 'faculty', 'admin').
        query: Raw query string (will be hashed with SHA-256).
        decision: Decision code ('allowed', 'abstained', 'blocked_l1', 'blocked_l3', 'blocked_l4').
        blocked_candidates: Count of unauthorized candidates blocked.
        request_id: Optional correlation/request UUID.

    Returns:
        Persisted AccessAudit instance or None if database is unavailable.
    """
    try:
        # Compute SHA-256 hash of query (never store raw text)
        q_hash = hashlib.sha256((query or "").strip().encode("utf-8")).hexdigest()

        entry = AccessAudit(
            role=role,
            query_hash=q_hash,
            blocked_candidates=blocked_candidates,
            decision=decision,
            request_id=request_id,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry
    except Exception as exc:
        logger.warning("Failed to record access audit entry: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None

