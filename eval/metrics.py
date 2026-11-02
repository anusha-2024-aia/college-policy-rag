"""Evaluation metrics: Hit Rate@5, MRR, RAGAS integration, and custom domain metrics."""

import logging
import re
from pathlib import Path
from typing import Any, Optional
import numpy as np
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
    # 1. Check if response contains any forbidden canary tokens
    if golden.forbidden_canaries:
        ans_lower = (result.answer or "").lower()
        for cnry in golden.forbidden_canaries:
            if cnry.lower() in ans_lower:
                return True, f"Canary token '{cnry}' leaked to unauthorized role '{golden.role}'"

    # 2. Check if retrieved candidates or citations contain forbidden sources
    if golden.forbidden_sources:
        for c in result.retrieved_candidates:
            if matches_expected_source(c.file_name, c.page_number, golden.forbidden_sources):
                return True, f"Restricted chunk '{c.file_name}' leaked to unauthorized role '{golden.role}'"
        for cite in result.citations:
            if matches_expected_source(cite.file_name, cite.page_number, golden.forbidden_sources):
                return True, f"Restricted citation '{cite.file_name}' leaked to unauthorized role '{golden.role}'"

    # 3. Check restricted_for_roles
    if golden.restricted_for_roles and golden.role in golden.restricted_for_roles:
        # If any candidate from expected sources was retrieved or cited, that's an RBAC leak
        if not result.abstained or result.citations or result.retrieved_candidates:
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
        import ragas  # noqa: F401
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


def compute_bootstrap_ci(
    values: list[float | int | bool],
    n_resamples: int = 2000,
    confidence_level: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    """Compute empirical non-parametric bootstrap confidence interval for the sample mean.

    Uses percentile bootstrap resampling with replacement.
    Required by Phase 4 for all metrics where n >= 30.
    """
    if not values:
        return (0.0, 0.0)

    arr = np.array([float(v) for v in values], dtype=np.float64)
    if len(arr) < 2:
        m = float(np.mean(arr))
        return (round(m, 4), round(m, 4))

    # If n < 30, return exact mean as endpoints per requirement
    if len(arr) < 30:
        m = float(np.mean(arr))
        return (round(m, 4), round(m, 4))

    rng = np.random.RandomState(seed)
    indices = rng.randint(0, len(arr), size=(n_resamples, len(arr)))
    boot_samples = arr[indices]
    boot_means = np.mean(boot_samples, axis=1)

    alpha = 1.0 - confidence_level
    lower_pct = (alpha / 2.0) * 100.0
    upper_pct = (1.0 - alpha / 2.0) * 100.0

    ci_lower = float(np.percentile(boot_means, lower_pct))
    ci_upper = float(np.percentile(boot_means, upper_pct))

    return (round(ci_lower, 4), round(ci_upper, 4))


def format_metric_with_ci(
    k: int,
    n: int,
    ci: tuple[float, float],
    as_percentage: bool = True,
) -> str:
    """Format metric as: '96.0% (96/100) [92.0%, 99.0%]'."""
    if n == 0:
        return "N/A (0/0) [N/A, N/A]"

    pct = (k / n) * 100.0 if as_percentage else (k / n)
    if as_percentage:
        return f"{pct:.1f}% ({k}/{n}) [{ci[0]*100:.1f}%, {ci[1]*100:.1f}%]"
    else:
        return f"{pct:.4f} ({k}/{n}) [{ci[0]:.4f}, {ci[1]:.4f}]"


def check_citation_evidence_grounding(
    citations: list[Any],
    db_session: Any,
) -> tuple[bool, int, int]:
    """Verify that cited pages in citations deterministically contain the cited text snippets.

    Returns:
        (all_grounded: bool, valid_citations: int, total_citations: int)
    """
    if not citations:
        return True, 0, 0

    from app.models.chunk import Chunk

    valid_count = 0
    total_count = len(citations)

    for cite in citations:
        file_name = normalize_filename(getattr(cite, "file_name", ""))
        page_num = getattr(cite, "page_number", 1)
        snippet = getattr(cite, "snippet", "").strip().lower()

        # Query chunk from database
        chunks = (
            db_session.query(Chunk)
            .filter(
                Chunk.page_number == page_num,
            )
            .all()
        )

        matched = False
        for chk in chunks:
            # Check document filename match
            doc_file = normalize_filename(chk.document.file_name if chk.document else "")
            if doc_file == file_name:
                chk_text = chk.text.lower()
                # Check snippet containment or significant word overlap (>70%)
                if snippet in chk_text:
                    matched = True
                    break
                words = [w for w in re.findall(r"\w+", snippet) if len(w) > 3]
                if words:
                    found = sum(1 for w in words if w in chk_text)
                    if found / len(words) >= 0.7:
                        matched = True
                        break

        if matched:
            valid_count += 1

    return (valid_count == total_count, valid_count, total_count)


def check_deterministic_key_facts(
    answer: str,
    expected_key_facts: list[str],
) -> tuple[bool, int, int]:
    """Deterministically check if expected key factual statements/entities are present in the answer.

    Returns:
        (all_present: bool, matched_count: int, total_expected: int)
    """
    if not expected_key_facts:
        return True, 0, 0

    ans_lower = (answer or "").lower()
    matched = 0

    for fact in expected_key_facts:
        fact_clean = fact.strip().lower().rstrip(".,;")
        if not fact_clean:
            continue

        # Direct substring search
        if fact_clean in ans_lower:
            matched += 1
            continue

        # Check numeric tokens (e.g. "160", "80%", "14")
        nums = re.findall(r"\b\d+(?:\.\d+)?%?\b", fact_clean)
        if nums and all(n in ans_lower for n in nums):
            matched += 1
            continue

        # Keyword overlap: >= 60% of significant words present
        words = [w for w in re.findall(r"\b[a-z]{3,}\b", fact_clean)]
        if words:
            found = sum(1 for w in words if w in ans_lower)
            if (found / len(words)) >= 0.60:
                matched += 1
                continue

    return (matched == len(expected_key_facts), matched, len(expected_key_facts))


def calculate_query_cost(
    input_tokens: int,
    output_tokens: int,
    model_name: str = "gemini-2.5-flash",
) -> float:
    """Calculate estimated cost per query in USD based on official published rates."""
    # Gemini 2.5 Flash pricing: $0.075 / 1M input tokens, $0.30 / 1M output tokens
    # Local ONNX / FlashRank: $0.00
    if "gemini" in model_name.lower():
        input_cost = (input_tokens / 1_000_000.0) * 0.075
        output_cost = (output_tokens / 1_000_000.0) * 0.30
        return round(input_cost + output_cost, 6)
    return 0.0

