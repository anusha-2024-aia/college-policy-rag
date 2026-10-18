"""Chunk ORM model definition with vector and full-text search indexing."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.types import TypeDecorator
from sqlalchemy.dialects.postgresql import TSVECTOR
from pgvector.sqlalchemy import Vector
from app.core.database import Base


def generate_uuid() -> str:
    """Generate a UUID4 hex string."""
    return str(uuid.uuid4())


class TSVectorType(TypeDecorator):
    """Platform-independent TSVector type.

    Renders as native TSVECTOR on PostgreSQL and falls back to TEXT on SQLite/other dialects.
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(TSVECTOR())
        return dialect.type_descriptor(Text())


class Chunk(Base):
    """Chunk model storing parsed text, page isolation metadata, embeddings, and FTS data."""

    __tablename__ = "chunks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=False, index=True)  # 1-based index
    text = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False)
    embedding = Column(Vector(1536), nullable=False)
    tsv = Column(TSVectorType, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationship back to Document
    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        # HNSW index for vector cosine similarity on PostgreSQL + pgvector
        Index(
            "idx_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # GIN index for PostgreSQL full-text search
        Index(
            "idx_chunks_tsv_gin",
            "tsv",
            postgresql_using="gin",
        ),
        # Compound index for document order retrieval
        Index("idx_chunks_doc_chunk", "document_id", "chunk_index"),
        # Compound index for document page retrieval
        Index("idx_chunks_doc_page", "document_id", "page_number"),
    )

    def __repr__(self) -> str:
        return (
            f"<Chunk(id={self.id}, doc_id={self.document_id}, "
            f"page={self.page_number}, chunk_idx={self.chunk_index}, tokens={self.token_count})>"
        )
