"""Unit tests for the isolated ONNXEmbeddingService (app/services/embedding_onnx.py)."""

import pytest
import numpy as np
from pathlib import Path
from app.services.embedding_onnx import ONNXEmbeddingService, DEFAULT_MODEL_DIR


@pytest.fixture(scope="module")
def onnx_service():
    """Module-level ONNXEmbeddingService instance using default local model directory."""
    return ONNXEmbeddingService(model_dir=DEFAULT_MODEL_DIR)


def test_onnx_service_initialization(onnx_service):
    """Verify service initializes with dimension 384 and correct configuration."""
    assert onnx_service.dimension == 384
    assert onnx_service.max_length == 256
    assert onnx_service.session is not None
    assert onnx_service.tokenizer is not None


def test_onnx_service_missing_assets_raise_filenotfound(tmp_path):
    """Verify missing model or tokenizer assets produce clear FileNotFoundError."""
    # Empty directory (both missing)
    with pytest.raises(FileNotFoundError) as exc_model:
        ONNXEmbeddingService(model_dir=tmp_path)
    assert "ONNX model file not found" in str(exc_model.value)

    # Only model.onnx present, tokenizer missing
    dummy_model = tmp_path / "model.onnx"
    dummy_model.write_bytes(b"dummy")
    with pytest.raises(FileNotFoundError) as exc_tok:
        ONNXEmbeddingService(model_dir=tmp_path)
    assert "Tokenizer file not found" in str(exc_tok.value)


def test_onnx_service_empty_input(onnx_service):
    """Verify empty input list returns empty list."""
    assert onnx_service.embed_texts([]) == []


def test_onnx_service_empty_strings_handled_safely(onnx_service):
    """Verify empty strings and whitespace-only strings do not crash and return unit vectors."""
    vectors = onnx_service.embed_texts(["", "   ", "valid text"])
    assert len(vectors) == 3
    for v in vectors:
        assert len(v) == 384
        norm = np.linalg.norm(v)
        assert pytest.approx(norm, abs=1e-4) == 1.0


def test_onnx_service_vector_properties_and_normalization(onnx_service):
    """Verify dimension, finite values, and strict L2 normalization."""
    sample_texts = [
        "Students must maintain testing integrity during examinations.",
        "Dormitory curfew is 10:00 PM for all residential students.",
        "Tuition reimbursement is available within the first fourteen calendar days.",
    ]
    vectors = onnx_service.embed_texts(sample_texts)
    assert len(vectors) == 3

    for vec in vectors:
        assert len(vec) == 384
        # Confirm all numbers are finite
        assert np.all(np.isfinite(vec))
        # Confirm L2 unit norm
        norm = np.linalg.norm(vec)
        assert pytest.approx(norm, abs=1e-4) == 1.0


def test_onnx_service_deterministic_output(onnx_service):
    """Verify embedding generation is 100% deterministic."""
    text = "Academic misconduct incurs immediate disciplinary suspension."
    vec1 = onnx_service.embed_query(text)
    vec2 = onnx_service.embed_query(text)
    assert vec1 == vec2


def test_onnx_service_batched_vs_single(onnx_service):
    """Verify batched embedding matches single-text embedding."""
    texts = [
        "First college policy text regarding scholarships.",
        "Second college policy text regarding library fines.",
    ]
    batched = onnx_service.embed_texts(texts)
    single_0 = onnx_service.embed_query(texts[0])
    single_1 = onnx_service.embed_query(texts[1])

    # Within floating-point tolerances, batching must match single inference
    np.testing.assert_allclose(batched[0], single_0, atol=1e-5)
    np.testing.assert_allclose(batched[1], single_1, atol=1e-5)


def test_onnx_service_semantic_discrimination(onnx_service):
    """Verify real semantic discrimination on paraphrase vs unrelated text."""
    query = "What happens if a student is caught cheating during a semester exam?"
    paraphrase = "Students found violating testing integrity will be awarded a grade of XF and suspended."
    unrelated = "Campus parking permits must be permanently displayed on registered motor vehicles."

    q_vec = np.array(onnx_service.embed_query(query))
    para_vec = np.array(onnx_service.embed_query(paraphrase))
    unrel_vec = np.array(onnx_service.embed_query(unrelated))

    sim_para = float(np.dot(q_vec, para_vec))
    sim_unrel = float(np.dot(q_vec, unrel_vec))

    # Real semantic embedding must show substantial margin between paraphrase and unrelated text
    assert sim_para > sim_unrel
    assert (sim_para - sim_unrel) > 0.25


def test_onnx_service_offline_no_network_calls(onnx_service, monkeypatch):
    """Confirm ONNXEmbeddingService executes strictly offline without attempting network calls."""
    def forbidden_network(*args, **kwargs):
        raise RuntimeError("Network connection attempted by ONNXEmbeddingService!")

    import socket
    monkeypatch.setattr(socket, "create_connection", forbidden_network)

    vec = onnx_service.embed_query("Testing offline isolation guarantee.")
    assert len(vec) == 384
