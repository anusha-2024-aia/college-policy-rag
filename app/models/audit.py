"""Access Audit ORM model definition."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime
from app.core.database import Base


def generate_uuid() -> str:
    """Generate a UUID4 hex string."""
    return str(uuid.uuid4())


class AccessAudit(Base):
    """Audit log tracking queries, access control decisions, and blocked candidates.

    CRITICAL SECURITY INVARIANT:
    Never stores raw user query text, prompt contents, or retrieved document snippets.
    Stores strictly SHA-256 query hashes and numeric candidate metrics.
    """

    __tablename__ = "access_audit"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    ts = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    role = Column(String(50), nullable=False, index=True)
    query_hash = Column(String(64), nullable=False, index=True)
    blocked_candidates = Column(Integer, nullable=False, default=0)
    decision = Column(String(50), nullable=False, index=True)  # allowed, abstained, blocked_l1, blocked_l3, blocked_l4
    request_id = Column(String(64), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<AccessAudit(id={self.id}, role='{self.role}', decision='{self.decision}', blocked={self.blocked_candidates})>"

