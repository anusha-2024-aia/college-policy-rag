"""Local ONNX-based embedding engine for all-MiniLM-L6-v2 (Phase 5.2A).

This service runs strictly offline using local ONNX Runtime and tokenizers,
producing 384-dimensional L2-normalized dense semantic embeddings.

CRITICAL GUARDRAIL:
- Makes zero network calls and executes no automatic model downloads.
- Operates in complete isolation without changing existing active embedding provider
  or modifying database/retrieval code.
"""

import logging
from pathlib import Path
from typing import Optional, Sequence
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from app.services.embedding import BaseEmbeddingService

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path("models/embeddings/all-MiniLM-L6-v2")


class ONNXEmbeddingService(BaseEmbeddingService):
    """Local, offline embedding service powered by ONNX Runtime and HuggingFace Tokenizers.

    Produces unit-normalized 384-dimensional dense vectors using mean pooling over
    BERT token representations.
    """

    def __init__(
        self,
        model_dir: Optional[str | Path] = None,
        max_length: int = 256,
        batch_size: int = 32,
    ):
        self.model_dir = Path(model_dir) if model_dir else DEFAULT_MODEL_DIR
        self.max_length = max_length
        self.batch_size = batch_size
        self._dimension = 384

        model_path = self.model_dir / "model.onnx"
        tokenizer_path = self.model_dir / "tokenizer.json"

        if not model_path.exists():
            raise FileNotFoundError(
                f"ONNX model file not found at: {model_path.resolve()}. "
                f"Please ensure model.onnx is present in {self.model_dir}."
            )
        if not tokenizer_path.exists():
            raise FileNotFoundError(
                f"Tokenizer file not found at: {tokenizer_path.resolve()}. "
                f"Please ensure tokenizer.json is present in {self.model_dir}."
            )

        # Initialize ONNX inference session strictly on CPU
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(model_path),
            sess_options=sess_options,
            providers=["CPUExecutionProvider"],
        )

        # Initialize fast tokenizer without network access
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self.tokenizer.enable_truncation(max_length=self.max_length)

        # Inspect and verify model inputs
        self.input_names = [i.name for i in self.session.get_inputs()]
        self.has_token_type_ids = "token_type_ids" in self.input_names

        logger.info(
            "Initialized ONNXEmbeddingService from %s (dim=%d, max_length=%d)",
            self.model_dir,
            self._dimension,
            self.max_length,
        )

    @property
    def dimension(self) -> int:
        """Vector dimensionality (384 for all-MiniLM-L6-v2)."""
        return self._dimension

    def _mean_pooling(
        self,
        last_hidden_state: np.ndarray,
        attention_mask: np.ndarray,
    ) -> np.ndarray:
        """Mean Pooling: average token embeddings weighted by attention mask."""
        # last_hidden_state: [batch_size, seq_len, hidden_dim]
        # attention_mask:    [batch_size, seq_len]
        input_mask_expanded = np.expand_dims(attention_mask, -1).astype(float)
        sum_embeddings = np.sum(last_hidden_state * input_mask_expanded, axis=1)
        sum_mask = np.clip(np.sum(input_mask_expanded, axis=1), a_min=1e-9, a_max=None)
        return sum_embeddings / sum_mask

    def _l2_normalize(self, vectors: np.ndarray) -> np.ndarray:
        """Normalize vectors to unit length (L2 norm = 1.0)."""
        norms = np.linalg.norm(vectors, ord=2, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return vectors / norms

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate 384-dimensional dense semantic embeddings for a list of texts."""
        if not texts:
            return []

        all_embeddings: list[list[float]] = []

        # Process in batches to control memory footprint
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]

            # Preprocess: sanitize strings, replacing newlines with space
            cleaned_batch = [t.replace("\n", " ").strip() if t else "" for t in batch]
            # Replace completely empty strings with placeholder token to preserve batch alignment
            safe_batch = [t if t else "[PAD]" for t in cleaned_batch]

            encodings = self.tokenizer.encode_batch(safe_batch)

            input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
            attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)

            feed_dict = {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            }
            if self.has_token_type_ids:
                token_type_ids = np.array([e.type_ids for e in encodings], dtype=np.int64)
                feed_dict["token_type_ids"] = token_type_ids

            outputs = self.session.run(["last_hidden_state"], feed_dict)
            last_hidden_state = outputs[0]

            # Apply mean pooling followed by L2 normalization
            pooled = self._mean_pooling(last_hidden_state, attention_mask)
            normalized = self._l2_normalize(pooled)

            # Validate all values are finite float numbers
            if not np.all(np.isfinite(normalized)):
                raise ValueError("ONNX embedding forward pass produced non-finite (NaN/Inf) values.")

            for row in normalized:
                all_embeddings.append([round(float(v), 6) for v in row])

        return all_embeddings

    def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query string."""
        results = self.embed_texts([query])
        return results[0]
