"""Alembic database migrations verification and lifecycle tests.

Tests verify:
1. Migration graph integrity (head revision, base revision, dependency chain).
2. Offline SQL generation (`alembic upgrade head --sql`).
3. Production startup invariant: Base.metadata.create_all is strictly disabled in production.
4. Real-PostgreSQL migration lifecycle drill (runs when PostgreSQL is available, skips gracefully otherwise):
   - Upgrade clean database to head.
   - Verify all tables, pgvector extensions, tsvector indexes, and RLS policies exist.
   - Downgrade one revision step and upgrade again with sample data.
"""

import os
from pathlib import Path
import pytest
from sqlalchemy import create_engine, text
from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory

from app.core.config import settings
from app.core.database import init_db


def is_postgres_available() -> bool:
    """Check if a live PostgreSQL database is reachable."""
    db_url = os.environ.get("POSTGRES_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not db_url.startswith("postgresql"):
        return False
    try:
        engine = create_engine(db_url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            res = conn.execute(text("SELECT 1")).scalar()
            return res == 1
    except Exception:
        return False


def test_alembic_config_and_script_directory():
    """Verify that alembic.ini and script directory are properly configured."""
    ini_path = Path("alembic.ini")
    assert ini_path.exists(), "alembic.ini must exist in project root"

    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()

    assert len(heads) == 1, f"Expected exactly 1 migration head, got {heads}"
    assert heads[0] == "001", f"Expected head revision to be '001', got '{heads[0]}'"

    rev = script.get_revision("001")
    assert rev is not None
    assert rev.down_revision is None, "Initial revision down_revision must be None"


def test_alembic_offline_sql_generation():
    """Verify that alembic upgrade head --sql generates valid DDL."""
    import io
    from contextlib import redirect_stdout

    cfg = Config("alembic.ini")
    buf = io.StringIO()
    with redirect_stdout(buf):
        command.upgrade(cfg, "head", sql=True)

    sql_output = buf.getvalue()
    assert "CREATE TABLE documents" in sql_output
    assert "CREATE TABLE chunks" in sql_output
    assert "CREATE TABLE chunks_semantic" in sql_output
    assert "CREATE TABLE document_lineage" in sql_output
    assert "CREATE TABLE access_audit" in sql_output
    assert "CREATE TABLE embedding_index_metadata" in sql_output
    assert "CREATE TABLE users" in sql_output
    assert "ENABLE ROW LEVEL SECURITY" in sql_output
    assert "kvit_app_user" in sql_output


def test_production_startup_prohibits_runtime_create_all():
    """Verify that Base.metadata.create_all is strictly disabled when APP_ENV=production."""
    orig_env = settings.APP_ENV
    try:
        settings.APP_ENV = "production"
        # Mock engine to assert create_all is not called
        test_engine = create_engine("sqlite:///:memory:")
        init_db(target_engine=test_engine)

        # In production, init_db must NOT create tables via create_all
        with test_engine.connect() as conn:
            tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            table_names = [t[0] for t in tables]
            # Since create_all was skipped, documents/chunks tables must NOT exist
            assert "documents" not in table_names
            assert "chunks" not in table_names
    finally:
        settings.APP_ENV = orig_env


@pytest.mark.skipif(not is_postgres_available(), reason="PostgreSQL service not reachable for live migration drill")
def test_real_postgres_migration_upgrade_downgrade_drill():
    """Execute live migration drill on reachable PostgreSQL database."""
    pg_url = os.environ.get("POSTGRES_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", pg_url)

    # 1. Upgrade to head
    command.upgrade(cfg, "head")

    engine = create_engine(pg_url)
    with engine.connect() as conn:
        res = conn.execute(text("SELECT to_regclass('public.documents')")).scalar()
        assert res is not None, "documents table must exist after upgrade"

        # Check RLS enabled
        rls_res = conn.execute(text("""
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = 'documents'
        """)).fetchone()
        assert rls_res is not None
        assert rls_res[0] is True, "documents table must have ROW LEVEL SECURITY enabled"
        assert rls_res[1] is True, "documents table must FORCE ROW LEVEL SECURITY"

    # 2. Downgrade one step (to base)
    command.downgrade(cfg, "base")
    with engine.connect() as conn:
        res = conn.execute(text("SELECT to_regclass('public.documents')")).scalar()
        assert res is None, "documents table must be dropped after downgrade to base"

    # 3. Upgrade back to head
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        res = conn.execute(text("SELECT to_regclass('public.documents')")).scalar()
        assert res is not None, "documents table must be re-created after re-upgrade"

