"""Application settings configuration using Pydantic Settings."""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment or .env file."""

    # Server Settings
    APP_NAME: str = "Document RAG API"
    APP_ENV: str = "development"
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    DEBUG: bool = True

    # Database Configuration (PostgreSQL + pgvector)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/document_rag"

    # LLM Settings
    LLM_PROVIDER: str = "gemini"
    LLM_MODEL: str = "gemini-2.5-flash"
    LLM_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None

    # Embedding Settings
    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: int = 1536
    EMBEDDING_API_KEY: Optional[str] = None

    # Reranker Settings
    RERANKER_PROVIDER: str = "flashrank"
    RERANKER_MODEL: str = "ms-marco-TinyBERT-L-2-v2"
    RERANKER_API_KEY: Optional[str] = None

    # Ingestion & Chunking Settings
    CHUNK_SIZE_TOKENS: int = 500
    CHUNK_OVERLAP_TOKENS: int = 80
    MANIFEST_PATH: str = "docs/documents_manifest.csv"
    RAW_PDFS_DIR: str = "data/raw_pdfs"

    # Hybrid Retrieval Settings
    RRF_K: int = 60
    RETRIEVAL_K: int = 20
    RERANKER_TOP_N: int = 5

    # Version-Aware Policy Settings
    VERSION_AWARE_ENABLED: bool = True

    @property
    def sync_database_url(self) -> str:
        """Return synchronous database URL for sync sessions/migrations/CLI."""
        url = self.DATABASE_URL
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
