# Document RAG Project

An enterprise-grade Retrieval-Augmented Generation (RAG) system for ingesting, querying, and extracting insights from PDF documents using vector search, reranking, and LLMs.

---

## Architecture Overview

```
Document_RAG_Project/
├── app/
│   ├── main.py                     # FastAPI application entrypoint & middleware
│   ├── core/
│   │   ├── config.py               # Pydantic Settings & environment variables
│   │   └── database.py             # Database engine & session management
│   ├── api/
│   │   ├── router.py               # Combined API router
│   │   └── routes/
│   │       └── health.py           # GET /health endpoint
│   ├── models/                     # Database / ORM models (Phase 1+)
│   ├── schemas/                    # Pydantic request/response schemas
│   └── services/                   # Business logic (Ingestion, Retrieval, LLM)
├── tests/
│   ├── conftest.py                 # Pytest fixtures & TestClient
│   └── test_health.py              # Health check test suite
├── data/
│   ├── raw_pdfs/                   # Local storage for private PDFs (git-ignored)
│   └── processed/                  # Chunked text & artifacts (git-ignored)
├── docker-compose.yml              # PostgreSQL 16 + pgvector container
├── .env.example                    # Configuration template
├── .gitignore                      # Git exclusion rules
├── pyproject.toml                  # Python package configuration
├── requirements.txt                # Pip dependency specifications
└── AGENTS.md                       # Architecture & agent development standards
```

---

## Getting Started

### 1. Prerequisites
- **Python 3.11+** installed on your system.
- **Docker & Docker Compose** (optional, for local pgvector database) OR a **Managed PostgreSQL instance** with pgvector support.

---

### 2. Environment Setup

#### Create and Activate a Virtual Environment
On Windows (PowerShell):
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

On macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

#### Install Dependencies
```powershell
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

---

### 3. Environment Variables
Copy the example environment configuration:
```powershell
Copy-Item .env.example .env
```
Edit `.env` to configure your API keys and database connection:
- `DATABASE_URL`: PostgreSQL connection string with pgvector support.
- `LLM_API_KEY`: API key for your LLM provider (OpenAI, Anthropic, etc.).
- `EMBEDDING_PROVIDER` & `EMBEDDING_MODEL`: Vector embedding model configuration.
- `RERANKER_PROVIDER` & `RERANKER_MODEL`: Reranker model configuration.

---

### 4. Database Setup

#### Option A: Local Docker Compose (Recommended if Docker Desktop is running)
Start PostgreSQL 16 with pgvector enabled:
```powershell
docker compose up -d
```
To verify the container is running and healthy:
```powershell
docker compose ps
```
To stop the database:
```powershell
docker compose down
```

#### Option B: Managed Database (Supabase, Neon, AWS RDS, Tembo)
If you do not run Docker locally, use a managed cloud PostgreSQL database:
1. Create a PostgreSQL project on [Supabase](https://supabase.com/) or [Neon](https://neon.tech/).
2. Enable the `vector` extension in your database SQL console:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
3. Update `DATABASE_URL` in your `.env` file with your connection string:
   ```env
   DATABASE_URL="postgresql+asyncpg://<username>:<password>@<host>:<port>/<dbname>"
   ```

---

### 5. Running the API

Start the FastAPI development server with auto-reload:
```powershell
py -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Once started:
- **API Health Endpoint**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- **Interactive OpenAPI Documentation (Swagger)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Alternative API Docs (ReDoc)**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

### 6. Running Tests

Run the test suite with pytest:
```powershell
py -m pytest -v
```

To run tests with specific output details:
```powershell
py -m pytest -v -s tests/test_health.py
```

---

## Health Check Endpoint Specification

- **Method**: `GET`
- **Route**: `/health`
- **Status Code**: `200 OK`
- **Response Example**:
  ```json
  {
    "status": "ok",
    "app": "Document RAG API",
    "version": "0.1.0",
    "environment": "development"
  }
  ```

---

## 7. PDF Ingestion Pipeline

### Document Manifest
Documents to ingest are declared in `docs/documents_manifest.csv`. Each row contains:
- `file`: Path to the PDF document (e.g., `data/raw_pdfs/employee_handbook.pdf`).
- `title`: Human-readable document title.
- `effective_date`: Document effective date in `YYYY-MM-DD` format.
- `supersedes`: Identifier or title of the superseded document version (or blank).
- `allowed_roles`: Semicolon or comma-separated list of permitted access roles (e.g., `admin;hr;legal`).

### Running Ingestion via CLI
Run the ingestion command line tool:
```powershell
py -m app.cli.ingest --manifest docs/documents_manifest.csv
```

#### CLI Options:
- `--manifest <path>`: Custom manifest path (default: `docs/documents_manifest.csv`).
- `--force`: Re-chunk and re-embed documents even if file hash matches.
- `--chunk-size <int>`: Tokens per chunk (default: `500`).
- `--chunk-overlap <int>`: Overlap tokens between adjacent chunks on the same page (default: `80`).
- `--mock-embeddings`: Run ingestion using deterministic offline embeddings without requiring external API keys.

---

## 8. Hybrid Retrieval Pipeline

The retrieval pipeline combines dense vector search, sparse keyword search, Reciprocal Rank Fusion (RRF), and cross-encoder reranking:

1. **Dense Vector Search**: Uses `pgvector` cosine similarity (`1.0 - cosine_distance`) to identify semantically related chunks.
2. **Sparse Keyword Search**: Uses PostgreSQL full-text search (`tsvector` & `ts_rank`) for exact lexical matching.
3. **Reciprocal Rank Fusion (RRF)**: Merges vector and keyword candidate rankings with configurable $k_{rrf} = 60$. Candidates present in both lists are deduplicated and receive score boosts.
4. **Cross-Encoder Reranking**: Re-orders candidate passages using hosted (Cohere) or lightweight CPU-only scoring.

### Running Retrieval Inspection via CLI
```powershell
py -m app.cli.search "What is the policy on remote work and hybrid days?" --stage all
```

#### CLI Options:
- `--stage`: `all` (default), `vector`, `keyword`, `fused`, `reranked`.
- `--k <int>`: Number of initial candidates per search stage (default: `20`).
- `--top-n <int>`: Number of final reranked passages to return (default: `5`).
- `--k-rrf <int>`: Reciprocal Rank Fusion constant (default: `60`).
- `--mock-embeddings`: Use deterministic vectors for CPU-only / offline execution.
- `--mock-reranker`: Use deterministic lexical-semantic reranking without external API calls.

> [!NOTE]
> **Production Boundary**: In Phase 2 & 3, version-aware filtering (e.g. hiding superseded documents) and role-based access control (RBAC) are documented with `# TODO(security)` and remain deferred to subsequent phases.

---

## 9. Question Answering & Citation Generation (`POST /ask`)

Phase 3 introduces grounded question answering with verified citations, strict anti-hallucination controls, configurable abstention, and real-time Server-Sent Events (SSE) streaming.

### Features
1. **Evidence-Grounded Synthesis**: LLM prompt enforces strict adherence only to the supplied numbered evidence passages (`[1]`, `[2]`).
2. **Citation Validation**: All citation identifiers (`[N]`) are parsed and validated against retrieved passages. Any model-invented citation indices (e.g. `[99]`) are stripped and omitted, guaranteeing that the API never invents source files or page numbers.
3. **Calibrated Abstention Policy**: Automatically abstains when evidence is missing, when reranker confidence scores fall below `abstention_threshold`, or when the query is unanswerable from the corpus, outputting the exact sentence:
   `"I do not have sufficient information in the provided documents to answer this question."`
4. **Resilient Error Mapping**:
   - `503 Service Unavailable`: Missing API credentials or provider failure.
   - `429 Too Many Requests`: LLM provider rate limit exceeded.
   - `504 Gateway Timeout`: LLM provider response timeout.
5. **Streaming via SSE (`POST /ask/stream`)**: Real-time token streaming with `metadata`, `token`, `citations`, and `done` events.

---

### Endpoints

#### 1. Standard QA: `POST /ask`

**Request Body (`application/json`)**:
```json
{
  "question": "What is the corporate architecture and standard operating procedures?",
  "top_k": 20,
  "top_n": 5,
  "abstention_threshold": 0.0,
  "include_diagnostics": true
}
```

**Response (`200 OK`)**:
```json
{
  "question": "What is the corporate architecture and standard operating procedures?",
  "answer": "According to corporate documentation, the system establishes a modular architecture [1]. Standard operating procedures require compliance checks [2].",
  "citations": [
    {
      "index": 1,
      "file_name": "valid_doc.pdf",
      "page_number": 1,
      "snippet": "Overview of corporate architecture and mission..."
    },
    {
      "index": 2,
      "file_name": "valid_doc.pdf",
      "page_number": 2,
      "snippet": "Standard operating procedures and safety regulations..."
    }
  ],
  "passages": [
    {
      "index": 1,
      "chunk_id": "3dcb0ee6-...",
      "file_name": "valid_doc.pdf",
      "page_number": 1,
      "text": "Page 1: Overview of corporate architecture and mission.",
      "score": 0.85
    }
  ],
  "abstained": false,
  "diagnostics": {
    "timings_ms": {
      "vector_search_ms": 1.5,
      "keyword_search_ms": 1.2,
      "rrf_fusion_ms": 0.4,
      "reranking_ms": 0.8,
      "total_retrieval_ms": 3.9
    },
    "vector_count": 5,
    "keyword_count": 5,
    "fused_count": 8,
    "reranked_count": 5
  }
}
```

#### 2. Streaming QA: `POST /ask/stream`

Streams Server-Sent Events with media type `text/event-stream`:
```text
event: metadata
data: {"passages": [...], "diagnostics": {...}}

event: token
data: {"token": "According "}

event: token
data: {"token": "to "}

event: citations
data: {"citations": [{"index": 1, "file_name": "valid_doc.pdf", "page_number": 1, ...}], "abstained": false}

event: done
data: {}
```

---

## 10. Version-Aware Policy Handling

Phase 4 introduces directed version lineage graphs, relationship validation, targeted precedence, conflict detection, and current-first answer synthesis.

### Core Capabilities
1. **Lineage Graph Construction**: Connects predecessor and successor documents based on `effective_date`, `supersedes`, and document titles/filenames/IDs.
2. **Graph Validation**:
   - Detects and flags missing `supersedes` targets (`MissingSupersedesTargetError`).
   - Detects circular dependencies ($A \rightarrow B \rightarrow A$) using depth-first cycle traversal (`CircularVersionError`).
   - Detects temporal ordering contradictions ($T_{\text{predecessor}} > T_{\text{successor}}$) (`TemporalOrderError`).
3. **Preservation of Historical Citations**: Superseded documents and their chunks remain queryable and citable in the database; historical records are never deleted.
4. **Targeted Lineage Precedence**: A newer document only supersedes documents within its explicit lineage. Unrelated documents (such as a 2025 Travel Policy or 2022 Core Values) are never falsely marked as superseded.
5. **Conflict Detection & Current-First Synthesis**:
   - When evidence contains both active and superseded policies for a relevant topic, `has_policy_conflict` is set to `true`.
   - `conflict_details` contains the current and superseded document titles, files, effective dates, and citation indices.
   - The generated answer explains the **current policy first** citing its reference `[1]`, and identifies the older policy as superseded citing `[2]`.
6. **Ablation & Evaluation Toggle**:
   - Globally toggleable via `VERSION_AWARE_ENABLED` in `.env` or settings.
   - Per-request toggleable via `version_aware: bool` in `AskRequest`.

### Example Request with Version-Awareness:
```json
POST /ask
{
  "question": "How many days per week are employees permitted to work remotely?",
  "version_aware": true,
  "top_k": 10,
  "top_n": 4
}
```

### Example Response with Policy Conflict:
```json
{
  "question": "How many days per week are employees permitted to work remotely?",
  "answer": "Under the current policy (effective 2024-01-01), Employees are permitted to work remotely 3 days per week [1]. However, this supersedes the previous policy (effective 2023-01-01), which stated that Employees are permitted to work remotely 1 day per week [2].",
  "citations": [
    {
      "index": 1,
      "file_name": "remote_work_policy_v2.pdf",
      "page_number": 1,
      "snippet": "Remote Work Policy 2024. Employees are permitted to work remotely 3 days per week."
    },
    {
      "index": 2,
      "file_name": "remote_work_policy_v1.pdf",
      "page_number": 1,
      "snippet": "Remote Work Policy 2023. Employees are permitted to work remotely 1 day per week."
    }
  ],
  "passages": [...],
  "abstained": false,
  "has_policy_conflict": true,
  "conflict_details": [
    {
      "current_title": "Remote Work Policy 2024",
      "current_file": "remote_work_policy_v2.pdf",
      "current_effective_date": "2024-01-01",
      "current_citation_index": 1,
      "superseded_title": "Remote Work Policy 2023",
      "superseded_file": "remote_work_policy_v1.pdf",
      "superseded_effective_date": "2023-01-01",
      "superseded_citation_index": 2,
      "description": "Policy 'Remote Work Policy 2023' (effective 2023-01-01) has been superseded by 'Remote Work Policy 2024' (effective 2024-01-01)."
    }
  ]
}
```
---

## 11. Role-Based Access Control (RBAC)

Phase 5 enforces multi-tenant, role-based access control directly at the SQL database layer to guarantee information security across dense vector search, sparse keyword search, RRF fusion, cross-encoder reranking, and generative answer synthesis.

### Permitted Roles
Access control is governed by three strictly validated roles:
1. `student`: Standard learner role with access only to public course materials, syllabi, and general institutional policies.
2. `faculty`: Academic teaching and instructional staff with access to syllabi, grading rubrics, and exam solution keys.
3. `admin`: Institutional leadership and systems administration with full access across all documents, executive compensation records, budgets, and confidential disciplinary records.

Unrecognized, unknown, or empty roles (e.g., `role: "hacker"`) are rejected at the API boundary with `HTTP 422 Unprocessable Content`.

### SQL-Level Query Filtering Invariant
Role filtering is applied **inside the database query** using native SQL predicates:
- **Dense Vector Search**: Evaluated inside the SQL `WHERE` clause before vector distance calculation and candidate ordering.
- **Sparse Keyword Search**: Evaluated inside the SQL `WHERE` clause before full-text tsvector matching and ts_rank scoring.
- **Cross-Dialect Support**:
  - **PostgreSQL**: Implemented via JSONB containment operators: `cast(Document.allowed_roles, JSONB).op("@>")(f'["{clean_role}"]') | cast(Document.allowed_roles, JSONB).op("@>")('["all"]')`.
  - **SQLite**: Implemented via table-valued JSON functions: `func.json_each(Document.allowed_roles).table_valued("value")` combined with `where(je.c.value.in_([clean_role, "all"])).exists()`.

Because unauthorized records are never returned from the database:
- Reciprocal Rank Fusion (RRF) and Cross-Encoder Reranking never process unauthorized candidates.
- The LLM context never receives unauthorized passages.
- Citations, passages, diagnostics, and abstention messages never disclose restricted titles, filenames, or snippet tokens.

### Production Security Demarcation
> [!CAUTION]
> **Production Boundary**: The `role` field on `POST /ask`, `POST /ask/stream`, and the CLI `--role` flag is an evaluation and testing interface.
> In production environments, client-supplied role parameters MUST NOT be trusted. Production deployments must resolve authenticated user identity on the server side using cryptographically signed JWT tokens, session middleware, or OIDC/OAuth2 claims, injecting the verified role into the request context.

### Example Request with Access Control:
```json
POST /ask
{
  "question": "What is the grading criteria for CS101?",
  "role": "student",
  "top_k": 10,
  "top_n": 3
}
```

### CLI Inspection with Role Simulation:
```bash
python -m app.cli.search "CS101 Final Exam Solution Key Question 1 answer" --role student
python -m app.cli.search "CS101 Final Exam Solution Key Question 1 answer" --role faculty
python -m app.cli.search "Executive compensation and Dean salary" --role admin
```

### Measured Adversarial Security Audit
An adversarial test suite evaluates 22 distinct attack vectors against synthetic restricted documents (`student_syllabus.pdf`, `faculty_exam_key.pdf`, `admin_salary_records.pdf`, `admin_disciplinary_cases.pdf`):
- Direct confidential inquiries (salaries, exam answer keys)
- Rephrasing and semantic evasion
- System prompt overrides and jailbreak directives
- Roleplay and persona hijacking
- Hypothetical scenario prompts
- Markdown table exfiltration
- Developer debug mode overrides
- Document enumeration discovery
- False identity claims in question text
- Delimiter manipulation and prompt injection
- Multilingual translation evasion
- Base64 encoding requests
- SQL injection payloads
- Reverse psychology and typoglycemia obfuscation
- Role escalation attempts (faculty requesting executive administrative files)

**Measured Leak Report**:
```text
==========================================================================================
 RBAC AUDIT SUMMARY: 22/22 Passed
 MEASURED LEAK COUNT: 0 / 22 (Leak Rate: 0.00%)
==========================================================================================
```
Zero restricted passages reached model context, zero restricted filenames appeared in citations, and zero secret tokens were disclosed.

---

## 12. Evaluation Framework

Phase 6 introduces an automated, reproducible evaluation framework (`eval/run_eval.py`) to benchmark the system across 5 configurations on a verified golden dataset (`eval/golden.jsonl`).

### Golden Dataset Schema (`eval/golden.jsonl`)
Each line in `eval/golden.jsonl` defines a verified evaluation record:
```json
{
  "id": "Q-001",
  "question": "What is the corporate architecture and mission?",
  "role": "student",
  "expected_answer": "The system establishes a modular architecture...",
  "expected_sources": [
    {"file": "valid_doc.pdf", "page": 1}
  ],
  "should_abstain": false,
  "is_version_conflict": false,
  "superseded_sources": [],
  "restricted_for_roles": [],
  "notes": "Verified against raw_pdfs/valid_doc.pdf page 1"
}
```

### 5 Benchmarked System Configurations
Every configuration strictly enforces role-based SQL access filtering (`role=q.role`):
1. `vector_only`: Dense cosine search only ($k=5$).
2. `keyword_only`: Sparse PostgreSQL tsvector search only ($k=5$).
3. `hybrid`: Dense vector ($k=20$) + Sparse keyword ($k=20$) fused via RRF ($k_{rrf}=60$), top 5 fused candidates.
4. `hybrid_plus_reranking`: Vector ($k=20$) + Keyword ($k=20$) + RRF + Cross-Encoder reranking ($top\_n=5$), version-awareness disabled.
5. `hybrid_plus_reranking_plus_version_awareness`: Full production pipeline: Vector + Keyword + RRF + Cross-Encoder + Version Lineage Graph & Conflict Detection + RBAC.

### Evaluated Metrics
- **Retrieval Hit Rate@5**: Proportion of answerable queries where an expected `(file, page)` appears in top 5 candidates.
- **Mean Reciprocal Rank (MRR)**: Average reciprocal rank ($1 / \text{rank}$) of the first matching expected source.
- **RAGAS Faithfulness & Relevance**: Measured where external judge LLM and `ragas` package are available (explicitly recorded as `N/A*` when unavailable, never fabricated as `0.00`).
- **Unsupported Answers Rate**: Proportion of non-abstained answers lacking citations or citing hallucinated brackets `[N]`.
- **Stale-Policy Errors Rate**: Proportion of version queries citing superseded documents as current or failing to report `has_policy_conflict`.
- **Unauthorized Information Leaks Rate**: Proportion of queries leaking restricted context or files (strictly $0.00\%$).
- **Correct Abstention Rate**: Proportion of unanswerable queries (`should_abstain=True`) correctly abstained.

### Failure Classification Taxonomy
Failures are automatically diagnosed and categorized:
- `retrieval_miss`: Expected source was not present anywhere in candidate pool.
- `ranking_miss`: Expected source was in candidate pool, but ranked outside top 5.
- `generation_error`: Model hallucinated citations or ungrounded claims.
- `version_error`: Model cited superseded policy as active or missed policy conflict.
- `access_control_failure`: Model context or citations disclosed restricted information.
- `abstention_error`: Failed to abstain on unanswerable query, or falsely abstained on answerable query.

### Running the Evaluation CLI
```bash
python -m eval.run_eval \
  --golden-path eval/golden.jsonl \
  --output-dir eval/results \
  --configs all \
  --top-k 20 \
  --top-n 5 \
  --abstention-threshold 0.35
```
Results are saved to `eval/results/eval_results_<timestamp>.json` and formatted as a Markdown comparison table in `eval/results/eval_report_<timestamp>.md`.

---

## 13. Streamlit User Interface

Phase 7 implements a web-based user interface (`ui/app.py`) for querying college policy documents, inspecting citations, reviewing policy conflicts, and monitoring evaluation benchmarks.

### Architecture Invariant
The UI communicates strictly with the FastAPI backend (`POST /ask`) via HTTP (`ui/client.py`). It **never** duplicates retrieval, chunking, database, or LLM logic in Streamlit.

### Core Features
1. **Interactive Policy Assistant**:
   - Natural language question input via `st.chat_input`.
   - Conversational message history stored in `st.session_state`.
   - Grounded answers displaying bracketed citation indicators `[1]`, `[2]`.
2. **Verified Citations Panel**:
   - Expandable citations accordion displaying evidence index, source filename, 1-based page number, and supporting excerpt snippet.
3. **Policy Version Conflict Warning**:
   - Prominently displays an alert when `has_policy_conflict == True`, showing active and superseded document titles, effective dates, and conflict explanations.
4. **Abstention & Not-Found State**:
   - Informative status card when `abstained == True`, confirming that the system found insufficient authorized evidence and abstained to prevent hallucinations.
5. **Role-Filtered Diagnostics Panel**:
   - Disabled by default; when toggled in the sidebar, displays vector/keyword/fused/reranked candidate counts and millisecond timing breakdown. Never reveals unauthorized document metadata.
6. **Evaluation Benchmarks Tab**:
   - Automatically discovers and displays real evaluation reports from `eval/results/`, presenting the multi-configuration comparison table and failure taxonomy.
7. **Institutional Decision Disclaimer**:
   - Prominently warns users that responses are synthesized from available documents and do not constitute official or legally binding institutional decisions.
8. **Role Selector Security Demarcation**:
   - Clearly documents that the client-side role selector (`student`, `faculty`, `admin`) is a simulation/evaluation interface, and that production requires server-side cryptographically authenticated identity.

### Running the Streamlit App
Ensure the FastAPI backend is running first:
```bash
# Terminal 1: Start FastAPI backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then start the Streamlit UI:
```bash
# Terminal 2: Start Streamlit interface
streamlit run ui/app.py --server.port 8501 --server.address 127.0.0.1
```
Open `http://127.0.0.1:8501` in your browser.

### Running UI Automated Tests
```bash
pytest tests/test_ui.py -v
```
