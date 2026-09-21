from __future__ import annotations

from services.reranker_service import (
    RerankerService,
)


class FakeCrossEncoder:
    def __init__(
        self,
        scores,
    ):
        self.scores = scores
        self.calls = []

    def predict(
        self,
        pairs,
        *,
        batch_size,
        show_progress_bar,
    ):
        self.calls.append(
            {
                "pairs": pairs,
                "batch_size": batch_size,
                "show_progress_bar": show_progress_bar,
            }
        )
        return self.scores


def test_rerank_sorts_candidates_by_cross_encoder_score():
    model = FakeCrossEncoder(
        [
            0.20,
            0.95,
            0.60,
        ]
    )

    service = RerankerService(
        model=model,
        batch_size=8,
        max_length=256,
    )

    candidates = [
        {
            "document_id": 1,
            "content": "First passage",
            "similarity": 0.90,
        },
        {
            "document_id": 2,
            "content": "Second passage",
            "similarity": 0.80,
        },
        {
            "document_id": 3,
            "content": "Third passage",
            "similarity": 0.70,
        },
    ]

    result = service.rerank(
        "Which passage matters?",
        candidates,
    )

    assert [
        item["document_id"]
        for item in result
    ] == [
        2,
        3,
        1,
    ]

    assert [
        item["rerank_score"]
        for item in result
    ] == [
        0.95,
        0.60,
        0.20,
    ]

    assert result[0]["similarity"] == 0.80

    assert model.calls == [
        {
            "pairs": [
                (
                    "Which passage matters?",
                    "First passage",
                ),
                (
                    "Which passage matters?",
                    "Second passage",
                ),
                (
                    "Which passage matters?",
                    "Third passage",
                ),
            ],
            "batch_size": 8,
            "show_progress_bar": False,
        }
    ]


def test_rerank_includes_candidate_title_when_available():
    model = FakeCrossEncoder([0.90])

    service = RerankerService(model=model)

    service.rerank(
        "How can I add a web page to NOVA knowledge?",
        [
            {
                "title": "NOVA URL Knowledge Ingestion",
                "content": (
                    "URL knowledge ingestion validates and safely "
                    "fetches web pages."
                ),
            }
        ],
    )

    assert model.calls == [
        {
            "pairs": [
                (
                    "How can I add a web page to NOVA knowledge?",
                    (
                        "Title: NOVA URL Knowledge Ingestion\\n"
                        "Content: URL knowledge ingestion validates and safely "
                        "fetches web pages."
                    ),
                )
            ],
            "batch_size": 16,
            "show_progress_bar": False,
        }
    ]


def test_rerank_supports_top_k():
    model = FakeCrossEncoder(
        [
            0.10,
            0.90,
            0.50,
        ]
    )

    service = RerankerService(model=model)

    result = service.rerank(
        "query",
        [
            {"content": "a"},
            {"content": "b"},
            {"content": "c"},
        ],
        top_k=2,
    )

    assert [
        item["content"]
        for item in result
    ] == [
        "b",
        "c",
    ]


def test_rerank_preserves_input_order_for_equal_scores():
    model = FakeCrossEncoder(
        [
            0.50,
            0.50,
            0.50,
        ]
    )

    service = RerankerService(model=model)

    result = service.rerank(
        "query",
        [
            {"content": "a"},
            {"content": "b"},
            {"content": "c"},
        ],
    )

    assert [
        item["content"]
        for item in result
    ] == [
        "a",
        "b",
        "c",
    ]


def test_rerank_returns_empty_for_empty_candidates():
    model = FakeCrossEncoder([])

    service = RerankerService(model=model)

    assert service.rerank(
        "query",
        [],
    ) == []

    assert model.calls == []


def test_rerank_rejects_empty_query():
    model = FakeCrossEncoder([])

    service = RerankerService(model=model)

    try:
        service.rerank(
            " ",
            [],
        )
    except ValueError as exc:
        assert "query" in str(exc)
    else:
        raise AssertionError(
            "Expected empty query rejection"
        )


def test_rerank_rejects_invalid_top_k():
    model = FakeCrossEncoder([])

    service = RerankerService(model=model)

    try:
        service.rerank(
            "query",
            [{"content": "text"}],
            top_k=0,
        )
    except ValueError as exc:
        assert "top_k" in str(exc)
    else:
        raise AssertionError(
            "Expected invalid top_k rejection"
        )


def test_rerank_rejects_missing_candidate_content():
    model = FakeCrossEncoder([])

    service = RerankerService(model=model)

    try:
        service.rerank(
            "query",
            [{"document_id": 1}],
        )
    except ValueError as exc:
        assert "missing content" in str(exc)
    else:
        raise AssertionError(
            "Expected missing content rejection"
        )


def test_rerank_rejects_empty_candidate_content():
    model = FakeCrossEncoder([])

    service = RerankerService(model=model)

    try:
        service.rerank(
            "query",
            [{"content": "   "}],
        )
    except ValueError as exc:
        assert "empty content" in str(exc)
    else:
        raise AssertionError(
            "Expected empty content rejection"
        )


def test_rerank_rejects_invalid_batch_size():
    model = FakeCrossEncoder([])

    try:
        RerankerService(
            model=model,
            batch_size=0,
        )
    except ValueError as exc:
        assert "batch_size" in str(exc)
    else:
        raise AssertionError(
            "Expected invalid batch size rejection"
        )


def test_rerank_rejects_invalid_max_length():
    model = FakeCrossEncoder([])

    try:
        RerankerService(
            model=model,
            max_length=0,
        )
    except ValueError as exc:
        assert "max_length" in str(exc)
    else:
        raise AssertionError(
            "Expected invalid max length rejection"
        )


def test_rerank_rejects_score_count_mismatch():
    model = FakeCrossEncoder(
        [
            0.50,
        ]
    )

    service = RerankerService(model=model)

    try:
        service.rerank(
            "query",
            [
                {"content": "a"},
                {"content": "b"},
            ],
        )
    except ValueError as exc:
        assert "unexpected number of scores" in str(exc)
    else:
        raise AssertionError(
            "Expected score count mismatch rejection"
        )
