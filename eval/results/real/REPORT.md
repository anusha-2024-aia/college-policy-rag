# Evaluation Benchmark Report: REAL Mode

- **Timestamp**: `2026-11-01T01:33:45.391223+00:00`
- **Mode**: `REAL`
- **Embedding Model**: `all-MiniLM-L6-v2` (dimension `384`, is_mock: `False`)
- **Reranker Model**: `ms-marco-TinyBERT-L-2-v2` (is_mock: `False`)
- **LLM Model**: `none (retrieval-only)` (is_mock: `False`)
- **Dataset Size**: `100` questions (SHA-256: `d22559b1b17f2bf1...`)
- **Corpus Size**: `16` documents, `43` chunks
- **Chance Baseline Recall@5**: `11.63%`
- **Git Commit**: `10329c61e02624972175e993f083dbc055aa66d1`
- **Random Seed**: `42`

> [!WARNING]
> **Corpus Size Warning**: Corpus contains only 43 chunks (< 150). The chance baseline for Recall@5 is 11.63%. High recall is substantially easier to achieve at this corpus size.

## Five-Configuration Comparison

| Configuration | Hit@1 | Hit@3 | Hit@5 | MRR | Stale Policy Err % | Missing Conflict % | Leak Rate % | Avg Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `vector_only` | 0.8000 | 0.9867 | **0.9867** | 0.8844 | 0.0% | 100.0% | 0.0% | 21.0ms |
| `keyword_only` | 0.6800 | 0.9867 | **0.9867** | 0.8222 | 0.0% | 100.0% | 0.0% | 8.6ms |
| `hybrid` | 0.8267 | 1.0000 | **1.0000** | 0.9067 | 0.0% | 100.0% | 0.0% | 26.2ms |
| `hybrid_plus_reranking` | 0.7867 | 1.0000 | **1.0000** | 0.8867 | 0.0% | 100.0% | 0.0% | 124.2ms |
| `hybrid_plus_reranking_plus_version_awareness` | 0.8533 | 0.9467 | **0.9600** | 0.9033 | 0.0% | 8.3% | 0.0% | 147.3ms |

## Component Integrity Attestation

```json
{
  "embedding": false,
  "reranker": false,
  "llm": false,
  "any": false
}
```
