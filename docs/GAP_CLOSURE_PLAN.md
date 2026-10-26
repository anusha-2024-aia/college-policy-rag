# Gap Closure Plan: College Policy RAG (Antigravity prompts)

Save this file as `docs/GAP_CLOSURE_PLAN.md` in your repo. Run one phase at a time.
Each phase is a ready-to-paste prompt. Paste the **Global rules** block first, once per new Antigravity session.

**Order matters:** Phase 0 (audit) tells you what is already done, so the agent does not rebuild it.
Then Phase 1 and 2 are the critical ones: real embeddings, and an auth endpoint that cannot be abused.

| Phase | Closes | Priority |
|---|---|---|
| 0 | Audit: README claims vs real code | Do first |
| 1 | Real embeddings and a trustworthy benchmark | Critical |
| 2 | Authentication and authorization hardening, RLS proof | Critical |
| 3 | Credibility bugs (leaky Library, citation snippets, Evaluations page) | High |
| 4 | Stronger evaluation (more questions, denominators, error analysis) | High |
| 5 | Database reliability (Alembic, upgrade tests, backup) | High |
| 6 | CI, security scanning | Medium |
| 7 | Policy change intelligence (clause-level diff + evidence verification) | Differentiator |
| 8 | Demo, README, claims ledger | Final |

Do not promise yourself a final score. The rating depends on what the code actually does and what you can defend in an interview.

---

## Global rules (apply to every phase)

```
GLOBAL RULES FOR THIS REPO (apply to every phase)
1. Work one phase at a time. For each phase: write a plan, WAIT for my approval, implement, run the full test suite, then summarise: changed / not done / assumptions / risks.
2. Never invent metrics. Every number in the README, UI or docs must come from a script in eval/ that I can rerun. Show the command.
3. Never weaken, skip or delete a test to make it pass. If a test is wrong, explain why and wait for my approval.
4. Mocks are allowed ONLY in unit tests. Any result produced with a mock component must be labelled MOCK and kept separate from real results.
5. Ask before adding any dependency or changing the stack. Give a one-line reason and the alternative.
6. Never commit secrets. Secrets come from environment variables. Keep .env.example current.
7. Keep existing behaviour working. Do not rename public endpoints without asking.
8. Before declaring a phase done, run its "Done when" checks and paste the actual command output.
9. If something is ambiguous or you find that a requirement is already implemented, STOP and tell me instead of guessing or rebuilding.
10. Make one git commit per phase with a clear message.
```

---

## Phase 0: Read-only audit (no code changes)

```
/phase-start Phase 0: Read-only audit. Do NOT change any code.

Goal: produce docs/AUDIT.md that compares what the README claims with what the code really does.

Report, with file paths and line references:
1. Components and whether each is REAL or MOCK in the evaluation path and in the live demo path: embeddings (model name, dimension), reranker, LLM, vector store, keyword search.
2. Every HTTP route: method, path, whether it requires authentication, where the caller's role is read from, and whether the role filter is applied (include Library list, document detail, PDF preview, ask, ask/stream, eval, debug, health).
3. The auth flow: how /auth/token (or equivalent) decides the role. Can a client request any role? Is there a user store? How is the JWT secret set? Is there a default secret?
4. Database: SQLite vs PostgreSQL usage, how the schema is created (migrations or create_all), whether RLS is enabled and FORCED, which DB role the app connects as, and whether that role can bypass RLS.
5. Tests: run the full suite, report exact counts (passed / failed / skipped), and which tests run only on SQLite or with mocks.
6. Evaluation: dataset files, number of questions, corpus size (documents and chunks), metrics computed, where results are written, and whether any result file was produced with mock components.
7. Secrets: scan the repo and git history for committed keys or .env files (git ls-files, git log -p -S "API_KEY" for obvious patterns). List findings only, never print secret values.
8. A gap table: each phase of docs/GAP_CLOSURE_PLAN.md marked NOT STARTED / PARTIAL / DONE with evidence.

Done when: docs/AUDIT.md exists, every claim has a file path, and the test counts come from a command you actually ran.
```

---

## Phase 1: Real embeddings and a trustworthy benchmark

```
/phase-start Phase 1: Real embeddings and benchmark validity

Context: the evaluation path may use deterministic mock embeddings or other mocks. A benchmark with mocks does not prove real semantic retrieval. Use docs/AUDIT.md as the starting point.

Tasks:
1. Create an EmbeddingProvider interface with: embed_documents(texts), embed_query(text), model_id, dim, normalized, is_mock.
   Providers: (a) local real model, default all-MiniLM-L6-v2 (384d) via the existing ONNX/sentence-transformers path; (b) optional Gemini embeddings via API key; (c) MockEmbeddings for unit tests only.
2. Store model_id, dim and normalisation with the embeddings (table or metadata). At query time, FAIL LOUDLY if the active query model does not match the index model. Documents and queries must always use the same model.
3. Add: python -m app.cli.reindex --model <id>. It builds the new embeddings and swaps them in atomically (no half-built index). It must be idempotent.
4. The reranker used in evaluation must be the real cross-encoder (FlashRank). Mock rerankers are for unit tests only.
5. Evaluation runner: python -m eval.run_all --mode real|mock --seed 42.
   - Configurations: vector-only, keyword-only, hybrid (RRF), hybrid + rerank, hybrid + rerank + version-aware.
   - Every result file records: embedding model, reranker model, LLM model, an is_mock flag for each component, corpus size (documents, chunks), dataset sha256, git commit, seed, timestamp.
   - If ANY component is mock, write only to eval/results/mock/. Real results go to eval/results/real/. The README and UI read only from eval/results/real/.
   - Retrieval metrics must not need an LLM. Generation metrics run with --llm real|mock and are labelled.
6. Add a test that fails if a file in eval/results/real/ has any is_mock flag set to true.
7. Corpus-size honesty: print the corpus size and the chance baseline for Recall@5 (k / number of chunks). If chunks < 150, the report must show a warning that Recall@5 is easy at this corpus size.
8. Re-ingest with real chunking (about 500 tokens, 80 overlap, clause boundaries respected) if the audit shows one chunk per page.

Done when:
- python -m eval.run_all --mode real --seed 42 produces eval/results/real/<timestamp>.json with every is_mock = false.
- Switching the embedding model without reindexing raises a clear error (add a test).
- A committed report eval/results/real/REPORT.md lists the model names, dataset, configurations and measured results, plus the five-configuration comparison table.

Plan first, wait for approval.
```

---

## Phase 2: Authentication and authorization hardening

```
/phase-start Phase 2: Authentication, authorization and Row-Level Security proof

Context: documentation shows a token endpoint that may accept a role in the request body. If a client can choose its own role, the access-control design is not secure. Verify first (use docs/AUDIT.md), then fix whatever is confirmed.

Tasks:
1. The role must NEVER come from the request body, query string or any client-controlled header. It comes only from the verified JWT claim, which is issued from a server-side user record.
2. Users table: id, username, password_hash (argon2 or bcrypt; ask before adding the dependency), role, is_active. Seed three demo users (student, faculty, admin). Only an admin route can change roles, and every change is audit-logged.
3. DEMO_MODE env flag:
   - DEMO_MODE=false (default): username + password login required.
   - DEMO_MODE=true: the login page shows the demo accounts (public demo credentials for the three seeded users) so recruiters can try each role. Show a visible "demo accounts" label in the UI. There is no passwordless role picker anywhere.
4. JWT: pinned algorithm, short expiry, iss, aud, jti. The secret comes from an env var, and the app refuses to start if it is missing or equals a default value. Rate-limit the login route. Restrict CORS to configured origins.
5. Every route except health and login must depend on get_current_role. Missing token means 401. Add a startup/test check that enumerates app.routes and fails if any other route lacks the dependency.
6. PostgreSQL Row-Level Security (real Postgres, not SQLite):
   - ENABLE and FORCE RLS on documents and chunks (and any table with restricted content).
   - The application connects as a dedicated non-owner role without BYPASSRLS.
   - Each request runs inside a transaction that does SET LOCAL app.current_role from the verified role.
   - If the setting is unset, zero rows are visible.
7. Cache isolation: any cache key includes role and corpus version.

Tests (all must run against a real Postgres, using the docker-compose service):
- A client cannot obtain a faculty or admin token by sending role in the body, query or headers.
- Tokens with alg=none, a tampered role claim, an expired token, a wrong audience, and a missing token are rejected.
- Student, faculty and admin each see exactly the documents allowed by docs/role_permission_matrix.csv.
- Connecting as the app role with no role set returns 0 rows from chunks.
- Cache isolation: admin asks a question, then student asks the same; the student receives no restricted content.
- Negative control: a test-only flag disables the filter layers; the leak suite must then report leaks > 0.

Done when: all of the above pass, and the leak suite prints "leaks: 0 / N" with N reported, and "negative control leaks: M / N" with M > 0.

Plan first, wait for approval.
```

---

## Phase 3: Credibility bugs (verify each, skip those already fixed)

```
/phase-start Phase 3: Credibility bugs. For each item, first check whether it still exists; report FIXED/STILL PRESENT before changing anything.

1. Document Library and every list/detail/preview endpoint must apply the role filter server-side. For hidden documents return only a count ("6 documents hidden for your role"). A student must not see restricted filenames or titles anywhere, including network responses.
2. Remove documents unrelated to the college corpus (for example financial_disclosure_q3.pdf and employee_handbook_v1.pdf) and any extra roles (finance, executive, board, employee, hr). Only student, faculty and admin remain.
3. Library status and lineage come from the manifest: Active, Superseded, Partially amended, plus "superseded by X".
4. Citation snippets show the best-matching sentence, not the page header. Strip repeated header and footer lines at ingestion, then re-ingest.
5. Citation numbers are sequential ([1], [2], [3]). The "governing documents" list contains only documents actually cited.
6. The Evaluations page renders from the JSON results (tables and charts), never from markdown. Remove build-stage wording such as "Stage 5". Show k/n beside every percentage.
7. One source of truth for model names: a config endpoint feeds the dashboard, the System page and the benchmark. If the live demo and the benchmark use different models, show two labelled lines.
8. Rename "System Information" to "How it works": a short pipeline view, three design decisions (hybrid search, role filter first, version-aware answers), tech chips, measured result tiles read from the API, and a limitations section. No "mock", "development" or "stage" wording.

Tests: a student-role sweep over every route asserts no restricted filename, title or canary appears (use eval/canaries.json).

Done when: the sweep test passes and I can confirm items 1-8 visually in the UI at desktop and 375px width.

Plan first, wait for approval.
```

---

## Phase 4: Stronger evaluation

```
/phase-start Phase 4: Evaluation quality

Keep the existing 100-question golden set unchanged (eval/golden.jsonl). Add new material in eval/golden_extended.jsonl.

Tasks:
1. Extended set (never merged automatically):
   - 3 paraphrases for each of 30 questions of different types.
   - 10 more stale-policy traps, 5 "as of date" historical questions, 5 questions on unchanged clauses (to measure false conflict flags), 10 more unanswerable questions.
   Write candidates to eval/candidates/ first. I will review and approve them before they enter golden_extended.jsonl.
2. Metrics, each reported as a percentage AND k/n, with a 95% bootstrap confidence interval where n >= 30:
   Recall@1/3/5, MRR, citation correctness (deterministic: the cited page contains the evidence sentence), answer correctness (deterministic key-fact check; an LLM judge is optional and clearly labelled), correct-abstain rate, stale-answer rate, conflict-detection precision and recall, false-flag rate on unchanged clauses, leak count, latency p50/p95, tokens and estimated cost per query.
3. Ablation matrix: version-aware off/on x lineage expansion off/on x role enforcement on/off (the "off" setting exists only behind a test flag, as a negative control).
4. Failure taxonomy for every wrong answer: retrieval miss, rerank drop, lineage miss, generation error, abstain error. Write eval/results/real/FAILURES.md with question ids, expected vs got, and the cause.
5. Honesty gates: the report must show corpus size and the chance baseline for Recall@5, and a "limitations" section (dataset size, synthetic data, single embedding model).
6. Seeded and reproducible: python -m eval.run_all --mode real --seed 42 reproduces the same numbers.

Done when: eval/results/real/REPORT.md contains the metrics table with k/n, the ablation table, the failure taxonomy and the limitations, all generated by one command.

Plan first, wait for approval.
```

---

## Phase 5: Database reliability

```
/phase-start Phase 5: Database migrations and reliability

Tasks:
1. Adopt Alembic (ask before adding it). The initial migration reproduces the current schema, including pgvector and tsvector indexes, RLS policies and the non-owner app role. Remove create_all from production startup.
2. Migration tests on a real Postgres (docker compose): create a clean DB and upgrade to head; downgrade one step and upgrade again; upgrade from the previous schema revision with sample data present.
3. Ingestion behaviour tests: idempotent re-ingestion (no duplicate rows), replacing a document with a new version (lineage preserved, old chunks marked superseded not deleted), and a failed ingestion rolling back completely.
4. Real-Postgres CI job covers RLS and transaction handling; SQLite remains a dev-only mode and the docs say so.
5. Backup and recovery: scripts/backup.sh and scripts/restore.sh using pg_dump / pg_restore. Add a test or documented drill that restores into an empty database and verifies row counts and a sample query.
6. docs/OPERATIONS.md: environment variables, migration commands, backup and restore steps, health endpoints.

Done when: tests for items 2-3 pass, the restore drill output is pasted in the summary, and OPERATIONS.md exists.

Plan first, wait for approval.
```

---

## Phase 6: CI and security scanning

```
/phase-start Phase 6: GitHub Actions

Create .github/workflows/ci.yml. Ask before adding any new tool.
Jobs:
1. lint: ruff (and a light type check if the project already uses types).
2. test: pytest against a Postgres service that includes pgvector. Fail if any test is skipped for missing database.
3. security: pip-audit (dependencies) and a secret scan (gitleaks). Also fail if .env or any private key file is tracked.
4. eval-smoke: run a 20-question subset in mock mode, labelled MOCK, to catch pipeline breakage. Real benchmarks are NOT run in CI; document that.
5. Add the status badge to the README.

Done when: the workflow runs green on a pull request, and I have pasted the run link or log summary.

Plan first, wait for approval.
```

---

## Phase 7: Policy change intelligence (the differentiator)

```
/phase-start Phase 7: Clause-level change intelligence with evidence verification

Goal: for any lineage (old document, new document or amendment), show exactly what changed, with proof.

Tasks:
1. Clause extraction: parse clause references (for example "Clause 4.2") and section headings into clause records with text, page and effective date.
2. Deterministic diff in code (not by the LLM): match clauses across versions by clause_ref, then by similarity. Classify each as unchanged, changed, added or removed. For changed clauses extract normalised values (numbers, percentages, currency, times) and list old -> new.
3. Partial amendments: an amendment that names specific clauses retires only those clauses. All other clauses of the older document remain current.
4. Endpoint: GET /policies/{lineage_id}/diff?from=<date>&to=<date>, role-filtered like every other route. Return the change cards: topic, old value + source + page, new value + source + page, effective dates, scope.
5. Evidence verification: before an answer is delivered, verify that each cited sentence appears verbatim on the cited page, and that the cited version is in force on the as_of date. If verification fails, drop the citation, and if no valid evidence remains, abstain with a reason.
6. The answer schema (validated with Pydantic) includes: current rule, effective date, previous rule and source, supporting passages, uncertainty note. The LLM only phrases what the code produced.
7. UI: a "Compare versions" view with old value struck through and new value highlighted, plus an "as of" date picker.

Tests (use the KVIT dataset): attendance 80% -> 75%, fee Rs. 500 -> Rs. 300, 70% -> 65% lower bound; hostel: curfew change plus an added late-pass clause; exam rules: only Clauses 4.2 and 6.1 changed, all other clauses unchanged; "how early must I report to the exam hall" must produce no conflict flag.

Done when: the diff endpoint returns exactly the expected change cards for the three lineages, and the false-flag rate on unchanged-clause questions is reported from eval.

Plan first, wait for approval.
```

---

## Phase 8: Demo, README and claims ledger

```
/phase-start Phase 8: Recruiter-ready presentation

Tasks:
1. README rewrite. Top to bottom: one-line value statement; live link; a short demo GIF or screenshots (I will record these; create docs/DEMO_SCRIPT.md with the exact click path: upload policy, ask a question, inspect citations, compare versions, switch roles and see the boundary); "What makes this different"; a Mermaid architecture diagram that shows the role filter BEFORE retrieval and lineage expansion; results tables generated from eval/results/real/; failure log; security model with honest limits; quickstart; limitations; synthetic-data notice.
2. Fix the quickstart: use the real clone URL, verify every command from a clean checkout, and add one command to run everything (docker compose up plus a seed script).
3. Repository metadata: write a one-line description and a list of topics for me to paste into GitHub settings.
4. docs/CLAIMS.md, a claims ledger: every claim I will put on my resume or README (each test count, each metric, "0 leaks across N queries") with the exact command that reproduces it and the date it was last verified. Any claim without a reproducing command is removed.
5. Cold-start handling for the free host: a loading state ("waking the server") and a /health check.
6. docs/INTERVIEW_NOTES.md: a 2-minute walkthrough of the request-to-answer pipeline, plus the 10 hardest questions a reviewer could ask about the design, with honest answers.

Done when: a fresh clone runs with the documented commands, and every number in the README appears in docs/CLAIMS.md with a working command.

Plan first, wait for approval.
```

---

## After each phase (your checklist)

- Run the phase's "Done when" check yourself; do not rely only on the agent's summary.
- Run `pytest` and the leak test again.
- Read the diff of anything touching auth, RLS or the evaluation numbers.
- If something breaks: "Do not guess. Reproduce the error, show the exact command and output, explain the root cause in 3 sentences, propose the smallest fix, wait for my approval."

## Resume rule

Put a number on your resume only if it is in `docs/CLAIMS.md` with a command that reproduces it. Do not claim a zero-leak guarantee; say "0 leaks across N adversarial queries" with the real N.

