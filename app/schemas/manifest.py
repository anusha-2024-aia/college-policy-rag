"""Manifest validation schemas."""

from datetime import date
from typing import Optional, Union
from pydantic import BaseModel, Field, field_validator


class DocumentManifestRow(BaseModel):
    """Schema for validating rows in docs/documents_manifest.csv."""

    file: str = Field(..., description="Relative or absolute path to the PDF file")
    title: str = Field(..., min_length=1, description="Document title")
    effective_date: date = Field(..., description="Effective date of the document (YYYY-MM-DD)")
    supersedes: Optional[str] = Field(None, description="Previous document version or identifier")
    allowed_roles: list[str] = Field(
        default_factory=list,
        description="List of access roles permitted to view this document",
    )

    @field_validator("file")
    @classmethod
    def validate_file(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("file path cannot be empty")
        if not trimmed.lower().endswith(".pdf"):
            raise ValueError(f"file must be a PDF document, got '{trimmed}'")
        return trimmed

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("title cannot be empty or whitespace only")
        return trimmed

    @field_validator("supersedes", mode="before")
    @classmethod
    def clean_supersedes(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        trimmed = str(v).strip()
        return trimmed if trimmed and trimmed.lower() not in ("none", "null", "nan", "") else None

    @field_validator("allowed_roles", mode="before")
    @classmethod
    def parse_allowed_roles(cls, v: Union[str, list[str]]) -> list[str]:
        if isinstance(v, list):
            return [str(role).strip() for role in v if str(role).strip()]
        if not v:
            return ["public"]
        # Split on semicolon or comma
        raw_roles = str(v).replace(",", ";").split(";")
        roles = [r.strip() for r in raw_roles if r.strip()]
        return roles or ["public"]
