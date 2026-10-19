"""Document catalog and inspection API routes."""

import io
import logging
from typing import List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
import pypdf

from app.core.database import get_db
from app.core.roles import build_role_filter, PERMITTED_ROLES, validate_role, InvalidRoleError
from app.models.document import Document
from app.schemas.document_api import (
    DocumentCatalogResponse,
    DocumentSummaryItem,
    PDFInspectionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])


def _build_superseded_by_map(all_docs: list[Document]) -> dict[str, Tuple[str, str]]:
    """Build a mapping from file_name -> (status_label, replacing_doc_title).

    Parses the manifest `supersedes` field across documents to determine whether
    an older document has been fully superseded or partially amended by a newer one.
    """
    superseded_by: dict[str, Tuple[str, str]] = {}
    for doc in all_docs:
        if not doc.supersedes:
            continue
        raw = doc.supersedes.strip()
        if raw.lower().startswith("partial:"):
            # Format: "partial: Clause X and Clause Y only:old_file.pdf"
            parts = raw.split(":")
            old_file = parts[-1].strip() if parts else ""
            if old_file:
                superseded_by[old_file] = ("Partially amended", doc.title)
        else:
            old_file = raw.strip()
            if old_file:
                superseded_by[old_file] = ("Superseded", doc.title)
    return superseded_by


@router.get(
    "",
    response_model=DocumentCatalogResponse,
    status_code=status.HTTP_200_OK,
    summary="List Ingested Policy Documents",
    description=(
        "Returns documents the requesting role is authorised to see. "
        "Hidden documents are counted but their titles are never exposed."
    ),
)
def list_documents(
    role: Optional[str] = None,
    db: Session = Depends(get_db),
) -> DocumentCatalogResponse:
    """Retrieve indexed documents from PostgreSQL with strict server-side role enforcement."""
    is_postgres = (
        db.bind is not None and db.bind.dialect.name == "postgresql"
    )
    dialect = "postgresql" if is_postgres else "sqlite"

    # Fetch ALL document rows to accurately compute hidden_count and full corpus lineage
    all_docs: list[Document] = (
        db.query(Document).order_by(Document.effective_date.desc()).all()
    )
    total_in_db = len(all_docs)

    # Validate and filter by role server-side if specified
    if role:
        try:
            clean_role = validate_role(role)
        except InvalidRoleError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        role_filter = build_role_filter(Document, clean_role, dialect)
        visible_docs: list[Document] = (
            db.query(Document)
            .filter(role_filter)
            .order_by(Document.effective_date.desc())
            .all()
        )
    else:
        # Default or unauthenticated overview: student role is the baseline public role
        clean_role = "student"
        role_filter = build_role_filter(Document, clean_role, dialect)
        visible_docs = (
            db.query(Document)
            .filter(role_filter)
            .order_by(Document.effective_date.desc())
            .all()
        )

    hidden_count = total_in_db - len(visible_docs)

    # Lineage mapping across visible documents
    superseded_by_map = _build_superseded_by_map(all_docs)

    items: list[DocumentSummaryItem] = []
    for d in visible_docs:
        roles = (
            d.allowed_roles
            if isinstance(d.allowed_roles, list)
            else [str(d.allowed_roles)]
        )

        # Derive manifest-based status and lineage
        if d.file_name in superseded_by_map:
            display_status, replacing_title = superseded_by_map[d.file_name]
            superseded_by_title = f"{display_status} by {replacing_title}"
        else:
            display_status = "Active"
            superseded_by_title = None

        items.append(
            DocumentSummaryItem(
                id=d.id,
                file_name=d.file_name,
                title=d.title,
                effective_date=str(d.effective_date),
                supersedes=d.supersedes,
                superseded_by_title=superseded_by_title,
                allowed_roles=roles,
                total_pages=d.total_pages,
                total_chunks=d.total_chunks,
                status=display_status,
            )
        )

    total_chunks = sum(d.total_chunks for d in visible_docs)
    total_pages = sum(d.total_pages for d in visible_docs)

    return DocumentCatalogResponse(
        total_docs=len(items),
        total_chunks=total_chunks,
        total_pages=total_pages,
        hidden_count=hidden_count,
        documents=items,
    )


@router.post(
    "/inspect",
    response_model=PDFInspectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Inspect Uploaded PDF Metadata (In-Memory)",
    description="Parses an uploaded PDF in-memory to extract page count, size, and page 1 text preview without persisting.",
)
async def inspect_pdf(
    file: UploadFile = File(...),
) -> PDFInspectionResponse:
    """Read-only preview inspection for candidate policy PDF documents."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported for policy preview.",
        )

    try:
        content = await file.read()
        file_size_kb = round(len(content) / 1024.0, 2)
        stream = io.BytesIO(content)
        reader = pypdf.PdfReader(stream)
        num_pages = len(reader.pages)
        preview_text = ""
        if num_pages > 0:
            preview_text = reader.pages[0].extract_text() or ""

        return PDFInspectionResponse(
            filename=file.filename,
            num_pages=num_pages,
            file_size_kb=file_size_kb,
            preview_text=preview_text[:1000],
        )
    except Exception as exc:
        logger.error("Failed to inspect PDF: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unable to parse PDF file structure: {exc}",
        ) from exc
