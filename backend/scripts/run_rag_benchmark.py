from __future__ import annotations

import argparse
import json

from services.knowledge_service import KnowledgeService
from services.rag_evaluation_service import (
    RAGEvaluationService,
)
from tests.rag_benchmark_data import (
    DEFAULT_BENCHMARK_K_VALUES,
    RAG_BENCHMARK_CASES,
    RAG_BENCHMARK_DOCUMENTS,
)


BENCHMARK_USER_ID = "rag-benchmark-user"
BENCHMARK_SOURCE_PREFIX = "benchmark:"
RERANK_BENCHMARK_CANDIDATE_LIMIT = 24


def _benchmark_source(source_id: str) -> str:
    return f"{BENCHMARK_SOURCE_PREFIX}{source_id}"


def _source_id_from_result(
    result: dict,
) -> str | None:
    source = result.get("source")

    if not isinstance(source, str):
        return None

    if not source.startswith(
        BENCHMARK_SOURCE_PREFIX
    ):
        return None

    return source[
        len(BENCHMARK_SOURCE_PREFIX):
    ]


def _reset_benchmark_documents(
    service: KnowledgeService,
) -> None:
    documents = service.list_documents(
        user_id=BENCHMARK_USER_ID,
        limit=100,
    )

    for document in documents:
        source = document.get("source")

        if (
            isinstance(source, str)
            and source.startswith(
                BENCHMARK_SOURCE_PREFIX
            )
        ):
            service.delete_document(
                user_id=BENCHMARK_USER_ID,
                document_id=document["id"],
            )


def _seed_benchmark_documents(
    service: KnowledgeService,
) -> None:
    for benchmark_document in (
        RAG_BENCHMARK_DOCUMENTS
    ):
        service.create_document(
            user_id=BENCHMARK_USER_ID,
            title=benchmark_document.title,
            content=benchmark_document.content,
            source=_benchmark_source(
                benchmark_document.source_id
            ),
        )


def _run_evaluation(
    *,
    rerank: bool,
) -> dict:
    service = KnowledgeService()

    _reset_benchmark_documents(
        service
    )

    try:
        _seed_benchmark_documents(
            service
        )

        def retriever(
            query: str,
            limit: int,
        ) -> list[dict]:
            search_kwargs = {
                "user_id": BENCHMARK_USER_ID,
                "query": query,
                "threshold": 0.0,
                "limit": limit,
            }

            if rerank:
                search_kwargs.update(
                    {
                        "rerank": True,
                        "candidate_limit": (
                            RERANK_BENCHMARK_CANDIDATE_LIMIT
                        ),
                    }
                )

            return service.search(
                **search_kwargs
            )

        return RAGEvaluationService.evaluate_retriever(
            RAG_BENCHMARK_CASES,
            retriever,
            _source_id_from_result,
            k_values=DEFAULT_BENCHMARK_K_VALUES,
        )

    finally:
        _reset_benchmark_documents(
            service
        )


def run_baseline() -> dict:
    """
    Run the locked bi-encoder/pgvector retrieval baseline.

    This keeps the original benchmark semantics unchanged:
    threshold=0.0 and rerank=False.
    """

    return _run_evaluation(
        rerank=False
    )


def run_reranked() -> dict:
    """
    Run candidate retrieval followed by Cross-Encoder reranking.

    The benchmark intentionally keeps threshold=0.0 so the
    comparison measures the reranked retrieval path rather than
    introducing a different similarity-threshold policy.
    """

    return _run_evaluation(
        rerank=True
    )


def _calculate_metric_deltas(
    baseline: dict,
    reranked: dict,
) -> dict[str, float]:
    baseline_aggregate = baseline[
        "aggregate"
    ]
    reranked_aggregate = reranked[
        "aggregate"
    ]

    return {
        key: float(
            reranked_aggregate[key]
        )
        - float(
            baseline_aggregate[key]
        )
        for key in baseline_aggregate
        if (
            key in reranked_aggregate
            and isinstance(
                baseline_aggregate[key],
                (int, float),
            )
            and isinstance(
                reranked_aggregate[key],
                (int, float),
            )
        )
    }


def run_comparison() -> dict:
    """
    Run baseline and reranked retrieval and report metric deltas.
    """

    baseline = run_baseline()
    reranked = run_reranked()

    return {
        "baseline": baseline,
        "reranked": reranked,
        "delta": _calculate_metric_deltas(
            baseline,
            reranked,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run NOVA's deterministic RAG retrieval benchmark."
        )
    )
    parser.add_argument(
        "--mode",
        choices=(
            "baseline",
            "reranked",
            "compare",
        ),
        default="baseline",
        help=(
            "Benchmark mode. Default preserves the original "
            "baseline-only behavior."
        ),
    )

    args = parser.parse_args()

    if args.mode == "baseline":
        result = run_baseline()
    elif args.mode == "reranked":
        result = run_reranked()
    else:
        result = run_comparison()

    print(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
