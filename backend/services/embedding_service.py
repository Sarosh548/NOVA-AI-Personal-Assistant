from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Any


_MODEL_NAME = "all-MiniLM-L6-v2"
_SHARED_MODEL: Any | None = None
_SHARED_MODEL_LOCK = Lock()
MIN_LOCAL_EMBEDDING_MEMORY_BYTES = 768 * 1024 * 1024


class EmbeddingUnavailableError(RuntimeError):
    """Raised when local transformers cannot safely initialize or are disabled."""


def _container_memory_limit_bytes() -> int | None:
    """Read cgroup v2/v1 memory limits without importing any ML runtime."""
    candidates = (
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    )
    limits: list[int] = []
    for path in candidates:
        try:
            raw = path.read_text(encoding="ascii").strip().lower()
        except (OSError, UnicodeError):
            continue

        if not raw or raw == "max":
            continue
        try:
            value = int(raw)
        except ValueError:
            continue

        # cgroup v1 commonly reports a huge sentinel when there is no limit.
        if 0 < value < (1 << 60):
            limits.append(value)

    return min(limits) if limits else None


def local_embeddings_enabled() -> bool:
    """Use Transformers only when explicitly enabled or enough RAM is available."""
    setting = os.getenv("NOVA_LOCAL_EMBEDDINGS_ENABLED", "auto").strip().lower()
    if setting in {"1", "true", "yes", "on", "enabled"}:
        return True
    if setting in {"0", "false", "no", "off", "disabled"}:
        return False

    memory_limit = _container_memory_limit_bytes()
    return (
        memory_limit is None
        or memory_limit >= MIN_LOCAL_EMBEDDING_MEMORY_BYTES
    )


def _load_model() -> Any:
    """Import/load transformer weights only in a container with a safe RAM budget."""
    import torch
    from sentence_transformers import SentenceTransformer

    # The model is CPU-only; avoiding a large OpenMP pool saves memory and CPU
    # contention on small free-tier instances.
    torch.set_num_threads(max(1, int(os.getenv("NOVA_EMBEDDING_THREADS", "1"))))
    return SentenceTransformer(_MODEL_NAME, device="cpu")


def _get_shared_model() -> Any:
    """Reuse one read-only model per process, failing fast on low-memory hosts."""
    global _SHARED_MODEL
    if not local_embeddings_enabled():
        raise EmbeddingUnavailableError(
            "Local semantic embeddings are disabled because this container has "
            "less than 768 MiB of memory; using keyword retrieval instead."
        )

    if _SHARED_MODEL is None:
        with _SHARED_MODEL_LOCK:
            if _SHARED_MODEL is None:
                try:
                    _SHARED_MODEL = _load_model()
                except (ImportError, OSError, RuntimeError) as exc:
                    raise EmbeddingUnavailableError(
                        "Local semantic embeddings could not be initialized; "
                        "using keyword retrieval instead."
                    ) from exc
    return _SHARED_MODEL


class EmbeddingService:
    """Lazy embeddings with a safe low-memory fallback for production containers."""

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
