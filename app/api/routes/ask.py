"""Question Answering API routes."""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.schemas.qa import AskRequest, AskResponse
from app.services.retrieval import HybridRetrievalService
from app.services.llm import (
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMError,
    get_llm_service,
)
from app.services.qa import QAService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Question Answering"])


def get_qa_service(db: Session = Depends(get_db)) -> QAService:
    """Dependency injection factory for QAService."""
    retrieval_service = HybridRetrievalService(db_session=db)
    llm_service = get_llm_service()
    return QAService(retrieval_service=retrieval_service, llm_service=llm_service)


@router.post(
    "/ask",
    response_model=AskResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask Question against Ingested Documents",
    description=(
        "Retrieves and reranks evidence from ingested documents, synthesizes a grounded answer "
        "citing specific numbered passages [N], validates citations against retrieved evidence, "
        "and applies a configurable abstention policy for unanswerable questions."
    ),
)
async def ask_question(
    request: AskRequest,
    qa_service: QAService = Depends(get_qa_service),
) -> AskResponse:
    """Answer question with verified citations and abstention support."""
    try:
        response = qa_service.answer(request)
        return response
    except LLMAuthenticationError as exc:
        logger.error("LLM authentication failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM service configuration error or missing API credentials.",
        ) from exc
    except LLMRateLimitError as exc:
        logger.warning("LLM rate limit encountered: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="LLM provider rate limit exceeded. Please retry shortly.",
        ) from exc
    except LLMTimeoutError as exc:
        logger.error("LLM timeout encountered: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LLM provider timed out while generating response.",
        ) from exc
    except LLMError as exc:
        logger.error("LLM generic error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"LLM service error: {exc}",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error during /ask processing: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing the question.",
        ) from exc


@router.post(
    "/ask/stream",
    summary="Stream Answer Tokens via Server-Sent Events",
    description="Streams answer text tokens and citation metadata using text/event-stream format.",
)
async def ask_question_stream(
    request: AskRequest,
    qa_service: QAService = Depends(get_qa_service),
) -> StreamingResponse:
    """Stream answer generation as Server-Sent Events (SSE)."""
    try:
        generator = qa_service.stream_answer(request)
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as exc:
        logger.exception("Error initiating streaming response: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate stream: {exc}",
        ) from exc
