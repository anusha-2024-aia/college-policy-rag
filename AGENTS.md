# AGENTS.md

## Document RAG Project - Architecture and Guidelines

### Overview
Document RAG is an enterprise-grade Retrieval-Augmented Generation system designed for querying, searching, and synthesizing information from PDF documents using hybrid retrieval, vector embeddings, reranking, and large language models.

---

### Project Structure & Directory Layout
```
Document_RAG_Project/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application entrypoint & middleware
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py               # Pydantic Settings & environment config
│   │   └── database.py             # Database engine & session management
│   ├── api/
│   │   ├── __init__.py
│   │   ├── router.py               # Main API router aggregating route modules
│   │   └── routes/
│   │       ├── __init__.py
│   │       └── health.py           # Health check endpoints
│   ├── models/
│   │   └── __init__.py             # Database / ORM models
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── health.py               # Pydantic request / response schemas
│   └── services/
│       └── __init__.py             # Ingestion, embedding, retrieval & LLM services
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Test fixtures & test client setup
│   └── test_health.py              # Health check endpoint tests
├── data/
│   ├── raw_pdfs/                   # Raw input PDFs (git-ignored for privacy)
│   └── processed/                  # Processed document chunks & artifacts (git-ignored)
├── docker-compose.yml              # PostgreSQL + pgvector container configuration
├── .env.example                    # Environment variable template
├── .gitignore                      # Git exclusion rules
├── pyproject.toml                  # Python package configuration
├── requirements.txt                # Python dependencies
├── README.md                       # Setup and usage guide
└── AGENTS.md                       # Architecture, agent instructions & guidelines
```

---

### Agent Behavioral & Implementation Rules
1. **Phased Development**:
   - Strictly follow the current phase scope. Do not implement future phase logic (e.g., ingestion, embeddings, LLM generation) until instructed.
2. **Security**:
   - Never bind servers or databases to `0.0.0.0` during development or testing; use `127.0.0.1` or `localhost`.
   - Never hardcode secrets, API keys, or fallback credentials in source files.
   - All external data must be validated using Pydantic schemas.
   - Use parameterized queries or ORM abstractions for all database interactions.
3. **Data Privacy**:
   - Treat all user-uploaded PDF files as sensitive/private. Do not commit PDF files or raw extracted text to source control.
4. **Testing**:
   - All endpoints must have automated pytest tests using FastAPI `TestClient` or `httpx`.
   - Maintain clean test isolation.
