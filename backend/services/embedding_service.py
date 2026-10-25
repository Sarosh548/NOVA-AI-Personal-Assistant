from __future__ import annotations

from threading import Lock
from typing import Any


_MODEL_NAME = "all-MiniLM-L6-v2"
_SHARED_MODEL: Any | None = None
_SHARED_MODEL_LOCK = Lock()


def _load_model() -> Any:
    """Import and load the sentence-transformer only when embeddings are needed."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(_MODEL_NAME)


def _get_shared_model() -> Any:
    """Load the embedding model once per process, safely and lazily."""
    global _SHARED_MODEL

    if _SHARED_MODEL is None:
        with _SHARED_MODEL_LOCK:
            if _SHARED_MODEL is None:
                _SHARED_MODEL = _load_model()

    return _SHARED_MODEL


class EmbeddingService:
    """Embedding access that does not download/load ML weights during API startup."""

    @property
    def model(self) -> Any:
        # Preserve the previous public attribute for existing callers/tests,
        # but defer heavyweight imports/model loading until first access.
        return _get_shared_model()

    def create_embedding(self, text: str):
        return self.model.encode(text)

    def similarity(self, text1: str, text2: str) -> float:
        embedding1 = self.create_embedding(text1)
        embedding2 = self.create_embedding(text2)

        from sentence_transformers import util

        score = util.cos_sim(embedding1, embedding2).item()

        return float(score)
