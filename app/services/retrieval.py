"""Hybrid retrieval service combining pgvector cosine search, full-text search, RRF, and reranking."""

import logging
import math
import re
import time
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.document import Document
from app.models.chunk import Chunk
from app.schemas.retrieval import (
    ScoredChunk,
    FusedChunk,
    RerankedChunk,
    RetrievalDiagnostics,
    RetrievalResponse,
)
from app.services.embedding import BaseEmbeddingService, get_embedding_service
from app.services.reranker import BaseRerankerService, get_reranker_service
from app.core.config import settings
from app.core.roles import validate_role, build_role_filter, InvalidRoleError

logger = logging.getLogger(__name__)


# Role-Based Access Control (RBAC) enforced in all SQL queries below.


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    dot = sum(a * b for a, b in zip(vec1, vec2, strict=False))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


FTS_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he",
    "in", "is", "it", "its", "of", "on", "that", "the", "to", "was", "were",
    "will", "with", "what", "where", "when", "who", "how", "why", "which",
    "does", "can", "could", "should", "would", "about", "regarding", "take",
    "place", "event", "say", "said", "tell", "have", "had", "do", "did", "or",
}


def build_disjunctive_tsquery(query: str) -> Optional[str]:
    """Convert conversational natural-language question into a disjunctive tsquery string.

    Strips conversational stop words, extracts clean alphanumeric tokens, and joins with
    the '|' operator for robust full-text recall under ts_rank ordering.
    """
    raw_tokens = re.findall(r"\b\w+\b", query)
    cleaned = [re.sub(r"[^\w]", "", t.lower()) for t in raw_tokens]
    # Filter out conversational stop words and single-character tokens
    content_tokens = [t for t in cleaned if len(t) >= 2 and t not in FTS_STOP_WORDS]
    if not content_tokens:
        content_tokens = [t for t in cleaned if len(t) >= 2]
    if not content_tokens:
        content_tokens = cleaned
    return " | ".join(content_tokens) if content_tokens else None


class HybridRetrievalService:
    """Orchestrates vector search, keyword search, Reciprocal Rank Fusion, and reranking."""

    def __init__(
        self,
        db_session: Session,
        embedding_service: Optional[BaseEmbeddingService] = None,
        reranker_service: Optional[BaseRerankerService] = None,
        rrf_k: int = 60,
    ):
        self.db = db_session
        self.embedding_service = embedding_service or get_embedding_service()
        self.reranker_service = reranker_service or get_reranker_service()
        self.rrf_k = rrf_k or settings.RRF_K

    def vector_search(self, query: str, k: int = 20, role: str = "student") -> list[ScoredChunk]:
        """Retrieve top k chunks by vector cosine distance filtered strictly by authorized role.

        Enforces role-based SQL access control directly inside the database query before candidates
        are ranked or passed to downstream fusion.
        """
        if not query.strip() or k <= 0:
            return []

        clean_role = validate_role(role)
        query_vec = self.embedding_service.embed_query(query)
        is_postgres = self.db.bind is not None and self.db.bind.dialect.name == "postgresql"
        role_filter = build_role_filter(Document, clean_role, "postgresql" if is_postgres else "sqlite")

        scored_chunks: list[ScoredChunk] = []

        if is_postgres:
            # Native PostgreSQL + pgvector cosine distance filtered by authorized role
            distance_expr = Chunk.embedding.cosine_distance(query_vec).label("distance")
            results = (
                self.db.query(Chunk, Document, distance_expr)
                .join(Document, Chunk.document_id == Document.id)
                .filter(role_filter)
                .order_by(distance_expr.asc())
                .limit(k)
                .all()
            )

            for rank_idx, (chunk, doc, distance) in enumerate(results, start=1):
                # Convert distance to similarity score
                similarity = round(max(0.0, 1.0 - float(distance)), 4)
                scored_chunks.append(
                    ScoredChunk(
                        chunk_id=chunk.id,
                        document_id=doc.id,
                        file_name=doc.file_name,
                        title=doc.title,
                        page_number=chunk.page_number,
                        text=chunk.text,
                        score=similarity,
                        rank=rank_idx,
                    )
                )
        else:
            # In-memory cosine similarity fallback filtered by authorized role in SQL
            chunks_with_doc = (
                self.db.query(Chunk, Document)
                .join(Document, Chunk.document_id == Document.id)
                .filter(role_filter)
                .all()
            )

            candidate_scores: list[tuple[float, Chunk, Document]] = []
            for chunk, doc in chunks_with_doc:
                sim = cosine_similarity(query_vec, chunk.embedding)
                clamped_sim = max(0.0, sim)
                candidate_scores.append((clamped_sim, chunk, doc))

            candidate_scores.sort(key=lambda x: x[0], reverse=True)

            for rank_idx, (sim, chunk, doc) in enumerate(candidate_scores[:k], start=1):
                scored_chunks.append(
                    ScoredChunk(
                        chunk_id=chunk.id,
                        document_id=doc.id,
                        file_name=doc.file_name,
                        title=doc.title,
                        page_number=chunk.page_number,
                        text=chunk.text,
                        score=round(sim, 4),
                        rank=rank_idx,
                    )
                )

        return scored_chunks

    def keyword_search(self, query: str, k: int = 20, role: str = "student") -> list[ScoredChunk]:
        """Retrieve matching passages using full-text search filtered strictly by authorized role.

        Enforces role-based SQL access control directly inside the database query before candidates
        are ranked or passed to downstream fusion.
        """
        cleaned_query = query.strip()
        if not cleaned_query or k <= 0:
            return []

        clean_role = validate_role(role)
        is_postgres = self.db.bind is not None and self.db.bind.dialect.name == "postgresql"
        role_filter = build_role_filter(Document, clean_role, "postgresql" if is_postgres else "sqlite")
        scored_chunks: list[ScoredChunk] = []

        if is_postgres:
            disjunctive_str = build_disjunctive_tsquery(cleaned_query)
            if disjunctive_str:
                ts_query = func.to_tsquery("english", disjunctive_str)
            else:
                ts_query = func.plainto_tsquery("english", cleaned_query)
            rank_score = func.ts_rank(Chunk.tsv, ts_query).label("ts_rank")

            results = (
                self.db.query(Chunk, Document, rank_score)
                .join(Document, Chunk.document_id == Document.id)
                .filter(Chunk.tsv.op("@@")(ts_query))
                .filter(role_filter)
                .order_by(rank_score.desc())
                .limit(k)
                .all()
            )

            for rank_idx, (chunk, doc, score) in enumerate(results, start=1):
                scored_chunks.append(
                    ScoredChunk(
                        chunk_id=chunk.id,
                        document_id=doc.id,
                        file_name=doc.file_name,
                        title=doc.title,
                        page_number=chunk.page_number,
                        text=chunk.text,
                        score=round(float(score), 4),
                        rank=rank_idx,
                    )
                )
        else:
            # Fallback lexical term matching filtered by authorized role in SQL
            query_tokens = [w.lower() for w in re.findall(r"\w+", cleaned_query) if len(w) > 2]
            if not query_tokens:
                query_tokens = [cleaned_query.lower()]

            chunks_with_doc = (
                self.db.query(Chunk, Document)
                .join(Document, Chunk.document_id == Document.id)
                .filter(role_filter)
                .all()
            )

            matched_scores: list[tuple[float, Chunk, Document]] = []
            for chunk, doc in chunks_with_doc:
                text_lower = chunk.text.lower()
                matches = sum(text_lower.count(token) for token in query_tokens)
                if matches > 0:
                    score = float(matches) / max(len(text_lower.split()), 1)
                    matched_scores.append((score, chunk, doc))

            matched_scores.sort(key=lambda x: x[0], reverse=True)

            for rank_idx, (score, chunk, doc) in enumerate(matched_scores[:k], start=1):
                scored_chunks.append(
                    ScoredChunk(
                        chunk_id=chunk.id,
                        document_id=doc.id,
                        file_name=doc.file_name,
                        title=doc.title,
                        page_number=chunk.page_number,
                        text=chunk.text,
                        score=round(score, 4),
                        rank=rank_idx,
                    )
                )

        return scored_chunks

    def rrf_fuse(
        self,
        vector_results: list[ScoredChunk],
        keyword_results: list[ScoredChunk],
        k_rrf: Optional[int] = None,
    ) -> list[FusedChunk]:
        """Combine rankings using Reciprocal Rank Fusion (RRF).

        Formula: RRF_score(d) = sum_{m in {vector, keyword}} 1 / (k_rrf + rank_m(d))
        """
        constant = k_rrf if k_rrf is not None else self.rrf_k
        if constant <= 0:
            raise ValueError(f"k_rrf constant must be positive, got {constant}")

        # Map chunk_id to candidate data and score accumulators
        candidates: dict[str, dict] = {}

        for v_chunk in vector_results:
            cid = v_chunk.chunk_id
            rrf_val = 1.0 / (constant + v_chunk.rank)
            candidates[cid] = {
                "chunk_id": cid,
                "document_id": v_chunk.document_id,
                "file_name": v_chunk.file_name,
                "title": v_chunk.title,
                "page_number": v_chunk.page_number,
                "text": v_chunk.text,
                "vector_rank": v_chunk.rank,
                "keyword_rank": None,
                "vector_score": v_chunk.score,
                "keyword_score": None,
                "rrf_score": rrf_val,
            }

        for k_chunk in keyword_results:
            cid = k_chunk.chunk_id
            rrf_val = 1.0 / (constant + k_chunk.rank)

            if cid in candidates:
                # Merge duplicate candidate found in both vector and keyword search
                candidates[cid]["keyword_rank"] = k_chunk.rank
                candidates[cid]["keyword_score"] = k_chunk.score
                candidates[cid]["rrf_score"] += rrf_val
            else:
                candidates[cid] = {
                    "chunk_id": cid,
                    "document_id": k_chunk.document_id,
                    "file_name": k_chunk.file_name,
                    "title": k_chunk.title,
                    "page_number": k_chunk.page_number,
                    "text": k_chunk.text,
                    "vector_rank": None,
                    "keyword_rank": k_chunk.rank,
                    "vector_score": None,
                    "keyword_score": k_chunk.score,
                    "rrf_score": rrf_val,
                }

        # Sort candidates descending by combined RRF score
        sorted_candidates = sorted(
            candidates.values(),
            key=lambda x: x["rrf_score"],
            reverse=True,
        )

        fused_chunks: list[FusedChunk] = []
        for rank_idx, item in enumerate(sorted_candidates, start=1):
            fused_chunks.append(
                FusedChunk(
                    chunk_id=item["chunk_id"],
                    document_id=item["document_id"],
                    file_name=item["file_name"],
                    title=item["title"],
                    page_number=item["page_number"],
                    text=item["text"],
                    vector_rank=item["vector_rank"],
                    keyword_rank=item["keyword_rank"],
                    vector_score=item["vector_score"],
                    keyword_score=item["keyword_score"],
                    rrf_score=round(item["rrf_score"], 6),
                    fused_rank=rank_idx,
                )
            )

        return fused_chunks

    def rerank(
        self,
        query: str,
        candidates: list[FusedChunk],
        top_n: int = 5,
    ) -> list[RerankedChunk]:
        """Reorder candidate chunks using the configured reranker."""
        return self.reranker_service.rerank(query, candidates, top_n=top_n)

    def retrieve(
        self,
        query: str,
        top_k: int = 20,
        top_n: int = 5,
        k_rrf: Optional[int] = None,
        role: str = "student",
    ) -> RetrievalResponse:
        """Execute full hybrid retrieval pipeline returning authorized passages and diagnostics."""
        clean_role = validate_role(role)
        timings: dict[str, float] = {}

        # 1. Vector Search (filtered by authorized role)
        t0 = time.perf_counter()
        vector_results = self.vector_search(query, k=top_k, role=clean_role)
        timings["vector_search_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        # 2. Keyword Search (filtered by authorized role)
        t1 = time.perf_counter()
        keyword_results = self.keyword_search(query, k=top_k, role=clean_role)
        timings["keyword_search_ms"] = round((time.perf_counter() - t1) * 1000, 2)

        # 3. Reciprocal Rank Fusion
        t2 = time.perf_counter()
        fused_results = self.rrf_fuse(vector_results, keyword_results, k_rrf=k_rrf)
        timings["rrf_fusion_ms"] = round((time.perf_counter() - t2) * 1000, 2)

        # 4. Reranking
        t3 = time.perf_counter()
        reranked_results = self.rerank(query, fused_results, top_n=top_n)
        timings["reranking_ms"] = round((time.perf_counter() - t3) * 1000, 2)

        timings["total_retrieval_ms"] = round(sum(timings.values()), 2)

        diagnostics = RetrievalDiagnostics(
            vector_count=len(vector_results),
            keyword_count=len(keyword_results),
            fused_count=len(fused_results),
            reranked_count=len(reranked_results),
            timings_ms=timings,
        )

        return RetrievalResponse(
            query=query,
            vector_results=vector_results,
            keyword_results=keyword_results,
            fused_results=fused_results,
            reranked_results=reranked_results,
            diagnostics=diagnostics,
        )
