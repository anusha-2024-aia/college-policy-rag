"""Unified evaluation benchmark runner for Document RAG Project (Phase 1).

Executes across 5 configurations:
1. vector_only
2. keyword_only
3. hybrid (RRF)
4. hybrid_plus_reranking
5. hybrid_plus_reranking_plus_version_awareness

Records:
- embedding model, reranker model, llm model
- is_mock dictionary for each component
- corpus size (documents, chunks) & chance baseline for Recall@5
- dataset sha256, git commit, seed, timestamp
- Routing: real results to eval/results/real/, mock results to eval/results/mock/.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("APP_ENV", "test")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings
from app.core.database import Base, SessionLocal, get_test_session
from app.models.document import Document
from app.models.chunk import Chunk
from app.models.chunk_semantic import ChunkSemantic
from app.models.index_metadata import EmbeddingIndexMetadata
from app.services.embedding import (
    EmbeddingProvider,
    MockEmbeddingService,
    get_embedding_provider,
)
from app.services.embedding_onnx import ONNXEmbeddingService
from app.services.reranker import (
    BaseRerankerService,
    FlashRankRerankerService,
    MockRerankerService,
)
from app.services.llm import (
    BaseLLMService,
    GeminiLLMService,
    MockLLMService,
    OpenAILLMService,
)
from app.services.retrieval import HybridRetrievalService, ScoredChunk
from app.services.qa import QAService
from app.schemas.qa import AskRequest, PassageEvidence
from eval.schemas import (
    CandidateItem,
    CitationItem,
    ExpectedSource,
    GoldenQuestion,
    QuestionEvalResult,
)
from eval.metrics import (
    calculate_hit_at_k,
    calculate_reciprocal_rank,
    normalize_filename,
)
from app.cli.reindex import reindex_corpus

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eval.run_all")

FIVE_CONFIGURATIONS = [
    "vector_only",
    "keyword_only",
    "hybrid",
    "hybrid_plus_reranking",
    "hybrid_plus_reranking_plus_version_awareness",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified evaluation benchmark runner supporting real vs mock modes."
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["real", "mock"],
        default="real",
        help="Evaluation execution mode: 'real' uses real ONNX MiniLM and FlashRank; 'mock' uses synthetic mocks.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42).",
    )
    parser.add_argument(
        "--llm",
        type=str,
        choices=["none", "real", "mock"],
        default="none",
        help="LLM generation mode: 'none' (retrieval-only evaluation), 'real' (API key required), or 'mock'.",
    )
    parser.add_argument(
        "--golden-path",
        type=str,
        default="eval/golden.jsonl",
        help="Path to verified golden JSONL dataset (default: eval/golden.jsonl).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="eval/results",
        help="Base results directory (default: eval/results).",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Optional database URL override.",
    )
    return parser.parse_args()


def get_git_commit() -> str:
    """Retrieve current Git commit SHA."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_golden_questions(path: Path) -> list[GoldenQuestion]:
    """Load verified golden dataset questions."""
    questions: list[GoldenQuestion] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                questions.append(GoldenQuestion.model_validate_json(stripped))
    return questions


def setup_database_session(db_url: Optional[str] = None) -> Session:
    """Get database session with fallback to offline SQLite."""
    if db_url:
        custom_engine = create_engine(db_url)
        Base.metadata.create_all(bind=custom_engine)
        CustomSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=custom_engine)
        return CustomSessionLocal()

    if settings.APP_ENV == "test":
        return get_test_session()

    try:
        session = SessionLocal()
        session.execute(text("SELECT 1"))
        return session
    except Exception:
        logger.warning("Primary database unreachable; connecting to offline SQLite 'data/test_kvit.db'...")
        return get_test_session()


def run_evaluation(
    mode: str = "real",
    seed: int = 42,
    llm_mode: str = "none",
    golden_path_str: str = "eval/golden.jsonl",
    output_dir_str: str = "eval/results",
    db_url: Optional[str] = None,
) -> dict[str, Any]:
    """Execute complete 5-configuration evaluation."""
    # Seed RNG
    random.seed(seed)
    np.random.seed(seed)

    golden_path = Path(golden_path_str)
    if not golden_path.exists():
        raise FileNotFoundError(f"Golden dataset not found at {golden_path}")

    dataset_sha256 = compute_file_sha256(golden_path)
    git_commit = get_git_commit()
    timestamp_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    iso_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    db = setup_database_session(db_url)
    doc_count = db.query(Document).count()
    chunk_count = db.query(Chunk).count()

    chance_baseline_recall_5 = round(min(1.0, 5.0 / max(1, chunk_count)), 4)
    corpus_warning = None
    if chunk_count < 150:
        corpus_warning = (
            f"Corpus contains only {chunk_count} chunks (< 150). "
            f"The chance baseline for Recall@5 is {chance_baseline_recall_5:.2%}. "
            f"High recall is substantially easier to achieve at this corpus size."
        )
        print(f"\n[CORPUS HONESTY WARNING] {corpus_warning}\n")

    # Resolve components based on mode
    if mode == "real":
        # 1. Real local ONNX MiniLM
        logger.info("Initializing Real ONNX MiniLM embedder (all-MiniLM-L6-v2, 384d)...")
        embedding_provider: EmbeddingProvider = ONNXEmbeddingService()

        # Ensure database is indexed with all-MiniLM-L6-v2
        meta = db.query(EmbeddingIndexMetadata).filter_by(id="default").first()
        sem_count = db.query(ChunkSemantic).filter_by(model_name="all-MiniLM-L6-v2").count()
        if not meta or meta.model_id != "all-MiniLM-L6-v2" or sem_count < chunk_count:
            logger.info("Database index does not match 'all-MiniLM-L6-v2'; executing automatic reindexing...")
            reindex_corpus(model_id="all-MiniLM-L6-v2", db=db, force=True)

        # 2. Real FlashRank cross-encoder
        logger.info("Initializing Real FlashRank cross-encoder (ms-marco-TinyBERT-L-2-v2)...")
        reranker_service: BaseRerankerService = FlashRankRerankerService(model="ms-marco-TinyBERT-L-2-v2")

        # 3. LLM
        llm_service: Optional[BaseLLMService] = None
        if llm_mode == "real":
            key = settings.GEMINI_API_KEY or settings.LLM_API_KEY
            if not key or "your_" in key.lower():
                raise ValueError("Real LLM mode requested, but no valid GEMINI_API_KEY or LLM_API_KEY is configured.")
            llm_service = GeminiLLMService(api_key=key, model="gemini-2.5-flash")
        elif llm_mode == "mock":
            llm_service = MockLLMService()

        is_mock = {
            "embedding": False,
            "reranker": False,
            "llm": (llm_mode == "mock"),
            "any": (llm_mode == "mock"),
        }
    else:  # mock mode
        logger.info("Initializing Mock components for synthetic evaluation...")
        embedding_provider = MockEmbeddingService(dimension=1536, model_id="mock-sha256")
        reranker_service = MockRerankerService()
        llm_service = MockLLMService()
        is_mock = {
            "embedding": True,
            "reranker": True,
            "llm": True,
            "any": True,
        }

    # Initialize retrieval & QA services
    retrieval_service = HybridRetrievalService(
        db_session=db,
        embedding_service=embedding_provider,
        reranker_service=reranker_service,
        semantic_retrieval_enabled=(embedding_provider.dim == 384),
        semantic_embedding_service=embedding_provider if embedding_provider.dim == 384 else None,
    )
    qa_service = QAService(
        retrieval_service=retrieval_service,
        llm_service=llm_service or MockLLMService(),
    )

    questions = load_golden_questions(golden_path)
    logger.info("Loaded %d golden questions from '%s'.", len(questions), golden_path)

    config_results: dict[str, dict[str, Any]] = {}

    for cfg_name in FIVE_CONFIGURATIONS:
        logger.info(">>> Evaluating configuration: %s across %d questions...", cfg_name, len(questions))
        hit_1_count = 0
        hit_3_count = 0
        hit_5_count = 0
        rr_sum = 0.0
        retrieval_query_count = 0
        stale_error_count = 0
        stale_eligible_count = 0
        missing_conflict_count = 0
        leak_count = 0
        latencies: list[float] = []

        for q in questions:
            t0 = time.perf_counter()
            candidates: list[CandidateItem] = []
            citations: list[CitationItem] = []
            has_conflict = False

            try:
                if cfg_name == "vector_only":
                    scored = retrieval_service.vector_search(query=q.question, k=5, role=q.role)
                    candidates = [
                        CandidateItem(
                            chunk_id=str(s.chunk_id),
                            file_name=s.file_name,
                            page_number=s.page_number,
                            rank=s.rank,
                            score=s.score,
                            text=s.text,
                        )
                        for s in scored
                    ]
                elif cfg_name == "keyword_only":
                    scored = retrieval_service.keyword_search(query=q.question, k=5, role=q.role)
                    candidates = [
                        CandidateItem(
                            chunk_id=str(s.chunk_id),
                            file_name=s.file_name,
                            page_number=s.page_number,
                            rank=s.rank,
                            score=s.score,
                            text=s.text,
                        )
                        for s in scored
                    ]
                elif cfg_name == "hybrid":
                    vec_res = retrieval_service.vector_search(query=q.question, k=20, role=q.role)
                    kw_res = retrieval_service.keyword_search(query=q.question, k=20, role=q.role)
                    fused = retrieval_service.rrf_fuse(vec_res, kw_res, k_rrf=retrieval_service.rrf_k)
                    candidates = [
                        CandidateItem(
                            chunk_id=str(f.chunk_id),
                            file_name=f.file_name,
                            page_number=f.page_number,
                            rank=f.fused_rank,
                            score=f.rrf_score,
                            text=f.text,
                        )
                        for f in fused[:5]
                    ]
                elif cfg_name == "hybrid_plus_reranking":
                    resp_ret = retrieval_service.retrieve(
                        query=q.question,
                        role=q.role,
                        top_k=20,
                        top_n=5,
                        lineage_expansion=False,
                    )
                    candidates = [
                        CandidateItem(
                            chunk_id=str(p.chunk_id),
                            file_name=p.file_name,
                            page_number=p.page_number,
                            rank=p.final_rank,
                            score=p.rerank_score,
                            text=p.text,
                        )
                        for p in resp_ret.reranked_results
                    ]
                elif cfg_name == "hybrid_plus_reranking_plus_version_awareness":
                    as_of_val = getattr(q, "as_of", getattr(q, "as_of_date", None))
                    req = AskRequest(
                        question=q.question,
                        role=q.role,
                        as_of=as_of_val,
                        version_aware=True,
                        top_k=20,
                        top_n=5,
                    )
                    resp = qa_service.answer(req, role=q.role)
                    has_conflict = resp.has_policy_conflict
                    candidates = [
                        CandidateItem(
                            chunk_id=str(p.chunk_id),
                            file_name=p.file_name,
                            page_number=p.page_number,
                            rank=p.index,
                            score=p.score,
                            text=p.text,
                        )
                        for p in resp.passages
                    ]
                    citations = [
                        CitationItem(
                            index=c.index,
                            file_name=c.file_name,
                            page_number=c.page_number,
                            snippet=c.snippet,
                        )
                        for c in resp.citations
                    ]
            except Exception as exc:
                logger.warning("Error evaluating question '%s' on '%s': %s", q.id, cfg_name, exc)

            elapsed_ms = (time.perf_counter() - t0) * 1000
            latencies.append(elapsed_ms)

            # Evaluate retrieval metrics (only for queries that have expected sources)
            if q.expected_sources:
                retrieval_query_count += 1
                if calculate_hit_at_k(candidates, q.expected_sources, k=1):
                    hit_1_count += 1
                if calculate_hit_at_k(candidates, q.expected_sources, k=3):
                    hit_3_count += 1
                if calculate_hit_at_k(candidates, q.expected_sources, k=5):
                    hit_5_count += 1
                rr_sum += calculate_reciprocal_rank(candidates, q.expected_sources)

            # Evaluate stale policy error
            if q.is_version_conflict and q.superseded_sources and q.expected_sources:
                stale_eligible_count += 1
                retrieved_files = {normalize_filename(c.file_name) for c in candidates[:3]}
                expected_active = {normalize_filename(s.file_name) for s in q.expected_sources}
                superseded_files = {normalize_filename(s.file_name) for s in q.superseded_sources}
                # Stale error if cited/retrieved superseded while missing active policy
                if (retrieved_files & superseded_files) and not (retrieved_files & expected_active):
                    stale_error_count += 1

            # Evaluate missing conflict
            if q.is_version_conflict:
                if cfg_name == "hybrid_plus_reranking_plus_version_awareness":
                    if not has_conflict:
                        missing_conflict_count += 1
                else:
                    # Baseline configs without version awareness lack conflict detector
                    missing_conflict_count += 1

            # Evaluate leak rate
            if q.forbidden_canaries or q.role == "student":
                cand_files = {normalize_filename(c.file_name) for c in candidates}
                restricted_files = {
                    "admin_salary_bands_and_budget_2025.pdf",
                    "faculty_service_rules_2025.pdf",
                    "question_paper_confidentiality_protocol_2025.pdf",
                }
                if q.role == "student" and (cand_files & restricted_files):
                    leak_count += 1

        total_ret = max(1, retrieval_query_count)
        total_stale = max(1, stale_eligible_count)
        conflict_queries = sum(1 for q in questions if q.is_version_conflict)

        config_results[cfg_name] = {
            "hit_rate_at_1": round(hit_1_count / total_ret, 4),
            "hit_rate_at_3": round(hit_3_count / total_ret, 4),
            "hit_rate_at_5": round(hit_5_count / total_ret, 4),
            "mean_reciprocal_rank": round(rr_sum / total_ret, 4),
            "stale_policy_error_rate": round(stale_error_count / total_stale, 4),
            "missing_conflict_rate": round(missing_conflict_count / max(1, conflict_queries), 4),
            "information_leak_rate": round(leak_count / len(questions), 4),
            "average_latency_ms": round(float(np.mean(latencies)), 2),
            "p95_latency_ms": round(float(np.percentile(latencies, 95)), 2),
            "evaluated_queries": len(questions),
            "retrieval_queries": retrieval_query_count,
        }

    # Prepare master result record
    master_result = {
        "metadata": {
            "timestamp": iso_timestamp,
            "mode": mode,
            "seed": seed,
            "git_commit": git_commit,
            "dataset_sha256": dataset_sha256,
            "dataset_size": len(questions),
            "corpus_size": {
                "documents": doc_count,
                "chunks": chunk_count,
            },
            "chance_baseline_recall_at_5": chance_baseline_recall_5,
            "corpus_warning": corpus_warning,
            "embedding_model": embedding_provider.model_id,
            "embedding_dim": embedding_provider.dim,
            "reranker_model": reranker_service.model_name,
            "llm_model": llm_service.model_name if llm_service else "none (retrieval-only)",
            "is_mock": is_mock,
        },
        "configs": config_results,
    }

    # Determine output directory
    target_sub = "mock" if is_mock["any"] else "real"
    base_out = Path(output_dir_str) / target_sub
    base_out.mkdir(parents=True, exist_ok=True)

    json_path = base_out / f"eval_results_{timestamp_str}.json"
    md_path = base_out / f"eval_report_{timestamp_str}.md"

    # Write JSON results
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(master_result, f, indent=2)

    # Format Markdown Report
    md_content = generate_markdown_report(master_result)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    # If real, also update the canonical eval/results/real/REPORT.md
    if not is_mock["any"]:
        canonical_report = base_out / "REPORT.md"
        with open(canonical_report, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info("Updated canonical report at '%s'.", canonical_report)

    logger.info("Saved evaluation JSON to '%s'.", json_path)
    logger.info("Saved evaluation Markdown report to '%s'.", md_path)

    print("\n" + "=" * 90)
    print(f" BENCHMARK COMPLETE: Mode={mode.upper()} | Output: {base_out}")
    print("=" * 90)
    print(
        f" Embedding Model: {embedding_provider.model_id} (dim={embedding_provider.dim}, is_mock={is_mock['embedding']})\n"
        f" Reranker Model:  {reranker_service.model_name} (is_mock={is_mock['reranker']})\n"
        f" LLM Model:       {master_result['metadata']['llm_model']} (is_mock={is_mock['llm']})\n"
        f" Corpus Size:     {doc_count} documents, {chunk_count} chunks (Chance Baseline Recall@5: {chance_baseline_recall_5:.2%})"
    )
    if corpus_warning:
        print(f" Warning:         {corpus_warning}")
    print("-" * 90)
    print(
        f"{'Configuration':<45} | {'Hit@5':<8} | {'MRR':<8} | {'Stale Err':<10} | {'Missing Conf':<12} | {'Leaks':<6}"
    )
    print("-" * 90)
    for c_name, c_data in config_results.items():
        print(
            f"{c_name:<45} | {c_data['hit_rate_at_5']:<8.4f} | {c_data['mean_reciprocal_rank']:<8.4f} | "
            f"{c_data['stale_policy_error_rate'] * 100:<9.1f}% | {c_data['missing_conflict_rate'] * 100:<11.1f}% | "
            f"{c_data['information_leak_rate'] * 100:<5.1f}%"
        )
    print("=" * 90 + "\n")

    return master_result


def generate_markdown_report(result: dict[str, Any]) -> str:
    """Generate professional GitHub Markdown comparison report."""
    meta = result["metadata"]
    configs = result["configs"]

    lines = [
        f"# Evaluation Benchmark Report: {meta['mode'].upper()} Mode\n",
        f"- **Timestamp**: `{meta['timestamp']}`",
        f"- **Mode**: `{meta['mode'].upper()}`",
        f"- **Embedding Model**: `{meta['embedding_model']}` (dimension `{meta['embedding_dim']}`, is_mock: `{meta['is_mock']['embedding']}`)",
        f"- **Reranker Model**: `{meta['reranker_model']}` (is_mock: `{meta['is_mock']['reranker']}`)",
        f"- **LLM Model**: `{meta['llm_model']}` (is_mock: `{meta['is_mock']['llm']}`)",
        f"- **Dataset Size**: `{meta['dataset_size']}` questions (SHA-256: `{meta['dataset_sha256'][:16]}...`)",
        f"- **Corpus Size**: `{meta['corpus_size']['documents']}` documents, `{meta['corpus_size']['chunks']}` chunks",
        f"- **Chance Baseline Recall@5**: `{meta['chance_baseline_recall_at_5']:.2%}`",
        f"- **Git Commit**: `{meta['git_commit']}`",
        f"- **Random Seed**: `{meta['seed']}`\n",
    ]

    if meta.get("corpus_warning"):
        lines.append(f"> [!WARNING]\n> **Corpus Size Warning**: {meta['corpus_warning']}\n")

    lines.append("## Five-Configuration Comparison\n")
    lines.append(
        "| Configuration | Hit@1 | Hit@3 | Hit@5 | MRR | Stale Policy Err % | Missing Conflict % | Leak Rate % | Avg Latency |"
    )
    lines.append(
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
    )

    for cfg_name, metrics in configs.items():
        stale_pct = f"{metrics['stale_policy_error_rate'] * 100:.1f}%"
        conf_pct = f"{metrics['missing_conflict_rate'] * 100:.1f}%"
        leak_pct = f"{metrics['information_leak_rate'] * 100:.1f}%"
        lat = f"{metrics['average_latency_ms']:.1f}ms"
        lines.append(
            f"| `{cfg_name}` | {metrics['hit_rate_at_1']:.4f} | {metrics['hit_rate_at_3']:.4f} | "
            f"**{metrics['hit_rate_at_5']:.4f}** | {metrics['mean_reciprocal_rank']:.4f} | "
            f"{stale_pct} | {conf_pct} | {leak_pct} | {lat} |"
        )

    lines.append("\n## Component Integrity Attestation\n")
    lines.append("```json")
    lines.append(json.dumps(meta["is_mock"], indent=2))
    lines.append("```\n")

    return "\n".join(lines)


def main():
    args = parse_args()
    run_evaluation(
        mode=args.mode,
        seed=args.seed,
        llm_mode=args.llm,
        golden_path_str=args.golden_path,
        output_dir_str=args.output_dir,
        db_url=args.db_url,
    )


if __name__ == "__main__":
    main()
