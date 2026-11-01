"""Evaluation benchmark reports API routes."""

import json
import logging
import re
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import get_current_role

from app.schemas.evaluation_api import (
    EvaluationReportDetail,
    EvaluationReportListResponse,
    EvaluationReportSummary,
    EvaluationSummaryResponse,
    BenchmarkConfigMetrics,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evaluations", tags=["Evaluations"])

RESULTS_DIR = Path("eval/results")


def clean_benchmark_title(raw_title: str, filename: str) -> str:
    """Sanitize benchmark report title by removing any 'Stage N' references.

    Converts technical filenames and stage prefixes into professional, recruiter-grade
    benchmark titles with timestamps.
    """
    # Remove any Stage N or Stage 5 references
    t = re.sub(r"(?i)\bstage\s*\d+[\s:_-]*", "", raw_title).strip()
    t = re.sub(r"^\d+\.\s*", "", t)

    # Format recognizable runs
    if "eval_results_20261019_082717" in filename or "eval_report_20261019_082717" in filename:
        return "Comprehensive Multi-Configuration Benchmark (Golden 33 Suite)"
    if "stage5_retrieval_evaluation_20261019_104450" in filename:
        return "MiniLM Dense Semantic & Hybrid Retrieval Benchmark"
    if "stage5_retrieval_evaluation_20261019_103158" in filename:
        return "Retrieval Calibration Benchmark"
    if "eval_results_20261019_074029" in filename or "eval_report_20261019_074029" in filename:
        return "Multi-Configuration Retrieval & Conflict Benchmark"
    if "semantic_retrieval_benchmark" in filename:
        return "Dense Semantic Embedding Retrieval Evaluation"
    if "eval_results_20261018" in filename or "eval_report_20261018" in filename:
        return "Baseline Retrieval & Abstention Evaluation"

    return t if t else filename.replace(".json", "").replace(".md", "").replace("_", " ").title()


@router.get(
    "/summary",
    response_model=EvaluationSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Active Benchmark Evaluation Summary",
    description="Returns latest real evaluation metrics dynamically loaded from eval/results/real/.",
)
def get_evaluation_summary(
    verified_role: str = Depends(get_current_role),
) -> EvaluationSummaryResponse:
    """Load latest real benchmark results for dynamic UI rendering."""
    real_dir = RESULTS_DIR / "real"
    candidate_files = []
    if real_dir.exists() and real_dir.is_dir():
        candidate_files = sorted(list(real_dir.glob("eval_results_*.json")), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidate_files:
        candidate_files = sorted(list(RESULTS_DIR.glob("eval_results_*.json")), key=lambda p: p.stat().st_mtime, reverse=True)

    if not candidate_files:
        return EvaluationSummaryResponse(
            available=False,
            message="No evaluation benchmark results available. Run python -m eval.run_all --mode real to generate.",
        )

    target_json = candidate_files[0]
    try:
        data = json.loads(target_json.read_text(encoding="utf-8"))
        meta = data.get("metadata", {})
        configs_raw = data.get("configs", {})

        parsed_configs = {}
        for cfg_name, cfg_data in configs_raw.items():
            parsed_configs[cfg_name] = BenchmarkConfigMetrics(
                hit_rate_at_1=float(cfg_data.get("hit_rate_at_1", 0.0)),
                hit_rate_at_3=float(cfg_data.get("hit_rate_at_3", 0.0)),
                hit_rate_at_5=float(cfg_data.get("hit_rate_at_5", 0.0)),
                mean_reciprocal_rank=float(cfg_data.get("mean_reciprocal_rank", 0.0)),
                average_latency_ms=float(cfg_data.get("average_latency_ms", 0.0)),
                p95_latency_ms=float(cfg_data.get("p95_latency_ms", 0.0)),
                information_leak_rate=float(cfg_data.get("information_leak_rate", 0.0)),
                missing_conflict_rate=float(cfg_data.get("missing_conflict_rate", 0.0)),
                stale_policy_error_rate=float(cfg_data.get("stale_policy_error_rate", 0.0)),
            )

        primary = parsed_configs.get("hybrid_plus_reranking_plus_version_awareness") or parsed_configs.get("hybrid") or next(iter(parsed_configs.values()))
        corpus_size = meta.get("corpus_size", {})
        corpus_docs = int(corpus_size.get("documents", 16))
        corpus_chunks = int(corpus_size.get("chunks", 51))

        # Dynamically query active database if available
        try:
            from app.core.database import SessionLocal
            from app.models.document import Document
            from app.models.chunk import Chunk
            with SessionLocal() as s:
                d_cnt = s.query(Document).count()
                c_cnt = s.query(Chunk).count()
                if d_cnt > 0:
                    corpus_docs = d_cnt
                if c_cnt > 0:
                    corpus_chunks = c_cnt
        except Exception:
            pass

        return EvaluationSummaryResponse(
            available=True,
            timestamp=meta.get("timestamp"),
            mode=meta.get("mode", "real"),
            embedding_model=meta.get("embedding_model", "all-MiniLM-L6-v2"),
            reranker_model=meta.get("reranker_model", "ms-marco-TinyBERT-L-2-v2"),
            corpus_documents=corpus_docs,
            corpus_chunks=corpus_chunks,
            chance_baseline_recall_at_5=float(meta.get("chance_baseline_recall_at_5", 0.098)),
            primary_recall_at_5=round(primary.hit_rate_at_5, 4),
            primary_mrr=round(primary.mean_reciprocal_rank, 4),
            primary_leak_rate=round(primary.information_leak_rate, 4),
            primary_latency_ms=round(primary.average_latency_ms, 2),
            configs=parsed_configs,
            is_mock=meta.get("is_mock", {}),
        )
    except Exception as exc:
        logger.error("Failed to load evaluation summary: %s", exc)
        return EvaluationSummaryResponse(available=False, message=f"Error reading evaluation report: {exc}")


@router.get(
    "/reports",
    response_model=EvaluationReportListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Evaluation Benchmark Reports",
    description="Returns metadata of generated evaluation JSON reports and benchmarks in eval/results/.",
)
def list_reports(
    verified_role: str = Depends(get_current_role),
) -> EvaluationReportListResponse:
    """Discover all benchmark JSON report files in reverse-chronological order."""
    if not RESULTS_DIR.exists() or not RESULTS_DIR.is_dir():
        return EvaluationReportListResponse(reports=[], total_count=0)

    # Prioritize JSON evaluation result files
    json_files = sorted(
        list(RESULTS_DIR.glob("*.json")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    summaries = []
    seen_ids = set()

    for p in json_files:
        # Determine human title
        base_title = p.stem.replace("_", " ").title()
        title = clean_benchmark_title(base_title, p.name)

        summaries.append(
            EvaluationReportSummary(
                id=p.stem,
                filename=p.name,
                title=title,
                has_json=True,
                file_size_bytes=p.stat().st_size,
            )
        )
        seen_ids.add(p.stem)

    return EvaluationReportListResponse(reports=summaries, total_count=len(summaries))


@router.get(
    "/reports/{filename}",
    response_model=EvaluationReportDetail,
    status_code=status.HTTP_200_OK,
    summary="Get Evaluation Benchmark Report Content",
    description="Returns JSON benchmark data for a specific evaluation run without exposing Stage N prefixes.",
)
def get_report(
    filename: str,
    verified_role: str = Depends(get_current_role),
) -> EvaluationReportDetail:
    """Read a specific evaluation report safely with role-based canary redaction."""
    clean_name = Path(filename).name
    target_path = RESULTS_DIR / clean_name

    # If user passed a .md filename, map to .json if possible
    if not target_path.exists() or clean_name.endswith(".md"):
        json_candidate = target_path.with_suffix(".json")
        if not json_candidate.exists():
            alt_name = clean_name.replace("eval_report_", "eval_results_").replace(".md", ".json")
            json_candidate = target_path.parent / alt_name
        if json_candidate.exists():
            target_path = json_candidate
            clean_name = json_candidate.name

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation report '{clean_name}' not found.",
        )

    try:
        json_export = None
        has_json = False

        if target_path.suffix == ".json":
            with open(target_path, "r", encoding="utf-8") as jf:
                json_export = jf.read()
                json.loads(json_export)  # Validate JSON syntax
                has_json = True
            markdown_content = ""
        else:
            with open(target_path, "r", encoding="utf-8") as f:
                markdown_content = f.read()

        # Phase 5 Leak Surface Scoping: Redact confidential canaries and sensitive tokens for non-admin callers
        if verified_role != "admin":
            canary_pattern = r"\bKVIT-[A-Z]{3}-CNRY-\d{4}\b"
            restricted_terms = [
                r"faculty_service_rules_2025\.pdf",
                r"question_paper_confidentiality_protocol_2025\.pdf",
                r"marks_moderation_guidelines_2025\.pdf",
                r"disciplinary_committee_case_summaries_2025\.pdf",
                r"admin_fee_waiver_internal_criteria_2025\.pdf",
                r"admin_salary_bands_and_budget_2025\.pdf",
                r"faculty\s+service",
                r"salary\s+bands",
                r"disciplinary\s+committee",
                r"fee\s+waiver\s+internal",
                r"confidentiality\s+protocol",
                r"marks\s+moderation",
            ]
            combined_pattern = re.compile(
                r"|".join([canary_pattern] + [f"(?:{t})" for t in restricted_terms]),
                re.IGNORECASE,
            )
            if json_export:
                json_export = combined_pattern.sub("[REDACTED_CONFIDENTIAL]", json_export)
            if markdown_content:
                markdown_content = combined_pattern.sub("[REDACTED_CONFIDENTIAL]", markdown_content)

        title = clean_benchmark_title(clean_name.replace("_", " ").title(), clean_name)

        return EvaluationReportDetail(
            filename=clean_name,
            title=title,
            markdown_content=markdown_content,
            json_export=json_export,
            has_json=has_json,
        )
    except Exception as exc:
        logger.error("Failed to read report %s: %s", clean_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading report: {exc}",
        ) from exc
