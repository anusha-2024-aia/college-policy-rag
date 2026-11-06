"""Smoke evaluation script for continuous integration (Phase 6).

Executes a 20-question evaluation subset in deterministic MOCK mode to rapidly verify
end-to-end pipeline integrity (retrieval, ranking, lineage-aware QA synthesis, RBAC
filtering, and citation grounding) without introducing network flakiness, latency,
or external LLM API costs.

NOTE: Real statistical benchmarks using neural embeddings (all-MiniLM-L6-v2) and
cross-encoders (FlashRank) are intentionally NOT run inside CI. They are executed
offline via:
    python -m eval.run_all --mode real --seed 42
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("APP_ENV", "test")

from eval.schemas import GoldenQuestion
from eval.run_all import setup_database_session
from eval.metrics import check_citation_evidence_grounding
from eval.runner import EvaluationRunner
from app.services.embedding import MockEmbeddingService
from app.services.reranker import MockRerankerService
from app.services.llm import MockLLMService
from app.services.retrieval import HybridRetrievalService
from app.services.qa import QAService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eval.smoke")


def run_smoke_evaluation(
    golden_path_str: str = "eval/golden.jsonl",
    subset_size: int = 20,
    db_url: Optional[str] = None,
) -> bool:
    """Run smoke evaluation across first `subset_size` questions in MOCK mode.

    Returns True if all quality and security invariants pass, False otherwise.
    """
    golden_path = Path(golden_path_str)
    if not golden_path.exists():
        logger.error("Golden dataset not found at '%s'", golden_path)
        return False

    print("=" * 80)
    print(" [MOCK PIPELINE SMOKE EVALUATION: 20 QUESTIONS]")
    print(" Execution Mode: MOCK (Mock Embeddings, Mock Reranker, Mock LLM)")
    print(" NOTE: Real benchmarks with external LLMs and full datasets are NOT run in CI.")
    print("=" * 80)

    # 1. Load subset of questions
    questions: list[GoldenQuestion] = []
    with open(golden_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if idx >= subset_size:
                break
            stripped = line.strip()
            if stripped:
                questions.append(GoldenQuestion.model_validate_json(stripped))

    if len(questions) < subset_size:
        logger.error("Expected at least %d questions, but loaded %d", subset_size, len(questions))
        return False

    logger.info("Loaded %d questions for CI smoke verification.", len(questions))

    # 2. Initialize database session and mock services
    db = setup_database_session(db_url)
    try:
        embedding_service = MockEmbeddingService(dimension=1536, model_id="mock-sha256")
        reranker_service = MockRerankerService()
        llm_service = MockLLMService()

        retrieval_service = HybridRetrievalService(
            db_session=db,
            embedding_service=embedding_service,
            reranker_service=reranker_service,
            semantic_retrieval_enabled=False,
        )
        qa_service = QAService(
            retrieval_service=retrieval_service,
            llm_service=llm_service,
        )

        runner = EvaluationRunner(
            db_session=db,
            retrieval_service=retrieval_service,
            qa_service=qa_service,
        )

        config_name = "hybrid_plus_reranking_plus_version_awareness"
        logger.info("Running smoke evaluation on primary configuration '%s'...", config_name)
        metrics, results = runner.evaluate_configuration(config_name, questions)

        # 3. Verify deterministic citation grounding
        grounded_count = 0
        citation_checked = 0
        for r in results:
            if not r.abstained and r.citations:
                citation_checked += 1
                if check_citation_evidence_grounding(r.citations, db):
                    grounded_count += 1

        citation_grounding_rate = (grounded_count / citation_checked) if citation_checked > 0 else 1.0

        # 4. Display smoke benchmark summary table
        print("\n" + "-" * 80)
        print(" SMOKE EVALUATION RESULTS SUMMARY [MOCK]")
        print("-" * 80)
        print(f" Total Evaluated Queries:   {metrics.total_queries}")
        print(f" Hit Rate@5:                {metrics.hit_rate_at_5:.4f} (Threshold >= 0.90)")
        print(f" Mean Reciprocal Rank:      {metrics.mean_reciprocal_rank:.4f} (Threshold >= 0.80)")
        print(f" Information Leak Rate:     {metrics.information_leak_rate:.4f} (Threshold == 0.00)")
        print(f" Citation Grounding Rate:   {citation_grounding_rate:.4f} ({grounded_count}/{citation_checked})")
        print(f" Correct Abstention Rate:   {metrics.correct_abstention_rate:.4f}")
        print(f" Average Latency (ms):      {metrics.average_latency_ms:.2f} ms")
        print("-" * 80)

        # 5. Assert CI Invariants
        assert metrics.hit_rate_at_5 >= 0.90, f"Hit@5 ({metrics.hit_rate_at_5}) fell below 0.90"
        assert metrics.mean_reciprocal_rank >= 0.80, f"MRR ({metrics.mean_reciprocal_rank}) fell below 0.80"
        assert metrics.information_leak_rate == 0.0, f"Information leak detected: {metrics.information_leak_rate}"
        assert citation_grounding_rate >= 0.95, f"Citation grounding rate ({citation_grounding_rate}) fell below 0.95"

        print("[SUCCESS] All CI smoke evaluation invariants verified successfully!\n")
        return True

    finally:
        db.close()


if __name__ == "__main__":
    success = run_smoke_evaluation()
    sys.exit(0 if success else 1)

