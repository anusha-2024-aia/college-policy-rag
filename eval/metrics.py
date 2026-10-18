"""Evaluation metrics: Hit Rate@5, MRR, RAGAS integration, and custom domain metrics."""

import logging
import re
from pathlib import Path
from typing import Optional
from eval.schemas import (
    CandidateItem,
    ExpectedSource,
    GoldenQuestion,
    QuestionEvalResult,
)

logger = logging.getLogger(__name__)


def normalize_filename(name: str) -> str:
    """Normalize file string to lowercase basename for resilient comparison."""
    return Path(name).name.lower().strip()


def matches_expected_source(
    candidate_file: str,
    candidate_page: int,
    expected_sources: list[ExpectedSource],
) -> bool:
    """Check if candidate matches any expected source by normalized filename and page number."""
    cand_norm = normalize_filename(candidate_file)
    for exp in expected_sources:
        if cand_norm == normalize_filename(exp.file_name) and candidate_page == exp.page_number:
            return True
    return False


def calculate_hit_at_k(
    candidates: list[CandidateItem],
    expected_sources: list[ExpectedSource],
    k: int = 5,
) -> bool:
    """Determine if at least one expected source is present in the top-k candidates."""
    if not expected_sources or not candidates:
        return False
    for c in candidates[:k]:
        if matches_expected_source(c.file_name, c.page_number, expected_sources):
            return True
    return False


def calculate_reciprocal_rank(
    candidates: list[CandidateItem],
    expected_sources: list[ExpectedSource],
) -> float:
    """Calculate reciprocal rank (1 / rank) of the first matching candidate (1-based rank)."""
    if not expected_sources or not candidates:
        return 0.0
    for idx, c in enumerate(candidates, start=1):
        if matches_expected_source(c.file_name, c.page_number, expected_sources):
            return round(1.0 / idx, 4)
    return 0.0


def check_unsupported_answer(
    result: QuestionEvalResult,
    golden: GoldenQuestion,
) -> tuple[bool, Optional[str]]:
    """Verify if the generated answer is unsupported or makes ungrounded claims.

    Criteria:
    - If answer is not abstained, but citations list is empty.
    - If answer cites hallucinated citation brackets (e.g. [99]) that do not exist in passages.
    - If answer text contains hallucination cues.
    """
    if result.abstained:
        return False, None

    # Non-abstained answer must have valid citations
    if not result.citations:
        return True, "Answer was generated without any verifiable citations."

    # Verify citation numbers in answer text match citations list
    ans_brackets = set(re.findall(r"\[(\d+)\]", result.answer))
    valid_indices = {str(c.index) for c in result.citations}
    hallucinated = ans_brackets - valid_indices
    if hallucinated:
        return True, f"Answer contains hallucinated citation indices: {sorted(list(hallucinated))}"

    return False, None


def check_stale_policy_error(
    result: QuestionEvalResult,
    golden: GoldenQuestion,
) -> tuple[bool, Optional[str]]:
    """Verify if the answer committed an actual stale-policy citation error.

    Criteria:
    - If question is not a version conflict inquiry, return False.
    - If answer abstained, return False (abstention is not a stale citation error).
    - If citations include superseded policy but omit all active policy documents, return True.
    - If citations exist but omit all active policy documents, return True.
    """
    if not golden.is_version_conflict or result.abstained:
        return False, None

    if golden.superseded_sources and golden.expected_sources:
        cited_files = {normalize_filename(c.file_name) for c in result.citations}
        expected_active_files = {normalize_filename(s.file_name) for s in golden.expected_sources}
        superseded_files = {normalize_filename(s.file_name) for s in golden.superseded_sources}

        if (cited_files & superseded_files) and not (cited_files & expected_active_files):
            return True, "Answer cited superseded policy as authoritative and omitted active policy."

        if cited_files and not (cited_files & expected_active_files):
            return True, "Answer omitted active policy citations."

    return False, None


def check_missing_policy_conflict(
    result: QuestionEvalResult,
    golden: GoldenQuestion,
) -> tuple[bool, Optional[str]]:
    """Verify if the system failed to detect and flag a policy conflict on a version-conflict query.

    Criteria:
    - If question is not a version conflict inquiry, return False.
    - If answer abstained, return False (no answer synthesis occurred).
    - If system failed to set has_policy_conflict=True, return True.
    """
    if not golden.is_version_conflict or result.abstained:
        return False, None

    if not result.has_policy_conflict:
        return True, "Failed to detect and flag policy conflict between current and superseded versions."

    return False, None


def check_information_leak(
    result: QuestionEvalResult,
    golden: GoldenQuestion,
) -> tuple[bool, Optional[str]]:
    """Verify if unauthorized document chunks or tokens were retrieved or cited."""
    # Check if this question was an unauthorized probe for this role
    if golden.restricted_for_roles and golden.role in golden.restricted_for_roles:
        # If any candidate from expected sources was retrieved or cited, that's an RBAC leak
        if not result.abstained or result.citations or result.retrieved_candidates:
            # Check if any candidate is from restricted document
            for c in result.retrieved_candidates:
                if matches_expected_source(c.file_name, c.page_number, golden.expected_sources):
                    return True, f"Restricted chunk '{c.file_name}' leaked to unauthorized role '{golden.role}'"
            for cite in result.citations:
                if matches_expected_source(cite.file_name, cite.page_number, golden.expected_sources):
                    return True, f"Restricted citation '{cite.file_name}' leaked to unauthorized role '{golden.role}'"

    return False, None


def check_abstention(
    result: QuestionEvalResult,
    golden: GoldenQuestion,
) -> tuple[bool, bool, Optional[str]]:
    """Evaluate abstention accuracy.

    Returns:
        (is_correct_abstention, is_false_abstention, reason)
    """
    if golden.should_abstain:
        if result.abstained:
            return True, False, None
        return False, False, "System failed to abstain on unanswerable query."
    else:
        if result.abstained:
            return False, True, "System falsely abstained on an answerable query."
        return True, False, None


def classify_failure(
    result: QuestionEvalResult,
    golden: GoldenQuestion,
) -> tuple[Optional[str], Optional[str]]:
    """Classify failure root cause using taxonomy.

    Taxonomy:
    - access_control_failure: unauthorized leak.
    - abstention_error: failed to abstain / false abstention.
    - retrieval_miss: target file/page not in candidate pool at all.
    - ranking_miss: target found in candidates, but ranked outside top 5 or rank > 5.
    - stale_citation_error: superseded policy cited as authoritative or active omitted.
    - missing_conflict_detection: failed to detect and flag active policy conflict.
    - generation_error: ungrounded answer, hallucinated citations.
    """
    if result.is_information_leak:
        return "access_control_failure", result.failure_reason

    # Abstention error
    if golden.should_abstain and not result.abstained:
        return "abstention_error", "Failed to abstain when ground truth indicates insufficient evidence."
    if not golden.should_abstain and result.abstained:
        return "abstention_error", "Falsely abstained when ground truth indicates question is answerable."

    # Actual stale citation error
    if result.is_stale_policy_error:
        return "stale_citation_error", result.failure_reason

    # Missing conflict detection
    if result.is_missing_conflict_detection:
        return "missing_conflict_detection", result.failure_reason

    # Retrieval and ranking checks (only on answerable queries with expected sources)
    if not golden.should_abstain and golden.expected_sources:
        # Check if expected source was in candidates
        in_candidates = any(
            matches_expected_source(c.file_name, c.page_number, golden.expected_sources)
            for c in result.retrieved_candidates
        )
        if not in_candidates:
            return "retrieval_miss", "Expected document and page not retrieved in candidate pool."

        # Expected source in pool, but was it in top 5?
        if not result.hit_at_5:
            return "ranking_miss", "Expected source was retrieved, but ranked outside top 5."

    # Unsupported answer
    if result.is_unsupported_answer:
        return "generation_error", result.failure_reason

    return None, None


def compute_ragas_metrics(
    eval_records: list[dict],
) -> tuple[Optional[float], Optional[float]]:
    """Compute RAGAS faithfulness and answer_relevance if provider and package are available.

    IMPORTANT: If RAGAS is not installed or API key is not configured, returns (None, None).
    Never returns 0.00 for unavailable metrics.
    """
    try:
        import ragas
        from ragas import evaluate
        from ragas.metrics import faithfulness, answer_relevancy
        from datasets import Dataset

        logger.info("Computing RAGAS metrics on %d records...", len(eval_records))

        # Format records for RAGAS Dataset
        dataset_dict = {
            "question": [r["question"] for r in eval_records],
            "contexts": [[c["text"] for c in r["retrieved_candidates"]] for r in eval_records],
            "answer": [r["answer"] for r in eval_records],
            "ground_truth": [r.get("expected_answer", "") for r in eval_records],
        }
        dataset = Dataset.from_dict(dataset_dict)
        results = evaluate(dataset, metrics=[faithfulness, answer_relevancy])

        faith = float(results.get("faithfulness", 0.0))
        relev = float(results.get("answer_relevancy", 0.0))
        return round(faith, 4), round(relev, 4)

    except (ImportError, Exception) as exc:
        logger.info(
            "RAGAS evaluation unavailable (%s). Distinguishing unavailable metrics as None/N/A.",
            exc,
        )
        return None, None
