"""ChunkSemantic ORM model definition for 384-dimensional dense vectors."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.core.database import Base


def generate_uuid() -> str:
    """Generate a UUID4 hex string."""
    return str(uuid.uuid4())


class ChunkSemantic(Base):
    """Normalized parallel vector storage for 384-dimensional ONNX embeddings."""

    __tablename__ = "chunks_semantic"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    chunk_id = Column(
        String(36),
        ForeignKey("chunks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    embedding = Column(Vector(384), nullable=False)
    model_name = Column(String(100), nullable=False, default="all-MiniLM-L6-v2")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Unidirectional relationship to Chunk
    chunk = relationship("Chunk")

    __table_args__ = (
        Index(
            "idx_chunks_semantic_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<ChunkSemantic(id={self.id}, chunk_id={self.chunk_id}, model={self.model_name})>"
