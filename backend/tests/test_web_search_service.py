from __future__ import annotations

import json

import pytest

from services.web_search_service import (
    WebSearchService,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_web_search_requires_api_key():
    service = WebSearchService(api_key="")

    with pytest.raises(
        RuntimeError,
        match="TAVILY_API_KEY",
    ):
        service.search(query="latest AI news")


def test_web_search_normalizes_provider_results(
    monkeypatch,
):
    service = WebSearchService(
        api_key="tvly-test"
    )

    captured = {}

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        captured["body"] = json.loads(
            request.data.decode("utf-8")
        )

        return FakeResponse(
            {
                "results": [
                    {
                        "title": "AI News",
                        "url": "https://example.com/ai",
                        "content": "Fresh AI information.",
                        "score": 0.91,
                        "published_date": "2026-09-21",
                    },
                    {
                        "title": "",
                        "url": "https://example.com/ignored",
                        "content": "ignored",
                    },
                ]
            }
        )

    monkeypatch.setattr(
        "services.web_search_service.urlopen",
        fake_urlopen,
    )

    results = service.search(
        query="  latest   AI   news  ",
        max_results=5,
        topic="news",
        time_range="day",
    )

    assert captured["authorization"] == "Bearer tvly-test"
    assert captured["timeout"] == 10
    assert captured["body"] == {
        "query": "latest AI news",
        "search_depth": "basic",
        "topic": "news",
        "max_results": 5,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "time_range": "day",
    }

    assert results == [
        {
            "title": "AI News",
            "url": "https://example.com/ai",
            "content": "Fresh AI information.",
            "score": 0.91,
            "published_date": "2026-09-21",
        }
    ]


@pytest.mark.parametrize(
    "topic",
    ["bad", "", "search"],
)
def test_web_search_rejects_invalid_topic(topic):
    service = WebSearchService(
        api_key="tvly-test"
    )

    with pytest.raises(
        ValueError,
        match="topic must be one of",
    ):
        service.search(
            query="AI",
            topic=topic,
        )


@pytest.mark.parametrize(
    "time_range",
    ["hour", "invalid"],
)
def test_web_search_rejects_invalid_time_range(
    time_range,
):
    service = WebSearchService(
        api_key="tvly-test"
    )

    with pytest.raises(
        ValueError,
        match="time_range must be one of",
    ):
        service.search(
            query="AI",
            time_range=time_range,
        )
