"""Phase 1 Verification Tests: EmbeddingProvider, Model Mismatch Guardrails, and Real Benchmark Validity."""

import json
from pathlib import Path
import pytest

from app.core.database import get_test_session
from app.models.index_metadata import EmbeddingIndexMetadata
from app.services.embedding import (
    EmbeddingProvider,
    MockEmbeddingService,
    ModelMismatchError,
    get_embedding_provider,
)
from app.services.embedding_onnx import ONNXEmbeddingService
from app.services.reranker import FlashRankRerankerService, MockRerankerService
from app.services.retrieval import HybridRetrievalService
from app.cli.reindex import reindex_corpus


class TestEmbeddingProviderInterface:
    """Verifies that all embedding providers strictly implement the EmbeddingProvider contract."""

    def test_onnx_embedding_provider_contract(self):
        provider = ONNXEmbeddingService()
        assert isinstance(provider, EmbeddingProvider)
        assert provider.model_id == "all-MiniLM-L6-v2"
        assert provider.dim == 384
        assert provider.normalized is True
        assert provider.is_mock is False

        # Vector output check
        vec = provider.embed_query("test policy query")
        assert len(vec) == 384
        assert pytest.approx(sum(x * x for x in vec), rel=1e-3) == 1.0

    def test_mock_embedding_provider_contract(self):
        provider = MockEmbeddingService(dimension=1536, model_id="mock-sha256")
        assert isinstance(provider, EmbeddingProvider)
        assert provider.model_id == "mock-sha256"
        assert provider.dim == 1536
        assert provider.normalized is True
        assert provider.is_mock is True

        vec = provider.embed_query("test query")
        assert len(vec) == 1536
        assert pytest.approx(sum(x * x for x in vec), rel=1e-3) == 1.0

    def test_factory_returns_real_onnx_by_default(self):
        provider = get_embedding_provider(model_id="all-MiniLM-L6-v2")
        assert provider.is_mock is False
        assert provider.dim == 384


class TestModelMismatchFailLoud:
    """Verifies that queries fail loudly if active query model does not match indexed model."""

    def test_switching_query_model_without_reindexing_raises_error(self):
        db = get_test_session()

        meta = db.query(EmbeddingIndexMetadata).filter_by(id="default").first()
        orig_model = meta.model_id if meta else None
        orig_dim = meta.dim if meta else None

        try:
            # Set index metadata to all-MiniLM-L6-v2 (384d)
            if not meta:
                meta = EmbeddingIndexMetadata(
                    id="default",
                    model_id="all-MiniLM-L6-v2",
                    dim=384,
                    normalized=True,
                    is_mock=False,
                    chunk_count=43,
                )
                db.add(meta)
            else:
                meta.model_id = "all-MiniLM-L6-v2"
                meta.dim = 384
            db.commit()

            # Attempt to search using a mock 1536-dim provider
            mock_provider = MockEmbeddingService(dimension=1536, model_id="mock-sha256")
            retrieval_svc = HybridRetrievalService(db_session=db, embedding_service=mock_provider)

            with pytest.raises(ModelMismatchError) as exc_info:
                retrieval_svc.vector_search("minimum attendance", k=5, role="student", use_semantic=False)

            assert "Embedding model mismatch" in str(exc_info.value)
            assert "all-MiniLM-L6-v2" in str(exc_info.value)
            assert "mock-sha256" in str(exc_info.value)
        finally:
            # Restore state to prevent test contamination
            if orig_model is not None and meta is not None:
                meta.model_id = orig_model
                meta.dim = orig_dim
                db.commit()


class TestRealBenchmarkIntegrity:
    """Verifies that all results in eval/results/real/ have zero mock components."""

    def test_real_results_directory_has_zero_mocks(self):
        real_dir = Path("eval/results/real")
        assert real_dir.exists(), "eval/results/real directory must exist"

        json_files = list(real_dir.glob("*.json"))
        assert len(json_files) >= 1, "Must have at least one benchmark result in eval/results/real"

        for jf in json_files:
            data = json.loads(jf.read_text(encoding="utf-8"))
            meta = data.get("metadata", {})
            is_mock = meta.get("is_mock", {})

            assert is_mock.get("embedding") is False, f"File {jf.name} used mock embedding!"
            assert is_mock.get("reranker") is False, f"File {jf.name} used mock reranker!"
            assert is_mock.get("llm") is False, f"File {jf.name} used mock LLM!"
            assert is_mock.get("any") is False, f"File {jf.name} has is_mock['any'] = True!"

    def test_report_md_exists_and_contains_honesty_warning(self):
        report_md = Path("eval/results/real/REPORT.md")
        assert report_md.exists(), "eval/results/real/REPORT.md must exist"

        content = report_md.read_text(encoding="utf-8")
        assert "all-MiniLM-L6-v2" in content
        assert "ms-marco-TinyBERT-L-2-v2" in content
        assert "Five-Configuration Comparison" in content
        assert "Corpus Size Warning" in content or "chance baseline" in content.lower()

