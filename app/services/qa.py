"""Question answering, citation validation, and version-aware policy service."""

import json
import logging
import re
from collections.abc import Generator
from typing import Optional
from app.models.document import Document
from app.schemas.qa import (
    AskRequest,
    PassageEvidence,
    Citation,
    AskResponse,
    PolicyConflict,
)
from app.services.retrieval import HybridRetrievalService
from app.services.llm import BaseLLMService
from app.services.versioning import DocumentVersionService, DocumentVersionStatus
from app.core.config import settings
from app.core.roles import build_role_filter, validate_role

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an enterprise document question-answering assistant. You must answer the user's question solely and strictly based on the Context Evidence provided below.

Rules and Constraints:
1. Answer only using the direct facts present in the Context Evidence. Never extrapolate, assume, speculate, or introduce external knowledge.
2. Every factual statement or claim in your response must be supported by an exact bracketed citation corresponding to the evidence number, e.g., [1], [2].
3. Clearly distinguish supported facts from uncertainty.
4. If the Context Evidence does not contain sufficient information to answer the question, or if no evidence is provided, you MUST reply with this exact sentence and nothing else:
"I do not have sufficient information in the provided documents to answer this question."
5. Never invent or fabricate citations, source filenames, or page numbers. Only cite bracket numbers [N] that exist in the supplied Context Evidence.
6. Version-Aware Policies: If Context Evidence indicates status [STATUS: CURRENT ...] or [STATUS: SUPERSEDED ...]:
   - Explain the CURRENT policy first, supported by its citation.
   - If an older superseded policy is in the evidence and disagrees or was updated, explicitly state that the older policy in [N] (effective DATE) has been superseded.
   - For documents marked [STATUS: CURRENT (Partially amended ...)], only specifically amended clauses are superseded by the newer amendment circular; all unamended clauses remain active, valid, and in force.
   - Never claim that an unrelated document supersedes an older document unless an explicit superseding relationship is established.
"""


class QAService:
    """Orchestrates hybrid retrieval, evidence formatting, version awareness, LLM generation, and citation validation."""

    ABSTENTION_SENTENCE = "I do not have sufficient information in the provided documents to answer this question."

    def __init__(
        self,
        retrieval_service: HybridRetrievalService,
        llm_service: BaseLLMService,
        version_service: Optional[DocumentVersionService] = None,
    ):
        self.retrieval_service = retrieval_service
        self.llm_service = llm_service
        self.version_service = version_service or DocumentVersionService()

    def build_evidence_prompt(
        self, passages: list[PassageEvidence], version_aware: bool = False
    ) -> str:
        """Format retrieved passages into numbered evidence blocks with optional version status."""
        if not passages:
            return "None"

        blocks = []
        for p in passages:
            status_tag = ""
            if version_aware:
                if p.is_superseded:
                    status_tag = (
                        f" [STATUS: SUPERSEDED by {p.superseded_by or 'newer policy'} - "
                        f"Effective: {p.effective_date or 'N/A'}]"
                    )
                elif getattr(p, "is_partially_amended", False):
                    scope_str = f" ({p.amendment_scope})" if p.amendment_scope else ""
                    status_tag = (
                        f" [STATUS: CURRENT (Partially amended{scope_str}) - "
                        f"Effective: {p.effective_date or 'N/A'}]"
                    )
                elif p.effective_date:
                    status_tag = f" [STATUS: CURRENT - Effective: {p.effective_date}]"

            title_prefix = f"Title: {p.document_title} | " if p.document_title else ""
            blocks.append(
                f"[{p.index}] {title_prefix}File: {p.file_name} (Page {p.page_number}){status_tag}\n{p.text.strip()}"
            )
        return "\n\n".join(blocks)

    def build_full_prompt(
        self, question: str, passages: list[PassageEvidence], version_aware: bool = False
    ) -> tuple[str, str]:
        """Generate system and user prompts with numbered context evidence."""
        evidence_text = self.build_evidence_prompt(passages, version_aware=version_aware)
        user_prompt = f"Context Evidence:\n{evidence_text}\n\nUser Question: {question.strip()}"
        return SYSTEM_PROMPT, user_prompt

    def validate_citations(
        self,
        answer_text: str,
        passages: list[PassageEvidence],
    ) -> tuple[list[Citation], list[int]]:
        """Extract and validate all citation references [N] from answer text.

        Ensures every citation strictly points to an actual retrieved passage.
        Hallucinated indices (e.g., [99]) are flagged and omitted from the valid citation list.
        """
        passages_by_idx = {p.index: p for p in passages}
        raw_matches = re.findall(r"\[(\d+)\]", answer_text)

        valid_citations: list[Citation] = []
        invalid_indices: list[int] = []
        seen_indices: set[int] = set()

        for match_str in raw_matches:
            cited_idx = int(match_str)
            if cited_idx in passages_by_idx:
                if cited_idx not in seen_indices:
                    seen_indices.add(cited_idx)
                    passage = passages_by_idx[cited_idx]
                    valid_citations.append(
                        Citation(
                            index=cited_idx,
                            file_name=passage.file_name,
                            page_number=passage.page_number,
                            snippet=passage.text[:120].strip() + ("..." if len(passage.text) > 120 else ""),
                        )
                    )
            else:
                invalid_indices.append(cited_idx)
                logger.warning(
                    "Model hallucinated citation [%d]; valid passage indices are %s",
                    cited_idx,
                    list(passages_by_idx.keys()),
                )

        valid_citations.sort(key=lambda c: c.index)
        return valid_citations, invalid_indices

    def should_abstain(
        self,
        raw_answer: str,
        passages: list[PassageEvidence],
        abstention_threshold: float,
    ) -> bool:
        """Evaluate if system should abstain due to insufficient evidence or model signal."""
        if not passages:
            return True

        # Check evidence score floor
        top_score = max((p.score for p in passages), default=0.0)
        if top_score < abstention_threshold:
            logger.info("Top reranker score (%.4f) below floor (%.4f); abstaining.", top_score, abstention_threshold)
            return True

        # Check model explicit abstention signal
        clean_ans = raw_answer.strip().lower()
        if self.ABSTENTION_SENTENCE.lower() in clean_ans:
            return True
        if not clean_ans:
            return True

        return False

    def _prepare_passages_and_conflicts(
        self,
        request: AskRequest,
    ) -> tuple[list[PassageEvidence], bool, list[PolicyConflict], Optional[any]]:
        """Retrieve, rerank, and enrich passages with version awareness and conflict detection."""
        is_version_aware = (
            request.version_aware
            if request.version_aware is not None
            else settings.VERSION_AWARE_ENABLED
        )

        clean_role = validate_role(request.role)

        retrieval_res = self.retrieval_service.retrieve(
            query=request.question,
            top_k=request.top_k,
            top_n=request.top_n,
            role=clean_role,
        )

        raw_candidates = retrieval_res.reranked_results
        if not raw_candidates:
            return [], False, [], retrieval_res.diagnostics

        passages: list[PassageEvidence] = []
        has_conflict = False
        conflicts: list[PolicyConflict] = []

        if is_version_aware:
            # Query authorized documents and build version lineage graph
            is_postgres = self.retrieval_service.db.bind is not None and self.retrieval_service.db.bind.dialect.name == "postgresql"
            role_filter = build_role_filter(Document, clean_role, "postgresql" if is_postgres else "sqlite")
            docs = self.retrieval_service.db.query(Document).filter(role_filter).all()
            version_statuses = self.version_service.build_version_graph(docs, strict_validation=False)
            status_by_id = {s.document_id: s for s in version_statuses.values()}
            status_by_file = {s.file_name: s for s in version_statuses.values()}

            for c in raw_candidates:
                v_stat = status_by_id.get(c.document_id) or status_by_file.get(c.file_name)
                passages.append(
                    PassageEvidence(
                        index=0,  # re-indexed after sort
                        chunk_id=c.chunk_id,
                        file_name=c.file_name,
                        page_number=c.page_number,
                        text=c.text,
                        score=c.rerank_score,
                        document_title=v_stat.title if v_stat else c.title,
                        effective_date=v_stat.effective_date if v_stat else None,
                        is_superseded=v_stat.is_superseded if v_stat else False,
                        superseded_by=v_stat.superseded_by_title if v_stat else None,
                        is_partially_amended=v_stat.is_partially_amended if v_stat else False,
                        amendment_scope=v_stat.amendment_scope if v_stat else None,
                    )
                )

            # Group passages by lineage
            passages_by_lineage: dict[str, list[PassageEvidence]] = {}
            for p in passages:
                v_stat = status_by_file.get(p.file_name)
                lineage_id = v_stat.lineage_root_id if v_stat else p.file_name
                passages_by_lineage.setdefault(lineage_id, []).append(p)

            # Sort each lineage: active/current passages come first, then superseded
            for l_passages in passages_by_lineage.values():
                l_passages.sort(key=lambda p: (1 if p.is_superseded else 0, -p.score))

            # Order lineages by their highest-scoring passage descending
            sorted_lineages = sorted(
                passages_by_lineage.values(),
                key=lambda l_passages: max((p.score for p in l_passages), default=0.0),
                reverse=True,
            )

            # Flatten into final passages list and assign 1-based indices
            ordered_passages = [p for l_passages in sorted_lineages for p in l_passages]
            for idx, p in enumerate(ordered_passages, start=1):
                p.index = idx
            passages = ordered_passages

            # Detect policy conflicts in evidence
            has_conflict, conflicts = self.version_service.detect_conflicts(passages, version_statuses)

        else:
            # Baseline Phase 3 behavior without version metadata
            passages = [
                PassageEvidence(
                    index=idx,
                    chunk_id=c.chunk_id,
                    file_name=c.file_name,
                    page_number=c.page_number,
                    text=c.text,
                    score=c.rerank_score,
                    document_title=c.title,
                )
                for idx, c in enumerate(raw_candidates, start=1)
            ]

        return passages, has_conflict, conflicts, retrieval_res.diagnostics

    def answer(self, request: AskRequest) -> AskResponse:
        """Process question through retrieval, version awareness, evidence formatting, and LLM generation."""
        is_version_aware = (
            request.version_aware
            if request.version_aware is not None
            else settings.VERSION_AWARE_ENABLED
        )

        passages, has_conflict, conflicts, diagnostics = self._prepare_passages_and_conflicts(request)

        # Early abstention if no passages retrieved or below threshold
        top_score = max((p.score for p in passages), default=0.0)
        if not passages or top_score < request.abstention_threshold:
            return AskResponse(
                question=request.question,
                answer=self.ABSTENTION_SENTENCE,
                citations=[],
                passages=passages,
                abstained=True,
                has_policy_conflict=False,
                conflict_details=None,
                diagnostics=diagnostics if request.include_diagnostics else None,
            )

        # Build formatted context and prompts
        system_prompt, user_prompt = self.build_full_prompt(
            request.question, passages, version_aware=is_version_aware
        )

        # Generate answer from LLM
        raw_answer = self.llm_service.generate(prompt=user_prompt, system_prompt=system_prompt)

        # Evaluate abstention on generated output
        if self.should_abstain(raw_answer, passages, request.abstention_threshold):
            return AskResponse(
                question=request.question,
                answer=self.ABSTENTION_SENTENCE,
                citations=[],
                passages=passages,
                abstained=True,
                has_policy_conflict=False,
                conflict_details=None,
                diagnostics=diagnostics if request.include_diagnostics else None,
            )

        # Validate and extract citations
        valid_citations, invalid_indices = self.validate_citations(raw_answer, passages)

        return AskResponse(
            question=request.question,
            answer=raw_answer.strip(),
            citations=valid_citations,
            passages=passages,
            abstained=False,
            has_policy_conflict=has_conflict,
            conflict_details=conflicts if has_conflict else None,
            diagnostics=diagnostics if request.include_diagnostics else None,
        )

    def stream_answer(self, request: AskRequest) -> Generator[str, None, None]:
        """Stream answer tokens as Server-Sent Events (SSE) with version awareness and conflict metadata."""
        is_version_aware = (
            request.version_aware
            if request.version_aware is not None
            else settings.VERSION_AWARE_ENABLED
        )

        passages, has_conflict, conflicts, diagnostics = self._prepare_passages_and_conflicts(request)

        # Send passages metadata event
        metadata_payload = {
            "passages": [p.model_dump() for p in passages],
            "has_policy_conflict": has_conflict,
            "conflict_details": [c.model_dump() for c in conflicts] if has_conflict else None,
            "diagnostics": diagnostics.model_dump() if (diagnostics and request.include_diagnostics) else None,
        }
        yield f"event: metadata\ndata: {json.dumps(metadata_payload)}\n\n"

        # Check early abstention
        top_score = max((p.score for p in passages), default=0.0)
        if not passages or top_score < request.abstention_threshold:
            yield f'event: token\ndata: {json.dumps({"token": self.ABSTENTION_SENTENCE})}\n\n'
            yield f'event: citations\ndata: {json.dumps({"citations": [], "abstained": True, "has_policy_conflict": False})}\n\n'
            yield 'event: done\ndata: {}\n\n'
            return

        system_prompt, user_prompt = self.build_full_prompt(
            request.question, passages, version_aware=is_version_aware
        )
        full_tokens: list[str] = []

        for token in self.llm_service.generate_stream(prompt=user_prompt, system_prompt=system_prompt):
            full_tokens.append(token)
            yield f'event: token\ndata: {json.dumps({"token": token})}\n\n'

        complete_text = "".join(full_tokens)
        abstained = self.should_abstain(complete_text, passages, request.abstention_threshold)
        citations, _ = self.validate_citations(complete_text, passages) if not abstained else ([], [])

        citations_payload = {
            "citations": [c.model_dump() for c in citations],
            "abstained": abstained,
            "has_policy_conflict": has_conflict if not abstained else False,
            "conflict_details": [c.model_dump() for c in conflicts] if (has_conflict and not abstained) else None,
        }
        yield f"event: citations\ndata: {json.dumps(citations_payload)}\n\n"
        yield 'event: done\ndata: {}\n\n'
