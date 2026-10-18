"""Document ORM model definition."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Date, DateTime, Integer, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base


def generate_uuid() -> str:
    """Generate a UUID4 hex string."""
    return str(uuid.uuid4())


class Document(Base):
    """Document model storing document metadata, version tracking, and access roles."""

    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    file_name = Column(String(255), nullable=False, unique=True, index=True)
    file_hash = Column(String(64), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    effective_date = Column(Date, nullable=False)
    supersedes = Column(String(255), nullable=True)
    allowed_roles = Column(JSON, nullable=False, default=list)
    status = Column(String(50), nullable=False, default="ingested")
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

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, file_name='{self.file_name}', title='{self.title}')>"
