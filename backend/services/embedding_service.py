from __future__ import annotations

from threading import Lock
from typing import Any


_MODEL_NAME = "all-MiniLM-L6-v2"
_SHARED_MODEL: Any | None = None
_SHARED_MODEL_LOCK = Lock()


def _load_model() -> Any:
    """Import/load transformer weights on first embedding use, not API boot."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(_MODEL_NAME)


def _get_shared_model() -> Any:
    """Reuse one read-only embedding model per process, loaded lazily."""
    global _SHARED_MODEL
    if _SHARED_MODEL is None:
        with _SHARED_MODEL_LOCK:
            if _SHARED_MODEL is None:
                _SHARED_MODEL = _load_model()
    return _SHARED_MODEL


class EmbeddingService:
    """Lazy shared embedding service so free-tier API startup stays lightweight."""

    @property
    def model(self) -> Any:
        return _get_shared_model()

    def create_embedding(self, text: str):
        return self.model.encode(text)

    def similarity(self, text1: str, text2: str) -> float:
        embedding1 = self.create_embedding(text1)
        embedding2 = self.create_embedding(text2)
        from sentence_transformers import util

        return float(util.cos_sim(embedding1, embedding2).item())
