from __future__ import annotations

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


def run_baseline() -> dict:
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
            return service.search(
                user_id=BENCHMARK_USER_ID,
                query=query,
                threshold=0.0,
                limit=limit,
            )

        evaluation = (
            RAGEvaluationService.evaluate_retriever(
                RAG_BENCHMARK_CASES,
                retriever,
                _source_id_from_result,
                k_values=DEFAULT_BENCHMARK_K_VALUES,
            )
        )

        return evaluation

    finally:
        _reset_benchmark_documents(
            service
        )


def main() -> None:
    result = run_baseline()

    print(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
