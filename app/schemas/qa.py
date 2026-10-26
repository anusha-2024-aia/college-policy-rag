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


class VersionValueDetail(BaseModel):
    """Extracted value and provenance details for a specific policy version."""

    value: str = Field(..., description="Extracted metric, threshold, or parameter value")
    source: str = Field(..., description="Source document file name")
    page: int = Field(default=1, description="Page number of the source document")
    effective_date: Optional[str] = Field(default=None, description="Effective date (YYYY-MM-DD)")


class ChangeCard(BaseModel):
    """Deterministic diff between an old policy rule and a new policy rule."""

    topic: str = Field(..., description="Policy topic or clause identifier")
    old: VersionValueDetail = Field(..., description="Previous/superseded parameter details")
    new: VersionValueDetail = Field(..., description="Current/amended parameter details")
    scope: str = Field(default="full", description="Supersession scope: full or partial")


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
    lineage_expansion: Optional[bool] = Field(
        default=None,
        description="Enable sibling chunk lineage expansion across document versions",
    )
    as_of: Optional[str] = Field(
        default=None,
        description="Optional target date (YYYY-MM-DD) for historical time-travel retrieval",
    )
    semantic_retrieval: Optional[bool] = Field(
        default=None,
        description="Enable 384-dimensional ONNX semantic retrieval (defaults to system setting)",
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
    clause_ref: Optional[str] = Field(default=None, description="Clause reference, e.g. 'Clause 4.2'")
    document_title: Optional[str] = Field(default=None, description="Title of the source document")
    effective_date: Optional[str] = Field(default=None, description="Document effective date (YYYY-MM-DD)")
    is_superseded: bool = Field(default=False, description="True if document has been superseded in its version lineage")
    superseded_by: Optional[str] = Field(default=None, description="Title of the document that supersedes this version")
    is_partially_amended: bool = Field(default=False, description="True if document has partial amendments while remaining active")
    amendment_scope: Optional[str] = Field(default=None, description="Scope of partial amendments (e.g. Clauses 4.2 and 6.1)")
    allowed_roles: list[str] = Field(default_factory=list, description="Roles authorized to view this passage evidence")


class Citation(BaseModel):
    """Verified citation pointing to a specific retrieved passage, file, and page."""

    index: int = Field(..., description="1-based evidence index cited in answer text")
    file_name: str = Field(..., description="Source document file name")
    page_number: int = Field(..., description="1-based page number where fact originates")
    snippet: str = Field(..., description="Supporting excerpt from the cited passage")


class AnswerContract(BaseModel):
    """Pydantic validated answer contract returned by the LLM."""

    answer: str = Field(..., description="Grounded response text")
    authoritative_sources: list[int] = Field(
        default_factory=list,
        description="List of 1-based evidence passage indices for authoritative current rules",
    )
    historical_sources: list[int] = Field(
        default_factory=list,
        description="List of 1-based evidence passage indices for older/superseded rules",
    )
    conflict: bool = Field(
        default=False,
        description="True if policy conflict/change card is detected between versions",
    )
    change_cards: list[ChangeCard] = Field(
        default_factory=list,
        description="Structured diff cards comparing old and new values",
    )
    as_of: Optional[str] = Field(
        default=None,
        description="Evaluated temporal effective date",
    )
    abstain: bool = Field(
        default=False,
        description="True if system must abstain due to insufficient evidence or lack of authorization",
    )
    abstain_reason: Optional[str] = Field(
        default=None,
        description="Standardized reason for abstention (if any)",
    )


class AskResponse(BaseModel):
    """Structured response from POST /ask."""

    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list, description="Verified citations extracted from answer")
    passages: list[PassageEvidence] = Field(default_factory=list, description="Retrieved passages used as evidence")
    abstained: bool = Field(default=False, description="True if system abstained due to insufficient evidence")
    abstain_reason: Optional[str] = Field(default=None, description="Reason for abstention if abstained")
    has_policy_conflict: bool = Field(
        default=False,
        description="True if evidence contains conflicting current and superseded policies in the same lineage",
    )
    conflict: bool = Field(
        default=False,
        description="Alias for has_policy_conflict matching the answer contract schema",
    )
    authoritative_sources: list[int] = Field(
        default_factory=list,
        description="Passage indices of current authoritative sources",
    )
    historical_sources: list[int] = Field(
        default_factory=list,
        description="Passage indices of superseded or historical sources",
    )
    conflict_details: Optional[list[PolicyConflict]] = Field(
        default=None,
        description="Structured details of policy conflicts between current and superseded versions",
    )
    change_cards: list[ChangeCard] = Field(
        default_factory=list,
        description="Deterministic change cards detailing old vs new values",
    )
    as_of: Optional[str] = Field(
        default=None,
        description="Effective query date evaluated for temporal validity",
    )
    is_historical: bool = Field(
        default=False,
        description="True if response resolves to a historical rule rather than current policy",
    )
    diagnostics: Optional[RetrievalDiagnostics] = Field(
        default=None,
        description="Retrieval timings and candidate counts (if requested)",
    )
