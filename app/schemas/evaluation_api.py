"""Pydantic schemas for evaluation benchmark reports API."""

from typing import List, Optional
from pydantic import BaseModel


class EvaluationReportSummary(BaseModel):
    """Metadata summary of an evaluation benchmark report."""
    id: str
    filename: str
    title: str
    timestamp: Optional[str] = None
    has_json: bool = False
    file_size_bytes: int = 0


class EvaluationReportListResponse(BaseModel):
    """List response for available benchmark reports."""
    reports: List[EvaluationReportSummary]
    total_count: int


class EvaluationReportDetail(BaseModel):
    """Full detail of an evaluation report including raw content and optional JSON."""
    filename: str
    title: str
    markdown_content: str
    json_export: Optional[str] = None
    has_json: bool = False


class BenchmarkConfigMetrics(BaseModel):
    hit_rate_at_1: float
    hit_rate_at_3: float
    hit_rate_at_5: float
    mean_reciprocal_rank: float
    average_latency_ms: float
    p95_latency_ms: float
    information_leak_rate: float
    missing_conflict_rate: Optional[float] = 0.0
    stale_policy_error_rate: Optional[float] = 0.0


class EvaluationSummaryResponse(BaseModel):
    """Structured evaluation benchmark summary dynamically loaded from results."""
    available: bool = True
    timestamp: Optional[str] = None
    mode: str = "real"
    embedding_model: str = "all-MiniLM-L6-v2"
    reranker_model: str = "ms-marco-TinyBERT-L-2-v2"
    corpus_documents: int = 16
    corpus_chunks: int = 51
    chance_baseline_recall_at_5: float = 0.098
    primary_recall_at_5: float = 0.96
    primary_mrr: float = 0.9033
    primary_leak_rate: float = 0.0
    primary_latency_ms: float = 147.27
    configs: dict[str, BenchmarkConfigMetrics] = {}
    is_mock: dict[str, bool] = {}
    message: Optional[str] = None
