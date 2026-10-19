"""Data schemas for retrieval stages, ranking, and diagnostics."""

from typing import Optional
from pydantic import BaseModel, Field


class ScoredChunk(BaseModel):
    """Chunk retrieved with an individual retrieval score (vector similarity or keyword ts_rank)."""

    chunk_id: str
    document_id: str
    file_name: str
    title: str
    page_number: int
    text: str
    score: float = Field(..., description="Cosine similarity or BM25/ts_rank score")
    rank: int = Field(..., description="1-based rank within this stage")


class FusedChunk(BaseModel):
    """Candidate chunk after Reciprocal Rank Fusion of vector and keyword results."""

    chunk_id: str
    document_id: str
    file_name: str
    title: str
    page_number: int
    text: str
    vector_rank: Optional[int] = Field(None, description="1-based rank in vector search, if present")
    keyword_rank: Optional[int] = Field(None, description="1-based rank in keyword search, if present")
    vector_score: Optional[float] = Field(None, description="Original vector similarity score")
    keyword_score: Optional[float] = Field(None, description="Original keyword match score")
    rrf_score: float = Field(..., description="Combined Reciprocal Rank Fusion score")
    fused_rank: int = Field(..., description="1-based rank after RRF combination")


class RerankedChunk(BaseModel):
    """Final passage scored and ordered by the cross-encoder or reranking service."""

    chunk_id: str
    document_id: str
    file_name: str
    title: str
    page_number: int
    text: str
    vector_rank: Optional[int] = None
    keyword_rank: Optional[int] = None
    rrf_score: float
    rerank_score: float = Field(..., description="Cross-encoder relevance score")
    final_rank: int = Field(..., description="1-based final output rank")


class RetrievalDiagnostics(BaseModel):
    """Timing and candidate count metrics across retrieval stages."""

    vector_count: int
    keyword_count: int
    fused_count: int
    reranked_count: int
    semantic_retrieval_active: bool = False
    timings_ms: dict[str, float] = Field(default_factory=dict)


class RetrievalResponse(BaseModel):
    """Complete multi-stage retrieval response payload."""

    query: str
    vector_results: list[ScoredChunk]
    keyword_results: list[ScoredChunk]
    fused_results: list[FusedChunk]
    reranked_results: list[RerankedChunk]
    diagnostics: RetrievalDiagnostics
