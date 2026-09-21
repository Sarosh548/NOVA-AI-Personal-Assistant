from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Iterable, Sequence


RetrievalId = Hashable


@dataclass(frozen=True)
class RAGEvaluationCase:
    """
    One deterministic retrieval-evaluation case.

    relevant_ids contains the identifiers that should appear in the
    retrieved ranking for this query. The identifiers can represent
    documents, chunks, or another stable retrieval unit.
    """

    query: str
    relevant_ids: frozenset[RetrievalId]


class RAGEvaluationService:
    """
    Deterministic metrics for evaluating ranked RAG retrieval results.

    Metrics are intentionally independent from embeddings, databases,
    and model providers so benchmark tests remain reproducible.
    """

    @staticmethod
    def _normalize_ids(
        values: Iterable[RetrievalId],
    ) -> list[RetrievalId]:
        return list(values)

    @staticmethod
    def _validate_k(k: int) -> None:
        if k < 1:
            raise ValueError(
                "k must be greater than 0"
            )

    @classmethod
    def precision_at_k(
        cls,
        retrieved_ids: Sequence[RetrievalId],
        relevant_ids: Iterable[RetrievalId],
        *,
        k: int,
    ) -> float:
        cls._validate_k(k)

        relevant = set(relevant_ids)
        if not relevant:
            return 0.0

        top_k = cls._normalize_ids(
            retrieved_ids[:k]
        )

        if not top_k:
            return 0.0

        hits = sum(
            item in relevant
            for item in top_k
        )

        return hits / len(top_k)

    @classmethod
    def recall_at_k(
        cls,
        retrieved_ids: Sequence[RetrievalId],
        relevant_ids: Iterable[RetrievalId],
        *,
        k: int,
    ) -> float:
        cls._validate_k(k)

        relevant = set(relevant_ids)
        if not relevant:
            return 0.0

        top_k = cls._normalize_ids(
            retrieved_ids[:k]
        )

        hits = sum(
            item in relevant
            for item in set(top_k)
        )

        return hits / len(relevant)

    @classmethod
    def mean_reciprocal_rank(
        cls,
        retrieved_ids: Sequence[RetrievalId],
        relevant_ids: Iterable[RetrievalId],
        *,
        k: int | None = None,
    ) -> float:
        relevant = set(relevant_ids)
        if not relevant:
            return 0.0

        if k is not None:
            cls._validate_k(k)
            ranked_ids = retrieved_ids[:k]
        else:
            ranked_ids = retrieved_ids

        for rank, item in enumerate(
            ranked_ids,
            start=1,
        ):
            if item in relevant:
                return 1.0 / rank

        return 0.0

    @classmethod
    def evaluate_case(
        cls,
        case: RAGEvaluationCase,
        retrieved_ids: Sequence[RetrievalId],
        *,
        k_values: Sequence[int] = (1, 3, 5, 8),
    ) -> dict[str, float | str]:
        if not case.query.strip():
            raise ValueError(
                "query cannot be empty"
            )

        if not case.relevant_ids:
            raise ValueError(
                "relevant_ids cannot be empty"
            )

        normalized_k_values = sorted(
            set(k_values)
        )

        if not normalized_k_values:
            raise ValueError(
                "k_values cannot be empty"
            )

        metrics: dict[str, float | str] = {
            "query": case.query,
        }

        for k in normalized_k_values:
            metrics[
                f"precision_at_{k}"
            ] = cls.precision_at_k(
                retrieved_ids,
                case.relevant_ids,
                k=k,
            )
            metrics[
                f"recall_at_{k}"
            ] = cls.recall_at_k(
                retrieved_ids,
                case.relevant_ids,
                k=k,
            )

        metrics["mrr"] = (
            cls.mean_reciprocal_rank(
                retrieved_ids,
                case.relevant_ids,
            )
        )

        return metrics

    @staticmethod
    def aggregate(
        case_results: Sequence[
            dict[str, float | str]
        ],
    ) -> dict[str, float]:
        if not case_results:
            raise ValueError(
                "case_results cannot be empty"
            )

        numeric_keys = {
            key
            for result in case_results
            for key, value in result.items()
            if isinstance(value, (int, float))
        }

        return {
            key: sum(
                float(result[key])
                for result in case_results
                if key in result
                and isinstance(
                    result[key],
                    (int, float),
                )
            )
            / sum(
                1
                for result in case_results
                if key in result
                and isinstance(
                    result[key],
                    (int, float),
                )
            )
            for key in sorted(numeric_keys)
            if any(
                key in result
                and isinstance(
                    result[key],
                    (int, float),
                )
                for result in case_results
            )
        }
