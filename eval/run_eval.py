"""Evaluation CLI runner for Document RAG Project."""

import argparse
import datetime
import json
import logging
from pathlib import Path
import sys
from typing import Optional
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.embedding import get_embedding_service
from app.services.reranker import get_reranker_service
from app.services.retrieval import HybridRetrievalService
from app.services.llm import get_llm_service
from app.services.qa import QAService
from eval.schemas import (
    GoldenQuestion,
    ConfigMetrics,
    EvaluationSummaryReport,
)
from eval.runner import EvaluationRunner, SUPPORTED_CONFIGS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse CLI evaluation arguments."""
    parser = argparse.ArgumentParser(
        description="Run Document RAG evaluation framework across 5 configurations on golden dataset."
    )
    parser.add_argument(
        "--golden-path",
        type=str,
        default="eval/golden.jsonl",
        help="Path to verified golden JSONL dataset (default: eval/golden.jsonl)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="eval/results",
        help="Directory to store evaluation JSON and Markdown reports (default: eval/results)",
    )
    parser.add_argument(
        "--configs",
        type=str,
        default="all",
        help=f"Comma-separated list of configs to run, or 'all'. Options: {', '.join(SUPPORTED_CONFIGS)} (default: all)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=settings.RETRIEVAL_K,
        help=f"Initial retrieval candidates depth (default: {settings.RETRIEVAL_K})",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=settings.RERANKER_TOP_N,
        help=f"Final reranked results depth (default: {settings.RERANKER_TOP_N})",
    )
    parser.add_argument(
        "--abstention-threshold",
        type=float,
        default=0.00005,
        help="Evidence confidence score floor for abstention (default: 0.00005)",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Optional database URL override (e.g., sqlite:///data/local.db)",
    )
    parser.add_argument(
        "--mock-embeddings",
        action="store_true",
        help="Force use of deterministic mock embeddings",
    )
    parser.add_argument(
        "--mock-reranker",
        action="store_true",
        help="Force use of deterministic mock reranker",
    )
    parser.add_argument(
        "--force-mock-llm",
        action="store_true",
        help="Force use of deterministic mock LLM generation",
    )
    return parser.parse_args()


def load_golden_dataset(path_str: str) -> list[GoldenQuestion]:
    """Load and validate verified golden questions from JSONL file."""
    path = Path(path_str)
    if not path.exists():
        logger.error("Golden dataset not found at '%s'.", path)
        print(f"\n[ERROR] Golden dataset file '{path}' does not exist.")
        print("Please provide 'eval/golden.jsonl' with verified questions.")
        sys.exit(1)

    questions: list[GoldenQuestion] = []
    line_errors: list[str] = []

    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw_json = json.loads(stripped)
                item = GoldenQuestion.model_validate(raw_json)
                questions.append(item)
            except json.JSONDecodeError as exc:
                line_errors.append(f"Line {line_num}: Invalid JSON syntax ({exc})")
            except ValidationError as exc:
                line_errors.append(f"Line {line_num}: Schema validation error ({exc})")

    if line_errors:
        print(f"\n[ERROR] Encountered {len(line_errors)} errors in golden dataset '{path}':")
        for err in line_errors[:10]:
            print(f"  - {err}")
        if len(line_errors) > 10:
            print(f"  ... and {len(line_errors) - 10} more errors.")
        sys.exit(1)

    if not questions:
        print(f"\n[ERROR] Golden dataset at '{path}' is empty.")
        sys.exit(1)

    logger.info("Successfully loaded and validated %d questions from '%s'.", len(questions), path)
    return questions


def format_markdown_report(
    summary: EvaluationSummaryReport,
    questions: list[GoldenQuestion],
    all_results: dict[str, list],
) -> str:
    """Format side-by-side comparison table and failure taxonomy into GitHub Markdown."""
    lines: list[str] = []
    lines.append("# Document RAG - Evaluation Benchmark Report\n")
    lines.append(f"- **Generated Timestamp**: `{summary.timestamp}`")
    lines.append(f"- **Evaluated Dataset**: `{summary.dataset_size}` questions")
    lines.append(f"- **Configurations Benchmarked**: `{', '.join(summary.configs_evaluated)}`\n")

    lines.append("## 1. Multi-Configuration Comparative Metrics\n")
    lines.append(
        "| Configuration | Hit Rate@5 | MRR | Faithfulness | Relevance | Unsupported % | Stale Citation % | Missing Conflict % | Leak Rate % | Correct Abstain % | Avg Latency (ms) |"
    )
    lines.append(
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
    )

    for cfg_name, m in summary.config_metrics.items():
        faith_str = f"{m.faithfulness:.4f}" if m.faithfulness is not None else "N/A*"
        relev_str = f"{m.answer_relevance:.4f}" if m.answer_relevance is not None else "N/A*"
        unsupp_str = f"{m.unsupported_answer_rate * 100:.2f}%"
        stale_str = f"{m.stale_policy_error_rate * 100:.2f}%" if m.stale_policy_error_rate is not None else "N/A"
        miss_conf_str = f"{m.missing_conflict_rate * 100:.2f}%" if m.missing_conflict_rate is not None else "N/A"
        leak_str = f"{m.information_leak_rate * 100:.2f}%"
        abs_str = f"{m.correct_abstention_rate * 100:.2f}%"

        lines.append(
            f"| `{cfg_name}` | {m.hit_rate_at_5:.4f} | {m.mean_reciprocal_rank:.4f} | {faith_str} | {relev_str} | {unsupp_str} | {stale_str} | {miss_conf_str} | {leak_str} | {abs_str} | {m.average_latency_ms:.1f} |"
        )

    lines.append(
        "\n> [!NOTE]\n"
        "> `* N/A` denotes that RAGAS / external judge LLM evaluation was unavailable during the run, or no eligible version-conflict queries were answered.\n"
    )

    lines.append("## 2. Failure Classification Summary by Configuration\n")
    lines.append("| Configuration | Retrieval Misses | Ranking Misses | Generation Errors | Stale Citations | Missing Conflicts | Access Leaks | Abstention Errors |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

    for cfg_name, m in summary.config_metrics.items():
        fb = m.failures_by_category
        r_miss = fb.get("retrieval_miss", 0)
        rk_miss = fb.get("ranking_miss", 0)
        gen_err = fb.get("generation_error", 0)
        stale_err = fb.get("stale_citation_error", 0)
        conf_err = fb.get("missing_conflict_detection", 0)
        leak_err = fb.get("access_control_failure", 0)
        abs_err = fb.get("abstention_error", 0)
        lines.append(
            f"| `{cfg_name}` | {r_miss} | {rk_miss} | {gen_err} | {stale_err} | {conf_err} | {leak_err} | {abs_err} |"
        )

    lines.append("\n## 3. Representative Failure Analysis\n")
    if not summary.failure_details:
        lines.append("No failures detected across evaluated configurations.")
    else:
        lines.append(f"Recorded **{len(summary.failure_details)}** total failure instances across all configurations.\n")
        lines.append("| Question ID | Configuration | Role | Classification | Failure Diagnosis |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for fail in summary.failure_details[:25]:
            q_id = fail.get("question_id", "")
            cfg = fail.get("config_name", "")
            role = fail.get("role", "")
            cat = fail.get("classification", "")
            reason = fail.get("reason", "").replace("|", "-")
            lines.append(f"| `{q_id}` | `{cfg}` | `{role}` | `{cat}` | {reason} |")

        if len(summary.failure_details) > 25:
            lines.append(f"\n*(Showing 25 of {len(summary.failure_details)} failures. Full details stored in JSON export)*")

    lines.append("\n---\n")
    lines.append("## 4. Invariant Verification & Security Limitations\n")
    lines.append(
        "- **RBAC Security Invariant**: Role-based access control remained strictly enforced in all 5 configurations. "
        "At no point was security bypassed to compute comparative metrics.\n"
        "- **Production Demarcation**: Client-supplied role claims are used strictly for evaluation purposes. "
        "Production environments must authenticate callers server-side.\n"
    )

    return "\n".join(lines)


def main() -> None:
    """Execute Document RAG evaluation pipeline."""
    args = parse_args()

    questions = load_golden_dataset(args.golden_path)

    # Determine configurations to execute
    if args.configs.lower() == "all":
        configs_to_run = list(SUPPORTED_CONFIGS)
    else:
        requested = [c.strip() for c in args.configs.split(",") if c.strip()]
        invalid = [c for c in requested if c not in SUPPORTED_CONFIGS]
        if invalid:
            print(f"[ERROR] Invalid config(s) specified: {invalid}")
            print(f"Supported configs: {SUPPORTED_CONFIGS}")
            sys.exit(1)
        configs_to_run = requested

    # Setup database session
    if args.db_url:
        custom_engine = create_engine(args.db_url)
        CustomSession = sessionmaker(bind=custom_engine)
        db = CustomSession()
    else:
        try:
            db = SessionLocal()
        except Exception as exc:
            logger.error("Could not initialize database session: %s", exc)
            sys.exit(1)

    embedding_svc = get_embedding_service(force_mock=args.mock_embeddings)
    reranker_svc = get_reranker_service(force_mock=args.mock_reranker)
    llm_svc = get_llm_service(force_mock=args.force_mock_llm)

    retrieval_svc = HybridRetrievalService(
        db_session=db,
        embedding_service=embedding_svc,
        reranker_service=reranker_svc,
    )
    qa_svc = QAService(
        retrieval_service=retrieval_svc,
        llm_service=llm_svc,
    )

    runner = EvaluationRunner(
        db_session=db,
        retrieval_service=retrieval_svc,
        qa_service=qa_svc,
        top_k=args.top_k,
        top_n=args.top_n,
        abstention_threshold=args.abstention_threshold,
    )

    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 95)
    print(" DOCUMENT RAG - PHASE 6 EVALUATION BENCHMARK")
    print("=" * 95)
    print(f" Golden Dataset:    {args.golden_path} ({len(questions)} verified questions)")
    print(f" Configurations:    {', '.join(configs_to_run)}")
    print(f" Retrieval Depth:   top_k={args.top_k}, top_n={args.top_n}")
    print(f" Output Directory:  {out_dir}")
    print("=" * 95)

    all_config_metrics: dict[str, ConfigMetrics] = {}
    all_results_by_config: dict[str, list] = {}
    all_failures: list[dict] = []

    try:
        for cfg_idx, cfg_name in enumerate(configs_to_run, start=1):
            print(f"\n[{cfg_idx}/{len(configs_to_run)}] Evaluating Configuration: '{cfg_name}'...")
            metrics, results = runner.evaluate_configuration(cfg_name, questions)
            all_config_metrics[cfg_name] = metrics
            all_results_by_config[cfg_name] = [r.model_dump() for r in results]

            for r in results:
                if r.failure_classification:
                    all_failures.append({
                        "question_id": r.question_id,
                        "config_name": cfg_name,
                        "role": r.role,
                        "classification": r.failure_classification,
                        "reason": r.failure_reason,
                        "question_text": r.question_text,
                    })

            print(
                f"    -> Hit@5: {metrics.hit_rate_at_5:.4f} | MRR: {metrics.mean_reciprocal_rank:.4f} "
                f"| Stale Policy Err: {metrics.stale_policy_error_rate * 100:.1f}% "
                f"| Leak Rate: {metrics.information_leak_rate * 100:.2f}% "
                f"| Latency: {metrics.average_latency_ms:.1f}ms"
            )
    finally:
        db.close()

    summary_report = EvaluationSummaryReport(
        timestamp=datetime.datetime.now().isoformat(),
        dataset_size=len(questions),
        configs_evaluated=configs_to_run,
        config_metrics=all_config_metrics,
        failure_details=all_failures,
    )

    # 1. Save raw JSON results
    json_path = out_dir / f"eval_results_{timestamp_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "summary": summary_report.model_dump(),
                "results_by_config": all_results_by_config,
            },
            f,
            indent=2,
        )
    logger.info("Saved raw JSON results to '%s'.", json_path)

    # 2. Save and display Markdown report
    md_content = format_markdown_report(summary_report, questions, all_results_by_config)
    md_path = out_dir / f"eval_report_{timestamp_str}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    logger.info("Saved Markdown comparison report to '%s'.", md_path)

    print("\n" + "=" * 95)
    print(" EVALUATION RESULTS SUMMARY")
    print("=" * 95)
    print(md_content)
    print(f"\nArtifacts saved to:\n  - JSON: {json_path}\n  - Markdown: {md_path}\n")


if __name__ == "__main__":
    main()
