from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

import services.web_search_service as web_search_module
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


def test_day_scoped_web_search_filters_stale_and_undated_sources(monkeypatch):
    service = WebSearchService(api_key="", searxng_endpoint="http://127.0.0.1:8080/search")
    fresh_date = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        service,
        "_request_searxng",
        lambda **kwargs: {
            "results": [
                {
                    "title": "Latest NASA Artemis II mission update",
                    "url": "https://example.com/current-artemis-update",
                    "content": "A current, dated Artemis II update from today.",
                    "published_date": fresh_date,
                },
                {
                    "title": "Artemis II launches in June",
                    "url": "https://example.com/old-artemis-launch",
                    "content": "Historical coverage of a past launch.",
                    "published_date": "2026-06-23T07:00:00+00:00",
                },
                {
                    "title": "Undated Artemis article",
                    "url": "https://example.com/undated-artemis",
                    "content": "No publication timestamp was provided.",
                },
            ]
        },
    )

    results = service.search(query="latest NASA Artemis II update", time_range="day")

    assert [item["url"] for item in results] == ["https://example.com/current-artemis-update"]


def test_web_search_requires_a_search_provider(monkeypatch):
    service = WebSearchService(
        api_key="",
        searxng_endpoint="",
    )
    monkeypatch.setattr(
        service,
        "_request_brave_search",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("Brave unavailable")),
    )

    with pytest.raises(
        RuntimeError,
        match="temporarily unavailable",
    ):
        service.search(query="latest AI news")


def test_production_does_not_default_to_container_loopback_searxng(monkeypatch):
    monkeypatch.setenv("NOVA_ENV", "production")
    monkeypatch.delenv("SEARXNG_URL", raising=False)

    service = WebSearchService(api_key="")

    # In cloud, 127.0.0.1 points at NOVA itself unless a search container
    # really runs beside it. Let news fall back to Google News RSS instead.
    assert service.searxng_endpoint == ""


class FakeBytesResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, *_args):
        return self.body


def test_search_cleans_scraped_page_chrome_from_result_snippets(monkeypatch):
    service = WebSearchService(api_key="tvly-test", searxng_endpoint="")
    title = "Amid rising cyber threats, Moonshot AI limits hacking capabilities in latest model"
    noisy_content = (
        "Global stories. Indian perspective. Zero noise. Subscribe Now. No Spam. "
        "Unsubscribe Any Time. Tags Artificial Intelligence cybersecurity "
        "First Published: Oct 26, 2026. Home Tech "
        + title
        + " Advertisement Advertisement Up Next HomeVideosFirst AIQuick ReadsLive TV"
    )
    monkeypatch.setattr(service, "_request_tavily", lambda _payload: {"results": [{
        "title": title,
        "url": "https://example.com/moonshot-ai-news",
        "content": noisy_content,
        "score": 0.9,
        "published_date": "2026-10-26T08:46:25Z",
    }]})

    results = service.search(query="latest AI news", topic="general")

    assert len(results) == 1
    assert "Moonshot AI limits hacking capabilities" in results[0]["content"]
    assert not any(marker in results[0]["content"].lower() for marker in (
        "advertisement", "subscribe now", "unsubscribe any time", "homevideos", "quick reads",
    ))
    assert len(results[0]["content"]) <= 900


def test_search_uses_title_when_snippet_is_only_publisher_promotion(monkeypatch):
    service = WebSearchService(api_key="tvly-test", searxng_endpoint="")
    title = "Amid rising cyber threats, Moonshot AI limits hacking capabilities in latest model"
    monkeypatch.setattr(service, "_request_tavily", lambda _payload: {"results": [{
        "title": title,
        "url": "https://example.com/moonshot-ai-news",
        "content": "Global stories. Indian perspective. Zero noise. Subscribe Now. No Spam. Unsubscribe Any Time.",
        "score": 0.9,
    }]})

    results = service.search(query="latest AI news", topic="general")

    assert results[0]["content"] == title


def test_search_rejects_unrelated_headline_lists_as_article_excerpt(monkeypatch):
    service = WebSearchService(api_key="tvly-test", searxng_endpoint="")
    title = "Watch Moonshot's Latest AI Upgrade Takes on Top-Tier US Models - Bloomberg"
    related_headlines = (
        "### DeepSeek Nears $12B Funding Round Ahead of Potential IPO "
        "### China Stocks Dip As Soft Travel Data Drags on Sentiment "
        "### China Rejects Claims the Yuan Is Undervalued"
    )
    monkeypatch.setattr(service, "_request_tavily", lambda _payload: {"results": [{
        "title": title,
        "url": "https://example.com/moonshot-video",
        "content": related_headlines,
        "score": 0.7,
    }]})

    results = service.search(query="latest AI news", topic="general")

    assert results[0]["content"] == title
    assert "DeepSeek" not in results[0]["content"]


def test_search_trims_social_follow_widget_from_article_snippet(monkeypatch):
    service = WebSearchService(api_key="tvly-test", searxng_endpoint="")
    title = "1Password will now let AI agents log in to accounts for you without ever needing to see your password | TechRadar"
    noisy_content = (
        "Grok Bot and Meta Muse are among the first AI agents to get rollout over the coming days, "
        "while ChatGPT Work, Dots and Claude Duet are just listed as coming soon. "
        "Google logo on a black background next to text reading 'Click to follow TechRadar' "
        "Google logo on a black background next to text reading 'Click to follow TechRadar' "
        "Follow TechRadar on Google."
    )
    monkeypatch.setattr(service, "_request_tavily", lambda _payload: {"results": [{
        "title": title,
        "url": "https://example.com/1password-ai-agents",
        "content": noisy_content,
        "score": 0.9,
    }]})

    results = service.search(query="latest AI news", topic="general")

    assert len(results) == 1
    assert "Grok Bot and Meta Muse" in results[0]["content"]
    assert "Google logo" not in results[0]["content"]
    assert "Click to follow" not in results[0]["content"]
    assert "Follow TechRadar on Google" not in results[0]["content"]


def test_search_preserves_clean_article_snippet(monkeypatch):
    service = WebSearchService(api_key="tvly-test", searxng_endpoint="")
    content = "OpenAI announced a new model with improved reasoning and lower inference latency today."
    monkeypatch.setattr(service, "_request_tavily", lambda _payload: {"results": [{
        "title": "OpenAI announces a new model",
        "url": "https://example.com/openai-model",
        "content": content,
        "score": 0.8,
    }]})

    results = service.search(query="OpenAI new model", topic="general")

    assert results[0]["content"] == content


def test_brave_html_search_parses_title_snippet_and_direct_source_url(monkeypatch):
    body = b'''<!doctype html><html><body>
      <div class="snippet svelte-x" data-pos="0" data-type="web">
        <div class="result-content">
          <a href="https://academy.langchain.com/courses/intro-to-langgraph">
            <div class="title search-snippet-title" title="Introduction to LangGraph - Python">Introduction to LangGraph - Python</div>
          </a>
          <div class="generic-snippet"><div class="content">Learn LangGraph for building reliable agent workflows.</div></div>
        </div>
      </div>
    </body></html>'''
    observed = {}

    def fake_urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["timeout"] = timeout
        return FakeBytesResponse(body)

    monkeypatch.setattr(web_search_module, "urlopen", fake_urlopen)
    service = WebSearchService(api_key="", searxng_endpoint="")

    payload = service._request_brave_search(
        query="LangGraph tutorials",
        time_range=None,
    )

    assert payload["results"] == [{
        "title": "Introduction to LangGraph - Python",
        "url": "https://academy.langchain.com/courses/intro-to-langgraph",
        "content": "Learn LangGraph for building reliable agent workflows.",
        "score": None,
        "published_date": None,
    }]
    assert "q=LangGraph+tutorials" in observed["url"]
    assert "source=web" in observed["url"]
    assert observed["timeout"] <= 3


def test_cricbuzz_live_scores_are_preferred_and_completed_matches_are_rejected(monkeypatch):
    page = b'''<html><body>
      <a href="/live-cricket-scores/123/pak-eng-live" class="w-full bg-cbWhite flex flex-col p-3 gap-1" title="Pakistan vs England, 1st ODI">
        <span>Pakistan</span><span>PAK</span><span>241-4</span>
        <span>England</span><span>ENG</span><span>199-2</span><span>LIVE</span>
      </a>
      <a href="/live-cricket-scores/122/pak-eng-old" class="w-full bg-cbWhite flex flex-col p-3 gap-1" title="Pakistan vs England, Previous ODI - PAK won">
        <span>Pakistan</span><span>PAK</span><span>228-9</span><span>PAK won</span>
      </a>
      <a href="/live-cricket-scores/111/inda-nza-stumps" class="w-full bg-cbWhite flex flex-col p-3 gap-1" title="India A vs New Zealand A, Test - Stumps">
        <span>India A</span><span>INDA</span><span>488-8</span>
        <span>New Zealand A</span><span>NZA</span><span>317</span><span>Day 3: Stumps</span>
      </a>
    </body></html>'''
    monkeypatch.setattr(
        web_search_module,
        "urlopen",
        lambda _request, timeout: FakeBytesResponse(page),
    )
    service = WebSearchService(api_key="", searxng_endpoint="")

    results = service.search(
        query="Cricket ka score batao",
        topic="general",
    )

    assert len(results) == 1
    assert results[0]["url"] == "https://www.cricbuzz.com/live-cricket-scores/123/pak-eng-live"
    assert "241-4" in results[0]["content"]
    assert "just now" in results[0]["content"]


def test_live_cricket_score_intent_recognizes_roman_urdu():
    assert WebSearchService._is_live_cricket_score_query("Cricket ka score batao")
    assert WebSearchService._is_live_cricket_score_query("Aaj cricket mein match ho raha hai?")
    assert WebSearchService._is_live_sports_query("Pakistan ka score batao")


def test_live_sports_freshness_filter_rejects_stale_undated_and_future_results():
    now = datetime(2026, 10, 25, 17, 45, tzinfo=timezone.utc)
    results = [
        {
            "title": "Old Pakistan vs England score",
            "url": "https://example.com/old-score",
            "published_date": (now - timedelta(hours=5)).isoformat(),
        },
        {
            "title": "Recent Pakistan vs England score",
            "url": "https://www.espncricinfo.com/live-score",
            "published_date": (now - timedelta(minutes=12)).isoformat(),
        },
        {
            "title": "Undated scorecard",
            "url": "https://example.com/undated-score",
            "content": "Pakistan vs England scorecard",
        },
        {
            "title": "Future scorecard",
            "url": "https://example.com/future-score",
            "published_date": (now + timedelta(hours=1)).isoformat(),
        },
    ]

    filtered = WebSearchService._filter_fresh_live_sports_results(results, now=now)

    assert [item["title"] for item in filtered] == ["Recent Pakistan vs England score"]


def test_live_sports_search_never_returns_a_stale_score_as_current(monkeypatch):
    service = WebSearchService(api_key="tvly-test", searxng_endpoint="")
    monkeypatch.setattr(
        service,
        "_request_tavily",
        lambda _payload: {
            "results": [
                {
                    "title": "Pakistan vs England live score: ENG 241/10",
                    "url": "https://example.com/old-score",
                    "content": "ENG 241/10 in 46.4 overs. Pakistan need 242.",
                    "published_date": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(),
                }
            ]
        },
    )

    results = service.search(
        query="Pakistan vs England cricket live score today",
        topic="general",
        time_range="day",
        max_results=5,
    )

    assert results == []


def test_live_sports_result_ranking_prefers_scorecards_over_previews():
    results = [
        {
            "title": "Pakistan vs England match preview and prediction",
            "url": "https://www.espncricinfo.com/series/preview",
            "content": "Preview, team lineup and match prediction before the game.",
            "score": 0.8,
            "published_date": "2026-10-25",
        },
        {
            "title": "Pakistan vs England live scorecard, score and match updates",
            "url": "https://www.cricbuzz.com/live-cricket-score/123",
            "content": "Live cricket scorecard showing current runs, wickets and overs.",
            "score": 0.7,
            "published_date": "2026-10-25",
        },
        {
            "title": "Pakistan and England sports news roundup",
            "url": "https://example.com/roundup",
            "content": "A general sports news roundup.",
            "score": 0.9,
            "published_date": "2026-10-25",
        },
    ]

    ranked = WebSearchService._rank_live_sports_results(
        "Pakistan vs England cricket live score today",
        results,
    )

    assert ranked[0]["title"] == "Pakistan vs England live scorecard, score and match updates"
    assert ranked[-1]["title"] == "Pakistan vs England match preview and prediction"


def test_live_sports_ranking_prefers_newer_score_update_over_stale_scorecard():
    now = datetime.now(timezone.utc)
    stale_date = (now - timedelta(hours=5)).isoformat()
    fresh_date = (now - timedelta(minutes=10)).isoformat()
    results = [
        {
            "title": "Pakistan vs England live scorecard and match updates",
            "url": "https://www.cricbuzz.com/live-cricket-score/stale",
            "content": "Pakistan vs England cricket scorecard with current runs and wickets.",
            "score": 1.0,
            "published_date": stale_date,
        },
        {
            "title": "Pakistan vs England live scorecard and match updates",
            "url": "https://www.espncricinfo.com/live-cricket-score/fresh",
            "content": "Pakistan vs England cricket scorecard with current runs and wickets.",
            "score": 0.0,
            "published_date": fresh_date,
        },
    ]

    ranked = WebSearchService._rank_live_sports_results(
        "Pakistan vs England cricket live score today",
        results,
    )

    assert ranked[0]["url"].endswith("/fresh")


def test_live_sports_provider_timeouts_are_bounded(monkeypatch):
    service = WebSearchService(
        api_key="tvly-test",
        searxng_endpoint="https://searx.example/search",
        timeout_seconds=10,
    )
    observed = []

    class FakeRSSResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"<rss><channel></channel></rss>"

    def fake_urlopen(request, timeout):
        observed.append((request.full_url, timeout))
        if "news.google.com" in request.full_url:
            return FakeRSSResponse()
        return FakeResponse({"results": []})

    monkeypatch.setattr("services.web_search_service.urlopen", fake_urlopen)

    query = "Pakistan vs England cricket live score today"
    service._request_tavily({
        "query": query,
        "search_depth": "basic",
        "topic": "general",
        "max_results": 5,
    })
    service._request_searxng(query=query, topic="general", time_range="day")
    service._request_google_news_rss(query=query, time_range="day")

    assert [timeout for _url, timeout in observed] == [2.5, 2.5, 2.5]


def test_fresh_ai_news_avoids_serial_google_news_url_resolution(monkeypatch):
    service = WebSearchService(api_key="", searxng_endpoint="")
    fresh_published_date = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).isoformat()

    def fail_searxng(*, query, topic, time_range):
        raise RuntimeError("SearXNG unavailable")

    def rss_results(*, query, time_range):
        return {
            "results": [
                {
                    "title": "OpenAI announces a new AI model",
                    "url": "https://news.google.com/rss/articles/CBMiFreshAINews",
                    "content": "OpenAI announced a new AI model today.",
                    "published_date": fresh_published_date,
                }
            ]
        }

    def unexpected_resolution(_url):
        raise AssertionError("Fresh news should not wait on serial publisher URL resolution")

    monkeypatch.setattr(service, "_request_searxng", fail_searxng)
    monkeypatch.setattr(service, "_request_google_news_rss", rss_results)
    monkeypatch.setattr(service, "_resolve_google_news_article_url", unexpected_resolution)

    results = service.search(
        query="latest AI news today",
        topic="news",
        time_range="day",
        max_results=5,
    )

    assert len(results) == 1
    assert results[0]["url"] == "https://news.google.com/rss/articles/CBMiFreshAINews"
    assert "intermediary link" in results[0]["content"]


@pytest.mark.parametrize("tavily_mode", ["unavailable", "empty"])
def test_live_sports_search_falls_back_quickly_to_google_news_rss(monkeypatch, tavily_mode):
    service = WebSearchService(api_key="tvly-test", searxng_endpoint="")
    # This test verifies the legacy RSS fallback; current cricket scorecards
    # are covered by the direct scoreboard test below.
    monkeypatch.setattr(service, "_request_cricbuzz_live_scores", lambda *_args: None)
    rss_calls = []
    now = datetime.now(timezone.utc)

    if tavily_mode == "unavailable":
        def tavily_failure(_payload):
            raise RuntimeError("Tavily unavailable")
        monkeypatch.setattr(service, "_request_tavily", tavily_failure)
    else:
        monkeypatch.setattr(service, "_request_tavily", lambda _payload: {"results": []})

    searx_calls = []

    def empty_searxng(*, query, topic, time_range):
        searx_calls.append((query, topic, time_range))
        return {"results": []}

    monkeypatch.setattr(service, "_request_searxng", empty_searxng)

    def rss_results(*, query, time_range):
        rss_calls.append((query, time_range))
        return {
            "results": [
                {
                    "title": "Pakistan vs England live score and match updates",
                    "url": "https://news.google.com/rss/articles/live-score",
                    "content": "Live match score update and scorecard.",
                    "published_date": (now - timedelta(minutes=4)).isoformat(),
                },
                {
                    "title": "Pakistan England scorecard",
                    "url": "https://example.com/scorecard",
                    "content": "Current cricket match scorecard with runs and wickets.",
                    "published_date": (now - timedelta(minutes=5)).isoformat(),
                },
            ]
        }

    monkeypatch.setattr(service, "_request_google_news_rss", rss_results)

    def unexpected_article_resolution(_url):
        raise AssertionError("Live-score search must not serially resolve RSS intermediary URLs")

    monkeypatch.setattr(service, "_resolve_google_news_article_url", unexpected_article_resolution)

    results = service.search(
        query="Pakistan vs England cricket live score today",
        topic="general",
        time_range="day",
        max_results=5,
    )

    assert results
    assert rss_calls[0] == ("Pakistan vs England cricket live score today", "day")
    assert results[0]["title"] == "Pakistan vs England live score and match updates"
    assert searx_calls == [("Pakistan vs England cricket live score today", "general", "day")]
    # Fast live-score mode avoids one serial network request per Google News URL.
    assert "news.google.com" in results[0]["url"]
    assert "intermediary link" in results[0]["content"]


def test_web_search_falls_back_to_searxng_when_tavily_is_unavailable(
    monkeypatch,
):
    service = WebSearchService(
        api_key="",
        searxng_endpoint="http://127.0.0.1:8080/search",
    )

    captured = {}
    fresh_date = datetime.now(timezone.utc).isoformat()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "results": [
                    {
                        "title": "AI Voice Updates",
                        "url": "https://example.com/voice",
                        "content": "Fresh live result.",
                        "score": 0.87,
                        "publishedDate": fresh_date,
                    }
                ]
            }
        )

    monkeypatch.setattr(
        "services.web_search_service.urlopen",
        fake_urlopen,
    )

    results = service.search(
        query="latest AI voice assistants",
        topic="news",
        time_range="day",
    )

    assert "q=latest+AI+voice+assistants" in captured["url"]
    assert "format=json" in captured["url"]
    assert "categories=news" in captured["url"]
    assert "time_range=day" in captured["url"]
    assert captured["timeout"] == 2.5

    assert results == [
        {
            "title": "AI Voice Updates",
            "url": "https://example.com/voice",
            "content": "Fresh live result.",
            "score": 0.87,
            "published_date": fresh_date,
        }
    ]


def test_web_search_normalizes_provider_results(
    monkeypatch,
):
    service = WebSearchService(
        api_key="tvly-test"
    )

    captured = {}
    fresh_date = datetime.now(timezone.utc).isoformat()

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
                        "published_date": fresh_date,
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
    assert captured["timeout"] == 2.5
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
            "published_date": fresh_date,
        }
    ]


def test_web_search_uses_google_news_rss_when_news_providers_are_unavailable(monkeypatch, caplog):
    service = WebSearchService(api_key="", searxng_endpoint="")
    pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    class FakeRSSResponse:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self):
            return f"<rss><channel><item><title>AI voice assistant update</title><link>https://example.com/voice</link><pubDate>{pub_date}</pubDate><description>Fresh AI voice assistant update.</description><source>Example News</source></item></channel></rss>".encode("utf-8")

    monkeypatch.setattr(
        "services.web_search_service.urlopen",
        lambda request, timeout: FakeRSSResponse(),
    )

    with caplog.at_level(logging.INFO, logger="services.web_search_service"):
        results = service.search(
            query="latest AI voice assistant developments",
            topic="news",
            time_range="day",
        )

    assert "SearXNG is not configured; using Google News RSS fallback." in caplog.text
    assert "SearXNG search failed" not in caplog.text
    assert results == [{
        "title": "AI voice assistant update",
        "url": "https://example.com/voice",
        "content": "Source: Example News Fresh AI voice assistant update.",
        "score": None,
        "published_date": pub_date,
    }]


def test_web_search_retries_google_news_rss_once_after_transient_failure(monkeypatch):
    service = WebSearchService(api_key="", searxng_endpoint="")
    calls = []

    def fail_searxng(*, query, topic, time_range):
        raise RuntimeError("SearXNG unavailable")

    def flaky_rss(*, query, time_range):
        calls.append(query)
        if len(calls) == 1:
            raise RuntimeError("Transient RSS failure")
        return {
            "results": [
                {
                    "title": "Voice assistant update",
                    "url": "https://example.com/voice-update",
                    "content": "A current voice assistant development.",
                    "score": None,
                    "published_date": "2026-10-12",
                }
            ]
        }

    monkeypatch.setattr(service, "_request_searxng", fail_searxng)
    monkeypatch.setattr(service, "_request_google_news_rss", flaky_rss)

    results = service.search(
        query="latest developments in AI voice assistants",
        topic="news",
    )

    assert len(calls) == 2
    assert results == [
        {
            "title": "Voice assistant update",
            "url": "https://example.com/voice-update",
            "content": "A current voice assistant development.",
            "score": None,
            "published_date": "2026-10-12",
        }
    ]


def test_web_search_fallback_query_focuses_voice_assistant_topics():
    service = WebSearchService(
        api_key="tvly-test",
    )

    query = service._google_news_query(
        "latest developments in AI voice assistants",
        "news",
    )

    assert "\\\"voice AI\\\"" in query
    assert "\\\"voice agent\\\"" in query


def test_google_news_query_preserves_publisher_scope():
    service = WebSearchService(api_key="tvly-test")
    query = 'site:blog.google "Gemini Live" voice assistant 2026'

    assert service._google_news_query(query, "news") == query


def test_comparison_search_replaces_unrelated_rss_items_with_publisher_scoped_results(
    monkeypatch,
):
    service = WebSearchService(api_key="", searxng_endpoint="")
    comparison_query = (
        "consumer AI voice assistants 2026 Gemini Live Amazon Alexa+ "
        "Apple Siri ChatGPT Voice capabilities limitations official sources reviews"
    )
    generic_result = {
        "title": "Which Smart Home Platform Should You Choose in 2026?",
        "url": "https://example.com/smart-home",
        "content": "Source: Online Tips A broad smart-home comparison.",
        "score": None,
        "published_date": "Mon, 12 Oct 2026 12:00:00 GMT",
    }
    calls = []

    scoped_results = {
        'site:androidauthority.com "Gemini Live" voice 2026': {
            "title": "Gemini Live voice assistant update",
            "url": "https://example.com/gemini-live",
            "content": "Source: blog.google Verified voice assistant feature.",
            "score": None,
            "published_date": "Mon, 12 Oct 2026 12:00:00 GMT",
        },
        'site:techcrunch.com "Alexa+" voice assistant 2026': {
            "title": "Alexa+ expands as a next-generation AI assistant",
            "url": "https://example.com/alexa-plus",
            "content": "Source: About Amazon Alexa+ assistant update.",
            "score": None,
            "published_date": "Sun, 11 Oct 2026 12:00:00 GMT",
        },
        'site:theverge.com Siri AI voice assistant 2026': {
            "title": "Siri and Apple Intelligence add a voice assistant feature",
            "url": "https://example.com/siri",
            "content": "Source: Apple Newsroom Siri capability update.",
            "score": None,
            "published_date": "Sat, 10 Oct 2026 12:00:00 GMT",
        },
        'site:engadget.com "ChatGPT Voice" 2026': {
            "title": "ChatGPT Voice availability",
            "url": "https://example.com/chatgpt-voice",
            "content": "Source: OpenAI Help Center ChatGPT Voice information.",
            "score": None,
            "published_date": "Fri, 09 Oct 2026 12:00:00 GMT",
        },
    }

    def fake_rss(*, query, time_range):
        calls.append((query, time_range))
        if query == comparison_query:
            return {"results": [generic_result]}
        result = scoped_results.get(query)
        if result is not None:
            return {"results": [result]}
        return {"results": []}

    monkeypatch.setattr(
        service,
        "_request_google_news_rss",
        fake_rss,
    )

    results = service.search(
        query=comparison_query,
        topic="news",
    )

    assert calls == [
        (comparison_query, None),
        ('site:androidauthority.com "Gemini Live" voice 2026', None),
        ('site:techcrunch.com "Alexa+" voice assistant 2026', None),
        ('site:theverge.com Siri AI voice assistant 2026', None),
        ('site:engadget.com "ChatGPT Voice" 2026', None),
    ]
    assert {item["url"] for item in results} == {
        "https://example.com/gemini-live",
        "https://example.com/alexa-plus",
        "https://example.com/siri",
        "https://example.com/chatgpt-voice",
    }
    assert all(item["url"] != generic_result["url"] for item in results)


def test_comparison_search_withholds_broad_rss_items_if_no_targeted_source_matches(
    monkeypatch,
):
    service = WebSearchService(api_key="", searxng_endpoint="")
    comparison_query = (
        "consumer AI voice assistants 2026 Gemini Live Amazon Alexa+ "
        "Apple Siri ChatGPT Voice capabilities limitations official sources reviews"
    )
    calls = []

    def fake_rss(*, query, time_range):
        calls.append((query, time_range))
        return {
            "results": [
                {
                    "title": "Unrelated AI hardware announcement",
                    "url": "https://example.com/unrelated",
                    "content": "Source: Generic News unrelated hardware story.",
                    "score": None,
                    "published_date": "Mon, 12 Oct 2026 12:00:00 GMT",
                }
            ]
        }

    monkeypatch.setattr(
        service,
        "_request_google_news_rss",
        fake_rss,
    )

    results = service.search(
        query=comparison_query,
        topic="news",
    )

    assert results == []
    assert len(calls) == 5
    assert calls[0] == (comparison_query, None)
    assert all(query.startswith("site:") for query, _ in calls[1:])


def test_web_search_ranks_relevant_news_above_noise_and_deduplicates():
    results = WebSearchService._rank_news_results(
        "AI voice assistants",
        [
            {
                "title": "AI stocks investors should watch",
                "url": "https://example.com/stocks",
                "content": "Artificial intelligence market update.",
            },
            {
                "title": "New voice AI assistant reaches more users",
                "url": "https://example.com/voice",
                "content": "A voice assistant adds new capabilities.",
            },
            {
                "title": "Duplicate voice AI assistant story",
                "url": "https://example.com/voice",
                "content": "Same source URL should be kept once.",
            },
            {
                "title": "Enterprise voice agent launches",
                "url": "https://example.com/agent",
                "content": "A voice agent is now available.",
            },
        ],
    )

    assert [result["url"] for result in results] == [
        "https://example.com/voice",
        "https://example.com/agent",
        "https://example.com/stocks",
    ]


def test_latest_news_ranking_prefers_recent_relevant_voice_assistant_sources():
    now = datetime.now(timezone.utc)
    results = WebSearchService._rank_news_results(
        "latest developments in AI voice assistants",
        [
            {
                "title": "AI voice assistants voice AI voice-agent launch and speech AI platform",
                "url": "https://example.com/older-voice-news",
                "content": (
                    "Voice AI and voice agents for AI voice assistants. "
                    "A highly relevant launch story."
                ),
                "published_date": (
                    now - timedelta(days=300)
                ).isoformat(),
            },
            {
                "title": "AI voice assistant receives a new feature update",
                "url": "https://example.com/recent-voice-news",
                "content": "Recent changes to an AI voice assistant.",
                "published_date": (
                    now - timedelta(days=2)
                ).isoformat(),
            },
        ],
    )

    assert results[0]["url"] == "https://example.com/recent-voice-news"


def test_news_ranking_removes_duplicate_headline_when_one_copy_has_no_date():
    title = "Amazon Alexa+ arrives in India to take on ChatGPT and Gemini"
    results = WebSearchService._rank_news_results(
        "consumer AI voice assistants",
        [
            {
                "title": title,
                "url": "https://www.msn.com/en-in/technology/artificial-intelligence/story?ocid=BingNewsVerp",
                "content": "Amazon announced Alexa+ availability in India.",
                "published_date": None,
            },
            {
                "title": title,
                "url": "https://www.msn.com/en-in/technology/artificial-intelligence/story",
                "content": "Amazon announced Alexa+ availability in India.",
                "published_date": "2026-09-16T09:58:00",
            },
        ],
    )

    assert len(results) == 1


def test_news_ranking_prefers_recent_results_when_planner_drops_latest_keyword():
    now = datetime.now(timezone.utc)
    title = "Voice AI assistant update for business callers"
    results = WebSearchService._rank_news_results(
        "AI voice assistants",
        [
            {
                "title": title,
                "url": "https://example.com/older",
                "content": "A voice AI assistant update for business callers.",
                "published_date": (now - timedelta(days=300)).isoformat(),
            },
            {
                "title": title,
                "url": "https://example.com/recent",
                "content": "A voice AI assistant update for business callers.",
                "published_date": (now - timedelta(days=2)).isoformat(),
            },
        ],
    )

    assert [item["url"] for item in results] == [
        "https://example.com/recent",
        "https://example.com/older",
    ]


def test_web_search_falls_back_from_empty_news_to_general_search(
    monkeypatch,
):
    service = WebSearchService(
        api_key="",
        searxng_endpoint="http://127.0.0.1:8080/search",
    )
    calls = []

    def fake_request_searxng(
        *,
        query,
        topic,
        time_range,
    ):
        calls.append(
            (query, topic, time_range)
        )

        if topic == "news":
            return {"results": []}

        return {
            "results": [
                {
                    "title": "Current AI Voice Assistant Update",
                    "url": "https://example.com/current",
                    "content": "A current AI voice assistant result.",
                    "score": 0.9,
                    "publishedDate": datetime.now(timezone.utc).isoformat(),
                }
            ]
        }

    monkeypatch.setattr(
        service,
        "_request_searxng",
        fake_request_searxng,
    )

    results = service.search(
        query="latest AI voice assistants",
        topic="news",
        time_range="day",
    )

    assert calls == [
        ("latest AI voice assistants", "news", "day"),
        ("latest AI voice assistants", "general", "day"),
    ]
    assert results[0]["title"] == "Current AI Voice Assistant Update"
    assert results[0]["published_date"].startswith(datetime.now(timezone.utc).date().isoformat())


def test_empty_google_news_rss_retries_without_filter_without_reusing_failed_searxng(
    monkeypatch,
):
    service = WebSearchService(
        api_key="",
        searxng_endpoint="http://127.0.0.1:8080/search",
    )
    searxng_calls = []
    rss_calls = []
    query = "latest developments in AI voice assistants"

    def fail_searxng(*, query, topic, time_range):
        searxng_calls.append((query, topic, time_range))
        raise RuntimeError("SearXNG unavailable")

    def empty_then_successful_rss(*, query, time_range):
        rss_calls.append((query, time_range))
        if len(rss_calls) < 3:
            return {"results": []}
        assert query == "AI voice assistants"
        return {
            "results": [
                {
                    "title": "Voice assistant update",
                    "url": "https://example.com/voice-update",
                    "content": "A current voice assistant development.",
                    "score": None,
                    "published_date": datetime.now(timezone.utc).isoformat(),
                }
            ]
        }

    monkeypatch.setattr(service, "_request_searxng", fail_searxng)
    monkeypatch.setattr(
        service,
        "_request_google_news_rss",
        empty_then_successful_rss,
    )

    results = service.search(
        query=query,
        topic="news",
        time_range="day",
    )

    assert searxng_calls == [(query, "news", "day")]
    assert rss_calls == [
        (query, "day"),
        (query, None),
        ("AI voice assistants", None),
    ]
    assert results[0]["url"] == "https://example.com/voice-update"


def test_empty_google_news_rss_does_not_escalate_to_unavailable_searxng(
    monkeypatch,
):
    service = WebSearchService(
        api_key="",
        searxng_endpoint="http://127.0.0.1:8080/search",
    )
    searxng_calls = []
    rss_calls = []

    def fail_searxng(*, query, topic, time_range):
        searxng_calls.append((query, topic, time_range))
        raise RuntimeError("SearXNG unavailable")

    def empty_rss(*, query, time_range):
        rss_calls.append((query, time_range))
        return {"results": []}

    monkeypatch.setattr(service, "_request_searxng", fail_searxng)
    monkeypatch.setattr(service, "_request_google_news_rss", empty_rss)

    results = service.search(
        query="latest developments in AI voice assistants",
        topic="news",
    )

    assert results == []
    assert searxng_calls == [
        ("latest developments in AI voice assistants", "news", None)
    ]
    assert rss_calls == [
        ("latest developments in AI voice assistants", None),
        ("latest developments in AI voice assistants", None),
        ("AI voice assistants", None),
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


def test_web_search_filters_unsafe_result_urls(
    monkeypatch,
):
    service = WebSearchService(
        api_key="tvly-test"
    )

    def fake_urlopen(request, timeout):
        return FakeResponse(
            {
                "results": [
                    {
                        "title": "Unsafe JavaScript",
                        "url": "javascript:alert(1)",
                        "content": "ignored",
                    },
                    {
                        "title": "Unsafe Data",
                        "url": "data:text/plain,ignored",
                        "content": "ignored",
                    },
                    {
                        "title": "Unsafe Credentials",
                        "url": "https://user:password@example.com/private",
                        "content": "ignored",
                    },
                    {
                        "title": "Unsafe Missing Host",
                        "url": "https:///missing-host",
                        "content": "ignored",
                    },
                    {
                        "title": "Safe HTTP",
                        "url": "http://example.com/article",
                        "content": "accepted",
                    },
                    {
                        "title": "Safe HTTPS",
                        "url": "https://example.com/article",
                        "content": "accepted",
                    },
                ]
            }
        )

    monkeypatch.setattr(
        "services.web_search_service.urlopen",
        fake_urlopen,
    )

    results = service.search(
        query="AI safety"
    )

    assert results == [
        {
            "title": "Safe HTTP",
            "url": "http://example.com/article",
            "content": "accepted",
            "score": None,
            "published_date": None,
        },
        {
            "title": "Safe HTTPS",
            "url": "https://example.com/article",
            "content": "accepted",
            "score": None,
            "published_date": None,
        },
    ]


def test_web_search_uses_dedicated_open_meteo_path_for_weather(monkeypatch):
    service = WebSearchService(api_key="tvly-test")
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)

        if "geocoding-api.open-meteo.com" in request.full_url:
            return FakeResponse({
                "results": [{
                    "name": "Lahore",
                    "latitude": 31.558,
                    "longitude": 74.35071,
                    "country": "Pakistan",
                    "timezone": "Asia/Karachi",
                }]
            })

        return FakeResponse({
            "timezone": "Asia/Karachi",
            "current": {
                "time": "2026-10-08T20:15",
                "temperature_2m": 27.6,
                "relative_humidity_2m": 71,
                "apparent_temperature": 31.8,
                "precipitation": 0.0,
                "weather_code": 0,
                "wind_speed_10m": 3.4,
            },
        })

    monkeypatch.setattr(
        "services.web_search_service.urlopen",
        fake_urlopen,
    )

    results = service.search(
        query="What's the current weather in Lahore?",
        topic="weather",
    )

    assert len(calls) == 2
    assert "name=Lahore" in calls[0]
    assert "current=temperature_2m" in calls[1]
    assert results[0]["title"] == "Current weather in Lahore, Pakistan"
    assert "27.6°C" in results[0]["content"]
    assert "31.8°C" in results[0]["content"]
    assert "71.0%" in results[0]["content"]
    assert "3.4 km/h" in results[0]["content"]
    assert "clear sky" in results[0]["content"]


def test_web_search_weather_requires_a_location():
    service = WebSearchService(api_key="tvly-test")

    with pytest.raises(ValueError, match="requires a location"):
        service.search(
            query="What's the current weather?",
            topic="weather",
        )


def test_voice_assistant_comparison_prefers_recent_diverse_sources_without_redundant_searches(monkeypatch):
    service = WebSearchService(api_key="", searxng_endpoint="http://127.0.0.1:8080/search")
    comparison_query = (
        "consumer AI voice assistants 2026 Gemini Live Amazon Alexa+ "
        "Apple Siri ChatGPT Voice capabilities limitations official sources reviews"
    )
    searxng_calls = []

    broad_results = [
        {
            "title": "Gemini Live adds new voice capabilities",
            "url": "https://www.androidauthority.com/gemini-live-voice-2026/",
            "content": "Gemini Live supports more natural voice conversations and interruptions.",
            "publishedDate": "2026-10-01T10:00:00+00:00",
        },
        {
            "title": "Amazon makes its AI-powered Alexa+ free on Fire TV",
            "url": "https://techcrunch.com/2026/08/19/amazon-makes-its-ai-powered-alexa-free-on-fire-tv-no-prime-required/",
            "content": "Amazon said Alexa+ will roll out to compatible Fire TV devices.",
            "publishedDate": "2026-08-19T09:00:00+00:00",
        },
        {
            "title": "Apple details new Siri AI capabilities",
            "url": "https://www.theverge.com/2026/9/14/siri-ai",
            "content": "Apple described Siri capabilities powered by Apple Intelligence.",
            "publishedDate": "2026-09-14T10:00:00+00:00",
        },
        {
            "title": "ChatGPT Voice updates improve spoken conversations",
            "url": "https://www.engadget.com/chatgpt-voice-2026-update/",
            "content": "ChatGPT Voice supports spoken conversations and voice interaction.",
            "publishedDate": "2026-10-04T08:00:00+00:00",
        },
    ]

    def fake_searxng(*, query, topic, time_range):
        searxng_calls.append((query, topic, time_range))
        assert query == comparison_query
        return {"results": broad_results}

    def unexpected_rss(*, query, time_range):
        pytest.fail("RSS should not run when all four vendors have recent coverage.")

    monkeypatch.setattr(service, "_request_searxng", fake_searxng)
    monkeypatch.setattr(service, "_request_google_news_rss", unexpected_rss)

    results = service.search(query=comparison_query, topic="news")

    assert searxng_calls == [(comparison_query, "news", None)]
    assert {vendor for item in results for vendor in service._voice_assistant_vendors(item)} == {
        "google", "amazon", "apple", "openai"
    }
    assert {item["url"] for item in results} == {
        "https://www.androidauthority.com/gemini-live-voice-2026/",
        "https://techcrunch.com/2026/08/19/amazon-makes-its-ai-powered-alexa-free-on-fire-tv-no-prime-required/",
        "https://www.theverge.com/2026/9/14/siri-ai",
        "https://www.engadget.com/chatgpt-voice-2026-update/",
    }
    assert all(service._is_recently_published(item) for item in results)
    assert all(item["published_date"] for item in results)


def test_voice_comparison_supplements_only_missing_recent_vendor_with_rss(monkeypatch):
    service = WebSearchService(api_key="", searxng_endpoint="http://127.0.0.1:8080/search")
    query = (
        "consumer AI voice assistants 2026 Gemini Live Amazon Alexa+ "
        "Apple Siri ChatGPT Voice capabilities limitations official sources reviews"
    )
    searxng_calls = []
    rss_calls = []
    broad_results = [
        {
            "title": "Gemini Live adds new voice capabilities",
            "url": "https://www.androidauthority.com/gemini-live-voice-2026/",
            "content": "Gemini Live supports more natural voice conversations.",
            "published_date": "2026-10-01T10:00:00+00:00",
        },
        {
            "title": "Amazon Alexa+ arrives in India to take on ChatGPT and Gemini",
            "url": "https://www.androidauthority.com/amazon-alexa-plus-india/",
            "content": "Amazon's upgraded voice assistant is available in India, with competitor products mentioned for context.",
            "published_date": "2026-09-16T09:58:00+00:00",
        },
        {
            "title": "Apple details new Siri AI capabilities",
            "url": "https://www.theverge.com/2026/9/14/siri-ai",
            "content": "Apple described Siri capabilities powered by Apple Intelligence.",
            "published_date": "2026-09-14T10:00:00+00:00",
        },
    ]

    def fake_searxng(*, query, topic, time_range):
        searxng_calls.append((query, topic, time_range))
        return {"results": broad_results}

    def fake_rss(*, query, time_range):
        rss_calls.append((query, time_range))
        assert "site:engadget.com" in query
        return {"results": [{
            "title": "ChatGPT Voice update improves real-time conversation - Engadget",
            "url": "https://www.engadget.com/chatgpt-voice-2026-update/",
            "content": "ChatGPT Voice supports spoken conversations and voice interaction.",
            "published_date": "2026-10-04T08:00:00+00:00",
        }]}

    monkeypatch.setattr(service, "_request_searxng", fake_searxng)
    monkeypatch.setattr(service, "_request_google_news_rss", fake_rss)

    assert service._voice_assistant_vendors(broad_results[1]) == {"amazon"}

    results = service.search(query=query, topic="news", max_results=5)

    assert searxng_calls == [(query, "news", None)]
    assert len(rss_calls) == 1
    assert "site:engadget.com" in rss_calls[0][0]
    assert {vendor for item in results for vendor in service._voice_assistant_vendors(item)} == {
        "google", "amazon", "apple", "openai"
    }
    assert any(item["url"] == "https://www.engadget.com/chatgpt-voice-2026-update/" for item in results)
    assert all(service._is_recently_published(item) for item in results)


def test_publication_date_extraction_only_uses_a_leading_explicit_date():
    assert WebSearchService._publication_date_from_content(
        "Sep 14, 2026 ... Apple announces new features"
    ) == "2026-09-14"
    assert WebSearchService._publication_date_from_content(
        "2026-08-19T12:30:00 Alexa+ update"
    ) == "2026-08-19"
    assert WebSearchService._publication_date_from_content(
        "Apple announced features during September 2026"
    ) is None


def test_google_news_article_url_resolver_returns_verified_publisher_url(monkeypatch):
    service = WebSearchService(api_key="", searxng_endpoint="")
    article_id = "CBMiTest-article_ID"
    google_url = f"https://news.google.com/rss/articles/{article_id}?oc=5"
    publisher_url = "https://blog.google/example/real-article/"
    rpc_payload = [
        [
            "wrb.fr",
            "Fbv4je",
            json.dumps(["garturlres", publisher_url, 1]),
            None,
            None,
            None,
            "",
        ],
        ["di", 12],
        ["af.httprm", 12, "test", 338],
    ]
    responses = [
        b'<html><div data-n-a-sg="test-signature" data-n-a-ts="1791885967"></div></html>',
        (
            ")]}'\n\n"
            + json.dumps(rpc_payload, separators=(",", ":"))
        ).encode("utf-8"),
    ]
    calls = []

    class FakeResponse:
        def __init__(self, body):
            self.body = body
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self):
            return self.body

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr("services.web_search_service.urlopen", fake_urlopen)

    assert service._resolve_google_news_article_url(google_url) == publisher_url
    assert len(calls) == 2
    assert calls[0].full_url == f"https://news.google.com/rss/articles/{article_id}"
    assert calls[0].get_method() == "GET"
    assert "batchexecute" in calls[1].full_url
    assert calls[1].get_method() == "POST"
    assert b"f.req=" in calls[1].data


def test_google_news_article_url_resolver_caches_failure_without_guessing(monkeypatch):
    service = WebSearchService(api_key="", searxng_endpoint="")
    google_url = "https://news.google.com/rss/articles/CBMiUnresolvable?oc=5"
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self):
            return b"<html><title>Unavailable article page</title></html>"

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse()

    monkeypatch.setattr("services.web_search_service.urlopen", fake_urlopen)

    assert service._resolve_google_news_article_url(google_url) is None
    assert service._resolve_google_news_article_url(google_url) is None
    assert len(calls) == 1


def test_news_search_resolves_google_rss_links_and_labels_unresolved_intermediaries(monkeypatch):
    service = WebSearchService(api_key="", searxng_endpoint="")
    publisher_url = "https://example.com/voice-assistant-update"
    unresolved_url = "https://news.google.com/rss/articles/CBMiUnresolvable?oc=5"
    monkeypatch.setattr(
        service,
        "_request_google_news_rss",
        lambda *, query, time_range: {
            "results": [
                {
                    "title": "Voice assistant update",
                    "url": "https://news.google.com/rss/articles/CBMiResolvable?oc=5",
                    "content": "Source: Example publisher New voice assistant update.",
                    "published_date": "2026-10-12",
                },
                {
                    "title": "Second voice assistant update",
                    "url": unresolved_url,
                    "content": "Source: Another publisher A second update.",
                    "published_date": "2026-10-11",
                },
            ]
        },
    )
    monkeypatch.setattr(
        service,
        "_resolve_google_news_article_url",
        lambda url: publisher_url if "CBMiResolvable" in url else None,
    )
    monkeypatch.setattr(
        service,
        "_request_searxng",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("SearXNG unavailable")),
    )

    results = service.search(query="latest AI voice assistant developments", topic="news")

    assert results[0]["url"] == publisher_url
    assert results[1]["url"] == unresolved_url
    assert "Google News intermediary link" in results[1]["content"]
    assert "Google News intermediary link" not in results[0]["content"]


def test_latest_ai_news_filters_unrelated_news_and_ranks_relevant_stories(monkeypatch):
    service = WebSearchService(
        api_key="",
        searxng_endpoint="http://127.0.0.1:8080/search",
    )
    now = datetime.now(timezone.utc)
    raw_results = [
        {
            "title": "Why is the market rising today? Sensex surges 1,000 points",
            "url": "https://example.com/markets",
            "content": "Shares rose after a change in investor sentiment.",
            "publishedDate": now.isoformat(),
        },
        {
            "title": "Welsh government and Labour strike deal on mini-budget",
            "url": "https://example.com/welsh-budget",
            "content": "The parties reached an agreement on budget measures.",
            "publishedDate": now.isoformat(),
        },
        {
            "title": "An underwater AI data center proposal draws objections in Maine",
            "url": "https://example.com/ai-data-center",
            "content": "Residents raised concerns about the proposed AI data center on October 13.",
            "publishedDate": now.isoformat(),
        },
        {
            "title": "Anthropic warns AI models could soon copy themselves across home devices",
            "url": "https://example.com/anthropic-models",
            "content": "Anthropic described a potential model-safety risk in newly released research.",
            "publishedDate": (now - timedelta(hours=3)).isoformat(),
        },
        {
            "title": "AI could self-replicate on home devices within months, Anthropic says",
            "url": "https://example.com/anthropic-syndicated-copy",
            "content": "Anthropic described the same potential model-safety risk in a separate syndication.",
            "publishedDate": (now - timedelta(hours=2)).isoformat(),
        },
        {
            "title": "Samsung expands its AI memory push with AMD at OCP 2026",
            "url": "https://example.com/ai-memory",
            "content": "AI workloads are increasing demand for memory bandwidth and capacity.",
            "publishedDate": (now - timedelta(hours=8)).isoformat(),
        },
        {
            "title": "Latest news bulletin: world, business and politics",
            "url": "https://example.com/general-news",
            "content": "Today's general news bulletin includes politics and finance headlines.",
            "publishedDate": now.isoformat(),
        },
    ]
    monkeypatch.setattr(
        service,
        "_request_searxng",
        lambda **kwargs: {"results": raw_results},
    )

    results = service.search(
        query="latest AI news today",
        topic="news",
        time_range=None,
    )

    urls = [item["url"] for item in results]
    assert "https://example.com/markets" not in urls
    assert "https://example.com/welsh-budget" not in urls
    assert "https://example.com/general-news" not in urls
    assert {
        "https://example.com/ai-data-center",
        "https://example.com/ai-memory",
    }.issubset(set(urls))
    assert urls[0] == "https://example.com/ai-data-center"
    assert len([item for item in results if "anthropic" in item["title"].lower()]) == 1
    assert all(WebSearchService._matches_ai_news_query(item) for item in results)


def test_today_ai_news_query_promotes_general_search_to_news_day_scope(monkeypatch):
    service = WebSearchService(api_key="tvly-test", searxng_endpoint="")
    now = datetime.now(timezone.utc)
    fresh_date = (now - timedelta(hours=1)).isoformat()
    stale_date = (now - timedelta(days=2)).isoformat()
    captured = {}

    def fake_tavily(payload):
        captured.update(payload)
        return {
            "results": [
                {
                    "title": "AI model update announced today",
                    "url": "https://example.com/fresh-ai-model",
                    "content": "A new AI model update was announced today.",
                    "published_date": fresh_date,
                },
                {
                    "title": "OpenAI announces an AI model",
                    "url": "https://example.com/stale-ai-model",
                    "content": "OpenAI announced a new AI model.",
                    "published_date": stale_date,
                },
                {
                    "title": "Market rises after investors welcome a budget",
                    "url": "https://example.com/unrelated-market-story",
                    "content": "Markets rose on investor sentiment.",
                    "published_date": fresh_date,
                },
            ]
        }

    monkeypatch.setattr(service, "_request_tavily", fake_tavily)

    results = service.search(
        query="Search the web for the latest AI news from today",
        topic="general",
        max_results=5,
    )

    assert captured["topic"] == "news"
    assert captured["time_range"] == "day"
    assert [item["url"] for item in results] == ["https://example.com/fresh-ai-model"]


def test_ai_news_query_filter_does_not_accept_generic_politics_just_because_results_are_fresh():
    assert WebSearchService._is_ai_news_query("latest AI news today") is True
    assert WebSearchService._is_ai_news_query("latest OpenAI news") is True
    assert WebSearchService._is_ai_news_query("latest world news today") is False
    assert WebSearchService._matches_ai_news_query({
        "title": "Anthropic warns AI models could soon copy themselves",
        "content": "Safety research details.",
    }) is True
    assert WebSearchService._matches_ai_news_query({
        "title": "Welsh government and Labour strike deal on mini-budget",
        "content": "A budget agreement was announced today.",
    }) is False
    assert WebSearchService._matches_ai_news_query({
        "title": "Generic technology story",
        "content": "Related links: AI systems, smart financial services and politics.",
    }) is False


def test_ai_news_query_retries_without_provider_date_filter_when_relevance_filter_empties_results(monkeypatch):
    service = WebSearchService(
        api_key="",
        searxng_endpoint="http://127.0.0.1:8080/search",
    )
    calls = []

    def fake_searxng(*, query, topic, time_range):
        calls.append((query, topic, time_range))
        if time_range == "day":
            return {
                "results": [
                    {
                        "title": "Welsh government and Labour strike deal on mini-budget",
                        "url": "https://example.com/budget",
                        "content": "The parties reached a budget agreement.",
                        "publishedDate": "2026-10-13",
                    }
                ]
            }
        return {
            "results": [
                {
                    "title": "Anthropic releases new AI safety research",
                    "url": "https://example.com/anthropic-ai-safety",
                    "content": "New AI safety research from Anthropic was published today.",
                    "publishedDate": "2026-10-13T08:00:00",
                },
                {
                    "title": "Market rises after investors welcome new budget",
                    "url": "https://example.com/market",
                    "content": "Stocks moved higher during today's session.",
                    "publishedDate": "2026-10-13",
                },
            ]
        }

    monkeypatch.setattr(service, "_request_searxng", fake_searxng)
    monkeypatch.setattr(
        service,
        "_request_google_news_rss",
        lambda **kwargs: {"results": []},
    )

    results = service.search(
        query="latest AI news today",
        topic="news",
        time_range="day",
    )

    assert calls == [
        ("latest AI news today", "news", "day"),
        ("latest AI news today", "news", None),
    ]
    # The unfiltered retry only returned 13 October coverage, stale for a
    # day-scoped request on 26 October. Do not present it as the latest update.
    assert results == []

def test_openai_news_result_filter_rejects_roundups_forums_stale_and_undated_items():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=2)).isoformat()
    assert not WebSearchService._matches_openai_news_result({
        "title": "OpenAI Reviews, News, and Deals - PCMag",
        "url": "https://www.pcmag.com/brands/openai",
        "content": "Reviews and news about OpenAI.",
        "published_date": recent,
    })
    assert not WebSearchService._matches_openai_news_result({
        "title": "OpenAI Developer Community latest topics",
        "url": "https://community.openai.com/latest?page=1",
        "content": "Community posts about OpenAI.",
        "published_date": recent,
    })
    assert not WebSearchService._matches_openai_news_result({
        "title": "OpenAI News Today | AI Weekly",
        "url": "https://aiweekly.co/ai-news-today/openai-news",
        "content": "A roundup of AI news stories.",
        "published_date": recent,
    })
    assert not WebSearchService._matches_openai_news_result({
        "title": "OpenAI announces a new model",
        "url": "https://www.reuters.com/technology/openai-example/",
        "content": "OpenAI announces a new model.",
    })
    assert not WebSearchService._matches_openai_news_result({
        "title": "OpenAI announces a new model",
        "url": "https://www.reuters.com/technology/openai-example/",
        "content": "OpenAI announces a new model.",
        "published_date": (now - timedelta(days=60)).isoformat(),
    })


def test_openai_news_result_filter_accepts_recent_official_and_reputable_articles():
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    official = {
        "title": "New updates from OpenAI",
        "url": "https://openai.com/index/example-update/",
        "content": "OpenAI announced an update.",
        "published_date": recent,
    }
    press = {
        "title": "OpenAI announces product update",
        "url": "https://www.reuters.com/technology/openai-product-update/",
        "content": "OpenAI announced a product update.",
        "published_date": recent,
    }
    assert WebSearchService._matches_openai_news_result(official)
    assert WebSearchService._matches_openai_news_result(press)


def test_openai_news_search_uses_publisher_scoped_results_only(monkeypatch):
    service = WebSearchService(api_key="", searxng_endpoint="http://127.0.0.1:8080/search")
    query = "latest OpenAI news"
    now = datetime.now(timezone.utc).isoformat()
    broad = {"results": [
        {
            "title": "OpenAI Reviews, News, and Deals - PCMag",
            "url": "https://www.pcmag.com/brands/openai",
            "content": "A brand directory.",
            "published_date": now,
        },
        {
            "title": "OpenAI News Today | AI Weekly",
            "url": "https://aiweekly.co/ai-news-today/openai-news",
            "content": "A roundup.",
            "published_date": now,
        },
    ]}
    calls = []

    def fake_searxng(*, query, topic, time_range):
        calls.append((query, topic, time_range))
        if query == "latest OpenAI news" and topic == "news":
            return broad
        if "site:openai.com/index" in query:
            return {"results": [{
                "title": "OpenAI announces a product update",
                "url": "https://openai.com/index/example-update/",
                "content": "OpenAI announced an update.",
                "published_date": now,
            }]}
        if "site:reuters.com" in query:
            return {"results": [{
                "title": "OpenAI announces a product update",
                "url": "https://www.reuters.com/technology/openai-example/",
                "content": "OpenAI announced an update.",
                "published_date": now,
            }]}
        return {"results": []}

    monkeypatch.setattr(service, "_request_searxng", fake_searxng)
    monkeypatch.setattr(
        service,
        "_request_google_news_rss",
        lambda *, query, time_range: {"results": []},
    )
    results = service.search(query=query, topic="news")

    assert len(calls) == 5
    assert calls[0] == ("latest OpenAI news", "news", None)
    assert all(topic == "general" and time_range is None for _, topic, time_range in calls[1:])
    assert {item["url"] for item in results} == {
        "https://openai.com/index/example-update/",
        "https://www.reuters.com/technology/openai-example/",
    }

def test_openai_news_search_falls_back_to_scoped_rss_when_searxng_targets_are_empty(monkeypatch):
    service = WebSearchService(api_key="", searxng_endpoint="http://127.0.0.1:8080/search")
    now = datetime.now(timezone.utc).isoformat()
    searx_calls = []
    rss_calls = []

    def fake_searxng(*, query, topic, time_range):
        searx_calls.append((query, topic, time_range))
        if query == "latest OpenAI news" and topic == "news":
            return {"results": [{
                "title": "OpenAI Reviews, News, and Deals - PCMag",
                "url": "https://www.pcmag.com/brands/openai",
                "content": "Brand directory",
                "published_date": now,
            }]}
        return {"results": []}

    def fake_rss(*, query, time_range):
        rss_calls.append((query, time_range))
        if "site:openai.com/index" in query:
            return {"results": [{
                "title": "GPT-6 and Intelligent UI for everyone - OpenAI",
                "url": "https://openai.com/index/gpt6-intelligent-ui/",
                "content": "OpenAI announced new features.",
                "source": "OpenAI",
                "published_date": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
            }]}
        if "site:reuters.com" in query:
            return {"results": [{
                "title": "OpenAI announces a new product update - Reuters",
                "url": "https://www.reuters.com/technology/openai-update/",
                "content": "OpenAI announced a new product update.",
                "source": "Reuters",
                "published_date": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
            }]}
        return {"results": []}

    monkeypatch.setattr(service, "_request_searxng", fake_searxng)
    monkeypatch.setattr(service, "_request_google_news_rss", fake_rss)

    results = service.search(query="latest OpenAI news", topic="news")

    assert len(searx_calls) == 5
    assert len(rss_calls) == 4
    assert {item["url"] for item in results} == {
        "https://openai.com/index/gpt6-intelligent-ui/",
        "https://www.reuters.com/technology/openai-update/",
    }
