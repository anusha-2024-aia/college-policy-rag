"""Embedding service and provider interfaces for text vector representations."""

from __future__ import annotations

import abc
import hashlib
import logging
import math
from typing import Optional
from openai import OpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)


class ModelMismatchError(Exception):
    """Raised when active query embedding model does not match indexed document model."""
    pass


class EmbeddingProvider(abc.ABC):
    """Abstract base interface for text embedding providers.

    All embedding providers (real or mock) must declare:
    - model_id: Unique string identifier for the model.
    - dim: Vector dimensionality.
    - normalized: Whether output vectors are unit L2-normalized.
    - is_mock: Whether the provider is a synthetic/mock generator.
    - embed_documents(texts): Batch embedding generation for documents.
    - embed_query(text): Single query embedding generation.
    """

    @property
    @abc.abstractmethod
    def model_id(self) -> str:
        """Identifier for the model (e.g., 'all-MiniLM-L6-v2', 'mock-sha256')."""
        pass

    @property
    @abc.abstractmethod
    def dim(self) -> int:
        """Vector dimensionality."""
        pass

    @property
    def dimension(self) -> int:
        """Backwards compatibility alias for dim."""
        return self.dim

    @property
    @abc.abstractmethod
    def normalized(self) -> bool:
        """Whether vectors produced by this provider are unit L2-normalized."""
        pass

    @property
    @abc.abstractmethod
    def is_mock(self) -> bool:
        """True if the provider produces synthetic mock vectors, False if real model."""
        pass

    @abc.abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of document texts."""
        pass

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Backwards compatibility alias for embed_documents."""
        return self.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        """Generate embedding for a single query string."""
        results = self.embed_documents([text])
        return results[0]


# Backwards compatibility alias for BaseEmbeddingService
BaseEmbeddingService = EmbeddingProvider


class MockEmbeddingService(EmbeddingProvider):
    """Deterministic, offline embedding service for testing and CI environments.

    Produces unit-normalized vectors based on SHA-256 hash.
    """

    def __init__(self, dimension: int = 1536, model_id: str = "mock-sha256"):
        self._dimension = dimension
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dim(self) -> int:
        return self._dimension

    @property
    def normalized(self) -> bool:
        return True

    @property
    def is_mock(self) -> bool:
        return True

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

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Generate deterministic embeddings for all input texts."""
        return [self._generate_vector(t) for t in texts]


# Alias for explicit provider naming
MockEmbeddingProvider = MockEmbeddingService


class OpenAIEmbeddingService(EmbeddingProvider):
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
    def model_id(self) -> str:
        return self._model

    @property
    def dim(self) -> int:
        return self._dimension

    @property
    def normalized(self) -> bool:
        return True

    @property
    def is_mock(self) -> bool:
        return False

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
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


class GeminiEmbeddingService(EmbeddingProvider):
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
    def model_id(self) -> str:
        return self._model

    @property
    def dim(self) -> int:
        return self._dimension

    @property
    def normalized(self) -> bool:
        return True

    @property
    def is_mock(self) -> bool:
        return False

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
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


def get_embedding_provider(
    model_id: Optional[str] = None,
    force_mock: bool = False,
) -> EmbeddingProvider:
    """Factory creating configured embedding provider.

    Options:
    - 'all-MiniLM-L6-v2': Local real ONNX model (384 dimensions, normalized, is_mock=False).
    - 'openai': Hosted OpenAI embedding API.
    - 'gemini': Hosted Google Gemini embedding API.
    - 'mock' or 'mock-sha256': Deterministic unit-normalized mock provider for testing.

    If model_id is not specified, defaults to local ONNX 'all-MiniLM-L6-v2' when available
    in non-mock execution, or MockEmbeddingService when force_mock=True or in test environment.
    """
    requested = (model_id or settings.EMBEDDING_PROVIDER or "").lower()

    if force_mock or requested in ("mock", "mock-sha256"):
        logger.info("Using deterministic MockEmbeddingService (dimension=%d)", settings.EMBEDDING_DIMENSION)
        return MockEmbeddingService(dimension=settings.EMBEDDING_DIMENSION, model_id="mock-sha256")

    if requested == "all-minilm-l6-v2" or requested == "onnx":
        from app.services.embedding_onnx import ONNXEmbeddingService
        logger.info("Using local ONNXEmbeddingService (all-MiniLM-L6-v2, 384d)")
        return ONNXEmbeddingService()

    if requested == "gemini":
        key = settings.GEMINI_API_KEY or settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        if key and "your_" not in key.lower() and key not in ("test", "dummy"):
            logger.info("Using GeminiEmbeddingService (model=%s)", settings.EMBEDDING_MODEL)
            return GeminiEmbeddingService(api_key=key, model=settings.EMBEDDING_MODEL, dimension=settings.EMBEDDING_DIMENSION)
        logger.warning("Gemini API key missing, falling back to local ONNX model")
        from app.services.embedding_onnx import ONNXEmbeddingService
        return ONNXEmbeddingService()

    if requested == "openai":
        key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        if key and "your_" not in key.lower() and key not in ("test", "dummy"):
            logger.info("Using OpenAIEmbeddingService (model=%s)", settings.EMBEDDING_MODEL)
            return OpenAIEmbeddingService(api_key=key, model=settings.EMBEDDING_MODEL, dimension=settings.EMBEDDING_DIMENSION)
        logger.warning("OpenAI API key missing, falling back to local ONNX model")
        from app.services.embedding_onnx import ONNXEmbeddingService
        return ONNXEmbeddingService()

    # Default fallback: if local ONNX model exists, use real ONNX model!
    from pathlib import Path
    if Path("models/embeddings/all-MiniLM-L6-v2/model.onnx").exists():
        from app.services.embedding_onnx import ONNXEmbeddingService
        return ONNXEmbeddingService()

    return MockEmbeddingService(dimension=settings.EMBEDDING_DIMENSION)


def get_embedding_service(force_mock: bool = False) -> EmbeddingProvider:
    """Backwards compatibility alias for get_embedding_provider."""
    return get_embedding_provider(force_mock=force_mock)
