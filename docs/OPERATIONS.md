# Operations, Database Reliability & Disaster Recovery Manual

This document details the production operations, configuration invariants, schema migration workflows, disaster recovery procedures, and health diagnostics for the KVIT Policy Intelligence Document RAG system.

---

## 1. Database Architecture & Environment Notice

> [!IMPORTANT]
> **Production Requirement vs. Development Fallback**:
> - **Production Requirement**: **PostgreSQL 16+ with `pgvector` extension** is mandatory for all multi-tenant and production deployments. PostgreSQL enforces Layer 2 transaction-scoped Row-Level Security (`SET LOCAL app.current_role`), HNSW vector cosine indexing (`idx_chunks_embedding_hnsw`), and GIN full-text search (`idx_chunks_tsv_gin`).
> - **Development Fallback Only**: **SQLite** (`data/test_kvit.db` or in-memory `:memory:`) is strictly a local offline-developer and test fallback. SQLite lacks native PostgreSQL RLS and hardware-accelerated pgvector indexing. Production deployments MUST connect to PostgreSQL.

---

## 2. Configuration Environment Variables

Configure application parameters using environment variables or a `.env` file in the project root:

| Variable | Type | Default | Description / Security Invariant |
| :--- | :---: | :---: | :--- |
| `APP_ENV` | `str` | `development` | Deployment environment: `production`, `development`, or `test`. In `production`, runtime `create_all` is prohibited. |
| `DATABASE_URL` | `str` | `postgresql+asyncpg://...` | Master connection string. Alembic and sync tools automatically translate to `postgresql+psycopg2://`. |
| `JWT_SECRET_KEY` | `str` | *(required in prod)* | Cryptographic HMAC-SHA256 signing key. Production startup halts if key is default or insecure. |
| `JWT_ALGORITHM` | `str` | `HS256` | JWT cryptographic signature algorithm. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `int` | `60` | Access token time-to-live. |
| `L2_RLS_ENABLED` | `bool` | `true` | Layer 2 PostgreSQL Row-Level Security enforcement toggle. |
| `SECURITY_ENFORCEMENT_ENABLED` | `bool` | `true` | Master defence-in-depth switch (L1 SQL filter, L2 RLS, L3 passage filter). |
| `QUERY_CACHE_ENABLED` | `bool` | `true` | Role-scoped caching of retrieval and synthesis queries. |
| `SHOW_HIDDEN_DOCUMENT_COUNT` | `bool` | `true` | Controls whether `/documents` returns `hidden_count` metadata. |
| `SEMANTIC_RETRIEVAL_ENABLED` | `bool` | `true` | Toggles dense 384-dimensional ONNX vector retrieval. |
| `EMBEDDING_PROVIDER` | `str` | `all-minilm-l6-v2` | Embedding model (`all-minilm-l6-v2`, `openai`, `gemini`, or `mock-sha256`). |
| `RERANKER_PROVIDER` | `str` | `flashrank` | Cross-encoder reranker (`flashrank` or `cohere`). |
| `CORS_ORIGINS` | `str` | `""` | Comma-separated permitted CORS origin whitelist. |

---

## 3. Schema Migrations (Alembic)

Database schema lifecycle is managed deterministically via **Alembic**.

### Migration Invariants:
1. **No Runtime `create_all` in Production**: When `APP_ENV=production`, runtime schema generation (`Base.metadata.create_all`) is strictly disabled. The database schema must be initialized and updated via migration revisions prior to launching backend application workers.
2. **Single Migration Tree**: Revisions are linearly chained from base to `head`.

### Migration Commands:

```bash
# Apply all pending migrations to latest schema version
alembic upgrade head

# Generate offline static SQL DDL without database connection
alembic upgrade head --sql

# Roll back the most recent migration revision
alembic downgrade -1

# Roll back to completely empty database (base)
alembic downgrade base

# Check migration revision status
alembic current
alembic history --verbose

# Create a new schema migration revision
alembic revision -m "add_audit_retention_policy"
```

---

## 4. Ingestion Reliability & Lineage Tracking

The ingestion pipeline (`app/services/ingestion.py`) implements three fundamental data reliability guarantees:

1. **Idempotency**: Running ingestion on an unchanged file (matching SHA-256 hash) skips re-chunking and re-embedding. Zero duplicate chunk records are created.
2. **Lineage Preservation & Non-Destructive Supersession**: When a newer document supersedes an older version, the older document is updated to `status='superseded'` and its chunks receive `valid_to = new_effective_date`. Historical chunks are **never deleted**, ensuring historical "as-of" queries can always be answered accurately.
3. **Atomic Transactional Rollback**: Document metadata and all associated chunks and dense embeddings are written within a single database transaction. If an error occurs during parsing, chunking, or embedding, `db.rollback()` executes automatically, preventing orphaned documents or dangling chunks.

---

## 5. Backup, Disaster Recovery & Restore Procedures

### 5.1 Performing a Database Backup

#### Linux / macOS:
```bash
# Automated compressed pg_dump archive into data/backups/
bash scripts/backup.sh
# Or specify a custom output path:
bash scripts/backup.sh /var/backups/document_rag_custom.dump
```

#### Windows (PowerShell):
```powershell
.\scripts\backup.ps1 -OutputFile "data\backups\manual_backup.dump"
```

### 5.2 Restoring from Backup Archive

#### Linux / macOS:
```bash
# Restores into DATABASE_URL using pg_restore
bash scripts/restore.sh data/backups/document_rag_20261102_100000.dump
```

#### Windows (PowerShell):
```powershell
.\scripts\restore.ps1 -BackupFile "data\backups\document_rag_20261102_100000.dump"
```

### 5.3 Automated Disaster Recovery Drill

Execute the automated verification drill to validate backup archive creation, restoration into an empty database, exact table row count matching, and vector query execution:

```bash
python scripts/drill_backup_restore.py
```

Expected Drill Output:
```text
================================================================================
 KVIT POLICY INTELLIGENCE - DISASTER RECOVERY & BACKUP/RESTORE DRILL
================================================================================
 [STEP 1] Generating Atomic Database Backup Archive... [OK]
 [STEP 2] Initializing Clean Target Database and Restoring Archive... [OK]
 [STEP 3] Verifying Restored Database Invariants & Row Counts...
 Table Name                     | Source Count   | Restored Count | Status
 ------------------------------ | -------------- | -------------- | --------
 documents                      | 16             | 16             | MATCH
 chunks                         | 51             | 51             | MATCH
 chunks_semantic                | 51             | 51             | MATCH
 document_lineage               | 3              | 3              | MATCH
 users                          | 3              | 3              | MATCH
 embedding_index_metadata       | 1              | 1              | MATCH
 [STEP 4] Executing Sample Retrieval Query Against Restored Database... [OK]
 --------------------------------------------------------------------------------
 DRILL STATUS: SUCCESS
================================================================================
```

---

## 6. System Health & Diagnostic Endpoints

The API exposes endpoints for monitoring uptime, versioning, and database statistics:

### 1. Basic Health Check: `GET /health`
- **Authentication**: Public
- **Response**:
  ```json
  {
    "status": "ok",
    "app": "Document RAG API",
    "version": "0.1.0",
    "environment": "production"
  }
  ```

### 2. Live System Metrics: `GET /system/stats`
- **Authentication**: Required (`Bearer <JWT>` with role `student`, `faculty`, or `admin`)
- **Behavior**: Scopes document and chunk counts to the caller's role.
- **Response**:
  ```json
  {
    "app_name": "Document RAG API",
    "environment": "production",
    "total_docs": 10,
    "total_chunks": 32,
    "total_pages": 44,
    "semantic_retrieval_enabled": true,
    "embedding_model": "all-MiniLM-L6-v2",
    "embedding_dimension": 384,
    "reranker_model": "ms-marco-TinyBERT-L-2-v2",
    "llm_provider": "gemini",
    "llm_model": "gemini-3.5-flash"
  }
  ```

