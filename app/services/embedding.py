"""Embedding service for generating text vector representations."""

import abc
import hashlib
import logging
import math
from typing import Optional
from openai import OpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)


class BaseEmbeddingService(abc.ABC):
    """Abstract base class for embedding generation services."""

    @property
    @abc.abstractmethod
    def dimension(self) -> int:
        """Vector dimensionality."""
        pass

    @abc.abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        pass

    def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query string."""
        results = self.embed_texts([query])
        return results[0]


class MockEmbeddingService(BaseEmbeddingService):
    """Deterministic, offline embedding service for testing and CI environments.

    Produces unit-normalized vectors of the specified dimension based on SHA-256 hash.
    """

    def __init__(self, dimension: int = 1536):
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def _generate_vector(self, text: str) -> list[float]:
        """Generate a deterministic unit-normalized vector for given text."""
        seed_hash = hashlib.sha256(text.encode("utf-8")).digest()
        raw_vals: list[float] = []

        for i in range(self._dimension):
            byte_val = seed_hash[i % len(seed_hash)]
            mod_factor = float((i % 11) - 5) * 0.05
            raw_vals.append(((float(byte_val) - 128.0) / 128.0) + mod_factor)

        norm = math.sqrt(sum(v * v for v in raw_vals))
        if norm == 0:
            return [0.0] * self._dimension

        return [round(v / norm, 6) for v in raw_vals]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate deterministic embeddings for all input texts."""
        return [self._generate_vector(t) for t in texts]


class OpenAIEmbeddingService(BaseEmbeddingService):
    """OpenAI API-backed embedding service."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
    ):
        self._api_key = api_key or settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        if not self._api_key:
            raise ValueError("OpenAI API key must be provided for OpenAIEmbeddingService.")

        self._model = model or settings.EMBEDDING_MODEL
        self._dimension = dimension or settings.EMBEDDING_DIMENSION
        self.client = OpenAI(api_key=self._api_key)

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings in batches using OpenAI API."""
        if not texts:
            return []

        cleaned_texts = [t.replace("\n", " ") for t in texts]
        all_embeddings: list[list[float]] = []
        batch_size = 64

        for i in range(0, len(cleaned_texts), batch_size):
            batch = cleaned_texts[i : i + batch_size]
            response = self.client.embeddings.create(
                input=batch,
                model=self._model,
                dimensions=self._dimension,
            )
            batch_embeddings = [record.embedding for record in response.data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings


class GeminiEmbeddingService(BaseEmbeddingService):
    """Google Gemini API embedding service using text-embedding-004 (768 dimensions)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "text-embedding-004",
        dimension: int = 768,
        timeout_seconds: float = 30.0,
    ):
        self._api_key = api_key or settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        if not self._api_key:
            raise ValueError("Gemini API key must be provided for GeminiEmbeddingService.")

        self._model = model or settings.EMBEDDING_MODEL
        if not self._model.startswith("models/"):
            self._model_path = f"models/{self._model}"
        else:
            self._model_path = self._model

        self._dimension = dimension or settings.EMBEDDING_DIMENSION
        self.timeout_seconds = timeout_seconds
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings in batches using Google Gemini REST API."""
        if not texts:
            return []

        import httpx

        cleaned_texts = [t.replace("\n", " ") for t in texts]
        all_embeddings: list[list[float]] = []
        batch_size = 50

        for i in range(0, len(cleaned_texts), batch_size):
            batch = cleaned_texts[i : i + batch_size]
            requests = [
                {
                    "model": self._model_path,
                    "content": {"parts": [{"text": text}]},
                }
                for text in batch
            ]
            payload = {"requests": requests}
            url = f"{self.base_url}/{self._model_path}:batchEmbedContents"

            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    url,
                    params={"key": self._api_key},
                    json=payload,
                )
                if response.status_code != 200:
                    raise ValueError(f"Gemini embedding API error ({response.status_code}): {response.text}")

                data = response.json()
                embeddings_data = data.get("embeddings", [])
                for item in embeddings_data:
                    vec = item.get("values", [])
                    all_embeddings.append(vec)

        return all_embeddings


def get_embedding_service(force_mock: bool = False) -> BaseEmbeddingService:
    """Factory creating configured embedding service.

    Defaults to MockEmbeddingService when running without configured API keys, in test mode, or provider=mock.
    """
    provider = (settings.EMBEDDING_PROVIDER or "openai").lower()
    key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
    is_placeholder = not key or "your_" in key.lower() or key in ("test", "dummy")

    if force_mock or is_placeholder or settings.APP_ENV == "test" or provider == "mock":
        logger.info(
            "Using deterministic MockEmbeddingService (dimension=%d)",
            settings.EMBEDDING_DIMENSION,
        )
        return MockEmbeddingService(dimension=settings.EMBEDDING_DIMENSION)

    if provider == "gemini":
        logger.info(
            "Using GeminiEmbeddingService (model=%s, dimension=%d)",
            settings.EMBEDDING_MODEL,
            settings.EMBEDDING_DIMENSION,
        )
        return GeminiEmbeddingService(
            api_key=key,
            model=settings.EMBEDDING_MODEL,
            dimension=settings.EMBEDDING_DIMENSION,
        )

    if provider == "openai":
        logger.info(
            "Using OpenAIEmbeddingService (model=%s, dimension=%d)",
            settings.EMBEDDING_MODEL,
            settings.EMBEDDING_DIMENSION,
        )
        return OpenAIEmbeddingService(
            api_key=key,
            model=settings.EMBEDDING_MODEL,
            dimension=settings.EMBEDDING_DIMENSION,
        )

    logger.warning("Unrecognized embedding provider '%s', using MockEmbeddingService", provider)
    return MockEmbeddingService(dimension=settings.EMBEDDING_DIMENSION)
