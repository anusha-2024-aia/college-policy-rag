"""Request and response schemas for Question Answering, Citations, and Version-Aware Policies."""

from typing import Optional
from pydantic import BaseModel, Field, field_validator
from app.schemas.retrieval import RetrievalDiagnostics
from app.core.roles import PERMITTED_ROLES, validate_role


class PolicyConflict(BaseModel):
    """Details of a policy conflict between a current policy and its superseded predecessor."""

    current_title: str = Field(..., description="Title of the active/current document")
    current_file: str = Field(..., description="File name of the active/current document")
    current_effective_date: str = Field(..., description="Effective date of the current policy (YYYY-MM-DD)")
    current_citation_index: int = Field(..., description="Citation index [N] of the current policy evidence")
    superseded_title: str = Field(..., description="Title of the older superseded document")
    superseded_file: str = Field(..., description="File name of the older superseded document")
    superseded_effective_date: str = Field(..., description="Effective date of the superseded policy (YYYY-MM-DD)")
    superseded_citation_index: int = Field(..., description="Citation index [N] of the superseded policy evidence")
    description: Optional[str] = Field(default=None, description="Summary of the policy disagreement/update")


class AskRequest(BaseModel):
    """Payload for POST /ask and POST /ask/stream."""

    question: str = Field(..., min_length=1, description="User question to answer from retrieved documents")
    top_k: int = Field(default=20, ge=1, le=100, description="Initial candidates per search stage")
    top_n: int = Field(default=5, ge=1, le=20, description="Reranked passages included in model context")
    include_diagnostics: bool = Field(default=False, description="Whether to include timing and stage diagnostics")
    abstention_threshold: float = Field(
        default=0.00005,
        ge=0.0,
        le=1.0,
        description="Minimum evidence confidence score floor below which the model abstains",
    )
    version_aware: Optional[bool] = Field(
        default=None,
        description="Enable version-aware policy prioritization and conflict detection (defaults to system setting)",
    )
    role: str = Field(
        default="student",
        description="User access control role for retrieval authorization (student, faculty, admin)",
    )

    @field_validator("role")
    @classmethod
    def validate_user_role(cls, v: str) -> str:
        clean = (v or "").strip().lower()
        if clean not in PERMITTED_ROLES:
            raise ValueError(f"Invalid role '{v}'. Permitted roles are: {sorted(PERMITTED_ROLES)}")
        return clean


class PassageEvidence(BaseModel):
    """Numbered passage supplied as context evidence."""

    index: int = Field(..., description="1-based passage number ([1], [2], ...)")
    chunk_id: str
    file_name: str
    page_number: int
    text: str
    score: float
    document_title: Optional[str] = Field(default=None, description="Title of the source document")
    effective_date: Optional[str] = Field(default=None, description="Document effective date (YYYY-MM-DD)")
    is_superseded: bool = Field(default=False, description="True if document has been superseded in its version lineage")
    superseded_by: Optional[str] = Field(default=None, description="Title of the document that supersedes this version")
    is_partially_amended: bool = Field(default=False, description="True if document has partial amendments while remaining active")
    amendment_scope: Optional[str] = Field(default=None, description="Scope of partial amendments (e.g. Clauses 4.2 and 6.1)")


class Citation(BaseModel):
    """Verified citation pointing to a specific retrieved passage, file, and page."""

    index: int = Field(..., description="1-based evidence index cited in answer text")
    file_name: str = Field(..., description="Source document file name")
    page_number: int = Field(..., description="1-based page number where fact originates")
    snippet: str = Field(..., description="Supporting excerpt from the cited passage")


class AskResponse(BaseModel):
    """Structured response from POST /ask."""

    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list, description="Verified citations extracted from answer")
    passages: list[PassageEvidence] = Field(default_factory=list, description="Retrieved passages used as evidence")
    abstained: bool = Field(default=False, description="True if system abstained due to insufficient evidence")
    has_policy_conflict: bool = Field(
        default=False,
        description="True if evidence contains conflicting current and superseded policies in the same lineage",
    )
    conflict_details: Optional[list[PolicyConflict]] = Field(
        default=None,
        description="Structured details of policy conflicts between current and superseded versions",
    )
    diagnostics: Optional[RetrievalDiagnostics] = Field(
        default=None,
        description="Retrieval timings and candidate counts (if requested)",
    )
