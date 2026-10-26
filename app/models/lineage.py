"""DocumentLineage ORM model for version lineage tracking and supersession scope."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    DateTime,
    ForeignKey,
    JSON,
    Index,
)
from sqlalchemy.orm import relationship
from app.core.database import Base


def generate_uuid() -> str:
    """Generate a UUID4 hex string."""
    return str(uuid.uuid4())


class DocumentLineage(Base):
    """Lineage model linking predecessor documents to successor/amendment documents."""

    __tablename__ = "document_lineage"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    old_doc_id = Column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    new_doc_id = Column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope = Column(String(50), nullable=False)  # "full" or "partial"
    amended_clauses = Column(JSON, nullable=False, default=list)  # list of strings, e.g. ["Clause 4.2", "Clause 6.1"]
    evidence_page = Column(Integer, nullable=True)
    evidence_text = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    old_document = relationship(
        "Document",
        foreign_keys=[old_doc_id],
        back_populates="lineage_out",
    )
    new_document = relationship(
        "Document",
        foreign_keys=[new_doc_id],
        back_populates="lineage_in",
    )

    __table_args__ = (
        Index("idx_doc_lineage_old_new", "old_doc_id", "new_doc_id", unique=True),
        Index("idx_doc_lineage_scope", "scope"),
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentLineage(id={self.id}, old={self.old_doc_id}, "
            f"new={self.new_doc_id}, scope={self.scope}, clauses={self.amended_clauses})>"
        )
