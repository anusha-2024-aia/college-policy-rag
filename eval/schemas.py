"""Pydantic schemas for golden dataset validation and evaluation metrics."""

from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator
from app.core.roles import PERMITTED_ROLES, validate_role


class ExpectedSource(BaseModel):
    """Ground truth source file and page reference."""

    file_name: str
    page_number: int = Field(ge=1, description="1-based page number")

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: Any) -> Any:
        """Allow 'file' for file_name and 'page' for page_number."""
        if isinstance(data, dict):
            clean_dict = dict(data)
            if "file" in clean_dict and "file_name" not in clean_dict:
                clean_dict["file_name"] = clean_dict.pop("file")
            if "page" in clean_dict and "page_number" not in clean_dict:
                clean_dict["page_number"] = clean_dict.pop("page")
            if "file_name" in clean_dict and isinstance(clean_dict["file_name"], str):
                # Normalize any path prefixes to standard basename
                clean_dict["file_name"] = Path(clean_dict["file_name"]).name
            return clean_dict
        return data


class GoldenQuestion(BaseModel):
    """Schema for a single verified question in eval/golden.jsonl."""

    id: str = Field(description="Unique question identifier (e.g., Q-001)")
    question: str = Field(min_length=3, description="Evaluated question text")
    role: str = Field(default="student", description="Intended access role (student, faculty, admin)")
    expected_answer: Optional[str] = Field(default=None, description="Ground truth answer or expected synthesis")
    expected_sources: list[ExpectedSource] = Field(default_factory=list, description="Target source documents and pages")
    should_abstain: bool = Field(default=False, description="True if question cannot be answered from corpus")
    is_version_conflict: bool = False
    superseded_sources: list[ExpectedSource] = Field(default_factory=list, description="Historical superseded sources")
    restricted_for_roles: list[str] = Field(default_factory=list, description="Roles barred from accessing evidence")
    notes: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def clean_and_validate(cls, data: Any) -> Any:
        if isinstance(data, dict):
            clean = dict(data)
            # Ensure role is validated
            role_val = clean.get("role", "student")
            clean["role"] = validate_role(role_val)
            return clean
        return data


class CandidateItem(BaseModel):
    """Retrieved candidate passage snapshot for evaluation."""

    chunk_id: Optional[str] = None
    file_name: str
    page_number: int
    rank: int
    score: float
    text: str = ""


class CitationItem(BaseModel):
    """Extracted citation snapshot."""

    index: int
    file_name: str
    page_number: int
    snippet: str = ""


class QuestionEvalResult(BaseModel):
    """Single question evaluation output under a specific configuration."""

    question_id: str
    config_name: str
    role: str
    question_text: str
    retrieved_candidates: list[CandidateItem] = Field(default_factory=list)
    hit_at_5: bool = False
    reciprocal_rank: float = 0.0
    answer: str = ""
    citations: list[CitationItem] = Field(default_factory=list)
    abstained: bool = False
    has_policy_conflict: bool = False
    latency_ms: float = 0.0
    is_unsupported_answer: bool = False
    is_stale_policy_error: bool = False
    is_missing_conflict_detection: bool = False
    is_information_leak: bool = False
    is_correct_abstention: bool = False
    failure_classification: Optional[str] = None
    failure_reason: Optional[str] = None


class ConfigMetrics(BaseModel):
    """Aggregated evaluation metrics for a single configuration."""

    config_name: str
    total_queries: int
    eval_retrieval_queries: int
    hit_rate_at_5: float
    mean_reciprocal_rank: float
    faithfulness: Optional[float] = None
    answer_relevance: Optional[float] = None
    unsupported_answer_rate: float
    stale_policy_error_rate: Optional[float] = None
    missing_conflict_rate: Optional[float] = None
    information_leak_rate: float
    correct_abstention_rate: float
    false_abstention_rate: float
    average_latency_ms: float
    failures_by_category: dict[str, int] = Field(default_factory=dict)


class EvaluationSummaryReport(BaseModel):
    """Complete multi-configuration evaluation summary report."""

    timestamp: str
    dataset_size: int
    configs_evaluated: list[str]
    config_metrics: dict[str, ConfigMetrics]
    failure_details: list[dict[str, Any]] = Field(default_factory=list)
