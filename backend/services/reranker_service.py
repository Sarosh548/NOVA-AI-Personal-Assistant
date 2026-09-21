from __future__ import annotations

from typing import Any, Mapping, Sequence

from sentence_transformers import CrossEncoder


DEFAULT_RERANKER_MODEL = (
    "cross-encoder/ms-marco-MiniLM-L6-v2"
)
DEFAULT_RERANKER_BATCH_SIZE = 16
DEFAULT_RERANKER_MAX_LENGTH = 512


class RerankerService:
    """
    Cross-Encoder reranking for an existing candidate set.

    The service is deliberately independent from database retrieval:
    the existing bi-encoder/pgvector search produces candidates first,
    then this service re-scores those candidates using query-passage
    pairs and returns the candidates ordered by reranker score.
    """

    def __init__(
        self,
        *,
        model: CrossEncoder | None = None,
        model_name: str = DEFAULT_RERANKER_MODEL,
        batch_size: int = DEFAULT_RERANKER_BATCH_SIZE,
        max_length: int = DEFAULT_RERANKER_MAX_LENGTH,
    ) -> None:
        if batch_size < 1:
            raise ValueError(
                "batch_size must be greater than 0"
            )

        if max_length < 1:
            raise ValueError(
                "max_length must be greater than 0"
            )

        self.model_name = model_name
        self.batch_size = batch_size
        self.max_length = max_length
        self._model = model

    @property
    def model(self) -> CrossEncoder:
        if self._model is None:
            self._model = CrossEncoder(
                self.model_name,
                max_length=self.max_length,
            )

        return self._model

    @staticmethod
    def _normalize_query(query: str) -> str:
        normalized = str(query).strip()

        if not normalized:
            raise ValueError(
                "query cannot be empty"
            )

        return normalized

    @staticmethod
    def _candidate_text(
        candidate: Mapping[str, Any],
        index: int,
    ) -> str:
        content = candidate.get("content")

        if content is None:
            raise ValueError(
                f"candidate at index {index} is missing content"
            )

        normalized = str(content).strip()

        if not normalized:
            raise ValueError(
                f"candidate at index {index} has empty content"
            )

        return normalized

    def rerank(
        self,
        query: str,
        candidates: Sequence[Mapping[str, Any]],
        *,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        normalized_query = self._normalize_query(
            query
        )

        if top_k is not None and top_k < 1:
            raise ValueError(
                "top_k must be greater than 0"
            )

        if not candidates:
            return []

        pairs = [
            (
                normalized_query,
                self._candidate_text(
                    candidate,
                    index,
                ),
            )
            for index, candidate in enumerate(
                candidates
            )
        ]

        raw_scores = self.model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
        )

        scores = [
            float(score)
            for score in raw_scores
        ]

        if len(scores) != len(candidates):
            raise ValueError(
                "reranker returned an unexpected number of scores"
            )

        ranked = [
            (
                index,
                score,
                dict(candidate),
            )
            for index, (
                score,
                candidate,
            ) in enumerate(
                zip(
                    scores,
                    candidates,
                )
            )
        ]

        ranked.sort(
            key=lambda item: (
                -item[1],
                item[0],
            )
        )

        if top_k is not None:
            ranked = ranked[:top_k]

        return [
            {
                **candidate,
                "rerank_score": score,
            }
            for _, score, candidate in ranked
        ]
