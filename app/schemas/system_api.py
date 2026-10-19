"""Pydantic schemas for system status and statistics API."""

from pydantic import BaseModel


class SystemStatsResponse(BaseModel):
    """Real system-level summary metrics from database and active configuration."""
    app_name: str
    environment: str
    total_docs: int
    total_chunks: int
    total_pages: int
    semantic_retrieval_enabled: bool
    embedding_model: str
    embedding_dimension: int
    reranker_model: str
    llm_provider: str
    llm_model: str
