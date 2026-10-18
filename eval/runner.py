"""Execution runner comparing 5 Document RAG configurations with strict RBAC enforcement."""

import logging
import time
from typing import Any, Optional
from sqlalchemy.orm import Session
from eval.metrics import (
    calculate_hit_at_k,
    calculate_reciprocal_rank,
    check_unsupported_answer,
    check_stale_policy_error,
    check_missing_policy_conflict,
    check_information_leak,
    check_abstention,
    classify_failure,
    compute_ragas_metrics,
)
from eval.schemas import (
    CandidateItem,
    CitationItem,
    ConfigMetrics,
    GoldenQuestion,
    QuestionEvalResult,
    EvaluationSummaryReport,
)
from app.models.document import Document
from app.schemas.qa import AskRequest, PassageEvidence
from app.services.retrieval import HybridRetrievalService, ScoredChunk, FusedChunk, RerankedChunk
from app.services.qa import QAService

logger = logging.getLogger(__name__)

SUPPORTED_CONFIGS = [
    "vector_only",
    "keyword_only",
    "hybrid",
    "hybrid_plus_reranking",
    "hybrid_plus_reranking_plus_version_awareness",
]


class EvaluationRunner:
    """Orchestrates evaluation across Document RAG configurations with RBAC enforced at every step."""

    def __init__(
        self,
        db_session: Session,
        retrieval_service: HybridRetrievalService,
        qa_service: QAService,
        top_k: int = 20,
        top_n: int = 5,
        abstention_threshold: float = 0.00005,
    ):
        self.db = db_session
        self.retrieval_service = retrieval_service
        self.qa_service = qa_service
        self.top_k = top_k
        self.top_n = top_n
        self.abstention_threshold = abstention_threshold

    def run_question_on_config(
        self,
        question: GoldenQuestion,
        config_name: str,
    ) -> QuestionEvalResult:
        """Execute a single question through the designated configuration with RBAC filter active."""
        start_time = time.perf_counter()
        role = question.role

        candidates: list[CandidateItem] = []
        answer_text = ""
        citations: list[CitationItem] = []
        abstained = False
        has_conflict = False

        if config_name == "vector_only":
            # Dense Vector Search only (k=5)
            scored = self.retrieval_service.vector_search(query=question.question, k=self.top_n, role=role)
            for s in scored:
                candidates.append(
                    CandidateItem(chunk_id=str(s.chunk_id), file_name=s.file_name, page_number=s.page_number, rank=s.rank, score=s.score, text=s.text)
                )

            # Synthesize answer from top vector candidates
            passages = [
                PassageEvidence(
                    index=idx,
                    chunk_id=c.chunk_id or str(c.rank),
                    file_name=c.file_name,
                    page_number=c.page_number,
                    text=c.text,
                    score=c.score,
                )
                for idx, c in enumerate(candidates, start=1)
            ]
            if not passages:
                abstained = True
                answer_text = self.qa_service.ABSTENTION_SENTENCE
            else:
                sys_p, usr_p = self.qa_service.build_full_prompt(question.question, passages, version_aware=False)
                raw_ans = self.qa_service.llm_service.generate(usr_p, sys_p)
                abstained = self.qa_service.should_abstain(raw_ans, passages, self.abstention_threshold)
                if abstained:
                    answer_text = self.qa_service.ABSTENTION_SENTENCE
                else:
                    answer_text = raw_ans
                    valid_cites, _ = self.qa_service.validate_citations(answer_text, passages)
                    citations = [
                        CitationItem(index=c.index, file_name=c.file_name, page_number=c.page_number, snippet=c.snippet)
                        for c in valid_cites
                    ]

        elif config_name == "keyword_only":
            # Sparse Keyword Search only (k=5)
            scored = self.retrieval_service.keyword_search(query=question.question, k=self.top_n, role=role)
            for s in scored:
                candidates.append(
                    CandidateItem(chunk_id=str(s.chunk_id), file_name=s.file_name, page_number=s.page_number, rank=s.rank, score=s.score, text=s.text)
                )

            passages = [
                PassageEvidence(
                    index=idx,
                    chunk_id=c.chunk_id or str(c.rank),
                    file_name=c.file_name,
                    page_number=c.page_number,
                    text=c.text,
                    score=c.score,
                )
                for idx, c in enumerate(candidates, start=1)
            ]
            if not passages:
                abstained = True
                answer_text = self.qa_service.ABSTENTION_SENTENCE
            else:
                sys_p, usr_p = self.qa_service.build_full_prompt(question.question, passages, version_aware=False)
                raw_ans = self.qa_service.llm_service.generate(usr_p, sys_p)
                abstained = self.qa_service.should_abstain(raw_ans, passages, self.abstention_threshold)
                if abstained:
                    answer_text = self.qa_service.ABSTENTION_SENTENCE
                else:
                    answer_text = raw_ans
                    valid_cites, _ = self.qa_service.validate_citations(answer_text, passages)
                    citations = [
                        CitationItem(index=c.index, file_name=c.file_name, page_number=c.page_number, snippet=c.snippet)
                        for c in valid_cites
                    ]

        elif config_name == "hybrid":
            # Hybrid Vector + Keyword fused via RRF (no cross-encoder)
            vec_res = self.retrieval_service.vector_search(query=question.question, k=self.top_k, role=role)
            kw_res = self.retrieval_service.keyword_search(query=question.question, k=self.top_k, role=role)
            fused = self.retrieval_service.rrf_fuse(vec_res, kw_res, k_rrf=self.retrieval_service.rrf_k)
            top_fused = fused[: self.top_n]

            for f in top_fused:
                candidates.append(
                    CandidateItem(chunk_id=str(f.chunk_id), file_name=f.file_name, page_number=f.page_number, rank=f.fused_rank, score=f.rrf_score, text=f.text)
                )

            passages = [
                PassageEvidence(
                    index=idx,
                    chunk_id=c.chunk_id or str(c.rank),
                    file_name=c.file_name,
                    page_number=c.page_number,
                    text=c.text,
                    score=c.score,
                )
                for idx, c in enumerate(candidates, start=1)
            ]
            if not passages:
                abstained = True
                answer_text = self.qa_service.ABSTENTION_SENTENCE
            else:
                sys_p, usr_p = self.qa_service.build_full_prompt(question.question, passages, version_aware=False)
                raw_ans = self.qa_service.llm_service.generate(usr_p, sys_p)
                abstained = self.qa_service.should_abstain(raw_ans, passages, self.abstention_threshold)
                if abstained:
                    answer_text = self.qa_service.ABSTENTION_SENTENCE
                else:
                    answer_text = raw_ans
                    valid_cites, _ = self.qa_service.validate_citations(answer_text, passages)
                    citations = [
                        CitationItem(index=c.index, file_name=c.file_name, page_number=c.page_number, snippet=c.snippet)
                        for c in valid_cites
                    ]

        elif config_name == "hybrid_plus_reranking":
            # Hybrid Vector + Keyword + RRF + Cross-Encoder Reranker (version_aware=False)
            req = AskRequest(
                question=question.question,
                role=role,
                top_k=self.top_k,
                top_n=self.top_n,
                version_aware=False,
                abstention_threshold=self.abstention_threshold,
            )
            resp = self.qa_service.answer(req)
            abstained = resp.abstained
            answer_text = resp.answer
            has_conflict = resp.has_policy_conflict

            for p in resp.passages:
                candidates.append(
                    CandidateItem(file_name=p.file_name, page_number=p.page_number, rank=p.index, score=p.score, text=p.text)
                )
            for c in resp.citations:
                citations.append(
                    CitationItem(index=c.index, file_name=c.file_name, page_number=c.page_number, snippet=c.snippet)
                )

        elif config_name == "hybrid_plus_reranking_plus_version_awareness":
            # Complete Production Pipeline (version_aware=True)
            req = AskRequest(
                question=question.question,
                role=role,
                top_k=self.top_k,
                top_n=self.top_n,
                version_aware=True,
                abstention_threshold=self.abstention_threshold,
            )
            resp = self.qa_service.answer(req)
            abstained = resp.abstained
            answer_text = resp.answer
            has_conflict = resp.has_policy_conflict

            for p in resp.passages:
                candidates.append(
                    CandidateItem(file_name=p.file_name, page_number=p.page_number, rank=p.index, score=p.score, text=p.text)
                )
            for c in resp.citations:
                citations.append(
                    CitationItem(index=c.index, file_name=c.file_name, page_number=c.page_number, snippet=c.snippet)
                )
        else:
            raise ValueError(f"Unknown configuration name: {config_name}")

        latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        # Compute retrieval metric indicators
        hit_at_5 = calculate_hit_at_k(candidates, question.expected_sources, k=self.top_n)
        reciprocal_rank = calculate_reciprocal_rank(candidates, question.expected_sources)

        # Create basic result
        result = QuestionEvalResult(
            question_id=question.id,
            config_name=config_name,
            role=role,
            question_text=question.question,
            retrieved_candidates=candidates,
            hit_at_5=hit_at_5,
            reciprocal_rank=reciprocal_rank,
            answer=answer_text,
            citations=citations,
            abstained=abstained,
            has_policy_conflict=has_conflict,
            latency_ms=latency_ms,
        )

        # Compute custom metric evaluations
        unsupp, unsupp_reason = check_unsupported_answer(result, question)
        result.is_unsupported_answer = unsupp

        stale, stale_reason = check_stale_policy_error(result, question)
        result.is_stale_policy_error = stale

        miss_conf, conf_reason = check_missing_policy_conflict(result, question)
        result.is_missing_conflict_detection = miss_conf

        leak, leak_reason = check_information_leak(result, question)
        result.is_information_leak = leak

        corr_abs, false_abs, abs_reason = check_abstention(result, question)
        result.is_correct_abstention = corr_abs

        # Classify any failures
        fail_cat, fail_reason = classify_failure(result, question)
        result.failure_classification = fail_cat
        result.failure_reason = fail_reason or unsupp_reason or stale_reason or conf_reason or leak_reason or abs_reason

        return result

    def evaluate_configuration(
        self,
        config_name: str,
        questions: list[GoldenQuestion],
    ) -> tuple[ConfigMetrics, list[QuestionEvalResult]]:
        """Run all questions for a single configuration and compute aggregated metrics."""
        results: list[QuestionEvalResult] = []
        failures_count: dict[str, int] = {}

        for q in questions:
            res = self.run_question_on_config(q, config_name)
            results.append(res)
            if res.failure_classification:
                failures_count[res.failure_classification] = (
                    failures_count.get(res.failure_classification, 0) + 1
                )

        # Aggregated Metrics Calculation
        total_queries = len(questions)

        # Retrieval metrics on answerable queries with expected sources
        retrieval_queries = [
            (q, r) for q, r in zip(questions, results, strict=False)
            if not q.should_abstain and len(q.expected_sources) > 0
        ]
        eval_retrieval_count = len(retrieval_queries)

        if eval_retrieval_count > 0:
            hit_rate_at_5 = round(sum(1.0 for _, r in retrieval_queries if r.hit_at_5) / eval_retrieval_count, 4)
            mrr = round(sum(r.reciprocal_rank for _, r in retrieval_queries) / eval_retrieval_count, 4)
        else:
            hit_rate_at_5 = 0.0
            mrr = 0.0

        # Custom Domain Metrics
        non_abstained = [r for r in results if not r.abstained]
        unsupported_rate = (
            round(sum(1.0 for r in non_abstained if r.is_unsupported_answer) / len(non_abstained), 4)
            if non_abstained
            else 0.0
        )

        answered_version_conflicts = [
            (q, r) for q, r in zip(questions, results, strict=False)
            if q.is_version_conflict and not r.abstained
        ]
        if answered_version_conflicts:
            stale_policy_rate = round(
                sum(1.0 for _, r in answered_version_conflicts if r.is_stale_policy_error)
                / len(answered_version_conflicts),
                4,
            )
            missing_conflict_rate = round(
                sum(1.0 for _, r in answered_version_conflicts if r.is_missing_conflict_detection)
                / len(answered_version_conflicts),
                4,
            )
        else:
            # Mark N/A (None) when no eligible answers exist (e.g. all abstained)
            stale_policy_rate = None
            missing_conflict_rate = None

        leak_rate = round(sum(1.0 for r in results if r.is_information_leak) / total_queries, 4) if total_queries else 0.0

        expected_abstentions = [(q, r) for q, r in zip(questions, results, strict=False) if q.should_abstain]
        correct_abstention_rate = (
            round(sum(1.0 for _, r in expected_abstentions if r.abstained) / len(expected_abstentions), 4)
            if expected_abstentions
            else 1.0
        )

        answerable_queries = [(q, r) for q, r in zip(questions, results, strict=False) if not q.should_abstain]
        false_abstention_rate = (
            round(sum(1.0 for _, r in answerable_queries if r.abstained) / len(answerable_queries), 4)
            if answerable_queries
            else 0.0
        )

        avg_latency = round(sum(r.latency_ms for r in results) / total_queries, 2) if total_queries else 0.0

        # Optional RAGAS metrics
        ragas_records = [
            {
                "question": r.question_text,
                "retrieved_candidates": [c.model_dump() for c in r.retrieved_candidates],
                "answer": r.answer,
                "expected_answer": next((q.expected_answer for q in questions if q.id == r.question_id), ""),
            }
            for r in results
            if not r.abstained
        ]
        faithfulness, relevance = compute_ragas_metrics(ragas_records)

        metrics = ConfigMetrics(
            config_name=config_name,
            total_queries=total_queries,
            eval_retrieval_queries=eval_retrieval_count,
            hit_rate_at_5=hit_rate_at_5,
            mean_reciprocal_rank=mrr,
            faithfulness=faithfulness,
            answer_relevance=relevance,
            unsupported_answer_rate=unsupported_rate,
            stale_policy_error_rate=stale_policy_rate,
            missing_conflict_rate=missing_conflict_rate,
            information_leak_rate=leak_rate,
            correct_abstention_rate=correct_abstention_rate,
            false_abstention_rate=false_abstention_rate,
            average_latency_ms=avg_latency,
            failures_by_category=failures_count,
        )

        return metrics, results
