"""Document ORM model definition."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Date, DateTime, Integer, JSON, ForeignKey
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import relationship
from app.core.database import Base


def generate_uuid() -> str:
    """Generate a UUID4 hex string."""
    return str(uuid.uuid4())


class PolicyStatus(str):
    """String subclass that treats 'current' and 'ingested' as compatible for backward compatibility."""

    def __eq__(self, other):
        val = str(self)
        if val in ("current", "ingested") and other in ("current", "ingested"):
            return True
        return super().__eq__(other)

    def __hash__(self):
        return hash(str(self))


class DocumentStatusType(TypeDecorator):
    """Platform-independent status type returning PolicyStatus."""

    impl = String(50)
    cache_ok = True

    def process_result_value(self, value, dialect):
        return PolicyStatus(value) if value is not None else None

    def process_bind_param(self, value, dialect):
        return str(value) if value is not None else None


class Document(Base):
    """Document model storing document metadata, version tracking, and access roles."""

    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    file_name = Column(String(255), nullable=False, unique=True, index=True)
    file_hash = Column(String(64), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    doc_version = Column(String(50), nullable=True)
    effective_date = Column(Date, nullable=False)
    expires_date = Column(Date, nullable=True)
    supersedes = Column(String(255), nullable=True)
    supersedes_doc_id = Column(
        String(36),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    allowed_roles = Column(JSON, nullable=False, default=list)
    status = Column(DocumentStatusType, nullable=False, default=lambda: PolicyStatus("current"))
    total_pages = Column(Integer, nullable=False, default=0)
    total_chunks = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Cascade delete chunks when a document is deleted/re-ingested
    chunks = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.chunk_index",
    )

    # Lineage relationships
    lineage_out = relationship(
        "DocumentLineage",
        foreign_keys="DocumentLineage.old_doc_id",
        back_populates="old_document",
        cascade="all, delete-orphan",
    )
    lineage_in = relationship(
        "DocumentLineage",
        foreign_keys="DocumentLineage.new_doc_id",
        back_populates="new_document",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, file_name='{self.file_name}', title='{self.title}')>"
