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
