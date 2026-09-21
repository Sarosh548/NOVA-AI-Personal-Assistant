from services.rag_evaluation_service import (
    RAGEvaluationCase,
    RAGEvaluationService,
)


def test_evaluate_retriever_uses_ranked_result_ids():
    cases = [
        RAGEvaluationCase(
            query="python",
            relevant_ids=frozenset({"python"}),
        ),
        RAGEvaluationCase(
            query="calendar",
            relevant_ids=frozenset({"calendar"}),
        ),
    ]

    calls = []

    def retriever(query, limit):
        calls.append(
            {
                "query": query,
                "limit": limit,
            }
        )

        if query == "python":
            return [
                {"source": "memory"},
                {"source": "python"},
                {"source": "planner"},
            ]

        return [
            {"source": "calendar"},
            {"source": "permission"},
        ]

    result = RAGEvaluationService.evaluate_retriever(
        cases,
        retriever,
        lambda item: item.get("source"),
        k_values=(1, 3),
    )

    assert calls == [
        {
            "query": "python",
            "limit": 3,
        },
        {
            "query": "calendar",
            "limit": 3,
        },
    ]

    assert result["cases"][0]["precision_at_1"] == 0.0
    assert result["cases"][0]["recall_at_3"] == 1.0
    assert result["cases"][0]["mrr"] == 1 / 2

    assert result["cases"][1]["precision_at_1"] == 1.0
    assert result["cases"][1]["recall_at_3"] == 1.0

    assert result["aggregate"]["recall_at_1"] == 0.5


def test_evaluate_retriever_ignores_results_without_ids():
    case = RAGEvaluationCase(
        query="python",
        relevant_ids=frozenset({"python"}),
    )

    result = RAGEvaluationService.evaluate_retriever(
        [case],
        lambda query, limit: [
            {"source": None},
            {"source": "python"},
        ],
        lambda item: item.get("source"),
        k_values=(1, 3),
    )

    assert result["cases"][0]["recall_at_1"] == 1.0
    assert result["cases"][0]["mrr"] == 1.0


def test_evaluate_retriever_rejects_empty_k_values():
    case = RAGEvaluationCase(
        query="python",
        relevant_ids=frozenset({"python"}),
    )

    try:
        RAGEvaluationService.evaluate_retriever(
            [case],
            lambda query, limit: [],
            lambda item: item.get("source"),
            k_values=(),
        )
    except ValueError as exc:
        assert "k_values" in str(exc)
    else:
        raise AssertionError(
            "Expected empty k_values rejection"
        )
