from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_TAVILY_ENDPOINT = "https://api.tavily.com/search"
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_RESULTS = 5
MAX_MAX_RESULTS = 10
MAX_QUERY_LENGTH = 4000
MAX_SNIPPET_LENGTH = 4000
SUPPORTED_TOPICS = {"general", "news", "finance"}
SUPPORTED_TIME_RANGES = {"day", "week", "month", "year"}


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    content: str
    score: float | None = None
    published_date: str | None = None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "score": self.score,
            "published_date": self.published_date,
        }


class WebSearchService:
    """
    Read-only live web search boundary for NOVA.

    The default provider is Tavily's Search API. API credentials
    are read only from the TAVILY_API_KEY environment variable.
    Search results are normalized before entering NOVA's agent
    context so provider-specific response shapes do not leak
    into the rest of the application.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str = DEFAULT_TAVILY_ENDPOINT,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        normalized_endpoint = str(endpoint).strip()

        if not normalized_endpoint:
            raise ValueError("Web search endpoint cannot be empty.")

        if not normalized_endpoint.startswith("https://"):
            raise ValueError("Web search endpoint must use HTTPS.")

        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be greater than zero."
            )

        self.api_key = (
            str(api_key).strip()
            if api_key is not None
            else os.getenv("TAVILY_API_KEY", "").strip()
        )
        self.endpoint = normalized_endpoint
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _normalize_query(query: str) -> str:
        normalized = " ".join(
            str(query).strip().split()
        )

        if not normalized:
            raise ValueError("Search query cannot be empty.")

        if len(normalized) > MAX_QUERY_LENGTH:
            raise ValueError(
                f"Search query exceeds the maximum length of "
                f"{MAX_QUERY_LENGTH} characters."
            )

        return normalized

    @staticmethod
    def _normalize_result_url(
        url: str,
    ) -> str | None:
        """
        Accept only browser-navigable HTTP(S) result URLs.

        Provider responses are untrusted input. Reject non-web
        schemes, missing hosts, and embedded URL credentials before
        source metadata reaches the agent or API response.
        """

        normalized = str(url).strip()

        if not normalized:
            return None

        try:
            parsed = urlparse(normalized)
        except ValueError:
            return None

        if parsed.scheme.lower() not in {
            "http",
            "https",
        }:
            return None

        if not parsed.netloc:
            return None

        if (
            parsed.username is not None
            or parsed.password is not None
        ):
            return None

        return normalized

    @staticmethod
    def _normalize_max_results(max_results: int) -> int:
        if max_results < 1 or max_results > MAX_MAX_RESULTS:
            raise ValueError(
                f"max_results must be between 1 and {MAX_MAX_RESULTS}."
            )

        return max_results

    @staticmethod
    def _normalize_topic(topic: str) -> str:
        normalized = str(topic).strip().lower()

        if normalized not in SUPPORTED_TOPICS:
            raise ValueError(
                "topic must be one of: general, news, finance."
            )

        return normalized

    @staticmethod
    def _normalize_time_range(
        time_range: str | None,
    ) -> str | None:
        if time_range is None:
            return None

        normalized = str(time_range).strip().lower()

        if not normalized:
            return None

        if normalized not in SUPPORTED_TIME_RANGES:
            raise ValueError(
                "time_range must be one of: day, week, month, year."
            )

        return normalized

    def _request(self, payload: dict) -> dict:
        if not self.api_key:
            raise RuntimeError(
                "Live web search is not configured. "
                "Set TAVILY_API_KEY."
            )

        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "NOVA-AI-Personal-Assistant/1.0",
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                raw_body = response.read()

        except HTTPError as exc:
            raise RuntimeError(
                f"Live web search provider returned HTTP {exc.code}."
            ) from exc
        except (OSError, URLError, TimeoutError) as exc:
            raise RuntimeError(
                "Live web search provider could not be reached."
            ) from exc

        try:
            parsed = json.loads(
                raw_body.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError(
                "Live web search provider returned invalid JSON."
            ) from exc

        if not isinstance(parsed, dict):
            raise RuntimeError(
                "Live web search provider returned an invalid response."
            )

        return parsed

    def search(
        self,
        *,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        topic: str = "general",
        time_range: str | None = None,
    ) -> list[dict]:
        normalized_query = self._normalize_query(query)
        normalized_max_results = self._normalize_max_results(
            max_results
        )
        normalized_topic = self._normalize_topic(topic)
        normalized_time_range = self._normalize_time_range(
            time_range
        )

        payload = {
            "query": normalized_query,
            "search_depth": "basic",
            "topic": normalized_topic,
            "max_results": normalized_max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }

        if normalized_time_range is not None:
            payload["time_range"] = normalized_time_range

        response = self._request(payload)
        raw_results = response.get("results", [])

        if not isinstance(raw_results, list):
            raise RuntimeError(
                "Live web search provider returned invalid results."
            )

        results: list[dict] = []

        for raw_result in raw_results:
            if not isinstance(raw_result, dict):
                continue

            title = str(
                raw_result.get("title") or ""
            ).strip()
            url = self._normalize_result_url(
                raw_result.get("url") or ""
            )
            content = str(
                raw_result.get("content") or ""
            ).strip()

            if not title or not url or not content:
                continue

            score = raw_result.get("score")

            try:
                normalized_score = (
                    float(score)
                    if score is not None
                    else None
                )
            except (TypeError, ValueError):
                normalized_score = None

            published_date = raw_result.get(
                "published_date"
            )
            normalized_published_date = (
                str(published_date).strip()
                if published_date is not None
                else None
            )

            results.append(
                WebSearchResult(
                    title=title[:500],
                    url=url[:2000],
                    content=content[:MAX_SNIPPET_LENGTH],
                    score=normalized_score,
                    published_date=(
                        normalized_published_date[:100]
                        if normalized_published_date
                        else None
                    ),
                ).to_dict()
            )

            if len(results) >= normalized_max_results:
                break

        return results
