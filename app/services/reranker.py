"""Reranker service for re-ordering hybrid retrieval candidates."""

import abc
import logging
import re
from typing import Optional
from app.core.config import settings
from app.schemas.retrieval import FusedChunk, RerankedChunk

logger = logging.getLogger(__name__)


class BaseRerankerService(abc.ABC):
    """Abstract interface for reranking candidate passages."""

    @abc.abstractmethod
    def rerank(
        self,
        query: str,
        candidates: list[FusedChunk],
        top_n: int = 5,
    ) -> list[RerankedChunk]:
        """Reorder candidates according to query relevance and return top_n items."""
        pass


class MockRerankerService(BaseRerankerService):
    """Deterministic, CPU-only reranker for offline and test environments.

    Scores candidate passages using query-document lexical overlap, exact phrase bonuses,
    and prior RRF fusion signals, returning normalized scores without requiring GPU models.
    """

    def rerank(
        self,
        query: str,
        candidates: list[FusedChunk],
        top_n: int = 5,
    ) -> list[RerankedChunk]:
        """Rerank candidates using deterministic lexical and positional weighting."""
        if not candidates or top_n <= 0:
            return []

        stopwords = {
            "what", "is", "the", "for", "an", "and", "under", "per", "a", "in", "of", "to", "at", "by",
            "from", "with", "about", "as", "into", "like", "through", "after", "over", "between", "out",
            "against", "during", "without", "before", "around", "among", "how", "why", "when", "where",
            "which", "who", "whom", "this", "that", "these", "those", "does", "do", "did", "are", "be",
            "been", "being", "have", "has", "had", "can", "could", "should", "would", "may", "might",
            "must", "shall", "will", "much", "many", "more",
        }
        all_query_tokens = [w for w in re.findall(r"\w+", query.lower()) if len(w) >= 3]
        content_query_tokens = [w for w in all_query_tokens if w not in stopwords]
        tokens_to_match = set(content_query_tokens) if content_query_tokens else set(all_query_tokens)

        scored_items: list[tuple[float, FusedChunk]] = []

        for candidate in candidates:
            chunk_tokens = set(re.findall(r"\w+", candidate.text.lower()))
            overlap_count = len(tokens_to_match.intersection(chunk_tokens))
            lexical_ratio = overlap_count / max(len(tokens_to_match), 1)

            if lexical_ratio < 0.40:
                rerank_score = 0.0001
            else:
                phrase_bonus = 0.2 if query.lower() in candidate.text.lower() else 0.0
                rrf_component = candidate.rrf_score * 0.5
                raw_score = (lexical_ratio * 0.7) + phrase_bonus + rrf_component
                rerank_score = round(min(max(raw_score, 0.01), 0.9999), 4)

            scored_items.append((rerank_score, candidate))

        # Sort descending by rerank score, breaking ties with prior rrf_score
        scored_items.sort(key=lambda item: (item[0], item[1].rrf_score), reverse=True)

        reranked_chunks: list[RerankedChunk] = []
        for idx, (score, candidate) in enumerate(scored_items[:top_n], start=1):
            reranked_chunks.append(
                RerankedChunk(
                    chunk_id=candidate.chunk_id,
                    document_id=candidate.document_id,
                    file_name=candidate.file_name,
                    title=candidate.title,
                    page_number=candidate.page_number,
                    text=candidate.text,
                    vector_rank=candidate.vector_rank,
                    keyword_rank=candidate.keyword_rank,
                    rrf_score=candidate.rrf_score,
                    rerank_score=score,
                    final_rank=idx,
                )
            )

        return reranked_chunks


class FlashRankRerankerService(BaseRerankerService):
    """Local, lightweight CPU-only cross-encoder reranker powered by FlashRank."""

    def __init__(
        self,
        model: str = "ms-marco-TinyBERT-L-2-v2",
    ):
        self._model = model or settings.RERANKER_MODEL
        try:
            from flashrank import Ranker
            self.ranker = Ranker(model_name=self._model)
        except Exception as exc:
            logger.error("Failed to initialize FlashRank with model '%s': %s", self._model, exc)
            raise

    def rerank(
        self,
        query: str,
        candidates: list[FusedChunk],
        top_n: int = 5,
    ) -> list[RerankedChunk]:
        """Rerank candidates using local FlashRank ONNX cross-encoder."""
        if not candidates or top_n <= 0:
            return []

        from flashrank import RerankRequest

        passages = [
            {"id": str(i), "text": candidate.text}
            for i, candidate in enumerate(candidates)
        ]
        rerank_req = RerankRequest(query=query, passages=passages)
        results = self.ranker.rerank(rerank_req)

        reranked_chunks: list[RerankedChunk] = []
        for rank_idx, res in enumerate(results[:top_n], start=1):
            idx = int(res["id"])
            candidate = candidates[idx]
            reranked_chunks.append(
                RerankedChunk(
                    chunk_id=candidate.chunk_id,
                    document_id=candidate.document_id,
                    file_name=candidate.file_name,
                    title=candidate.title,
                    page_number=candidate.page_number,
                    text=candidate.text,
                    vector_rank=candidate.vector_rank,
                    keyword_rank=candidate.keyword_rank,
                    rrf_score=candidate.rrf_score,
                    rerank_score=round(float(res.get("score", 0.0)), 4),
                    final_rank=rank_idx,
                )
            )

        return reranked_chunks


class CohereRerankerService(BaseRerankerService):
    """Hosted Cohere Rerank API integration."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "rerank-v3.5",
    ):
        self._api_key = api_key or settings.RERANKER_API_KEY
        if not self._api_key:
            raise ValueError("Cohere API key is required for CohereRerankerService.")
        self._model = model or settings.RERANKER_MODEL

        try:
            import cohere
            self.client = cohere.Client(self._api_key)
        except ImportError as exc:
            raise ImportError("cohere package is required for CohereRerankerService. Install with `pip install cohere`.") from exc

    def rerank(
        self,
        query: str,
        candidates: list[FusedChunk],
        top_n: int = 5,
    ) -> list[RerankedChunk]:
        if not candidates or top_n <= 0:
            return []

        docs = [c.text for c in candidates]
        response = self.client.rerank(
            model=self._model,
            query=query,
            documents=docs,
            top_n=min(top_n, len(candidates)),
        )

        results: list[RerankedChunk] = []
        for rank_idx, result in enumerate(response.results, start=1):
            candidate = candidates[result.index]
            results.append(
                RerankedChunk(
                    chunk_id=candidate.chunk_id,
                    document_id=candidate.document_id,
                    file_name=candidate.file_name,
                    title=candidate.title,
                    page_number=candidate.page_number,
                    text=candidate.text,
                    vector_rank=candidate.vector_rank,
                    keyword_rank=candidate.keyword_rank,
                    rrf_score=candidate.rrf_score,
                    rerank_score=round(result.relevance_score, 4),
                    final_rank=rank_idx,
                )
            )

        return results


def get_reranker_service(force_mock: bool = False) -> BaseRerankerService:
    """Factory selecting FlashRankRerankerService, CohereRerankerService, or MockRerankerService.

    Defaults to CPU-only MockRerankerService when in test mode or force_mock=True.
    """
    provider = (settings.RERANKER_PROVIDER or "mock").lower()

    if force_mock or settings.APP_ENV == "test" or provider == "mock":
        logger.info("Using lightweight CPU-only MockRerankerService")
        return MockRerankerService()

    if provider == "flashrank":
        logger.info("Using local FlashRankRerankerService (model=%s)", settings.RERANKER_MODEL)
        try:
            return FlashRankRerankerService(model=settings.RERANKER_MODEL)
        except Exception as exc:
            logger.warning("FlashRank initialization failed (%s), falling back to MockRerankerService", exc)
            return MockRerankerService()

    if provider == "cohere":
        key = settings.RERANKER_API_KEY
        is_placeholder = not key or "your_" in key.lower() or key in ("test", "dummy")
        if is_placeholder:
            logger.warning("Cohere API key not set, falling back to MockRerankerService")
            return MockRerankerService()
        logger.info("Using CohereRerankerService (model=%s)", settings.RERANKER_MODEL)
        return CohereRerankerService(api_key=key, model=settings.RERANKER_MODEL)

    logger.warning("Unrecognized reranker provider '%s', falling back to MockRerankerService", provider)
    return MockRerankerService()
