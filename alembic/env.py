import os
import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import pool, create_engine
from alembic import context

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.models import Base

config = context.config

if config.config_file_name is not None and settings.APP_ENV != "test":
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> str:
    """Resolve database URL for Alembic migrations."""
    env_url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if env_url:
        if env_url.startswith("postgresql+asyncpg://"):
            return env_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
        if env_url.startswith("postgresql://"):
            return env_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        if env_url.startswith("postgres://"):
            return env_url.replace("postgres://", "postgresql+psycopg2://", 1)
        return env_url
    
    url = settings.sync_database_url
    if url and not url.startswith("sqlite:///:memory:"):
        return url

    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url

    return "sqlite:///data/test_kvit.db"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    db_url = get_url()
    connectable = create_engine(db_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
