from services.rag_evaluation_service import (
    RAGEvaluationCase,
    RAGEvaluationService,
)


def test_precision_at_k_counts_relevant_results():
    retrieved = [
        "a",
        "b",
        "c",
        "d",
    ]

    score = RAGEvaluationService.precision_at_k(
        retrieved,
        {"a", "c"},
        k=3,
    )

    assert score == 2 / 3


def test_recall_at_k_measures_relevant_coverage():
    retrieved = [
        "a",
        "b",
        "c",
        "d",
    ]

    score = RAGEvaluationService.recall_at_k(
        retrieved,
        {"a", "c", "e"},
        k=4,
    )

    assert score == 2 / 3


def test_recall_at_k_deduplicates_retrieved_ids():
    retrieved = [
        "a",
        "a",
        "b",
    ]

    score = RAGEvaluationService.recall_at_k(
        retrieved,
        {"a", "b"},
        k=3,
    )

    assert score == 1.0


def test_mean_reciprocal_rank_uses_first_relevant_rank():
    retrieved = [
        "x",
        "y",
        "target",
        "target-2",
    ]

    score = RAGEvaluationService.mean_reciprocal_rank(
        retrieved,
        {"target", "target-2"},
    )

    assert score == 1 / 3


def test_mean_reciprocal_rank_can_be_limited():
    retrieved = [
        "x",
        "y",
        "target",
    ]

    score = RAGEvaluationService.mean_reciprocal_rank(
        retrieved,
        {"target"},
        k=2,
    )

    assert score == 0.0


def test_evaluate_case_returns_precision_recall_and_mrr():
    case = RAGEvaluationCase(
        query="python",
        relevant_ids=frozenset({"a", "c"}),
    )

    result = RAGEvaluationService.evaluate_case(
        case,
        [
            "a",
            "b",
            "c",
        ],
        k_values=(1, 3),
    )

    assert result["query"] == "python"
    assert result["precision_at_1"] == 1.0
    assert result["recall_at_1"] == 0.5
    assert result["precision_at_3"] == 2 / 3
    assert result["recall_at_3"] == 1.0
    assert result["mrr"] == 1.0


def test_aggregate_averages_numeric_metrics():
    results = [
        {
            "query": "one",
            "precision_at_1": 1.0,
            "recall_at_1": 0.5,
            "mrr": 1.0,
        },
        {
            "query": "two",
            "precision_at_1": 0.0,
            "recall_at_1": 1.0,
            "mrr": 0.5,
        },
    ]

    aggregated = RAGEvaluationService.aggregate(
        results
    )

    assert aggregated == {
        "mrr": 0.75,
        "precision_at_1": 0.5,
        "recall_at_1": 0.75,
    }


def test_metrics_handle_empty_relevant_set():
    assert (
        RAGEvaluationService.precision_at_k(
            ["a"],
            set(),
            k=1,
        )
        == 0.0
    )

    assert (
        RAGEvaluationService.recall_at_k(
            ["a"],
            set(),
            k=1,
        )
        == 0.0
    )

    assert (
        RAGEvaluationService.mean_reciprocal_rank(
            ["a"],
            set(),
        )
        == 0.0
    )


def test_invalid_k_is_rejected():
    try:
        RAGEvaluationService.precision_at_k(
            ["a"],
            {"a"},
            k=0,
        )
    except ValueError as exc:
        assert "k" in str(exc)
    else:
        raise AssertionError(
            "Expected invalid k rejection"
        )


def test_invalid_case_query_is_rejected():
    case = RAGEvaluationCase(
        query=" ",
        relevant_ids=frozenset({"a"}),
    )

    try:
        RAGEvaluationService.evaluate_case(
            case,
            ["a"],
        )
    except ValueError as exc:
        assert "query" in str(exc)
    else:
        raise AssertionError(
            "Expected empty query rejection"
        )


def test_invalid_case_relevance_is_rejected():
    case = RAGEvaluationCase(
        query="python",
        relevant_ids=frozenset(),
    )

    try:
        RAGEvaluationService.evaluate_case(
            case,
            ["a"],
        )
    except ValueError as exc:
        assert "relevant_ids" in str(exc)
    else:
        raise AssertionError(
            "Expected empty relevance rejection"
        )


def test_empty_k_values_are_rejected():
    case = RAGEvaluationCase(
        query="python",
        relevant_ids=frozenset({"a"}),
    )

    try:
        RAGEvaluationService.evaluate_case(
            case,
            ["a"],
            k_values=(),
        )
    except ValueError as exc:
        assert "k_values" in str(exc)
    else:
        raise AssertionError(
            "Expected empty k_values rejection"
        )


def test_empty_aggregate_is_rejected():
    try:
        RAGEvaluationService.aggregate([])
    except ValueError as exc:
        assert "case_results" in str(exc)
    else:
        raise AssertionError(
            "Expected empty aggregate rejection"
        )
