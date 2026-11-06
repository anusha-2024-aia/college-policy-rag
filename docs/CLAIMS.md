# LexisPolicy AI — Verified Claims Ledger

This ledger documents every quantitative claim, benchmark metric, test count, and security invariant referenced on the project's **README**, documentation, or developer resumes.

> [!IMPORTANT]
> **Strict Claims Invariant**: Every claim in this ledger is tied to an automated, deterministic CLI command that reproduces the result from a clean terminal. Any claim without a working reproducing command has been removed.

---

## 1. Automated Test Suite Claims

| Metric Claimed | Status | Reproducing CLI Command | Last Verified Date |
| :--- | :---: | :--- | :---: |
| **350 automated tests passing (100%)**, 2 skipped (PostgreSQL socket drills) | Verified | `.venv\Scripts\python.exe -m pytest -q` | 2026-11-06 |
| **14 Phase 7 change intelligence & evidence tests passing** | Verified | `.venv\Scripts\python.exe -m pytest tests/test_policy_change_intelligence.py -v` | 2026-11-06 |
| **8 Phase 6 adversarial security suite tests passing** | Verified | `.venv\Scripts\python.exe -m pytest tests/test_phase6_suite.py -v` | 2026-11-06 |
| **12 Phase 9 demonstration showcase tests passing** | Verified | `.venv\Scripts\python.exe -m pytest tests/test_demo_and_ci.py -v` | 2026-11-06 |

---

## 2. Security & Defence-in-Depth Claims

| Metric Claimed | Result | Reproducing CLI Command | Last Verified Date |
| :--- | :---: | :--- | :---: |
| **0 leaks across 60 adversarial evaluations** (30 student + 30 faculty queries across 30 prompt injection attack vectors) | `0 / 60 (0.00% leak rate)` | `.venv\Scripts\python.exe -m eval.run_phase6_tests` | 2026-11-06 |
| **Negative Control Leak Rate**: Disabling L1-L4 security produces 16 confidential leaks out of 30 queries | `16 / 30 (53.33% leak rate)` | `.venv\Scripts\python.exe -m eval.run_phase6_tests` | 2026-11-06 |
| **Token Tampering & Alg=None Defense**: 100% rejection across 5 JWT attack vectors (tampered, expired, alg=none, wrong audience, empty) | `5 / 5 passed (100%)` | `.venv\Scripts\python.exe -m pytest tests/test_route_security.py` | 2026-11-06 |
| **Route Sweep Security**: 0 confidential leaks across 20 sensitive endpoints under student role | `0 leaks (20 endpoints)` | `.venv\Scripts\python.exe -m pytest tests/test_route_sweep.py` | 2026-11-06 |
| **Role-Scoped Cache Isolation**: Zero cross-role cache contamination between admin query and subsequent student query | `Isolated (True)` | `.venv\Scripts\python.exe -m pytest tests/test_phase6_suite.py -k "test_role_scoped_cache_isolation"` | 2026-11-06 |
| **Authorized Access (R11-R15)**: Authorized admin/faculty users successfully answer confidential queries with verified citations | `5 / 5 passed (100%)` | `.venv\Scripts\python.exe -m pytest tests/test_phase6_suite.py -k "test_golden_authorized_access_r11_to_r15"` | 2026-11-06 |

---

## 3. Policy Version Intelligence & Change Detection Claims

| Metric Claimed | Invariant Result | Reproducing CLI Command | Last Verified Date |
| :--- | :---: | :--- | :---: |
| **Unchanged Clause False-Flag Rate**: 0 false conflict flags across all 5 unchanged clause questions in `eval/golden_extended.jsonl` | `0.00% (0 / 5)` | `.venv\Scripts\python.exe -m pytest tests/test_policy_change_intelligence.py -k "test_extended_unchanged_clause_questions_zero_false_flags"` | 2026-11-06 |
| **Exam Hall Reporting Time Invariant**: Query *"how early must I report to the exam hall"* produces 0 conflict flags and 0 change cards | `has_policy_conflict == False, cards == 0` | `.venv\Scripts\python.exe -m pytest tests/test_policy_change_intelligence.py -k "test_exam_hall_reporting_time_produces_no_conflict"` | 2026-11-06 |
| **Attendance Policy Diff Invariant**: Attendance requirement changed 80% $\rightarrow$ 75%, fee Rs. 500 $\rightarrow$ Rs. 300, floor 70% $\rightarrow$ 65%, window 3 days $\rightarrow$ 5 days | `All 4 metrics matched` | `.venv\Scripts\python.exe -m pytest tests/test_policy_change_intelligence.py -k "test_attendance_lineage_diff"` | 2026-11-06 |
| **Hostel Rules Diff Invariant**: Curfew 9:30 PM $\rightarrow$ 10:30 PM, visitors 6:00 PM $\rightarrow$ 7:00 PM, added late-pass clause | `All 3 deltas matched` | `.venv\Scripts\python.exe -m pytest tests/test_policy_change_intelligence.py -k "test_hostel_lineage_diff"` | 2026-11-06 |
| **Exam Rules Partial Amendment Invariant**: Only Clauses 4.2 and 6.1 changed; all other clauses classified as unchanged | `amended == {4.2, 6.1}, unchanged >= 10` | `.venv\Scripts\python.exe -m pytest tests/test_policy_change_intelligence.py -k "test_examination_rules_partial_amendment_diff"` | 2026-11-06 |
| **Strict Verbatim Evidence Verification**: Fabricated citation dropped; authentic verbatim citation passes; invalid citations trigger clean abstention | `Verified (True)` | `.venv\Scripts\python.exe -m pytest tests/test_policy_change_intelligence.py -k "TestEvidenceVerificationAndAnswerContract"` | 2026-11-06 |

---

## 4. Multi-Configuration Benchmark Claims (100 Golden Questions)

Source artifact: [`eval/results/real/eval_results_20261101_111402.json`](file:///c:/Users/Lenovo/OneDrive/Desktop/Document_RAG_Project/eval/results/real/eval_results_20261101_111402.json)  
Dataset: `eval/golden.jsonl` (100 verified questions, SHA256: `d22559b1...`)  
Reproducing CLI Command: `python -m eval.run_eval --configs all`

| Configuration | Hit Rate@1 | Hit Rate@3 | Hit Rate@5 | MRR | Missing Conflict % | Info Leak Rate % | Mean Latency | p95 Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `vector_only` | 77.33% | 97.33% | 98.67% | 0.8678 | 100.00% | 0.00% | 22.27 ms | 37.98 ms |
| `keyword_only` (BM25) | 69.33% | 97.33% | 100.00% | 0.8349 | 100.00% | 0.00% | 8.85 ms | 11.10 ms |
| `hybrid` (RRF $k=60$) | 78.67% | 98.67% | 100.00% | 0.8856 | 100.00% | 0.00% | 27.34 ms | 31.51 ms |
| `hybrid_plus_reranking` | 82.67% | 97.33% | 100.00% | 0.9067 | 100.00% | 0.00% | 111.00 ms | 166.26 ms |
| **`hybrid_plus_reranking_plus_version_awareness` (Production)** | **86.67%** | **96.00%** | **97.33%** | **0.9144** | **8.33%** | **0.00%** | **128.72 ms** | **185.55 ms** |
| `security_ablated` (Ablation without RBAC) | 78.67% | 94.67% | 97.33% | 0.8733 | 100.00% | **43.00%** | 133.74 ms | 200.49 ms |

---

## 5. CI Smoke Evaluation Claims (20 Questions)

Source script: [`eval/smoke.py`](file:///c:/Users/Lenovo/OneDrive/Desktop/Document_RAG_Project/eval/smoke.py)  
Reproducing CLI Command: `.venv\Scripts\python.exe -m eval.smoke`  
Last Verified Date: 2026-11-06

| Metric | Measured Value | Acceptance Threshold | Result |
| :--- | :---: | :---: | :---: |
| **Hit Rate@5** | `1.0000 (100%)` | $\ge 0.90$ | PASSED |
| **Mean Reciprocal Rank (MRR)** | `0.9500` | $\ge 0.80$ | PASSED |
| **Information Leak Rate** | `0.0000 (0.00%)` | $== 0.00$ | PASSED |
| **Citation Grounding Rate** | `1.0000 (20/20)` | $== 1.00$ | PASSED |
| **Correct Abstention Rate** | `1.0000 (100%)` | $== 1.00$ | PASSED |
| **Average Query Latency** | `57.80 ms` | $< 500 \text{ ms}$ | PASSED |

---

## 6. Corpus & Chance Baseline Disclosures

To prevent misleading claims regarding small-corpus retrieval performance:

- **Corpus Size**: 16 documents, 51 chunks.
- **Chance Baseline Recall@5**: $5 / 51 = 9.80\%$.
- **Disclosure**: High Hit@5 rates are substantially easier to achieve on a 51-chunk corpus than at web scale. The true differentiator of LexisPolicy AI is **not high recall on a small corpus**, but **version DAG contradiction resolution** and **pre-retrieval 4-layer security isolation**.
