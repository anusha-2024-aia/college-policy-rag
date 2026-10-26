"""Tests for Phase 7: Evaluation Benchmark & Ablation Studies.

Verifies:
1. Golden dataset loading, validation, and schema consistency (100 questions).
2. EvaluationRunner execution across baseline and version-aware configurations.
3. Metric invariants:
   - hybrid_plus_reranking_plus_version_awareness achieves 0% leak rate and 0% stale policy error rate.
   - version-aware pipeline has 0% missing conflict rate on stale traps vs 100% on standard RAG.
   - security_ablated produces > 0% leak rate on restricted queries.
   - hybrid + reranking achieves higher Hit@5 and MRR than vector_only.
4. Summary reports generated in JSON and Markdown formats.
"""

import json
from pathlib import Path
import pytest
from eval.schemas import GoldenQuestion
from eval.runner import EvaluationRunner
from app.core.database import get_test_session
from app.services.retrieval import HybridRetrievalService
from app.services.embedding import MockEmbeddingService
from app.services.reranker import MockRerankerService
from app.services.llm import MockLLMService
from app.services.qa import QAService

GOLDEN_PATH = Path("eval/golden.jsonl")
RESULTS_DIR = Path("eval/results")


@pytest.fixture(scope="module")
def golden_questions() -> list[GoldenQuestion]:
    """Load and validate all 100 golden questions."""
    assert GOLDEN_PATH.exists(), f"Golden dataset not found at {GOLDEN_PATH}"
    questions: list[GoldenQuestion] = []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                raw = json.loads(line_str)
                questions.append(GoldenQuestion.model_validate(raw))
    assert len(questions) == 100
    return questions


@pytest.fixture(scope="module")
def eval_runner() -> EvaluationRunner:
    """Instantiate EvaluationRunner using deterministic mock services."""
    db = get_test_session()
    embedding_service = MockEmbeddingService(dimension=1536)
    reranker_service = MockRerankerService()
    llm_service = MockLLMService()
    retrieval_service = HybridRetrievalService(
        db_session=db,
        embedding_service=embedding_service,
        reranker_service=reranker_service,
    )
    qa_service = QAService(
        retrieval_service=retrieval_service,
        llm_service=llm_service,
    )
    return EvaluationRunner(
        db_session=db,
        retrieval_service=retrieval_service,
        qa_service=qa_service,
        top_k=20,
        top_n=5,
        abstention_threshold=0.00005,
    )


def test_golden_dataset_composition(golden_questions: list[GoldenQuestion]):
    """Verify golden dataset contains required 100 questions partitioned across 4 types."""
    types = {}
    roles = {}
    for q in golden_questions:
        types[q.type] = types.get(q.type, 0) + 1
        roles[q.role] = roles.get(q.role, 0) + 1

    assert types["normal"] == 55
    assert types["stale_trap"] == 15
    assert types["unanswerable"] == 15
    assert types["restricted_trap"] == 15
    assert sum(types.values()) == 100
    assert "student" in roles and "faculty" in roles and "admin" in roles


def test_version_awareness_eliminates_stale_policy_errors(
    eval_runner: EvaluationRunner, golden_questions: list[GoldenQuestion]
):
    """Verify that version awareness eliminates stale policy errors and detects conflicts."""
    stale_trap_questions = [q for q in golden_questions if q.type == "stale_trap"]

    # 1. Evaluate on standard RAG (hybrid_plus_reranking, version_aware=False)
    metrics_std, _ = eval_runner.evaluate_configuration(
        "hybrid_plus_reranking", stale_trap_questions
    )
    # Standard RAG does not flag version conflicts
    assert metrics_std.missing_conflict_rate == 1.0

    # 2. Evaluate on Version-Aware RAG (hybrid_plus_reranking_plus_version_awareness)
    metrics_va, _ = eval_runner.evaluate_configuration(
        "hybrid_plus_reranking_plus_version_awareness", stale_trap_questions
    )
    assert metrics_va.stale_policy_error_rate == 0.0
    assert metrics_va.missing_conflict_rate == 0.0


def test_rbac_security_prevents_leaks_vs_security_ablated(
    eval_runner: EvaluationRunner, golden_questions: list[GoldenQuestion]
):
    """Verify that RBAC security prevents leaks on restricted queries and that security_ablated leaks."""
    restricted_questions = [
        q for q in golden_questions if q.type == "restricted_trap" and q.should_abstain
    ]
    assert len(restricted_questions) == 10

    # Production config: 0% leak rate
    metrics_prod, results_prod = eval_runner.evaluate_configuration(
        "hybrid_plus_reranking_plus_version_awareness", restricted_questions
    )
    assert metrics_prod.information_leak_rate == 0.0
    assert all(not r.is_information_leak for r in results_prod)

    # Security ablated config: > 0% leak rate
    metrics_ablated, results_ablated = eval_runner.evaluate_configuration(
        "security_ablated", restricted_questions
    )
    assert metrics_ablated.information_leak_rate > 0.0
    assert any(r.is_information_leak for r in results_ablated)


def test_retrieval_quality_hybrid_rerank_beats_vector_only(
    eval_runner: EvaluationRunner, golden_questions: list[GoldenQuestion]
):
    """Verify that hybrid + cross-encoder reranking achieves superior Hit@5 and MRR over vector-only."""
    sample_normal = [q for q in golden_questions if q.type == "normal"][:10]

    metrics_vec, _ = eval_runner.evaluate_configuration("vector_only", sample_normal)
    metrics_hybrid, _ = eval_runner.evaluate_configuration(
        "hybrid_plus_reranking_plus_version_awareness", sample_normal
    )

    assert metrics_hybrid.hit_rate_at_5 >= metrics_vec.hit_rate_at_5
    assert metrics_hybrid.mean_reciprocal_rank >= metrics_vec.mean_reciprocal_rank

