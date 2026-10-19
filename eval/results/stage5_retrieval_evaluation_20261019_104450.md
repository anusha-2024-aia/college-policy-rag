# Stage 5 Semantic Retrieval Comparative Evaluation Report (Audited)

- **Timestamp**: 2026-10-19T10:46:14.585647
- **Golden Benchmark**: `eval\kvit_golden.jsonl` (33 institutional policy queries)
- **Corpus**: 20 documents, 40 chunks, 40 semantic rows
- **Execution Mode**: Strictly Offline (ONNX all-MiniLM-L6-v2, FlashRank TinyBERT, Mock LLM)
- **Methodology**: Warm-up queries included, isolated service per config, distinct retrieval vs. pipeline metrics

## 1. Multi-Configuration Comparative Performance Matrix

| Configuration | Scope | Recall@1 | Recall@3 | Recall@5 | MRR | Abstention Acc | Stale Cites | Conflict Det | RBAC Leaks | Avg Latency | p95 Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Baseline (Mock 1536-dim + FTS + RRF + FlashRank)** | Full Pipeline | 82.6% | 100.0% | 100.0% | 0.9058 | 100.0% | 0.0% | 100.0% | 0 | 1158.2 ms | 1353.1 ms |
| **2. Pure MiniLM Semantic (384-dim Vector Alone, Top-5)** | Vector Only | 82.6% | 95.7% | 100.0% | 0.8928 | N/A | N/A | N/A | 0 | 180.7 ms | 315.4 ms |
| **3. Hybrid MiniLM Semantic (384-dim + FTS + RRF + FlashRank)** | Full Pipeline | 82.6% | 100.0% | 100.0% | 0.9058 | 100.0% | 0.0% | 100.0% | 0 | 1114.0 ms | 1372.8 ms |

## 2. Methodological Audit & Key Observations

1. **Isolated Service Instances**: Each configuration is tested on its own isolated `HybridRetrievalService` instance, eliminating shared state or unintentional configuration leakage.
2. **Retrieval-Only vs. Full QA Pipeline**: Pure vector search is evaluated strictly on candidate retrieval (Recall@1/3/5, MRR, latency, RBAC filtering). Pipeline-level governance features (abstention, conflicts, citations) are properly marked as N/A for vector-only search.
3. **Dense Semantic Retrieval**: Pure MiniLM semantic search achieves **100.0% Recall@5** and **0.8928 MRR** at an average latency of **180.7 ms**.
4. **Hybrid Synergy (MiniLM + FTS + RRF + FlashRank)**: Full hybrid retrieval delivers **100.0% Recall@5** and **0.9058 MRR**, with **100.0%** abstention precision and **0.0%** stale citation rate.
5. **Zero Unauthorized Exposure**: All three configurations maintained **zero RBAC leaks** (0 unauthorized chunks exposed).
