"""System status, statistics, and diagnostic API routes."""

import logging
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document
from app.schemas.system_api import SystemStatsResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["System"])


@router.get(
    "/stats",
    response_model=SystemStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get System Summary Statistics",
    description="Returns aggregate counts of indexed documents, chunks, pages, and active model flags.",
)
def get_system_stats(db: Session = Depends(get_db)) -> SystemStatsResponse:
    """Query live metrics directly from PostgreSQL database."""
    docs = db.query(Document).all()
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
