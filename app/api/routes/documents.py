"""Document catalog and inspection API routes."""

import io
import logging
from typing import List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
import pypdf

from app.core.config import settings
from app.core.database import get_db
from app.core.auth import get_current_role
from app.core.rls import set_session_role
from app.core.roles import build_role_filter, PERMITTED_ROLES, validate_role, InvalidRoleError
from app.services.security_scanner import SecurityScanner
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
    verified_role: str = Depends(get_current_role),
    db: Session = Depends(get_db),
) -> DocumentCatalogResponse:
    """Retrieve indexed documents from PostgreSQL with strict server-side role enforcement."""
    clean_role = verified_role
    set_session_role(db, clean_role)

    is_postgres = (
        db.bind is not None and db.bind.dialect.name == "postgresql"
    )
    dialect = "postgresql" if is_postgres else "sqlite"

    # Fetch ALL document rows to accurately compute hidden_count and full corpus lineage
    all_docs: list[Document] = (
        db.query(Document).order_by(Document.effective_date.desc()).all()
    )
    total_in_db = len(all_docs)

    role_filter = build_role_filter(Document, clean_role, dialect)
    visible_docs: list[Document] = (
        db.query(Document)
        .filter(role_filter)
        .order_by(Document.effective_date.desc())
        .all()
    )

    hidden_count = total_in_db - len(visible_docs)
    if not getattr(settings, "SHOW_HIDDEN_DOCUMENT_COUNT", True):
        hidden_count = 0

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


@router.get(
    "/{document_id}",
    response_model=DocumentSummaryItem,
    status_code=status.HTTP_200_OK,
    summary="Get Document Detail by ID or Filename",
    description="Returns metadata of an indexed document. Hidden/unauthorized documents return uniform 404 to prevent existence discovery.",
)
def get_document_detail(
    document_id: str,
    verified_role: str = Depends(get_current_role),
    db: Session = Depends(get_db),
) -> DocumentSummaryItem:
    """Retrieve document detail with strict role authorization and uniform 404 masking."""
    set_session_role(db, verified_role)
    doc = db.query(Document).filter(
        or_(Document.id == document_id, Document.file_name == document_id)
    ).first()

    # Uniform 404 response for non-existent and unauthorized documents
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    roles = doc.allowed_roles if isinstance(doc.allowed_roles, list) else [str(doc.allowed_roles)]
    clean_roles = [str(r).lower() for r in roles]
    if verified_role not in clean_roles and "all" not in clean_roles:
        # Uniform 404 to avoid revealing existence of restricted documents
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    all_docs = db.query(Document).all()
    superseded_by_map = _build_superseded_by_map(all_docs)
    if doc.file_name in superseded_by_map:
        display_status, replacing_title = superseded_by_map[doc.file_name]
        superseded_by_title = f"{display_status} by {replacing_title}"
    else:
        display_status = "Active"
        superseded_by_title = None

    return DocumentSummaryItem(
        id=doc.id,
        file_name=doc.file_name,
        title=doc.title,
        effective_date=str(doc.effective_date),
        supersedes=doc.supersedes,
        superseded_by_title=superseded_by_title,
        allowed_roles=roles,
        total_pages=doc.total_pages,
        total_chunks=doc.total_chunks,
        status=display_status,
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
    verified_role: str = Depends(get_current_role),
) -> PDFInspectionResponse:
    """Read-only preview inspection for candidate policy PDF documents with role governance."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported for policy preview.",
        )

    # Restrict previewing confidential document filenames for non-admin
    scanner = SecurityScanner()
    if verified_role != "admin" and file.filename in scanner.canary_data:
        allowed = [r.lower() for r in scanner.canary_data[file.filename].get("allowed_roles", [])]
        if verified_role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: confidential document preview not permitted.",
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

        # Scan preview text for canaries or confidential statements
        if preview_text and verified_role != "admin":
            is_leak, leak_reason = scanner.scan_output(preview_text, verified_role)
            if is_leak:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: preview content contains restricted confidential text.",
                )

        return PDFInspectionResponse(
            filename=file.filename,
            num_pages=num_pages,
            file_size_kb=file_size_kb,
            preview_text=preview_text[:1000],
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to inspect PDF: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unable to parse PDF file structure: {exc}",
        ) from exc
