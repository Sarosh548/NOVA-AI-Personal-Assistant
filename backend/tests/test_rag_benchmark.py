from services.rag_evaluation_service import (
    RAGEvaluationService,
)
from tests.rag_benchmark_data import (
    DEFAULT_BENCHMARK_K_VALUES,
    RAG_BENCHMARK_CASES,
    RAG_BENCHMARK_DOCUMENTS,
)


def test_benchmark_document_source_ids_are_unique():
    source_ids = [
        document.source_id
        for document in RAG_BENCHMARK_DOCUMENTS
    ]

    assert source_ids
    assert len(source_ids) == len(set(source_ids))


def test_benchmark_documents_contain_usable_content():
    for document in RAG_BENCHMARK_DOCUMENTS:
        assert document.title.strip()
        assert document.content.strip()


def test_benchmark_cases_have_known_relevant_sources():
    source_ids = {
        document.source_id
        for document in RAG_BENCHMARK_DOCUMENTS
    }

    assert RAG_BENCHMARK_CASES

    for case in RAG_BENCHMARK_CASES:
        assert case.query.strip()
        assert case.relevant_ids
        assert case.relevant_ids <= source_ids


def test_benchmark_k_values_are_valid_and_ordered():
    assert DEFAULT_BENCHMARK_K_VALUES == (
        1,
        3,
        5,
        8,
    )


def test_benchmark_cases_can_be_evaluated_deterministically():
    case = RAG_BENCHMARK_CASES[0]

    result = RAGEvaluationService.evaluate_case(
        case,
        [
            "nova-memory",
            "nova-auth",
            "nova-planner",
        ],
        k_values=DEFAULT_BENCHMARK_K_VALUES,
    )

    assert result["query"] == case.query
    assert result["precision_at_1"] == 0.0
    assert result["precision_at_3"] == 1 / 3
    assert result["recall_at_3"] == 1.0
    assert result["mrr"] == 1 / 2


def test_benchmark_covers_multi_document_queries():
    multi_source_cases = [
        case
        for case in RAG_BENCHMARK_CASES
        if len(case.relevant_ids) > 1
    ]

    assert len(multi_source_cases) >= 2
