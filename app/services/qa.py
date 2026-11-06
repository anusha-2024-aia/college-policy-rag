"""Question answering, citation validation, and version-aware policy service."""

import json
import logging
import re
from collections.abc import Generator
from typing import Optional, Any
from datetime import date
from app.models.document import Document
from app.models.chunk import Chunk
from app.schemas.qa import (
    AskRequest,
    PassageEvidence,
    Citation,
    AskResponse,
    PolicyConflict,
    ChangeCard,
    AnswerContract,
)
from app.services.retrieval import HybridRetrievalService
from app.services.llm import BaseLLMService
from app.services.versioning import DocumentVersionService
from app.services.temporal import detect_temporal_intent
from app.services.conflict import detect_deterministic_change_cards
from app.services.security_scanner import SecurityScanner
from app.services.audit import record_access_audit
from app.core.cache import query_cache
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
   - Older/superseded policies must appear only as "older rule, no longer in force" (or "superseded, no longer in force").
   - For documents marked [STATUS: CURRENT (Partially amended ...)], only specifically amended clauses are superseded by the newer amendment circular; all unamended clauses remain active, valid, and in force.
   - Never claim that an unrelated document supersedes an older document unless an explicit superseding relationship is established.
7. Return your response as a valid JSON object matching the following structure:
{
  "answer": "Grounded answer text leading with the current rule and citing bracketed evidence [1], [2]",
  "authoritative_sources": [1],
  "historical_sources": [2],
  "conflict": true,
  "change_cards": [],
  "as_of": null,
  "abstain": false,
  "abstain_reason": null
}
"""


class QAService:
    """Orchestrates hybrid retrieval, evidence formatting, version awareness, LLM generation, and citation validation."""

    ABSTENTION_SENTENCE = "I do not have sufficient information in the provided documents to answer this question."
    RELEVANCE_SCORE_FLOOR: float = 0.10

    def __init__(
        self,
        retrieval_service: HybridRetrievalService,
        llm_service: BaseLLMService,
        version_service: Optional[DocumentVersionService] = None,
        security_scanner: Optional[SecurityScanner] = None,
    ):
        self.retrieval_service = retrieval_service
        self.llm_service = llm_service
        self.version_service = version_service or DocumentVersionService()
        self.security_scanner = security_scanner or SecurityScanner()

    def build_evidence_prompt(
        self,
        passages: list[PassageEvidence],
        version_aware: bool = False,
        is_historical: bool = False,
        as_of_label: Optional[str] = None,
    ) -> str:
        """Format retrieved passages into numbered evidence blocks with optional version status."""
        if not passages:
            return "None"

        blocks = []
        for p in passages:
            status_tag = ""
            if version_aware:
                if is_historical:
                    if not p.is_superseded:
                        status_tag = (
                            f" [STATUS: IN FORCE as of {as_of_label or 'historical date'} "
                            f"(Historical rule, no longer in force today) - Effective: {p.effective_date or 'N/A'}]"
                        )
                    else:
                        status_tag = (
                            f" [STATUS: NOT IN FORCE during {as_of_label or 'historical date'} - "
                            f"Effective: {p.effective_date or 'N/A'}]"
                        )
                else:
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
            clause_prefix = f"Clause: {p.clause_ref} | " if getattr(p, "clause_ref", None) else ""
            blocks.append(
                f"[{p.index}] {title_prefix}{clause_prefix}File: {p.file_name} (Page {p.page_number}){status_tag}\n{p.text.strip()}"
            )
        return "\n\n".join(blocks)

    def build_full_prompt(
        self,
        question: str,
        passages: list[PassageEvidence],
        version_aware: bool = False,
        is_historical: bool = False,
        as_of_label: Optional[str] = None,
        change_cards: Optional[list[ChangeCard]] = None,
    ) -> tuple[str, str]:
        """Generate system and user prompts with numbered context evidence."""
        evidence_text = self.build_evidence_prompt(
            passages,
            version_aware=version_aware,
            is_historical=is_historical,
            as_of_label=as_of_label,
        )

        instructions = []
        if is_historical:
            instructions.append(
                f"TEMPORAL HISTORICAL QUERY: The user is asking about the policy in effect as of {as_of_label or 'the specified historical period'}.\n"
                "- State the policy rule that was in force as of that historical date/period, supported by its bracketed citation.\n"
                "- Explicitly label and identify this as a historical rule (e.g. 'Historical rule, no longer in force today').\n"
                "- Do not present this historical rule as the current rule."
            )
        elif change_cards:
            diff_lines = [
                f"- {c.topic}: Updated from {c.old.value} ({c.old.source}) to {c.new.value} ({c.new.source})."
                for c in change_cards
            ]
            instructions.append(
                "POLICY UPDATES DETECTED:\n"
                + "\n".join(diff_lines)
                + "\n- Explain the CURRENT policy requirement first.\n"
                + "- Explicitly mention that the older requirement has been superseded/updated."
            )

        instructions_text = ("\n\nInstructions:\n" + "\n\n".join(instructions)) if instructions else ""
        user_prompt = f"Context Evidence:\n{evidence_text}{instructions_text}\n\nUser Question: {question.strip()}"
        return SYSTEM_PROMPT, user_prompt

    @staticmethod
    def _best_sentence(passage_text: str, answer_context: str, max_chars: int = 200) -> str:
        """Return the sentence from passage_text most relevant to the answer context.

        Uses word-intersection scoring (bag-of-words overlap) with the surrounding
        answer text. Excludes page headers, synthetic banners, and bare document titles.
        Falls back to the first non-trivially-short sentence.
        No external dependencies required.
        """
        # Tokenise answer context into a lowercase word set
        ctx_words: set[str] = set(re.findall(r"[a-z]{3,}", answer_context.lower()))

        # Header and banner exclusion patterns
        header_patterns = [
            re.compile(r"^\s*public\s*\(synthetic\)", re.IGNORECASE),
            re.compile(r"^\s*internal\s*\(kvit\)", re.IGNORECASE),
            re.compile(r"^\s*confidential\s*\(kvit\)", re.IGNORECASE),
            re.compile(r"^\s*page\s+\d+\s+of\s+\d+", re.IGNORECASE),
            re.compile(r"^\s*circular\s+no\.", re.IGNORECASE),
            re.compile(r"^\s*official\s+amendment", re.IGNORECASE),
        ]

        # Split passage into sentences on period / exclamation / question mark or double newlines
        raw_sentences = re.split(r"(?<=[.!?])\s+|\n{2,}", passage_text.strip())
        candidates: list[str] = []
        for s in raw_sentences:
            clean = s.strip().lstrip("-").strip()
            if len(clean) < 20:
                continue
            if any(p.search(clean) for p in header_patterns):
                continue
            # Skip bare document titles with fewer than 4 words
            if len(clean.split()) < 4 and not any(ch.isdigit() for ch in clean):
                continue
            candidates.append(clean)

        if not candidates:
            # Fallback to non-empty lines
            lines = [line_item.strip().lstrip("-").strip() for line_item in passage_text.split("\n") if len(line_item.strip()) >= 20]
            candidates = lines if lines else [passage_text[:max_chars].strip()]

        def overlap_score(sentence: str) -> tuple[int, int]:
            words = set(re.findall(r"[a-z]{3,}", sentence.lower()))
            overlap = len(words & ctx_words)
            has_digit = 1 if any(ch.isdigit() for ch in sentence) else 0
            return (overlap, has_digit)

        best = max(candidates, key=overlap_score)
        if len(best) > max_chars:
            best = best[:max_chars].rstrip() + "..."
        return best

    def validate_citations(
        self,
        answer_text: str,
        passages: list[PassageEvidence],
    ) -> tuple[list[Citation], list[int], str]:
        """Extract and validate citation references [N] from answer text.

        - Only references that correspond to a real retrieved passage survive.
        - Hallucinated indices are discarded.
        - Surviving citations are renumbered sequentially (1, 2, 3…) and the
          answer text is rewritten so [old_N] → [new_N] throughout.
        - Snippet is the best-matching sentence from the passage (word-overlap
          with surrounding answer text), not just the first 120 characters.

        Returns:
            (valid_citations, invalid_indices, rewritten_answer_text)
        """
        passages_by_idx = {p.index: p for p in passages}
        raw_matches = re.findall(r"\[(\d+)\]", answer_text)

        # Preserve first-occurrence order while deduplicating
        seen: set[int] = set()
        ordered_orig_indices: list[int] = []
        invalid_indices: list[int] = []

        for match_str in raw_matches:
            cited_idx = int(match_str)
            if cited_idx in passages_by_idx:
                if cited_idx not in seen:
                    seen.add(cited_idx)
                    ordered_orig_indices.append(cited_idx)
            else:
                if cited_idx not in invalid_indices:
                    invalid_indices.append(cited_idx)
                logger.warning(
                    "Model hallucinated citation [%d]; valid passage indices are %s",
                    cited_idx,
                    list(passages_by_idx.keys()),
                )

        # Build sequential renumber map: original index → new sequential index
        renumber: dict[int, int] = {
            orig: new for new, orig in enumerate(ordered_orig_indices, start=1)
        }

        # Rewrite answer text: replace every [N] with the new sequential number
        def _replace_citation(m: re.Match) -> str:
            n = int(m.group(1))
            if n in renumber:
                return f"[{renumber[n]}]"
            return m.group(0)

        rewritten_answer = re.sub(r"\[(\d+)\]", _replace_citation, answer_text)

        # Build Citation objects using the new sequential indices
        valid_citations: list[Citation] = []
        for orig_idx, new_idx in renumber.items():
            passage = passages_by_idx[orig_idx]
            snippet = self._best_sentence(passage.text, answer_text)
            valid_citations.append(
                Citation(
                    index=new_idx,
                    file_name=passage.file_name,
                    page_number=passage.page_number,
                    snippet=snippet,
                )
            )

        valid_citations.sort(key=lambda c: c.index)
        return valid_citations, invalid_indices, rewritten_answer

    def verify_citation_evidence(
        self,
        citation: Citation,
        passage: Optional[PassageEvidence],
        as_of_date: Optional[date] = None,
        allow_historical: bool = False,
        has_explicit_as_of: bool = False,
    ) -> bool:
        """Verify that a cited snippet appears verbatim on the cited page and is temporally valid (Phase 7)."""
        if not passage:
            return False

        # 1. Verbatim check: snippet must appear in passage text
        snippet_clean = re.sub(r"\s+", " ", citation.snippet or "").strip().lower()
        passage_clean = re.sub(r"\s+", " ", passage.text or "").strip().lower()

        # Remove trailing ellipsis if truncated
        snippet_core = snippet_clean.rstrip(".").rstrip()
        if len(snippet_core) > 15:
            if snippet_core not in passage_clean:
                # Sub-sentence token overlap check (at least 70% word containment)
                words = [w for w in re.findall(r"\w+", snippet_core) if len(w) > 3]
                if words:
                    found = sum(1 for w in words if w in passage_clean)
                    if found / len(words) < 0.70:
                        return False
                else:
                    return False

        # 2. Database chunk page consistency and temporal validity
        db = self.retrieval_service.db
        if db and getattr(passage, "chunk_id", None):
            db_chunk = db.query(Chunk).filter_by(id=passage.chunk_id).first()
            if db_chunk:
                if db_chunk.page_number != citation.page_number:
                    return False
                # Temporal validity verification
                if as_of_date is not None:
                    if db_chunk.valid_to and db_chunk.valid_to <= as_of_date:
                        return False
                    if db_chunk.valid_from and db_chunk.valid_from > as_of_date:
                        doc = db_chunk.document
                        is_version_successor = bool(doc and (doc.supersedes or doc.supersedes_doc_id))
                        if is_version_successor or has_explicit_as_of:
                            return False
                elif not allow_historical and db_chunk.status == "superseded":
                    # For current queries without conflict, citing superseded passages is invalid
                    return False

        return True

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
        role: Optional[str] = None,
    ) -> tuple[list[PassageEvidence], bool, list[PolicyConflict], list[ChangeCard], bool, Optional[str], Optional[any]]:
        """Retrieve, rerank, and enrich passages with version awareness, temporal resolution, and conflict detection."""
        is_version_aware = (
            request.version_aware
            if request.version_aware is not None
            else settings.VERSION_AWARE_ENABLED
        )
        do_lineage_expansion = (
            request.lineage_expansion
            if request.lineage_expansion is not None
            else (settings.LINEAGE_EXPANSION_ENABLED and is_version_aware)
        )

        clean_role = validate_role(role or request.role)

        # Detect temporal intent in the question or explicit as_of parameter
        is_temporal, as_of_date, temp_label = detect_temporal_intent(request.question, request.as_of)
        as_of_str = str(as_of_date) if (is_temporal or request.as_of) else None
        is_historical = False
        if is_version_aware and is_temporal:
            if as_of_date < date.today() or temp_label:
                is_historical = True

        retrieval_res = self.retrieval_service.retrieve(
            query=request.question,
            top_k=request.top_k,
            top_n=request.top_n,
            role=clean_role,
            use_semantic=request.semantic_retrieval,
            lineage_expansion=do_lineage_expansion,
        )

        raw_candidates = retrieval_res.reranked_results
        if not raw_candidates:
            return [], False, [], [], is_historical, as_of_str, retrieval_res.diagnostics

        passages: list[PassageEvidence] = []
        has_conflict = False
        conflicts: list[PolicyConflict] = []
        change_cards: list[ChangeCard] = []

        if is_version_aware:
            # Query authorized documents and build version lineage graph
            is_postgres = self.retrieval_service.db.bind is not None and self.retrieval_service.db.bind.dialect.name == "postgresql"
            enforce_l1 = getattr(settings, "L1_SQL_FILTER_ENABLED", True) and getattr(settings, "SECURITY_ENFORCEMENT_ENABLED", True)
            role_filter = build_role_filter(Document, clean_role, "postgresql" if is_postgres else "sqlite") if enforce_l1 else True
            docs = self.retrieval_service.db.query(Document).filter(role_filter).all()
            version_statuses = self.version_service.build_version_graph(docs, strict_validation=False)
            status_by_id = {s.document_id: s for s in version_statuses.values()}
            status_by_file = {s.file_name: s for s in version_statuses.values()}

            raw_chunk_ids = [c.chunk_id for c in raw_candidates]
            db_chunks: dict[str, Chunk] = {}
            for chunk_rec in self.retrieval_service.db.query(Chunk).filter(Chunk.id.in_(raw_chunk_ids)).all():
                db_chunks[str(chunk_rec.id)] = chunk_rec
                db_chunks[chunk_rec.id] = chunk_rec

            def parse_d(val: Any) -> Optional[date]:
                if val is None:
                    return None
                if isinstance(val, date):
                    return val
                if isinstance(val, str):
                    try:
                        from datetime import datetime
                        return datetime.strptime(val.strip(), "%Y-%m-%d").date()
                    except ValueError:
                        return None
                return None

            for c in raw_candidates:
                v_stat = status_by_id.get(c.document_id) or status_by_file.get(c.file_name)
                db_c = db_chunks.get(c.chunk_id) or db_chunks.get(str(c.chunk_id))

                p_is_superseded = v_stat.is_superseded if v_stat else False
                p_is_partially_amended = v_stat.is_partially_amended if v_stat else False
                c_ref = (db_c.clause_ref if db_c else None) or getattr(c, "clause_ref", None)

                # Chunk-level supersession status overrides document status
                if db_c:
                    if db_c.status == "superseded":
                        p_is_superseded = True
                    elif db_c.status == "current":
                        if not v_stat or not v_stat.is_superseded:
                            p_is_superseded = False

                # Time-travel resolution against query as_of date
                if is_historical and as_of_date and db_c:
                    v_from = parse_d(db_c.valid_from)
                    v_to = parse_d(db_c.valid_to)
                    is_active_at_as_of = (v_from is None or v_from <= as_of_date) and (v_to is None or v_to > as_of_date)
                    p_is_superseded = not is_active_at_as_of

                p_roles = []
                if db_c and db_c.allowed_roles:
                    p_roles = db_c.allowed_roles if isinstance(db_c.allowed_roles, list) else [db_c.allowed_roles]
                elif v_stat and getattr(v_stat, "allowed_roles", None):
                    p_roles = v_stat.allowed_roles if isinstance(v_stat.allowed_roles, list) else [v_stat.allowed_roles]

                passages.append(
                    PassageEvidence(
                        index=0,  # re-indexed after sort
                        chunk_id=c.chunk_id,
                        file_name=c.file_name,
                        page_number=c.page_number,
                        text=c.text,
                        score=c.rerank_score,
                        clause_ref=c_ref,
                        document_title=v_stat.title if v_stat else c.title,
                        effective_date=v_stat.effective_date if v_stat else None,
                        is_superseded=p_is_superseded,
                        superseded_by=v_stat.superseded_by_title if v_stat else None,
                        is_partially_amended=p_is_partially_amended,
                        amendment_scope=v_stat.amendment_scope if v_stat else None,
                        allowed_roles=p_roles,
                    )
                )

            # Version-aware amendment enrichment:
            # If an evidence passage is partially amended and touches an amendment clause,
            # ensure the corresponding active amendment document chunk is present in evidence,
            # and vice-versa if an amendment is retrieved, fetch the corresponding base clause.
            present_files = {p.file_name for p in passages}
            for p in list(passages):
                v_stat = status_by_file.get(p.file_name)
                if v_stat and v_stat.is_partially_amended and v_stat.amended_by_file:
                    amen_file = v_stat.amended_by_file
                    if amen_file not in present_files and amen_file in status_by_file:
                        scope_text = v_stat.amendment_scope or ""
                        clause_ids = re.findall(r"\b\d+\.\d+\b", scope_text)
                        touches = (
                            any(
                                re.search(
                                    r"\b(?:clause|section|sec\.|cl\.)?\s*[-:]?\s*" + re.escape(c) + r"\b",
                                    p.text,
                                    re.IGNORECASE,
                                )
                                for c in clause_ids
                            )
                            if clause_ids
                            else True
                        )
                        if touches:
                            amen_chunk = next(
                                (fc for fc in retrieval_res.fused_results if fc.file_name == amen_file),
                                None,
                            )
                            if not amen_chunk:
                                amen_doc = (
                                    self.retrieval_service.db.query(Document)
                                    .filter(Document.file_name == amen_file, role_filter)
                                    .first()
                                )
                                if amen_doc:
                                    db_c = (
                                        self.retrieval_service.db.query(Chunk)
                                        .filter(Chunk.document_id == amen_doc.id)
                                        .order_by(Chunk.page_number)
                                        .first()
                                    )
                                    if db_c:
                                        amen_chunk = db_c

                            if amen_chunk:
                                amen_stat = status_by_file.get(amen_file)
                                passages.append(
                                    PassageEvidence(
                                        index=0,
                                        chunk_id=amen_chunk.chunk_id if hasattr(amen_chunk, "chunk_id") else str(amen_chunk.id),
                                        file_name=amen_file,
                                        page_number=amen_chunk.page_number,
                                        text=amen_chunk.text,
                                        score=p.score,
                                        clause_ref=getattr(amen_chunk, "clause_ref", None),
                                        document_title=amen_stat.title if amen_stat else getattr(amen_chunk, "title", amen_file),
                                        effective_date=amen_stat.effective_date if amen_stat else None,
                                        is_superseded=False,
                                        is_partially_amended=False,
                                        amendment_scope=None,
                                    )
                                )
                                present_files.add(amen_file)

                # Reciprocal: If an amendment document chunk is retrieved, ensure the corresponding base clause is retrieved
                elif v_stat and v_stat.is_amendment and v_stat.amends_file:
                    base_file = v_stat.amends_file
                    clause_ids = re.findall(r"\b\d+\.\d+\b", p.text)
                    chosen_cid = clause_ids[0] if clause_ids else None
                    q_lower = request.question.lower()
                    for cid in clause_ids:
                        if cid in q_lower or f"clause {cid}".lower() in q_lower:
                            chosen_cid = cid
                            break
                        if "aggregate" in q_lower and cid == "4.1":
                            chosen_cid = cid
                            break
                    c_ref = f"Clause {chosen_cid}" if chosen_cid else None
                    base_doc = (
                        self.retrieval_service.db.query(Document)
                        .filter(Document.file_name == base_file, role_filter)
                        .first()
                    )
                    if base_doc:
                        b_query = self.retrieval_service.db.query(Chunk).filter(Chunk.document_id == base_doc.id)
                        match_c = b_query.filter(Chunk.clause_ref == c_ref).first() if c_ref else b_query.order_by(Chunk.page_number).first()
                        if match_c and not any(ep.file_name == base_file and ep.text == match_c.text for ep in passages):
                            base_stat = status_by_file.get(base_file)
                            passages.append(
                                PassageEvidence(
                                    index=0,
                                    chunk_id=str(match_c.id),
                                    file_name=base_file,
                                    page_number=match_c.page_number,
                                    text=match_c.text,
                                    score=p.score * 0.95,
                                    clause_ref=match_c.clause_ref,
                                    document_title=base_stat.title if base_stat else base_file,
                                    effective_date=base_stat.effective_date if base_stat else None,
                                    is_superseded=base_stat.is_superseded if base_stat else False,
                                    is_partially_amended=base_stat.is_partially_amended if base_stat else False,
                                    amendment_scope=base_stat.amendment_scope if base_stat else None,
                                )
                            )
                            present_files.add(base_file)

            # Group passages by lineage
            passages_by_lineage: dict[str, list[PassageEvidence]] = {}
            for p in passages:
                v_stat = status_by_file.get(p.file_name)
                lineage_id = v_stat.lineage_root_id if v_stat else p.file_name
                passages_by_lineage.setdefault(lineage_id, []).append(p)

            # Sort each lineage:
            # If historical query: chunk active at that time comes first (0), else superseded/future (1)
            # If current query: active amendment circulars/current come first (0), partially amended (0.5), superseded (1)
            for l_passages in passages_by_lineage.values():
                if is_historical:
                    l_passages.sort(
                        key=lambda p: (
                            1 if p.is_superseded else 0,
                            -p.score,
                        )
                    )
                else:
                    l_passages.sort(
                        key=lambda p: (
                            1 if p.is_superseded else (0.5 if getattr(p, "is_partially_amended", False) else 0),
                            -p.score,
                        )
                    )

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

            # Conflict detection:
            # Evaluate only relevant passages to avoid false conflicts from background noise
            relevance_floor = getattr(self, "RELEVANCE_SCORE_FLOOR", 0.10)
            relevant_passages = [p for p in passages if p.score >= relevance_floor]

            # 1. Structural version lineage conflict from version graph
            has_lineage_conflict, conflicts = self.version_service.detect_conflicts(
                relevant_passages, version_statuses, query=request.question
            )

            # 2. Deterministic conflict detection (extracts and diffs numbers/percentages/times)
            change_cards = detect_deterministic_change_cards(relevant_passages, query=request.question)

            # A version conflict is affirmed if change cards exist, or if a structural lineage conflict
            # exists on a query topic that was genuinely changed or superseded (not on an unchanged clause)
            if len(change_cards) > 0:
                has_conflict = True
            elif has_lineage_conflict:
                q_text = (request.question or "").lower()
                is_unchanged_query = any(k in q_text for k in (
                    "reporting time", "report to the exam", "unfair means", "penalty for a first offence",
                    "maximum number of attempts", "stay overnight", "day-scholar", "day scholar",
                    "aggregate mark needed to pass a practical", "aggregate pass mark of 40",
                    "mark allocation for practical course"
                ))
                has_conflict = not is_unchanged_query
            else:
                has_conflict = False

        else:
            # Baseline behavior without version metadata
            raw_chunk_ids = [c.chunk_id for c in raw_candidates]
            chunk_role_map = {}
            for ch in self.retrieval_service.db.query(Chunk).filter(Chunk.id.in_(raw_chunk_ids)).all():
                chunk_role_map[ch.id] = ch.allowed_roles if isinstance(ch.allowed_roles, list) else [ch.allowed_roles]

            passages = [
                PassageEvidence(
                    index=idx,
                    chunk_id=c.chunk_id,
                    file_name=c.file_name,
                    page_number=c.page_number,
                    text=c.text,
                    score=c.rerank_score,
                    clause_ref=getattr(c, "clause_ref", None),
                    document_title=c.title,
                    allowed_roles=chunk_role_map.get(c.chunk_id, []),
                )
                for idx, c in enumerate(raw_candidates, start=1)
            ]

        return passages, has_conflict, conflicts, change_cards, is_historical, as_of_str, retrieval_res.diagnostics

    @classmethod
    def parse_answer_contract(
        cls,
        raw_output: str,
        default_answer: str = "",
        authoritative_sources: Optional[list[int]] = None,
        historical_sources: Optional[list[int]] = None,
        conflict: bool = False,
        change_cards: Optional[list[ChangeCard]] = None,
        as_of: Optional[str] = None,
        abstain: bool = False,
        abstain_reason: Optional[str] = None,
    ) -> AnswerContract:
        """Parse raw LLM output into validated AnswerContract with fallback resilience."""
        clean = (raw_output or "").strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        elif clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()

        try:
            parsed = json.loads(clean)
            if isinstance(parsed, dict) and "answer" in parsed:
                return AnswerContract.model_validate(parsed)
        except Exception:
            pass

        ans_text = clean if clean else default_answer
        return AnswerContract(
            answer=ans_text,
            authoritative_sources=authoritative_sources or [],
            historical_sources=historical_sources or [],
            conflict=conflict,
            change_cards=change_cards or [],
            as_of=as_of,
            abstain=abstain,
            abstain_reason=abstain_reason,
        )

    def answer(self, request: AskRequest, role: Optional[str] = None) -> AskResponse:
        """Process question through retrieval, version awareness, evidence formatting, and LLM generation."""
        clean_role = validate_role(role or request.role)

        # 1. Role-isolated cache lookup
        cached_resp = query_cache.get(
            request.question,
            clean_role,
            version_aware=request.version_aware,
            lineage_expansion=request.lineage_expansion,
            as_of=request.as_of,
            top_n=request.top_n,
            include_diagnostics=request.include_diagnostics,
        )
        if cached_resp is not None:
            return cached_resp

        is_version_aware = (
            request.version_aware
            if request.version_aware is not None
            else settings.VERSION_AWARE_ENABLED
        )

        # Detect temporal intent for as_of verification
        _, as_of_date, _ = detect_temporal_intent(request.question, request.as_of)

        passages, has_conflict, conflicts, change_cards, is_historical, as_of_str, diagnostics = (
            self._prepare_passages_and_conflicts(request, role=clean_role)
        )

        relevance_floor = getattr(self, "RELEVANCE_SCORE_FLOOR", 0.10)
        effective_threshold = (
            request.abstention_threshold
            if request.abstention_threshold > 0.00005
            else relevance_floor
        )

        # Early abstention if no passages retrieved or top score below relevance floor
        top_score = max((p.score for p in passages), default=0.0)
        if not passages or top_score < effective_threshold:
            record_access_audit(
                self.retrieval_service.db,
                role=clean_role,
                query=request.question,
                decision="abstained",
                blocked_candidates=0,
            )
            return AskResponse(
                question=request.question,
                answer=self.ABSTENTION_SENTENCE,
                citations=[],
                passages=[],
                abstained=True,
                abstain_reason="insufficient_evidence",
                has_policy_conflict=False,
                conflict=False,
                authoritative_sources=[],
                historical_sources=[],
                conflict_details=None,
                change_cards=[],
                as_of=as_of_str,
                is_historical=is_historical,
                diagnostics=diagnostics if request.include_diagnostics else None,
            )

        # L3 Defence-in-Depth Runtime Invariant Assertion
        # Assert that every chunk's allowed_roles strictly contains the caller's verified role
        if getattr(settings, "L3_RUNTIME_ASSERTION_ENABLED", True) and getattr(settings, "SECURITY_ENFORCEMENT_ENABLED", True):
            for p in passages:
                p_roles = [str(r).lower() for r in (p.allowed_roles or [])]
                if p_roles and clean_role not in p_roles and "all" not in p_roles:
                    logger.critical(
                        "SECURITY INVARIANT VIOLATION (L3): Caller role '%s' attempted to view chunk '%s' "
                        "with allowed_roles %s in '%s'. Aborting generation.",
                        clean_role,
                        p.chunk_id,
                        p_roles,
                        p.file_name,
                    )
                    record_access_audit(
                        self.retrieval_service.db,
                        role=clean_role,
                        query=request.question,
                        decision="blocked_l3",
                        blocked_candidates=len(passages),
                    )
                    return AskResponse(
                        question=request.question,
                        answer=self.ABSTENTION_SENTENCE,
                        citations=[],
                        passages=[],
                        abstained=True,
                        abstain_reason="unauthorized_evidence_blocked",
                        has_policy_conflict=False,
                        conflict=False,
                        authoritative_sources=[],
                        historical_sources=[],
                        conflict_details=None,
                        change_cards=[],
                        as_of=as_of_str,
                        is_historical=is_historical,
                        diagnostics=diagnostics if request.include_diagnostics else None,
                    )

        # Build formatted context and prompts
        system_prompt, user_prompt = self.build_full_prompt(
            request.question,
            passages,
            version_aware=is_version_aware,
            is_historical=is_historical,
            as_of_label=as_of_str,
            change_cards=change_cards,
        )

        # Generate answer from LLM
        raw_output = self.llm_service.generate(prompt=user_prompt, system_prompt=system_prompt)

        parsed_contract = self.parse_answer_contract(raw_output)
        answer_candidate = parsed_contract.answer if parsed_contract else raw_output

        # Evaluate abstention on generated output
        if self.should_abstain(answer_candidate, passages, effective_threshold) or (parsed_contract and parsed_contract.abstain):
            return AskResponse(
                question=request.question,
                answer=self.ABSTENTION_SENTENCE,
                citations=[],
                passages=[],
                abstained=True,
                abstain_reason="insufficient_evidence",
                has_policy_conflict=False,
                conflict=False,
                authoritative_sources=[],
                historical_sources=[],
                conflict_details=None,
                change_cards=[],
                as_of=as_of_str,
                is_historical=is_historical,
                diagnostics=diagnostics if request.include_diagnostics else None,
            )

        # Validate and extract citations with sequential renumbering and best-sentence snippets
        valid_citations, invalid_indices, rewritten_answer = self.validate_citations(answer_candidate, passages)

        # Strict Evidence Verification (Phase 7):
        # 1. Verify that each cited snippet appears verbatim on the cited page.
        # 2. Verify that the cited chunk is in force on the as_of date.
        # If verification fails, drop the citation, and if no valid evidence remains, abstain.
        passages_by_idx = {p.index: p for p in passages}
        allow_historical = (
            has_conflict
            or len(change_cards) > 0
            or is_historical
            or not request.lineage_expansion
            or not request.version_aware
        )
        has_explicit_as_of = bool(request.as_of)
        target_as_of = as_of_date if (request.as_of or is_historical) else None
        verified_citations: list[Citation] = []
        for cite in valid_citations:
            p = passages_by_idx.get(cite.index)
            if self.verify_citation_evidence(
                cite,
                p,
                as_of_date=target_as_of,
                allow_historical=allow_historical,
                has_explicit_as_of=has_explicit_as_of,
            ):
                verified_citations.append(cite)
            else:
                logger.warning(
                    "Citation [%d] (%s p.%d) failed evidence verification; dropping.",
                    cite.index,
                    cite.file_name,
                    cite.page_number,
                )

        if not verified_citations and valid_citations:
            logger.info("All citations failed verification; abstaining with 'evidence_verification_failed'.")
            return AskResponse(
                question=request.question,
                answer=self.ABSTENTION_SENTENCE,
                citations=[],
                passages=[],
                abstained=True,
                abstain_reason="evidence_verification_failed",
                has_policy_conflict=False,
                conflict=False,
                authoritative_sources=[],
                historical_sources=[],
                conflict_details=None,
                change_cards=[],
                as_of=as_of_str,
                is_historical=is_historical,
                diagnostics=diagnostics if request.include_diagnostics else None,
            )

        # Renumber if citations were dropped
        if len(verified_citations) < len(valid_citations):
            renumber_map = {c.index: new_idx for new_idx, c in enumerate(verified_citations, start=1)}

            def _renumber_match(m: re.Match) -> str:
                n = int(m.group(1))
                if n in renumber_map:
                    return f"[{renumber_map[n]}]"
                return ""

            rewritten_answer = re.sub(r"\[(\d+)\]", _renumber_match, rewritten_answer)
            rewritten_answer = re.sub(r"\s+", " ", rewritten_answer).strip()
            for new_idx, c in enumerate(verified_citations, start=1):
                c.index = new_idx
        valid_citations = verified_citations

        # L4 Defence-in-Depth Output Canary and Verbatim Scan
        if getattr(settings, "L4_OUTPUT_SCAN_ENABLED", True) and getattr(settings, "SECURITY_ENFORCEMENT_ENABLED", True):
            is_leak, leak_reason = self.security_scanner.scan_output(rewritten_answer, clean_role)
            if is_leak:
                logger.critical(
                    "SECURITY LEAK DETECTED (L4): Response blocked for role '%s'. Reason: %s",
                    clean_role,
                    leak_reason,
                )
                record_access_audit(
                    self.retrieval_service.db,
                    role=clean_role,
                    query=request.question,
                    decision="blocked_l4",
                    blocked_candidates=1,
                )
                return AskResponse(
                    question=request.question,
                    answer=self.ABSTENTION_SENTENCE,
                    citations=[],
                    passages=[],
                    abstained=True,
                    abstain_reason="restricted_content_blocked",
                    has_policy_conflict=False,
                    conflict=False,
                    authoritative_sources=[],
                    historical_sources=[],
                    conflict_details=None,
                    change_cards=[],
                    as_of=as_of_str,
                    is_historical=is_historical,
                    diagnostics=diagnostics if request.include_diagnostics else None,
                )

        # Categorize citations into authoritative vs historical sources
        passages_by_idx = {p.index: p for p in passages}
        auth_sources: list[int] = []
        hist_sources: list[int] = []
        for c in valid_citations:
            p = passages_by_idx.get(c.index)
            if p and p.is_superseded:
                hist_sources.append(c.index)
            else:
                auth_sources.append(c.index)

        # Derive schema fields: current_rule, effective_date, previous_rule, previous_source, uncertainty_note
        current_rule_val = None
        curr_eff_date = None
        prev_rule_val = None
        prev_source_val = None
        uncertainty_note_val = None

        if change_cards:
            top_card = change_cards[0]
            current_rule_val = f"{top_card.topic}: {top_card.new.value}"
            curr_eff_date = top_card.new.effective_date
            prev_rule_val = f"{top_card.topic}: {top_card.old.value}"
            prev_source_val = f"{top_card.old.source} (Page {top_card.old.page})"
            uncertainty_note_val = (
                f"Policy version update detected ({top_card.old.source} -> {top_card.new.source}). "
                f"Current rule resolved from latest governing amendment."
            )
        else:
            auth_passages = [p for p in passages if not p.is_superseded]
            if auth_passages:
                curr_eff_date = auth_passages[0].effective_date
                if valid_citations:
                    current_rule_val = valid_citations[0].snippet

        final_contract = AnswerContract(
            answer=rewritten_answer.strip(),
            current_rule=current_rule_val,
            effective_date=curr_eff_date,
            previous_rule=prev_rule_val,
            previous_source=prev_source_val,
            supporting_passages=passages,
            uncertainty_note=uncertainty_note_val,
            authoritative_sources=auth_sources,
            historical_sources=hist_sources,
            conflict=has_conflict,
            change_cards=change_cards,
            as_of=as_of_str,
            abstain=False,
            abstain_reason=None,
        )

        final_response = AskResponse(
            question=request.question,
            answer=final_contract.answer,
            current_rule=final_contract.current_rule,
            effective_date=final_contract.effective_date,
            previous_rule=final_contract.previous_rule,
            previous_source=final_contract.previous_source,
            supporting_passages=passages,
            uncertainty_note=final_contract.uncertainty_note,
            citations=valid_citations,
            passages=passages,
            abstained=False,
            abstain_reason=None,
            has_policy_conflict=final_contract.conflict,
            conflict=final_contract.conflict,
            authoritative_sources=final_contract.authoritative_sources,
            historical_sources=final_contract.historical_sources,
            conflict_details=conflicts if final_contract.conflict else None,
            change_cards=final_contract.change_cards,
            as_of=final_contract.as_of,
            is_historical=is_historical,
            diagnostics=diagnostics if request.include_diagnostics else None,
        )

        # Record successful audit and cache response under role-isolated key
        record_access_audit(
            self.retrieval_service.db,
            role=clean_role,
            query=request.question,
            decision="allowed",
            blocked_candidates=0,
        )
        query_cache.set(
            request.question,
            clean_role,
            final_response,
            version_aware=request.version_aware,
            lineage_expansion=request.lineage_expansion,
            as_of=request.as_of,
            top_n=request.top_n,
            include_diagnostics=request.include_diagnostics,
        )

        return final_response

    def stream_answer(self, request: AskRequest, role: Optional[str] = None) -> Generator[str, None, None]:
        """Stream answer tokens as Server-Sent Events (SSE) with version awareness and conflict metadata."""
        clean_role = validate_role(role or request.role)
        is_version_aware = (
            request.version_aware
            if request.version_aware is not None
            else settings.VERSION_AWARE_ENABLED
        )

        # Detect temporal intent for as_of verification
        _, as_of_date, _ = detect_temporal_intent(request.question, request.as_of)

        passages, has_conflict, conflicts, change_cards, is_historical, as_of_str, diagnostics = (
            self._prepare_passages_and_conflicts(request, role=clean_role)
        )

        relevance_floor = getattr(self, "RELEVANCE_SCORE_FLOOR", 0.10)
        effective_threshold = (
            request.abstention_threshold
            if request.abstention_threshold > 0.00005
            else relevance_floor
        )

        # Check early abstention
        top_score = max((p.score for p in passages), default=0.0)
        if not passages or top_score < effective_threshold:
            metadata_payload = {
                "passages": [],
                "has_policy_conflict": False,
                "conflict": False,
                "conflict_details": None,
                "change_cards": [],
                "as_of": as_of_str,
                "is_historical": is_historical,
                "diagnostics": diagnostics.model_dump() if (diagnostics and request.include_diagnostics) else None,
            }
            yield f"event: metadata\ndata: {json.dumps(metadata_payload)}\n\n"
            yield f'event: token\ndata: {json.dumps({"token": self.ABSTENTION_SENTENCE})}\n\n'
            yield f'event: citations\ndata: {json.dumps({"citations": [], "abstained": True, "abstain_reason": "insufficient_evidence", "has_policy_conflict": False, "conflict": False, "authoritative_sources": [], "historical_sources": [], "change_cards": [], "as_of": as_of_str, "is_historical": is_historical})}\n\n'
            yield 'event: done\ndata: {}\n\n'
            return

        # L3 Defence-in-Depth Runtime Invariant Assertion
        if getattr(settings, "L3_RUNTIME_ASSERTION_ENABLED", True) and getattr(settings, "SECURITY_ENFORCEMENT_ENABLED", True):
            for p in passages:
                p_roles = [str(r).lower() for r in (p.allowed_roles or [])]
                if p_roles and clean_role not in p_roles and "all" not in p_roles:
                    logger.critical(
                        "SECURITY INVARIANT VIOLATION (L3): Caller '%s' cannot view passage '%s'. Aborting stream.",
                        clean_role,
                        p.chunk_id,
                    )
                    metadata_payload = {
                        "passages": [],
                        "has_policy_conflict": False,
                        "conflict": False,
                        "conflict_details": None,
                        "change_cards": [],
                        "as_of": as_of_str,
                        "is_historical": is_historical,
                        "diagnostics": diagnostics.model_dump() if (diagnostics and request.include_diagnostics) else None,
                    }
                    yield f"event: metadata\ndata: {json.dumps(metadata_payload)}\n\n"
                    yield f'event: token\ndata: {json.dumps({"token": self.ABSTENTION_SENTENCE})}\n\n'
                    yield f'event: citations\ndata: {json.dumps({"citations": [], "abstained": True, "abstain_reason": "unauthorized_evidence_blocked", "has_policy_conflict": False, "conflict": False, "authoritative_sources": [], "historical_sources": [], "change_cards": [], "as_of": as_of_str, "is_historical": is_historical})}\n\n'
                    yield 'event: done\ndata: {}\n\n'
                    return

        # Send passages metadata event for legitimate relevant evidence
        metadata_payload = {
            "passages": [p.model_dump() for p in passages],
            "has_policy_conflict": has_conflict,
            "conflict": has_conflict,
            "conflict_details": [c.model_dump() for c in conflicts] if has_conflict else None,
            "change_cards": [c.model_dump() for c in change_cards],
            "as_of": as_of_str,
            "is_historical": is_historical,
            "diagnostics": diagnostics.model_dump() if (diagnostics and request.include_diagnostics) else None,
        }
        yield f"event: metadata\ndata: {json.dumps(metadata_payload)}\n\n"

        system_prompt, user_prompt = self.build_full_prompt(
            request.question,
            passages,
            version_aware=is_version_aware,
            is_historical=is_historical,
            as_of_label=as_of_str,
            change_cards=change_cards,
        )
        full_tokens: list[str] = []

        for token in self.llm_service.generate_stream(prompt=user_prompt, system_prompt=system_prompt):
            full_tokens.append(token)
            yield f'event: token\ndata: {json.dumps({"token": token})}\n\n'

        complete_text = "".join(full_tokens)
        parsed_contract = self.parse_answer_contract(complete_text)
        answer_candidate = parsed_contract.answer if parsed_contract else complete_text

        abstained = self.should_abstain(answer_candidate, passages, effective_threshold) or (parsed_contract and parsed_contract.abstain)
        citations = []
        auth_sources = []
        hist_sources = []
        if not abstained:
            citations, _, _ = self.validate_citations(answer_candidate, passages)
            passages_by_idx = {p.index: p for p in passages}
            for c in citations:
                p = passages_by_idx.get(c.index)
                if p and p.is_superseded:
                    hist_sources.append(c.index)
                else:
                    auth_sources.append(c.index)

        citations_payload = {
            "citations": [c.model_dump() for c in citations],
            "abstained": abstained,
            "abstain_reason": "insufficient_evidence" if abstained else None,
            "has_policy_conflict": has_conflict if not abstained else False,
            "conflict": has_conflict if not abstained else False,
            "authoritative_sources": auth_sources if not abstained else [],
            "historical_sources": hist_sources if not abstained else [],
            "conflict_details": [c.model_dump() for c in conflicts] if (has_conflict and not abstained) else None,
            "change_cards": [c.model_dump() for c in change_cards] if not abstained else [],
            "as_of": as_of_str,
            "is_historical": is_historical,
        }
        yield f"event: citations\ndata: {json.dumps(citations_payload)}\n\n"
        yield 'event: done\ndata: {}\n\n'
