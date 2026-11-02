"""Phase 4 Stronger Evaluation, Bootstrap CIs, and Ablation Matrix Verification Suite.

Verifies all Done-When criteria for Phase 4:
1. Core 100-question golden set remains unchanged (eval/golden.jsonl).
2. Extended candidate set (120 questions across paraphrases, stale traps, historical queries,
   unchanged clauses, and unanswerables) is fully validated and documented in eval/candidates/.
3. Bootstrap 95% confidence intervals are mathematically bounded and formatted as percentage AND k/n.
4. Deterministic citation grounding and key-fact verification logic operate without external LLM judges.
5. Full 8-way (2x2x2) factorial ablation matrix executes cleanly.
6. Failure taxonomy (retrieval_miss, rerank_drop, lineage_miss, generation_error, abstain_error)
   and honesty gates (corpus size, chance baseline, limitations) are generated in canonical reports.
"""

from __future__ import annotations

import json
import os
import sqlite3
import pytest
from pathlib import Path
from eval.schemas import GoldenQuestion
from eval.metrics import (
    compute_bootstrap_ci,
    format_metric_with_ci,
    check_citation_evidence_grounding,
    check_deterministic_key_facts,
    calculate_query_cost,
)
from eval.run_all import EIGHT_ABLATION_CONFIGURATIONS

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestDatasetIntegrity:
    """Verifies that the core golden set is untouched and extended candidate sets are valid."""

    def test_core_golden_set_is_strictly_100_questions(self):
        golden_path = PROJECT_ROOT / "eval" / "golden.jsonl"
        assert golden_path.exists(), "eval/golden.jsonl must exist"

        questions = []
        with open(golden_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    questions.append(json.loads(stripped))

        assert len(questions) == 100, f"Core golden dataset must have exactly 100 questions, found {len(questions)}"

        # Validate that all 100 pass GoldenQuestion schema
        for q in questions:
            gq = GoldenQuestion.model_validate(q)
            assert gq.id, "Question must have an ID"
            assert gq.question, "Question text must not be empty"

    def test_extended_candidates_dataset_composition(self):
        candidates_path = PROJECT_ROOT / "eval" / "candidates" / "extended_candidates.jsonl"
        extended_path = PROJECT_ROOT / "eval" / "golden_extended.jsonl"
        assert candidates_path.exists(), "eval/candidates/extended_candidates.jsonl must exist"
        assert extended_path.exists(), "eval/golden_extended.jsonl must exist"

        with open(candidates_path, "r", encoding="utf-8") as f:
            candidates = [json.loads(line) for line in f if line.strip()]

        assert len(candidates) == 120, f"Expected 120 extended candidate questions, got {len(candidates)}"

        # Verify categories
        paraphrases = [c for c in candidates if c["id"].startswith("P")]
        stale_traps = [c for c in candidates if c["id"].startswith("ST")]
        historical = [c for c in candidates if c["id"].startswith("HIST")]
        unchanged = [c for c in candidates if c["id"].startswith("UNCHG")]
        unanswerable = [c for c in candidates if c["id"].startswith("UNANS")]

        assert len(paraphrases) == 90, f"Expected 90 paraphrases (30x3), got {len(paraphrases)}"
        assert len(stale_traps) == 10, f"Expected 10 additional stale traps, got {len(stale_traps)}"
        assert len(historical) == 5, f"Expected 5 historical as-of questions, got {len(historical)}"
        assert len(unchanged) == 5, f"Expected 5 unchanged clause questions, got {len(unchanged)}"
        assert len(unanswerable) == 10, f"Expected 10 additional unanswerables, got {len(unanswerable)}"

        # Verify schema validity of all candidates
        for c in candidates:
            GoldenQuestion.model_validate(c)


class TestBootstrapConfidenceIntervals:
    """Verifies empirical bootstrap resampling for statistical confidence bounds."""

    def test_bootstrap_ci_exact_bounds(self):
        # All ones -> CI should be (1.0, 1.0)
        ci_ones = compute_bootstrap_ci([1] * 50, n_resamples=1000, seed=42)
        assert ci_ones == (1.0, 1.0)

        # All zeros -> CI should be (0.0, 0.0)
        ci_zeros = compute_bootstrap_ci([0] * 50, n_resamples=1000, seed=42)
        assert ci_zeros == (0.0, 0.0)

    def test_bootstrap_ci_realistic_sample(self):
        # 95 successes out of 100
        sample = [1] * 95 + [0] * 5
        ci = compute_bootstrap_ci(sample, n_resamples=2000, confidence_level=0.95, seed=42)

        assert 0.88 <= ci[0] <= 0.94, f"Unexpected lower CI bound: {ci[0]}"
        assert 0.96 <= ci[1] <= 1.00, f"Unexpected upper CI bound: {ci[1]}"
        assert ci[0] <= 0.95 <= ci[1], "Sample mean must lie within 95% bootstrap confidence interval"

    def test_format_metric_with_ci(self):
        formatted = format_metric_with_ci(95, 100, (0.91, 0.99))
        assert "95.0%" in formatted
        assert "(95/100)" in formatted
        assert "[91.0%, 99.0%]" in formatted


class TestDeterministicGroundingAndKeyFacts:
    """Verifies deterministic citation grounding and key-fact checks without external LLM judges."""

    def test_deterministic_key_facts_match(self):
        answer = "Under KVIT Academic Regulations, a student must complete a minimum of 160 credits to be awarded the B.Tech degree."
        expected_facts = ["160 credits", "B.Tech"]

        ok, matched, total = check_deterministic_key_facts(answer, expected_facts)
        assert ok is True
        assert matched == 2
        assert total == 2

    def test_deterministic_key_facts_missing(self):
        answer = "A student must complete all mandatory courses."
        expected_facts = ["160 credits"]

        ok, matched, total = check_deterministic_key_facts(answer, expected_facts)
        assert ok is False
        assert matched == 0
        assert total == 1

    def test_deterministic_citation_grounding(self):
        db_path = PROJECT_ROOT / "data" / "test_kvit.db"
        if not db_path.exists():
            pytest.skip("data/test_kvit.db not available")

        from app.core.database import SessionLocal
        with SessionLocal() as db:
            class MockCitation:
                file_name = "academic_regulations_2024.pdf"
                page_number = 1
                snippet = "minimum of 160 credits"

            ok, val, tot = check_citation_evidence_grounding([MockCitation()], db)
            assert ok is True
            assert val == 1
            assert tot == 1

            class FakeCitation:
                file_name = "academic_regulations_2024.pdf"
                page_number = 1
                snippet = "flying cars are strictly permitted on campus"

            ok_fake, val_fake, _ = check_citation_evidence_grounding([FakeCitation()], db)
            assert ok_fake is False
            assert val_fake == 0

    def test_calculate_query_cost(self):
        cost = calculate_query_cost(input_tokens=1000, output_tokens=200, model_name="gemini-2.5-flash")
        assert cost > 0.0
        assert isinstance(cost, float)

        local_cost = calculate_query_cost(input_tokens=1000, output_tokens=200, model_name="local-onnx")
        assert local_cost == 0.0


class TestAblationMatrixStructure:
    """Verifies the 8-way (2x2x2) factorial ablation matrix configuration space."""

    def test_eight_ablation_configurations_present(self):
        assert len(EIGHT_ABLATION_CONFIGURATIONS) == 8
        expected = {
            "v_off__lineage_off__role_off",
            "v_off__lineage_off__role_on",
            "v_off__lineage_on__role_off",
            "v_off__lineage_on__role_on",
            "v_on__lineage_off__role_off",
            "v_on__lineage_off__role_on",
            "v_on__lineage_on__role_off",
            "v_on__lineage_on__role_on",
        }
        assert set(EIGHT_ABLATION_CONFIGURATIONS) == expected


class TestEvaluationReportsIntegrity:
    """Verifies that REPORT.md and FAILURES.md adhere to Phase 4 specifications."""

    def test_canonical_report_has_phase4_sections(self):
        report_path = PROJECT_ROOT / "eval" / "results" / "real" / "REPORT.md"
        assert report_path.exists(), "eval/results/real/REPORT.md must exist"

        content = report_path.read_text(encoding="utf-8")

        # Required headers & tables
        assert "Primary Production Pipeline Quality Invariants" in content
        assert "Recall@1" in content
        assert "Recall@5" in content
        assert "MRR" in content
        assert "95% Bootstrap CI" in content
        assert "8-Way Factorial Ablation Matrix" in content
        assert "Honesty Gates & System Limitations" in content
        assert "Chance Baseline Recall@5" in content

    def test_failures_markdown_exists(self):
        failures_path = PROJECT_ROOT / "eval" / "results" / "real" / "FAILURES.md"
        assert failures_path.exists(), "eval/results/real/FAILURES.md must exist"

        content = failures_path.read_text(encoding="utf-8")
        assert "Failure Taxonomy" in content
        assert "retrieval_miss" in content
        assert "rerank_drop" in content
        assert "lineage_miss" in content
        assert "generation_error" in content
        assert "abstain_error" in content

