# Architectural Audit: README Claims vs. Ground Truth Implementation

- **Date**: 2026-10-26
- **Auditor**: Antigravity Pair Programming Engine
- **Scope**: Entire codebase, Git tracking, evaluation framework, API security, and database layer
- **Audit Mode**: Strictly Read-Only (Zero Code Modifications)

---

## Executive Summary

This forensic audit rigorously compares the claims in the project's [`README.md`](../README.md) and [`docs/portfolio_architecture_guide.md`](./portfolio_architecture_guide.md) with the actual code implementation in `app/`, `eval/`, `tests/`, and `data/`.

While the project features deterministic ChangeCard generation, 4-layer access control concepts, and a 289-test passing regression suite, critical gaps exist regarding **evaluation realism**, **authentication security**, and **database isolation**:
1. **Evaluation & Demo Realism**: The latest benchmark (100% Hit@5 across 100 questions) and the live demo script were generated using **deterministic mock embeddings (1536-dim SHA-256 hash)**, a **mock heuristic reranker**, and a **mock regex LLM**. The real ONNX MiniLM embedder (384-dim) and FlashRank cross-encoder exist in the codebase but are bypassed during standard test and evaluation runs.
2. **Authentication Arbitrary Role Privilege**: The `/auth/demo-login` route allows any client to request any arbitrary role (`student`, `faculty`, `admin`) in the JSON body without password verification. There is no persistent `users` table or password hashing. Furthermore, `get_current_role` defaults to `"student"` on missing tokens rather than rejecting with `HTTP 401 Unauthorized`, and `/documents` allows an unauthenticated client to override its role via query parameter `?role=admin`.
3. **Database & RLS Execution**: 100% of automated tests run against **SQLite** (`data/test_kvit.db` or `:memory:`), not PostgreSQL. PostgreSQL Row-Level Security (RLS) is defined in a standalone SQL script (`scripts/setup_postgres_rls.sql`), but the application and Docker Compose configure connections as the PostgreSQL `postgres` superuser/owner rather than the restricted `kvit_app_user`.
4. **Corpus Denominator**: The active test corpus contains **16 documents and only 43 chunks**. The chance baseline of selecting a relevant chunk with top-$k=5$ purely at random is $5 / 43 = 11.63\%$, which was omitted from benchmark reporting.

---

## 1. Component Realism: Evaluation Path vs. Live Demo vs. Production

| Component | README Claim | Live Demo Path (`scripts/demo_walkthrough.py`) | Evaluation Path (`eval/run_eval.py`) | Production Code Default (`app/services/`) | Real Implementation Available? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Embeddings** | ONNX `all-MiniLM-L6-v2` (384d) & OpenAI/Gemini (1536d) | **MOCK** (`MockEmbeddingService`, 1536d SHA-256) [`scripts/demo_walkthrough.py#L247`](../scripts/demo_walkthrough.py#L247) | **MOCK** by default (runs with `--mock-embeddings`) [`eval/run_eval.py#L83-L86`](../eval/run_eval.py#L83-L86) | **MOCK** if no API key is present or in `test` environment [`app/services/embedding.py#L189`](../app/services/embedding.py#L189) | **YES**: `ONNXEmbeddingService` [`app/services/embedding_onnx.py#L26`](../app/services/embedding_onnx.py#L26), `OpenAIEmbeddingService`, `GeminiEmbeddingService` |
| **Reranker** | Cross-Encoder FlashRank `ms-marco-TinyBERT-L-2-v2` | **MOCK** (`MockRerankerService`, lexical token match) [`scripts/demo_walkthrough.py#L248`](../scripts/demo_walkthrough.py#L248) | **MOCK** by default (runs with `--mock-reranker`) [`eval/run_eval.py#L88-L90`](../eval/run_eval.py#L88-L90) | **MOCK** if `APP_ENV==test` or provider fails [`app/services/reranker.py#L230-L240`](../app/services/reranker.py#L230-L240) | **YES**: `FlashRankRerankerService` [`app/services/reranker.py#L125`](../app/services/reranker.py#L125), `CohereRerankerService` |
| **LLM Synthesis** | Google Gemini 2.5 Flash / OpenAI `gpt-4o-mini` | **MOCK** (`MockLLMService`, regex template synthesis) [`scripts/demo_walkthrough.py#L249`](../scripts/demo_walkthrough.py#L249) | **MOCK** (runs with `--force-mock-llm`) [`eval/run_eval.py#L93-L96`](../eval/run_eval.py#L93-L96) | **MOCK** if `APP_ENV==test` or API key is placeholder [`app/services/llm.py#L547-L556`](../app/services/llm.py#L547-L556) | **YES**: `GeminiLLMService` [`app/services/llm.py#L139`](../app/services/llm.py#L139), `OpenAILLMService` [`app/services/llm.py#L59`](../app/services/llm.py#L59) |
| **Vector Store** | PostgreSQL 16 + `pgvector` HNSW index | **SQLite In-Memory** (computes cosine similarity in Python) [`app/services/retrieval.py#L263-L270`](../app/services/retrieval.py#L263-L270) | **SQLite In-Memory** [`eval/run_eval.py#L12`](../eval/run_eval.py#L12) | Dual Dialect (PostgreSQL `pgvector` supported if connected) [`app/services/retrieval.py#L234-L245`](../app/services/retrieval.py#L234-L245) | **YES**: PostgreSQL pgvector distance query in `retrieval.py` |
| **Sparse Keyword** | PostgreSQL Full-Text Search `to_tsquery` / `ts_rank` | **SQLite Term Match** with length normalization [`app/services/retrieval.py#L345-L386`](../app/services/retrieval.py#L345-L386) | **SQLite Term Match** [`eval/run_eval.py#L12`](../eval/run_eval.py#L12) | Dual Dialect (PostgreSQL `Chunk.tsv @@ to_tsquery` supported) [`app/services/retrieval.py#L312-L343`](../app/services/retrieval.py#L312-L343) | **YES**: PostgreSQL `ts_rank` in `retrieval.py` |

---

## 2. HTTP Route Inventory & Access Governance

All endpoints registered in [`app/api/router.py`](../app/api/router.py) and [`app/main.py`](../app/main.py):

| Method | Path | Requires Auth? | Role Source | Role Filter Applied? | Vulnerability / Finding |
| :--- | :--- | :---: | :--- | :---: | :--- |
| `POST` | `/auth/demo-login` | **No** | Request Body (`payload.role`) | N/A | **High Risk**: Client chooses any role arbitrarily; zero password verification. [`app/api/routes/auth.py#L32-L46`](../app/api/routes/auth.py#L32-L46) |
| `POST` | `/ask` | **Soft Auth** | Header `Authorization: Bearer <token>` | **Yes** (L1 SQL + L3 assertion) | Missing token defaults to `"student"` instead of `HTTP 401`. [`app/core/auth.py#L178-L180`](../app/core/auth.py#L178-L180) |
| `POST` | `/ask/stream` | **Soft Auth** | Header `Authorization: Bearer <token>` | **Yes** (L1 SQL + L3 assertion) | Missing token defaults to `"student"` instead of `HTTP 401`. [`app/api/routes/ask.py#L96`](../app/api/routes/ask.py#L96) |
| `GET` | `/documents` | **Soft Auth** | Header OR query param `?role=` | **Yes** (server-side) | **High Risk**: If client sends no token, `?role=admin` is accepted and returns all admin docs! [`app/api/routes/documents.py#L79`](../app/api/routes/documents.py#L79) |
| `GET` | `/documents/{id}` | **Soft Auth** | Header `Authorization: Bearer <token>` | **Yes** (uniform 404) | Missing token defaults to `"student"`. [`app/api/routes/documents.py#L163`](../app/api/routes/documents.py#L163) |
| `POST` | `/documents/inspect` | **Soft Auth** | Header `Authorization: Bearer <token>` | **Yes** (canary scan) | Missing token defaults to `"student"`. [`app/api/routes/documents.py#L220`](../app/api/routes/documents.py#L220) |
| `GET` | `/evaluations/reports` | **NO** | None | **No** | Publicly accessible without authentication. Returns file listing. [`app/api/routes/evaluations.py#L52-L62`](../app/api/routes/evaluations.py#L52-L62) |
| `GET` | `/evaluations/reports/{filename}` | **Soft Auth** | Header `Authorization: Bearer <token>` | **Yes** (redacts canaries for non-admin) | Missing token defaults to `"student"`. Redacts sensitive file names from report text. [`app/api/routes/evaluations.py#L102`](../app/api/routes/evaluations.py#L102) |
| `GET` | `/system/stats` | **Soft Auth** | Header `Authorization: Bearer <token>` | **Yes** (doc counts scoped to role) | Missing token defaults to `"student"`. [`app/api/routes/system.py#L28`](../app/api/routes/system.py#L28) |
| `GET` | `/admin/security/denied-attempts`| **Yes** | Header `Authorization: Bearer <token>` | **Yes** (`require_admin` check) | Strictly enforces `verified_role == "admin"`; 403 on non-admin. [`app/api/routes/admin_security.py#L44-L51`](../app/api/routes/admin_security.py#L44-L51) |
| `GET` | `/admin/security/visible-document-counts` | **Yes** | Header `Authorization: Bearer <token>` | **Yes** (`require_admin` check) | Strictly enforces `verified_role == "admin"`. [`app/api/routes/admin_security.py#L99`](../app/api/routes/admin_security.py#L99) |
| `GET` | `/admin/security/last-leak-test` | **Yes** | Header `Authorization: Bearer <token>` | **Yes** (`require_admin` check) | Strictly enforces `verified_role == "admin"`. [`app/api/routes/admin_security.py#L132`](../app/api/routes/admin_security.py#L132) |
| `POST` | `/admin/security/run-leak-sweep` | **Yes** | Header `Authorization: Bearer <token>` | **Yes** (`require_admin` check) | Strictly enforces `verified_role == "admin"`. [`app/api/routes/admin_security.py#L151`](../app/api/routes/admin_security.py#L151) |
| `GET` | `/health` | **No** | None | **No** | Public healthcheck endpoint. [`app/api/routes/health.py#L10-L17`](../app/api/routes/health.py#L10-L17) |
| `GET` | `/` & `/ui` & 7 Studio Views | **No** | None | **No** | Static HTML studio files. [`app/main.py#L80-L110`](../app/main.py#L80-L110) |
| `GET` | `/download-ui-zip` | **No** | None | **No** | Downloads static UI zip artifact. [`app/main.py#L112-L121`](../app/main.py#L112-L121) |

---

## 3. Authentication & Authorization Flow Analysis

- **Role Decision & Client Privilege**:
  - In [`app/api/routes/auth.py#L32-L46`](../app/api/routes/auth.py#L32-L46), the only token issuing route is `POST /auth/demo-login`. It accepts `DemoLoginRequest(role: str)`.
  - Any client can submit `{"role": "admin"}` and obtain a cryptographically valid JWT with administrative claims.
  - The README claim in Section 6 (`curl -X POST http://127.0.0.1:8000/auth/token`) refers to `/auth/token`, but the actual router registers `/auth/demo-login`.
- **User Store & Credentials**:
  - There is **no `users` table** in SQLAlchemy models (`app/models/`).
  - No password hashing library (e.g., `bcrypt`, `argon2`, or `passlib`) is installed or utilized.
  - User accounts and identities are not persisted.
- **JWT Cryptographic Hardening**:
  - Implemented in [`app/core/auth.py#L60-L81`](../app/core/auth.py#L60-L81) using standard library `hmac`, `hashlib`, `base64`.
  - Algorithm is pinned to `HS256`; `alg=none` is strictly rejected ([`app/core/auth.py#L125-L127`](../app/core/auth.py#L125-L127)).
  - Expiry (`exp`) timestamp is validated ([`app/core/auth.py#L150`](../app/core/auth.py#L150)).
  - Signature verification uses constant-time comparison `hmac.compare_digest` ([`app/core/auth.py#L134`](../app/core/auth.py#L134)).
- **Default Secret Risk**:
  - In [`app/core/config.py#L66`](../app/core/config.py#L66), a fallback secret is hardcoded:
    `JWT_SECRET_KEY: str = "kvit-policy-intelligence-secret-key-2026-production"`
  - The application starts normally even if `JWT_SECRET_KEY` is not provided in environment variables.

---

## 4. Database, Schemas, Migrations & Row-Level Security (RLS)

- **Database Engine Usage**:
  - The project supports dual engines: SQLite and PostgreSQL.
  - However, in [`app/core/database.py#L23-L25`](../app/core/database.py#L23-L25), whenever `APP_ENV == "test"` (which is hardcoded in `tests/conftest.py#L4`), all queries execute against an **offline SQLite database** (`data/test_kvit.db` or `:memory:`).
- **Schema Creation & Migrations**:
  - Schemas are created imperatively via `Base.metadata.create_all()` ([`app/core/database.py#L48, L75`](../app/core/database.py#L48, L75)).
  - PostgreSQL incremental column additions (`ALTER TABLE ADD COLUMN IF NOT EXISTS`) are executed manually in Python code within `init_db()` ([`app/core/database.py#L65-L72`](../app/core/database.py#L65-L72)).
  - **Alembic is NOT implemented**; no `alembic/` migration directory or version tracking tables exist.
- **PostgreSQL Row-Level Security (RLS)**:
  - An RLS setup script exists at [`scripts/setup_postgres_rls.sql`](../scripts/setup_postgres_rls.sql). It correctly defines:
    - Dedicated role `kvit_app_user` with `NOBYPASSRLS`.
    - `ALTER TABLE documents ENABLE ROW LEVEL SECURITY; ALTER TABLE documents FORCE ROW LEVEL SECURITY;`
    - `CREATE POLICY ... USING (allowed_roles::jsonb ? current_setting('app.current_role', true) OR allowed_roles::jsonb ? 'all');`
  - In `app/core/rls.py#L41-L45`, `set_session_role()` correctly issues `SELECT set_config('app.current_role', :role, true)` on PostgreSQL connections.
  - **Ground Truth Gap**:
    - `setup_postgres_rls.sql` is never automatically executed by `init_db()`.
    - `docker-compose.yml#L35` configures the backend connection string as:
      `DATABASE_URL: "postgresql+psycopg2://postgres:postgres@pgvector:5432/document_rag"`
    - The application connects as `postgres` (superuser/table owner), which bypasses normal RLS policies unless specifically forced and tested under the unprivileged role `kvit_app_user`.
    - **Zero automated tests connect to real PostgreSQL to verify RLS execution**.

---

## 5. Automated Test Suite Execution & Analysis

Full test suite execution executed on 2026-10-26:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.1, pluggy-1.7.0
rootdir: C:\Users\Lenovo\OneDrive\Desktop\Document_RAG_Project
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1, asyncio-1.4.0
asyncio: mode=Mode.AUTO
collected 289 items

289 passed in 51.16s
============================ 289 passed in 51.16s =============================
```

- **Exact Counts**: **289 passed**, 0 failed, 0 skipped.
- **Execution Breakdown**:
  - **SQLite-Only**: 289 / 289 tests (100%) execute against SQLite (`data/test_kvit.db` or `:memory:`).
  - **PostgreSQL Tests**: 0 / 289 tests execute against PostgreSQL or real pgvector.
  - **Mock Embeddings**: ~270 / 289 tests use `MockEmbeddingService(1536)`. Only `test_embedding_onnx.py` (7 tests) and `test_backfill_semantic.py` instantiate the real local ONNX model.
  - **Mock Reranker**: ~280 / 289 tests use `MockRerankerService`. Only `test_reranker.py` tests `FlashRankRerankerService`.
  - **Mock LLM**: 289 / 289 tests use `MockLLMService`.

---

## 6. Evaluation Framework & Dataset Integrity

- **Evaluation Dataset Files**:
  - Golden Dataset: [`eval/golden.jsonl`](../eval/golden.jsonl) containing **100 validated questions** (55 standard, 15 stale-policy traps, 15 unanswerable out-of-corpus questions, 15 role-restricted questions).
  - Adversarial Dataset: [`eval/adversarial_queries.jsonl`](../eval/adversarial_queries.jsonl) containing **30 adversarial prompt injection and jailbreak queries**.
  - Canary Register: [`eval/canaries.json`](../eval/canaries.json) defining 8 confidential documents and synthetic cryptographic tokens (e.g., `KVIT-FAC-CNRY-7731`, `KVIT-ADM-CNRY-8870`).
- **Corpus Size & Denominator Honesty**:
  - Database: `data/test_kvit.db` contains **16 documents**, **43 chunks**, and **3 version lineage DAGs**.
  - **Chance Baseline**: In a corpus of 43 chunks, picking top-$k=5$ candidate chunks uniformly at random gives an expected baseline Recall@5 of:
    $$\text{Baseline Recall@5} = \frac{5}{43} \approx 11.63\%$$
  - This denominator warning was omitted from `README.md` and evaluation markdown summaries.
- **Benchmark Provenance & Mock Flagging**:
  - The benchmark report cited in the README ([`eval/results/eval_report_20261025_182748.md`](../eval/results/eval_report_20261025_182748.md)) was generated via:
    `python -m eval.run_eval --configs all --mock-embeddings --mock-reranker --force-mock-llm`
  - **Ground Truth**: The reported **100% Hit@5**, **0.9467 MRR**, and **0.00% stale policy error** reflect the behavior of the deterministic SHA-256 mock embedder, mock lexical reranker, and mock regex synthesizer.
  - The results were written to `eval/results/eval_results_20261025_182748.json` rather than a designated `eval/results/mock/` directory.

---

## 7. Secrets & Repository History Scan

- **Git Tracked Files (`git ls-files`)**:
  - `.env` is **NOT tracked** (correctly ignored in [`.gitignore`](../.gitignore)).
  - `.env.example` and `frontend/.env.example` are tracked and contain only placeholder templates.
  - Local SQLite databases (`data/test_kvit.db`) and raw PDFs (`data/raw_pdfs/`) are properly ignored.
- **Git Commit History Scan (`git log -p`)**:
  - Scanned commit diffs for secret patterns (`sk-[a-zA-Z0-9]{20,}`, `AIzaSy[a-zA-Z0-9_-]{30,}`).
  - **Finding**: **Zero live OpenAI or Google API keys were committed to Git history**.
- **Hardcoded Default Secrets**:
  - In [`app/core/config.py#L66`](../app/core/config.py#L66):
    `JWT_SECRET_KEY: str = "kvit-policy-intelligence-secret-key-2026-production"`
  - This hardcoded default should be replaced with mandatory environment variable loading that refuses to boot if missing.

---

## 8. Gap Analysis Table (`docs/GAP_CLOSURE_PLAN.md` Status)

| Phase | Description | Status | Evidence / Code References |
| :--- | :--- | :---: | :--- |
| **Phase 0** | Read-Only Audit (README vs. Real Code) | **DONE** | [`docs/AUDIT.md`](./AUDIT.md) completed with line citations and execution counts. |
| **Phase 1** | Real Embeddings & Trustworthy Benchmark | **PARTIAL** | Real ONNX model (`app/services/embedding_onnx.py`) and FlashRank (`app/services/reranker.py`) exist, but `EmbeddingProvider` unified interface with `is_mock` is missing; model mismatch query check missing; `python -m app.cli.reindex` missing; benchmark ran with `--mock-*` and saved to `eval/results/` instead of `eval/results/mock/`. |
| **Phase 2** | Auth Hardening & PostgreSQL RLS Proof | **PARTIAL** | `/auth/demo-login` allows arbitrary role selection without password; no `users` table; missing token returns `"student"` instead of `HTTP 401`; `?role=` query param leaks in `/documents`; RLS script exists (`setup_postgres_rls.sql`) but has no real PostgreSQL test suite. |
| **Phase 3** | Credibility Bugs (Library, Snippets, UI) | **PARTIAL** | Hidden document counts implemented; citation snippet extraction cleans headers (`app/services/qa.py#L400-L450`); sequential `[1], [2]` citations implemented; but `/evaluations/reports` has no auth, and "How it works" / system pages contain development artifacts. |
| **Phase 4** | Stronger Evaluation (Extended Golden, Denominators) | **PARTIAL** | 100 golden questions verified (`eval/golden.jsonl`); 7 configurations benchmarked; but extended golden set (`eval/golden_extended.jsonl`), bootstrap 95% CI, failure taxonomy markdown (`FAILURES.md`), and chance baseline warnings are missing. |
| **Phase 5** | Database Reliability (Alembic, Migrations, Backup) | **NOT STARTED** | No Alembic migrations (`alembic/`); tables created with `Base.metadata.create_all`; no backup/restore scripts (`scripts/backup.sh`); no `docs/OPERATIONS.md`. |
| **Phase 6** | CI & Security Scanning | **PARTIAL** | `.github/workflows/ci.yml` exists with 5 jobs, but runs on Ubuntu without a real PostgreSQL/pgvector service container; no `ruff`, `pip-audit`, or `gitleaks` steps. |
| **Phase 7** | Policy Change Intelligence (Clause-Level Diff) | **PARTIAL** | Deterministic ChangeCard regex generator (`app/services/conflict.py`) and partial amendment DAGs (`app/services/versioning.py`) implemented; but dedicated endpoint `GET /policies/{lineage_id}/diff` and interactive comparison UI views are not yet exposed. |
| **Phase 8** | Recruiter-Ready Presentation & Claims Ledger | **PARTIAL** | Portfolio guide (`docs/portfolio_architecture_guide.md`) and showcase script (`scripts/demo_walkthrough.py`) exist; but `docs/CLAIMS.md`, `docs/INTERVIEW_NOTES.md`, and `docs/DEMO_SCRIPT.md` are not yet created. |

---

## 9. Conclusion & Immediate Recommendations

Phase 0 confirms that the repository has a solid architectural core (clean Pydantic schemas, deterministic conflict detection, and an extensive test suite). However, to make this codebase defensible in technical interviews, the following critical steps must be addressed in priority order:

1. **Phase 1**: Replace mock evaluation benchmarks with **real ONNX MiniLM (384d) dense vectors** and **real FlashRank reranking**, segregating real vs. mock evaluation outputs into `eval/results/real/` vs `eval/results/mock/`.
2. **Phase 2**: Harden authentication by creating a persistent `users` table with password hashing, removing the unauthenticated role picker, requiring JWT auth on all protected routes (rejecting missing tokens with `HTTP 401`), and running automated RLS tests against real PostgreSQL under `kvit_app_user`.
