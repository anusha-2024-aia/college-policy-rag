"""System status, statistics, and diagnostic API routes."""

import logging
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.auth import get_current_role
from app.core.rls import set_session_role
from app.core.roles import build_role_filter
from app.models.document import Document
from app.schemas.system_api import SystemStatsResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["System"])


@router.get(
    "/stats",
    response_model=SystemStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get System Summary Statistics",
    description="Returns aggregate counts of indexed documents, chunks, pages, and active model flags scoped to user role.",
)
def get_system_stats(
    verified_role: str = Depends(get_current_role),
    db: Session = Depends(get_db),
) -> SystemStatsResponse:
    """Query live metrics directly from PostgreSQL database scoped to caller role."""
    set_session_role(db, verified_role)
    is_postgres = (
        db.bind is not None and db.bind.dialect.name == "postgresql"
    )
    dialect = "postgresql" if is_postgres else "sqlite"

    if verified_role == "admin":
        docs = db.query(Document).all()
    else:
        role_filter = build_role_filter(Document, verified_role, dialect)
        docs = db.query(Document).filter(role_filter).all()

    total_chunks = sum(d.total_chunks for d in docs)
    total_pages = sum(d.total_pages for d in docs)

    return SystemStatsResponse(
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV,
        total_docs=len(docs),
        total_chunks=total_chunks,
        total_pages=total_pages,
        semantic_retrieval_enabled=settings.SEMANTIC_RETRIEVAL_ENABLED,
        embedding_model=settings.EMBEDDING_MODEL,
        embedding_dimension=settings.EMBEDDING_DIMENSION,
        reranker_model=settings.RERANKER_MODEL,
        llm_provider=settings.LLM_PROVIDER,
        llm_model=settings.LLM_MODEL,
    )
