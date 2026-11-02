"""Initial database schema with pgvector, tsvector, and RLS policies.

Revision ID: 001
Revises: 
Create Date: 2026-11-02 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = (bind.dialect.name == "postgresql")

    # 1. Enable pgvector extension if PostgreSQL
    if is_postgres:
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector;"))

    # 2. Documents table
    op.create_table(
        'documents',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_hash', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('doc_version', sa.String(length=50), nullable=True),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('expires_date', sa.Date(), nullable=True),
        sa.Column('supersedes', sa.String(length=255), nullable=True),
        sa.Column('supersedes_doc_id', sa.String(length=36), nullable=True),
        sa.Column('allowed_roles', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='current'),
        sa.Column('total_pages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_chunks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['supersedes_doc_id'], ['documents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_documents_file_name', 'documents', ['file_name'], unique=True)
    op.create_index('ix_documents_file_hash', 'documents', ['file_hash'], unique=False)
    op.create_index('ix_documents_supersedes_doc_id', 'documents', ['supersedes_doc_id'], unique=False)

    # 3. Chunks table
    op.create_table(
        'chunks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('document_id', sa.String(length=36), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=False),
        sa.Column('clause_ref', sa.String(length=100), nullable=True),
        sa.Column('valid_from', sa.Date(), nullable=True),
        sa.Column('valid_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='current'),
        sa.Column('allowed_roles', sa.JSON(), nullable=False),
        sa.Column('embedding', Vector(1536), nullable=False),
        sa.Column('tsv', postgresql.TSVECTOR() if is_postgres else sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_chunks_document_id', 'chunks', ['document_id'], unique=False)
    op.create_index('ix_chunks_page_number', 'chunks', ['page_number'], unique=False)
    op.create_index('ix_chunks_clause_ref', 'chunks', ['clause_ref'], unique=False)
    op.create_index('idx_chunks_doc_chunk', 'chunks', ['document_id', 'chunk_index'], unique=False)
    op.create_index('idx_chunks_doc_page', 'chunks', ['document_id', 'page_number'], unique=False)
    op.create_index('idx_chunks_status', 'chunks', ['status'], unique=False)
    op.create_index('idx_chunks_validity', 'chunks', ['valid_from', 'valid_to'], unique=False)

    if is_postgres:
        op.create_index(
            'idx_chunks_embedding_hnsw',
            'chunks',
            ['embedding'],
            unique=False,
            postgresql_using='hnsw',
            postgresql_ops={'embedding': 'vector_cosine_ops'},
        )
        op.create_index(
            'idx_chunks_tsv_gin',
            'chunks',
            ['tsv'],
            unique=False,
            postgresql_using='gin',
        )

    # 4. Chunks Semantic table
    op.create_table(
        'chunks_semantic',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('chunk_id', sa.String(length=36), nullable=False),
        sa.Column('embedding', Vector(384), nullable=False),
        sa.Column('model_name', sa.String(length=100), nullable=False, server_default='all-MiniLM-L6-v2'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['chunk_id'], ['chunks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chunk_id'),
    )

    if is_postgres:
        op.create_index(
            'idx_chunks_semantic_embedding_hnsw',
            'chunks_semantic',
            ['embedding'],
            unique=False,
            postgresql_using='hnsw',
            postgresql_ops={'embedding': 'vector_cosine_ops'},
        )

    # 5. Document Lineage table
    op.create_table(
        'document_lineage',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('old_doc_id', sa.String(length=36), nullable=False),
        sa.Column('new_doc_id', sa.String(length=36), nullable=False),
        sa.Column('scope', sa.String(length=50), nullable=False),
        sa.Column('amended_clauses', sa.JSON(), nullable=False),
        sa.Column('evidence_page', sa.Integer(), nullable=True),
        sa.Column('evidence_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['new_doc_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['old_doc_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_document_lineage_new_doc_id', 'document_lineage', ['new_doc_id'], unique=False)
    op.create_index('ix_document_lineage_old_doc_id', 'document_lineage', ['old_doc_id'], unique=False)

    # 6. Access Audit table
    op.create_table(
        'access_audit',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('query_hash', sa.String(length=64), nullable=False),
        sa.Column('blocked_candidates', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('decision', sa.String(length=50), nullable=False),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_access_audit_decision', 'access_audit', ['decision'], unique=False)
    op.create_index('ix_access_audit_query_hash', 'access_audit', ['query_hash'], unique=False)
    op.create_index('ix_access_audit_request_id', 'access_audit', ['request_id'], unique=False)
    op.create_index('ix_access_audit_role', 'access_audit', ['role'], unique=False)
    op.create_index('ix_access_audit_ts', 'access_audit', ['ts'], unique=False)

    # 7. Embedding Index Metadata table
    op.create_table(
        'embedding_index_metadata',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('model_id', sa.String(length=100), nullable=False),
        sa.Column('dim', sa.Integer(), nullable=False),
        sa.Column('normalized', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('is_mock', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('chunk_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # 8. Users table
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False, server_default='student'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_username', 'users', ['username'], unique=True)

    # 9. PostgreSQL Row-Level Security (RLS) & Non-Owner Role
    if is_postgres:
        op.execute(sa.text("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kvit_app_user') THEN
                    CREATE ROLE kvit_app_user WITH
                        LOGIN
                        NOSUPERUSER
                        NOCREATEDB
                        NOCREATEROLE
                        NOBYPASSRLS
                        PASSWORD 'kvit_app_password';
                ELSE
                    ALTER ROLE kvit_app_user WITH NOBYPASSRLS;
                END IF;
            END $$;
        """))
        op.execute(sa.text("GRANT USAGE ON SCHEMA public TO kvit_app_user;"))
        op.execute(sa.text("GRANT SELECT ON documents TO kvit_app_user;"))
        op.execute(sa.text("GRANT SELECT ON chunks TO kvit_app_user;"))
        op.execute(sa.text("GRANT SELECT ON document_lineage TO kvit_app_user;"))
        op.execute(sa.text("GRANT SELECT ON chunks_semantic TO kvit_app_user;"))

        op.execute(sa.text("ALTER TABLE documents ENABLE ROW LEVEL SECURITY;"))
        op.execute(sa.text("ALTER TABLE documents FORCE ROW LEVEL SECURITY;"))
        op.execute(sa.text("DROP POLICY IF EXISTS documents_role_governance_policy ON documents;"))
        op.execute(sa.text("""
            CREATE POLICY documents_role_governance_policy ON documents
            FOR SELECT
            TO kvit_app_user
            USING (
                allowed_roles::jsonb ? current_setting('app.current_role', true)
                OR allowed_roles::jsonb ? 'all'
            );
        """))

        op.execute(sa.text("ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;"))
        op.execute(sa.text("ALTER TABLE chunks FORCE ROW LEVEL SECURITY;"))
        op.execute(sa.text("DROP POLICY IF EXISTS chunks_role_governance_policy ON chunks;"))
        op.execute(sa.text("""
            CREATE POLICY chunks_role_governance_policy ON chunks
            FOR SELECT
            TO kvit_app_user
            USING (
                allowed_roles::jsonb ? current_setting('app.current_role', true)
                OR allowed_roles::jsonb ? 'all'
            );
        """))


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = (bind.dialect.name == "postgresql")

    if is_postgres:
        op.execute(sa.text("DROP POLICY IF EXISTS chunks_role_governance_policy ON chunks;"))
        op.execute(sa.text("DROP POLICY IF EXISTS documents_role_governance_policy ON documents;"))
        op.execute(sa.text("REVOKE SELECT ON documents FROM kvit_app_user;"))
        op.execute(sa.text("REVOKE SELECT ON chunks FROM kvit_app_user;"))
        op.execute(sa.text("REVOKE SELECT ON document_lineage FROM kvit_app_user;"))
        op.execute(sa.text("REVOKE SELECT ON chunks_semantic FROM kvit_app_user;"))

    op.drop_table('users')
    op.drop_table('embedding_index_metadata')
    op.drop_table('access_audit')
    op.drop_table('document_lineage')
    op.drop_table('chunks_semantic')
    op.drop_table('chunks')
    op.drop_table('documents')

