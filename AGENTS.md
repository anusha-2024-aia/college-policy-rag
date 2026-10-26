# AGENTS.md

## Document RAG Project - Architecture and Guidelines

### Overview
Document RAG (LexisPolicy AI / KVIT Policy Intelligence) is an enterprise-grade Retrieval-Augmented Generation system designed for querying, searching, and synthesizing information from policy PDF documents using version-aware DAG lineage tracking, partial amendment resolution, deterministic ChangeCards, hybrid retrieval, and 4-layer defence-in-depth role-based access control.

---

### Project Structure & Directory Layout
```
Document_RAG_Project/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application entrypoint, middleware & UI mounts
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py               # Pydantic Settings & environment config
│   │   ├── database.py             # Database engine & session management (SQLite / Postgres)
│   │   ├── auth.py                 # Cryptographic JWT verification & role extraction
│   │   ├── rls.py                  # Layer 2 PostgreSQL transaction-scoped RLS policies
│   │   ├── cache.py                # Role-scoped query & retrieval candidate cache
│   │   └── roles.py                # Role validation (student, faculty, admin)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── router.py               # Main API router aggregating route modules
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── ask.py              # POST /ask & POST /ask/stream endpoints
│   │       ├── auth.py             # POST /auth/token endpoint
│   │       ├── documents.py        # GET /documents & /documents/versions endpoints
│   │       ├── evaluations.py      # GET /evaluations/reports & /evaluations/summary
│   │       ├── admin_security.py   # GET /admin/audit-log & /admin/canaries endpoints
│   │       └── health.py           # Health check & system metrics endpoints
│   ├── models/
│   │   ├── __init__.py             # Base ORM registry
│   │   ├── document.py             # Document model with lineage & versioning fields
│   │   ├── chunk.py                # Chunk model with clause_ref, valid_from/to & allowed_roles
│   │   └── semantic_chunk.py       # ChunkSemantic model for 384-dim ONNX embeddings
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── qa.py                   # AskRequest, AskResponse, PassageEvidence, ChangeCard
│   │   ├── document.py             # DocumentMetadata, ChunkDetail schemas
│   │   ├── retrieval.py            # RetrievalDiagnostics, ScoredChunk, FusedChunk
│   │   ├── versioning.py           # DocumentVersionStatus, VersionGraphResponse
│   │   ├── auth.py                 # TokenResponse, TokenRequest
│   │   └── health.py               # HealthResponse, SystemMetrics
│   └── services/
│       ├── __init__.py
│       ├── ingestion.py            # PDF parsing, token-aware chunking & idempotent hashing
│       ├── retrieval.py            # Hybrid vector + BM25 keyword + RRF fusion pipeline
│       ├── versioning.py           # Directed lineage DAGs & partial amendment resolution
│       ├── conflict.py             # Deterministic metric regex & ChangeCard generator
│       ├── reranker.py             # Cross-encoder rerankers (FlashRank / Cohere / Mock)
│       ├── embedding.py            # Embedding services (Gemini / OpenAI / ONNX / Mock)
│       └── llm.py                  # LLM services (Google Gemini / OpenAI / Mock)
├── .github/
│   └── workflows/
│       └── ci.yml                  # GitHub Actions CI/CD pipeline
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Test fixtures & test client setup
│   ├── helpers.py                  # Test helper utilities
│   ├── test_demo_and_ci.py         # Phase 9 showcase & CI/CD verification tests
│   ├── test_evaluation_benchmark.py# Benchmark invariants & ablation metrics
│   ├── test_phase6_suite.py        # Adversarial attack matrix & unchanged clause verification
│   ├── test_stage3_verification_fixes.py # Targeted verification regressions
│   ├── test_rbac.py                # SQL pre-filtering & L1-L3 security invariants
│   ├── test_versioning.py          # Lineage DAG & partial amendment tests
│   └── ...                         # 289 automated tests (100% passing)
├── scripts/
│   ├── demo_walkthrough.py         # 6-Scenario executive demonstration script
│   └── setup_postgres_rls.sql      # PostgreSQL Row-Level Security DDL
├── eval/
│   ├── golden.jsonl                # 100 verified golden questions
│   ├── adversarial_queries.jsonl   # 30 adversarial prompt injection and jailbreak queries
│   ├── canaries.json               # Synthetic cryptographic canary register
│   ├── schemas.py                  # Pydantic validation for evaluation records
│   ├── metrics.py                  # Hit@5, MRR, leak detection, and abstention metrics
│   ├── runner.py                   # EvaluationRunner for 7 configurations
│   ├── run_eval.py                 # Multi-configuration CLI benchmark runner
│   └── run_phase6_tests.py         # Adversarial evaluation test runner
├── ui/
│   ├── web/                        # LexisPolicy AI Studio (7 responsive views)
│   └── app.py                      # Streamlit interactive application fallback
├── data/
│   ├── raw_pdfs/                   # Raw input PDFs (git-ignored for privacy)
│   ├── processed/                  # Processed document chunks & artifacts (git-ignored)
│   └── test_kvit.db                # Offline test database (16 docs, 43 chunks, 3 lineages)
├── docker-compose.yml              # PostgreSQL + pgvector container configuration
├── .env.example                    # Environment variable template
├── .gitignore                      # Git exclusion rules
├── pyproject.toml                  # Python package configuration
├── requirements.txt                # Python dependencies
├── README.md                       # Master portfolio documentation & setup guide
└── AGENTS.md                       # Architecture, agent instructions & guidelines
```

---

### Agent Behavioral & Implementation Rules
1. **Phased Development**:
   - Strictly follow the current phase scope. Do not implement future phase logic until instructed.
2. **Security**:
   - Never bind servers or databases to `0.0.0.0` during development or testing; use `127.0.0.1` or `localhost`.
   - Never hardcode secrets, API keys, or fallback credentials in source files.
   - All external data must be validated using Pydantic schemas.
   - Use parameterized queries or ORM abstractions for all database interactions.
   - User role must come solely from verified cryptographic JWT token, never from client request body.
3. **Data Privacy**:
   - Treat all user-uploaded PDF files as sensitive/private. Do not commit PDF files or raw extracted text to source control.
4. **Testing**:
   - All endpoints must have automated pytest tests using FastAPI `TestClient` or `httpx`.
   - Maintain clean test isolation.
   - Never invent metrics. Only report numbers produced by scripts in `eval/`.
   - Never weaken or delete a test to make it pass.
