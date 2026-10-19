"""Pydantic schemas for document catalog and inspection API."""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class DocumentSummaryItem(BaseModel):
    """Structured representation of a document in the catalog."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_name: str
    title: str
    effective_date: str
    supersedes: Optional[str] = None
    superseded_by_title: Optional[str] = None
    allowed_roles: List[str]
    total_pages: int
    total_chunks: int
    status: str


class DocumentCatalogResponse(BaseModel):
    """Aggregate response for document repository listing."""
    total_docs: int
    total_chunks: int
    total_pages: int
    hidden_count: int = 0
    documents: List[DocumentSummaryItem]


class PDFInspectionResponse(BaseModel):
    """Response payload for in-memory PDF preview and inspection."""
    filename: str
    num_pages: int
    file_size_kb: float
    preview_text: str
