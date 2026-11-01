"""Database engine and session management."""

from collections.abc import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import StaticPool
from app.core.config import settings

Base = declarative_base()

# Sync engine for ingestion CLI, migrations, and synchronous sessions
engine = create_engine(
    settings.sync_database_url,
    pool_pre_ping=True,
    echo=settings.DEBUG and settings.APP_ENV == "development",
)

_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def SessionLocal() -> Session:
    """Session factory: returns isolated test session during tests, else database session."""
    if settings.APP_ENV == "test":
        return get_test_session()
    return _SessionLocal()

# In-memory SQLite engine for tests when APP_ENV == "test"
_test_engine = None
_TestSessionLocal = None


def get_test_session() -> Session:
    """Get or create singleton SQLite session for test isolation."""
    global _test_engine, _TestSessionLocal
    if _test_engine is None:
        from pathlib import Path
        test_db_path = Path("data/test_kvit.db")
        if test_db_path.exists():
            db_url = f"sqlite:///{test_db_path.resolve()}"
        else:
            db_url = "sqlite:///:memory:"
        _test_engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        import app.models  # noqa: F401
        Base.metadata.create_all(bind=_test_engine)
        _TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)
        # Seed test users
        from app.core.user_service import seed_default_users
        with _TestSessionLocal() as s:
            seed_default_users(s)
    return _TestSessionLocal()


def init_db(target_engine=None) -> None:
    """Initialize database extensions, run idempotent migrations, and create all declared tables."""
    import app.models  # noqa: F401 - ensure models are registered on Base.metadata
    if settings.APP_ENV == "test" and target_engine is None:
        target_engine = get_test_session().bind

    eng = target_engine or engine
    # Enable pgvector if connecting to PostgreSQL
    if eng.dialect.name == "postgresql":
        with eng.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            # Idempotent migrations for existing tables
            connection.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_version VARCHAR(50);"))
            connection.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS expires_date DATE;"))
            connection.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS supersedes_doc_id VARCHAR(36);"))
            connection.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS clause_ref VARCHAR(100);"))
            connection.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS valid_from DATE;"))
            connection.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS valid_to DATE;"))
            connection.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'current';"))
            connection.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS allowed_roles JSONB DEFAULT '[]'::jsonb;"))
            connection.commit()

    Base.metadata.create_all(bind=eng)

    # Seed default users idempotently
    from app.core.user_service import seed_default_users
    SessionMaker = sessionmaker(bind=eng)
    with SessionMaker() as seed_session:
        seed_default_users(seed_session)


def get_db() -> Generator[Session, None, None]:
    """Dependency for obtaining a database session."""
    if settings.APP_ENV == "test":
        db = get_test_session()
        try:
            yield db
        finally:
            db.close()
        return

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
