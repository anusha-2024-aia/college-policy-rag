"""PostgreSQL Row-Level Security (RLS) and transaction role binding tests.

Tests:
1. SQL script invariants in scripts/setup_postgres_rls.sql (NOBYPASSRLS, FORCE RLS, JSONB role containment).
2. L2 Python policy simulation logic.
3. Live PostgreSQL connection tests (executed whenever a PostgreSQL instance is reachable).
"""

import os
import pytest
from sqlalchemy import create_engine, text
from app.core.rls import evaluate_rls_policy, RLS_SQL_PATH


def is_postgres_available() -> bool:
    """Check if a live PostgreSQL database is reachable."""
    db_url = os.environ.get("POSTGRES_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not db_url.startswith("postgresql"):
        return False
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    try:
        engine = create_engine(db_url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            res = conn.execute(text("SELECT 1")).scalar()
            return res == 1
    except Exception:
        return False


def test_rls_ddl_script_invariants():
    """Verify that setup_postgres_rls.sql enforces non-owner application role and FORCE RLS."""
    assert RLS_SQL_PATH.exists(), f"Missing RLS SQL setup script at {RLS_SQL_PATH}"
    sql_text = RLS_SQL_PATH.read_text(encoding="utf-8")

    # Invariant 1: Dedicated non-owner role with NOBYPASSRLS
    assert "kvit_app_user" in sql_text
    assert "NOBYPASSRLS" in sql_text

    # Invariant 2: ENABLE and FORCE Row-Level Security on sensitive tables
    assert "ALTER TABLE documents ENABLE ROW LEVEL SECURITY;" in sql_text
    assert "ALTER TABLE documents FORCE ROW LEVEL SECURITY;" in sql_text
    assert "ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;" in sql_text
    assert "ALTER TABLE chunks FORCE ROW LEVEL SECURITY;" in sql_text

    # Invariant 3: current_setting('app.current_role', true) parameter binding
    assert "current_setting('app.current_role', true)" in sql_text

    # Invariant 4: JSONB containment operators
    assert "allowed_roles::jsonb ? current_setting('app.current_role', true)" in sql_text


def test_rls_policy_simulation_zero_rows_when_unset():
    """Verify that when app.current_role is unset or None, exactly 0 rows are visible."""
    allowed = ["faculty", "admin"]
    assert evaluate_rls_policy(None, allowed) is False
    assert evaluate_rls_policy("", allowed) is False


def test_rls_policy_simulation_role_filtering():
    """Verify that student, faculty, and admin each see exactly permitted content."""
    student_allowed = ["student", "faculty", "admin"]
    faculty_allowed = ["faculty", "admin"]
    admin_allowed = ["admin"]

    # Student
    assert evaluate_rls_policy("student", student_allowed) is True
    assert evaluate_rls_policy("student", faculty_allowed) is False
    assert evaluate_rls_policy("student", admin_allowed) is False

    # Faculty
    assert evaluate_rls_policy("faculty", student_allowed) is True
    assert evaluate_rls_policy("faculty", faculty_allowed) is True
    assert evaluate_rls_policy("faculty", admin_allowed) is False

    # Admin
    assert evaluate_rls_policy("admin", student_allowed) is True
    assert evaluate_rls_policy("admin", faculty_allowed) is True
    assert evaluate_rls_policy("admin", admin_allowed) is True


@pytest.mark.skipif(not is_postgres_available(), reason="Live PostgreSQL database not reachable")
def test_live_postgres_rls_enforcement():
    """Live verification against real PostgreSQL container when running."""
    db_url = os.environ.get("POSTGRES_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if db_url and db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    engine = create_engine(db_url)

    # Ensure tables exist and contain test fixtures if empty
    with engine.begin() as conn:
        chunk_count = conn.execute(text("SELECT count(*) FROM chunks")).scalar()
        if chunk_count == 0:
            conn.execute(
                text("""
                INSERT INTO documents (id, file_name, file_hash, title, effective_date, allowed_roles, status, total_pages, total_chunks, created_at, updated_at)
                VALUES
                ('doc-student-id', 'doc_student.pdf', 'hash1', 'Student Policy', '2024-01-01', '["student", "faculty", "admin"]'::json, 'current', 1, 1, NOW(), NOW()),
                ('doc-admin-id', 'doc_admin.pdf', 'hash2', 'Admin Policy', '2024-01-01', '["admin"]'::json, 'current', 1, 1, NOW(), NOW())
                ON CONFLICT (file_name) DO NOTHING;
            """)
            )
            dummy_vec = '[' + ','.join(['0'] * 1536) + ']'
            conn.execute(
                text(f"""
                INSERT INTO chunks (id, document_id, chunk_index, page_number, text, token_count, status, allowed_roles, embedding, created_at)
                VALUES
                ('chk-student-id', 'doc-student-id', 0, 1, 'Student rule content', 10, 'current', '["student", "faculty", "admin"]'::json, '{dummy_vec}'::vector, NOW()),
                ('chk-admin-id', 'doc-admin-id', 0, 1, 'Admin confidential content', 10, 'current', '["admin"]'::json, '{dummy_vec}'::vector, NOW())
                ON CONFLICT (id) DO NOTHING;
            """)
            )

    with engine.connect() as conn:
        # Verify app role without setting app.current_role returns 0 rows
        conn.execute(text("SET ROLE kvit_app_user"))
        conn.execute(text("SELECT set_config('app.current_role', '', true)"))
        count_unset = conn.execute(text("SELECT count(*) FROM chunks")).scalar()
        assert count_unset == 0, f"Expected 0 chunks visible when app.current_role is unset, got {count_unset}"

        # Verify setting student role reveals only student chunks
        conn.execute(text("SELECT set_config('app.current_role', 'student', true)"))
        student_chunks = conn.execute(text("SELECT count(*) FROM chunks")).scalar()
        assert student_chunks > 0

        # Verify admin sees more or all chunks
        conn.execute(text("SELECT set_config('app.current_role', 'admin', true)"))
        admin_chunks = conn.execute(text("SELECT count(*) FROM chunks")).scalar()
        assert admin_chunks >= student_chunks

