"""FastAPI Application Entry Point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.router import api_router
from app.core.config import settings


def create_application() -> FastAPI:
    """Application factory for FastAPI Document RAG service."""
    application = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Enterprise Document RAG (Retrieval-Augmented Generation) System API",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS configuration
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:8501",
            "http://127.0.0.1:8501",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # Root informational endpoint
    @application.get("/", tags=["Root"])
    def root() -> dict:
        return {
            "app": settings.APP_NAME,
            "version": "0.1.0",
            "status": "online",
            "docs": "/docs",
            "health": "/health",
            "streamlit_ui": "http://127.0.0.1:8501",
        }

    # Mount API routers
    application.include_router(api_router)

    return application


app = create_application()

if __name__ == "__main__":
    import uvicorn

    # Default to localhost for secure development
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
