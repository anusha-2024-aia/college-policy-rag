"""Evaluation benchmark reports API routes."""

import json
import logging
import re
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, status

from app.schemas.evaluation_api import (
    EvaluationReportDetail,
    EvaluationReportListResponse,
    EvaluationReportSummary,
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
    "/reports",
    response_model=EvaluationReportListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Evaluation Benchmark Reports",
    description="Returns metadata of generated evaluation JSON reports and benchmarks in eval/results/.",
)
def list_reports() -> EvaluationReportListResponse:
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
def get_report(filename: str) -> EvaluationReportDetail:
    """Read a specific evaluation report safely."""
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
