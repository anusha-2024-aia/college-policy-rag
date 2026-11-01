"""ORM model for tracking active embedding index metadata and configuration."""

from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime
from app.core.database import Base


class EmbeddingIndexMetadata(Base):
    """Stores the active embedding model, dimension, and normalization for the vector index.

    Guarantees document-query embedding model consistency: at query time, the active
    query embedding provider must match the indexed model metadata, or a ModelMismatchError
    is raised.
    """

    __tablename__ = "embedding_index_metadata"

    id = Column(String(50), primary_key=True, default="default")
    model_id = Column(String(100), nullable=False)
    dim = Column(Integer, nullable=False)
    normalized = Column(Boolean, nullable=False, default=True)
    is_mock = Column(Boolean, nullable=False, default=False)
    chunk_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<EmbeddingIndexMetadata(id={self.id}, model_id='{self.model_id}', "
            f"dim={self.dim}, normalized={self.normalized}, is_mock={self.is_mock}, "
            f"chunks={self.chunk_count})>"
        )

