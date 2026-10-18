"""Database engine and session management."""

from collections.abc import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings

Base = declarative_base()

# Sync engine for ingestion CLI, migrations, and synchronous sessions
engine = create_engine(
    settings.sync_database_url,
    pool_pre_ping=True,
    echo=settings.DEBUG and settings.APP_ENV == "development",
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(target_engine=None) -> None:
    """Initialize database extensions and create all declared tables."""
    import app.models  # noqa: F401 - ensure models are registered on Base.metadata
    eng = target_engine or engine
    # Enable pgvector if connecting to PostgreSQL
    if eng.dialect.name == "postgresql":
        with eng.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            connection.commit()

    Base.metadata.create_all(bind=eng)


def get_db() -> Generator[Session, None, None]:
    """Dependency for obtaining a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
