"""
Embedding layer.

We use sentence-transformers locally because:
- It's free (no API costs, no rate limits).
- 384-dim MiniLM is fast enough for real-time queries on CPU.
- Stays consistent with the "Ollama-first for sensitive data" philosophy:
  documents never leave the box for embedding.

The model is heavy to load (~80MB), so we cache it as a module-level
singleton. Encoding is CPU-bound, so we use asyncio.to_thread to keep the
FastAPI event loop free.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache

import numpy as np
from loguru import logger
from sentence_transformers import SentenceTransformer

from app.config import settings


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    """Load model once, cache forever. Triggered lazily on first embed call."""
    logger.info(f"Loading embedding model: {settings.embedding_model}")
    model = SentenceTransformer(settings.embedding_model)
    # Sanity check: dimension must match config.
    actual_dim = model.get_sentence_embedding_dimension()
    if actual_dim != settings.embedding_dim:
        raise RuntimeError(
            f"Model dim mismatch: model={actual_dim}, config={settings.embedding_dim}. "
            "Update settings.embedding_dim to match the model."
        )
    logger.info(f"Embedding model loaded (dim={actual_dim})")
    return model


class Embedder:
    """Thin async wrapper around sentence-transformers."""

    def __init__(self) -> None:
        # Don't load eagerly — let the first call trigger it.
        self._model: SentenceTransformer | None = None

    def _ensure_model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = _load_model()
        return self._model

    def _encode_sync(self, texts: list[str]) -> np.ndarray:
        """Synchronous encoding. Use embed() / embed_one() from async code."""
        model = self._ensure_model()
        # normalize_embeddings=True -> we can use inner-product as cosine sim,
        # which lets us use FAISS IndexFlatIP (faster than L2 + normalization).
        vectors = model.encode(
            texts,
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vectors.astype("float32")  # FAISS requires float32

    async def embed(self, texts: list[str]) -> np.ndarray:
        """Embed a batch of texts. Returns shape (N, embedding_dim)."""
        if not texts:
            return np.zeros((0, settings.embedding_dim), dtype="float32")
        return await asyncio.to_thread(self._encode_sync, texts)

    async def embed_one(self, text: str) -> np.ndarray:
        """Embed a single string. Returns shape (embedding_dim,)."""
        result = await self.embed([text])
        return result[0]


# Module-level singleton.
embedder = Embedder()