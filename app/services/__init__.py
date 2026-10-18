"""Application services package."""

from app.services.manifest import ManifestService, ManifestError
from app.services.pdf_parser import (
    PDFParserService,
    PDFParsingError,
    ParsedPDF,
    PageData,
)
from app.services.chunker import ChunkerService, DocumentChunk
from app.services.embedding import (
    BaseEmbeddingService,
    OpenAIEmbeddingService,
    MockEmbeddingService,
    get_embedding_service,
)
from app.services.ingestion import (
    IngestionService,
    IngestionReport,
    DocumentIngestionResult,
)
from app.services.reranker import (
    BaseRerankerService,
    CohereRerankerService,
    MockRerankerService,
    get_reranker_service,
)
from app.services.retrieval import HybridRetrievalService
from app.services.llm import (
    BaseLLMService,
    OpenAILLMService,
    MockLLMService,
    LLMError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    get_llm_service,
)
from app.services.qa import QAService
from app.services.versioning import (
    DocumentVersionService,
    DocumentVersionStatus,
    VersionError,
    MissingSupersedesTargetError,
    CircularVersionError,
    TemporalOrderError,
)

__all__ = [
    "ManifestService",
    "ManifestError",
    "PDFParserService",
    "PDFParsingError",
    "ParsedPDF",
    "PageData",
    "ChunkerService",
    "DocumentChunk",
    "BaseEmbeddingService",
    "OpenAIEmbeddingService",
    "MockEmbeddingService",
    "get_embedding_service",
    "IngestionService",
    "IngestionReport",
    "DocumentIngestionResult",
    "BaseRerankerService",
    "CohereRerankerService",
    "MockRerankerService",
    "get_reranker_service",
    "HybridRetrievalService",
    "BaseLLMService",
    "OpenAILLMService",
    "MockLLMService",
    "LLMError",
    "LLMAuthenticationError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "get_llm_service",
    "QAService",
    "DocumentVersionService",
    "DocumentVersionStatus",
    "VersionError",
    "MissingSupersedesTargetError",
    "CircularVersionError",
    "TemporalOrderError",
]
