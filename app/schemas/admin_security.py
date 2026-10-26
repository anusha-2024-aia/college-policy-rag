"""Schemas for Admin Security Dashboard and Audit Log Inspection."""

from typing import Optional
from pydantic import BaseModel, Field


class DeniedAttemptItem(BaseModel):
    """Details of a blocked or unauthorized access attempt."""

    id: str = Field(..., description="Audit record UUID")
    ts: str = Field(..., description="Timestamp of the access attempt (ISO 8601 UTC)")
    role: str = Field(..., description="Caller role during attempt")
    query_hash: str = Field(..., description="SHA-256 hash of the query (never stores raw query)")
    blocked_candidates: int = Field(..., description="Number of unauthorized candidate chunks intercepted")
    decision: str = Field(..., description="Security decision code (e.g. blocked_l1, blocked_l3, blocked_l4)")
    request_id: Optional[str] = Field(None, description="Request correlation identifier")


class DeniedAttemptsResponse(BaseModel):
    """List of intercepted and blocked access attempts."""

    total_denied: int = Field(..., description="Total count of recorded denied attempts")
    attempts: list[DeniedAttemptItem] = Field(default_factory=list, description="Recent denied attempt entries")


class VisibleDocumentCountsResponse(BaseModel):
    """Aggregate visibility metrics per user role."""

    counts_by_role: dict[str, int] = Field(..., description="Number of visible documents per role")
    total_corpus_documents: int = Field(..., description="Total documents in the system database")


class LeakTestResultResponse(BaseModel):
    """Results from the automated route leak sweep."""

    status: str = Field(..., description="Overall test outcome: 'passed' or 'failed'")
    leaks_detected: int = Field(..., description="Number of leaks discovered")
    last_tested_at: str = Field(..., description="Timestamp of the most recent leak test")
    routes_tested: list[str] = Field(default_factory=list, description="Endpoints scanned during test")

