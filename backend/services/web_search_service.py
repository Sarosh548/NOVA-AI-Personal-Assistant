from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


DEFAULT_TAVILY_ENDPOINT = "https://api.tavily.com/search"
DEFAULT_SEARXNG_ENDPOINT = "http://127.0.0.1:8080/search"
DEFAULT_GOOGLE_NEWS_RSS_ENDPOINT = "https://news.google.com/rss/search"
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_RESULTS = 5
MAX_MAX_RESULTS = 10
MAX_QUERY_LENGTH = 4000
MAX_SNIPPET_LENGTH = 4000
SUPPORTED_TOPICS = {"general", "news", "finance", "weather"}
SUPPORTED_TIME_RANGES = {"day", "week", "month", "year"}

logger = logging.getLogger(__name__)


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
        searxng_endpoint: str | None = None,
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

        configured_searxng_endpoint = searxng_endpoint
        if configured_searxng_endpoint is None:
            configured_searxng_endpoint = os.getenv("SEARXNG_URL", "").strip()
            if not configured_searxng_endpoint:
                # The loopback SearXNG default is for local development only.
                # In cloud containers it points back to this API container,
                # not to a search service; don't waste a timeout on that dead end.
                environment = os.getenv("NOVA_ENV", "development").strip().lower()
                configured_searxng_endpoint = (
                    ""
                    if environment in {"production", "prod"}
                    else DEFAULT_SEARXNG_ENDPOINT
                )
        self.searxng_endpoint = str(
            configured_searxng_endpoint
        ).strip()

        self._validate_searxng_endpoint(
            self.searxng_endpoint
        )

        self.endpoint = normalized_endpoint
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _validate_searxng_endpoint(
        endpoint: str,
    ) -> None:
        if not endpoint:
            return

        parsed = urlparse(endpoint)

        if parsed.scheme.lower() not in {
            "http",
            "https",
        }:
            raise ValueError(
                "SearXNG endpoint must use HTTP or HTTPS."
            )

        if not parsed.netloc:
            raise ValueError(
                "SearXNG endpoint must include a host."
            )

        if (
            parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(
                "SearXNG endpoint cannot include credentials."
            )

    @staticmethod
    def _is_live_sports_query(query: str) -> bool:
        normalized = " ".join(str(query or "").lower().split())
        has_sport = re.search(
            r"\b(?:cricket|football|soccer|sports?|match|matches|score|scores|"
            r"scorecard|fixture|fixtures|wickets?|innings|goals?|premier league|"
            r"world cup|t20|odi)\b",
            normalized,
        ) is not None
        has_freshness = re.search(
            r"\b(?:live|right now|today|today's|current|currently|latest|"
            r"now|aaj|abhi|filhal|real time|realtime)\b",
            normalized,
        ) is not None
        return has_sport and has_freshness

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

    @staticmethod
    def _parse_provider_json(
        raw_body: bytes,
    ) -> dict:
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

    def _request_tavily(
        self,
        payload: dict,
    ) -> dict:
        if not self.api_key:
            raise RuntimeError(
                "Tavily web search is not configured."
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
                timeout=(
                    min(self.timeout_seconds, 5)
                    if self._is_live_sports_query(payload.get("query", ""))
                    else self.timeout_seconds
                ),
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

        return self._parse_provider_json(
            raw_body
        )

    def _request_searxng(
        self,
        *,
        query: str,
        topic: str,
        time_range: str | None,
    ) -> dict:
        if not self.searxng_endpoint:
            raise RuntimeError(
                "Live web search is not configured. "
                "Set TAVILY_API_KEY or SEARXNG_URL."
            )

        category = (
            "news"
            if topic == "news"
            else "general"
        )

        params = {
            "q": query,
            "format": "json",
            "categories": category,
            "language": "en",
            "safesearch": 1,
            "pageno": 1,
        }

        if time_range is not None:
            params["time_range"] = time_range

        request_url = (
            f"{self.searxng_endpoint}"
            + (
                "&" if "?" in self.searxng_endpoint else "?"
            )
            + urlencode(params)
        )

        request = Request(
            request_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "NOVA-AI-Personal-Assistant/1.0",
            },
            method="GET",
        )

        try:
            with urlopen(
                request,
                timeout=(
                    min(self.timeout_seconds, 4)
                    if self._is_live_sports_query(query)
                    else self.timeout_seconds
                ),
            ) as response:
                raw_body = response.read()
        except HTTPError as exc:
            raise RuntimeError(
                f"SearXNG search provider returned HTTP {exc.code}."
            ) from exc
        except (OSError, URLError, TimeoutError) as exc:
            raise RuntimeError(
                "SearXNG search provider could not be reached."
            ) from exc

        return self._parse_provider_json(
            raw_body
        )

    @staticmethod
    def _google_news_query(
        query: str,
        topic: str,
    ) -> str:
        """Build a focused RSS query for the keyless news fallback."""
        normalized = " ".join(
            str(query).strip().split()
        )

        if topic != "news":
            return normalized

        lowered = normalized.lower()
        # Do not widen an explicitly publisher-scoped query with OR clauses;
        # doing so can defeat the requested domain restriction.
        if re.search(r"(?:^|\s)site:", lowered):
            return normalized
        voice_signals = (
            "voice",
            "speech",
            "spoken",
            "talking",
            "tts",
            "stt",
            "transcription",
        )
        assistant_signals = (
            "assistant",
            "assistants",
            "agent",
            "agents",
            "alexa",
            "siri",
            "gemini",
        )

        if not any(signal in lowered for signal in voice_signals):
            return normalized

        if not any(signal in lowered for signal in assistant_signals):
            return normalized

        return (
            f"({normalized} OR \\\"voice AI\\\" OR \\\"voice agent\\\")"
        )

    @staticmethod
    def _news_relevance_score(
        query: str,
        result: dict,
    ) -> float:
        """Score news fallback results for topical relevance."""
        title = str(result.get("title") or "").lower()
        content = str(result.get("content") or "").lower()
        haystack = f"{title} {content}"
        normalized_query = " ".join(
            str(query).lower().split()
        )

        score = 0.0

        if "voice assistant" in haystack or "voice assistants" in haystack:
            score += 8.0
        if "voice ai" in haystack:
            score += 7.0
        if "voice agent" in haystack or "voice agents" in haystack:
            score += 7.0
        if "speech ai" in haystack:
            score += 5.0

        if "assistant" in haystack or "assistants" in haystack:
            score += 3.0
        if "agent" in haystack or "agents" in haystack:
            score += 2.0
        if "voice" in haystack:
            score += 3.0

        query_terms = {
            term
            for term in re.findall(r"[a-z0-9]+", normalized_query)
            if len(term) >= 4
            and term not in {
                "latest",
                "recent",
                "current",
                "developments",
                "development",
            }
        }
        title_terms = set(
            re.findall(r"[a-z0-9]+", title)
        )
        score += min(
            4.0,
            1.0 * len(query_terms & title_terms),
        )

        non_topic_signals = (
            "stock",
            "stocks",
            "investor",
            "investors",
            "share price",
            "shares",
            "forecast",
            "marketbeat",
            "tradingview",
        )
        score -= 4.0 * sum(
            1 for signal in non_topic_signals if signal in haystack
        )

        return score

    @staticmethod
    def _rank_news_results(
        query: str,
        results: list[dict],
    ) -> list[dict]:
        """Rank news by relevance and freshness; suppress near-identical recent syndications."""
        now = datetime.now(timezone.utc)

        def published_at(result: dict) -> datetime | None:
            value = result.get("published_date") or result.get("publishedDate")
            if not value:
                value = WebSearchService._publication_date_from_content(
                    str(result.get("content") or "")
                )
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except (TypeError, ValueError):
                try:
                    return datetime.strptime(
                        str(value)[:25], "%a, %d %b %Y %H:%M:%S"
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    return None

        def freshness(result: dict) -> float:
            date = published_at(result)
            if date is None:
                return -5.0
            age = max(0.0, (now - date).total_seconds() / 86400)
            return max(-15.0, 35.0 - min(age, 365.0) * 0.2)

        ranked = sorted(
            enumerate(results),
            key=lambda item: (
                WebSearchService._news_relevance_score(query, item[1]) + freshness(item[1]),
                -item[0],
            ),
            reverse=True,
        )

        deduped: list[dict] = []
        seen_urls: set[str] = set()
        seen_stories: list[tuple[set[str], datetime | None]] = []
        for _, result in ranked:
            url = str(result.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            title = str(result.get("title") or "").lower()
            tokens = {
                token for token in re.findall(r"[a-z0-9]+", title)
                if token not in {"the", "a", "an", "and", "or", "to", "of", "in", "on", "says", "said", "voice", "assistant", "assistants", "update", "updates", "new", "current", "latest"}
            }
            date = published_at(result)
            duplicate_story = False
            if tokens:
                for prior_tokens, prior_date in seen_stories:
                    similarity = len(tokens & prior_tokens) / max(
                        1, min(len(tokens), len(prior_tokens))
                    )
                    within_same_week = (
                        date is not None
                        and prior_date is not None
                        and abs((date - prior_date).total_seconds()) <= 7 * 86400
                    )
                    # Identical syndicated headlines with one missing date are
                    # duplicates; distinct dated editions separated by weeks
                    # remain eligible. Paraphrased stories are deduped only
                    # when both dates prove they are from the same week.
                    if similarity >= 0.90 and (
                        date is None or prior_date is None or within_same_week
                    ):
                        duplicate_story = True
                        break
                    if within_same_week and similarity >= 0.50:
                        duplicate_story = True
                        break
            if duplicate_story:
                continue
            seen_urls.add(url)
            if tokens:
                seen_stories.append((tokens, date))
            deduped.append(result)

        return deduped

    def _request_google_news_rss(
        self,
        *,
        query: str,
        time_range: str | None,
    ) -> dict:
        """
        Read current news from Google's public RSS search feed.

        This is a keyless fallback for news/latest requests when the
        configured Tavily and local SearXNG providers are unavailable.
        """
        timelimit_days = {
            "day": 1,
            "week": 7,
            "month": 31,
            "year": 366,
        }.get(time_range or "")

        rss_query = self._google_news_query(
            query,
            "news",
        )

        if timelimit_days is not None:
            cutoff = (
                datetime.now(timezone.utc)
                - timedelta(days=timelimit_days)
            ).date().isoformat()
            rss_query = f"{rss_query} after:{cutoff}"

        params = {
            "q": rss_query,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }

        request_url = (
            f"{DEFAULT_GOOGLE_NEWS_RSS_ENDPOINT}?"
            f"{urlencode(params)}"
        )

        request = Request(
            request_url,
            headers={
                "Accept": "application/rss+xml, application/xml, text/xml",
                "User-Agent": "NOVA-AI-Personal-Assistant/1.0",
            },
            method="GET",
        )

        try:
            # Keep each RSS fallback bounded; evidence-sensitive comparison
            # searches may fetch several vendor-specific feeds in one turn.
            with urlopen(
                request,
                timeout=min(
                    self.timeout_seconds,
                    4 if self._is_live_sports_query(query) else 5,
                ),
            ) as response:
                raw_body = response.read()
        except HTTPError as exc:
            raise RuntimeError(
                f"Google News RSS provider returned HTTP {exc.code}."
            ) from exc
        except (OSError, URLError, TimeoutError) as exc:
            raise RuntimeError(
                "Google News RSS provider could not be reached."
            ) from exc

        try:
            root = ET.fromstring(raw_body)
        except ET.ParseError as exc:
            raise RuntimeError(
                "Google News RSS provider returned invalid XML."
            ) from exc

        raw_results: list[dict] = []

        for item in root.findall("./channel/item"):
            title = str(
                item.findtext("title") or ""
            ).strip()
            url = str(
                item.findtext("link") or ""
            ).strip()
            published_date = str(
                item.findtext("pubDate") or ""
            ).strip()
            description = str(
                item.findtext("description") or ""
            ).strip()
            source = str(
                item.findtext("source") or ""
            ).strip()

            description = re.sub(
                r"<[^>]+>",
                " ",
                unescape(description),
            )
            description = " ".join(
                description.split()
            )

            if not title or not url:
                continue

            content_parts = [
                f"Source: {source}" if source else "",
                description,
            ]
            content = " ".join(
                part for part in content_parts if part
            ).strip()

            if not content:
                content = title

            raw_results.append(
                {
                    "title": title,
                    "url": url,
                    "content": content,
                    "score": None,
                    "published_date": published_date or None,
                }
            )

        return {"results": raw_results}

    @staticmethod
    def _publication_date_from_content(content: str) -> str | None:
        """Extract a publication date only when it leads the snippet."""
        text = str(content or "").strip()
        patterns = (
            (r"^(\d{4}-\d{2}-\d{2})(?:T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?\b", "%Y-%m-%d"),
            (r"^([A-Z][a-z]{2} \d{1,2}, \d{4})\b", "%b %d, %Y"),
            (r"^([A-Z][a-z]{2} \d{1,2},? \d{4})\b", "%b %d, %Y"),
        )
        for pattern, date_format in patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            value = match.group(1)
            try:
                return datetime.strptime(value.replace(",", ""), date_format).date().isoformat()
            except ValueError:
                try:
                    return datetime.strptime(value, date_format).date().isoformat()
                except ValueError:
                    continue
        return None

    @staticmethod
    def _is_ai_news_query(query: str) -> bool:
        normalized = str(query or "").lower()
        has_ai_topic = any(term in normalized for term in (
            " ai ", "openai", "anthropic", "artificial intelligence",
            "chatgpt", "gemini", "llm", "machine learning",
        )) or normalized.startswith("ai ")
        has_news_intent = any(term in normalized for term in (
            "latest", "recent", "current", "today", "news", "developments",
        ))
        return has_ai_topic and has_news_intent

    @staticmethod
    def _matches_ai_news_query(result: dict) -> bool:
        title = str(result.get("title") or "").lower()
        content = str(result.get("content") or "").lower()
        text = f"{title} {content}"
        if any(term in title for term in (
            "mini-budget", "politics", "world news", "market rises",
            "stocks", "sensex", "investor",
        )):
            return False
        if any(term in title for term in (
            "news today", "news bulletin", "roundup", "round-up",
            "weekly roundup", "latest topics",
        )):
            return False
        # Topic evidence must be in the headline, or be a specific AI entity
        # in the headline; a generic related-links snippet is not evidence.
        title_evidence = any(term in title for term in (
            " ai ", "ai-", "-ai", "openai", "anthropic", "chatgpt",
            "artificial intelligence", "machine learning", "llm",
            "gemini", "gpt-", "ai:", "ai could", "ai model", "voice assistant", "voice assistants", "voice ai",
        )) or title.startswith("ai ")
        content_evidence = any(term in content for term in (
            "artificial intelligence", "ai model", "ai models",
            "openai", "anthropic", "chatgpt", "machine learning",
            "large language model", "llm ", "voice assistant",
            "voice assistants", "voice ai", "voice-agent",
        ))
        return title_evidence or content_evidence

    @staticmethod
    def _matches_openai_news_result(result: dict) -> bool:
        title = str(result.get("title") or "").lower()
        content = str(result.get("content") or "").lower()
        url = str(result.get("url") or "").lower()
        date_value = result.get("published_date") or result.get("publishedDate")
        if not date_value:
            date_value = WebSearchService._publication_date_from_content(content)
        if not date_value:
            return False
        try:
            parsed_date = datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
            if parsed_date.tzinfo is None:
                parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - parsed_date.astimezone(timezone.utc)).days
        except (TypeError, ValueError):
            try:
                parsed_date = datetime.strptime(str(date_value)[:25], "%a, %d %b %Y %H:%M:%S").replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - parsed_date).days
            except ValueError:
                return False
        if age_days < -1 or age_days > 30:
            return False
        if any(term in title for term in ("reviews, news, and deals", "community", "roundup", "round-up", "news today", "weekly")):
            return False
        if "community.openai.com" in url or "/brands/" in url or "forum" in url:
            return False
        host = urlparse(url).netloc.lower()
        official = host == "openai.com" or host.endswith(".openai.com")
        reputable_press = host == "reuters.com" or host.endswith(".reuters.com")
        if not (official or reputable_press):
            return False
        return "openai" in title or "openai" in content

    @staticmethod
    def _is_voice_assistant_comparison_query(query: str) -> bool:
        normalized = str(query or "").lower()
        return (
            ("voice" in normalized or "spoken" in normalized)
            and ("assistant" in normalized or "alexa" in normalized or "siri" in normalized)
            and any(term in normalized for term in ("compare", "comparison", "strongest", "limitations", "capabilities"))
        )

    @staticmethod
    def _voice_assistant_vendor(result: dict) -> str | None:
        """Identify the primary subject; competitor mentions alone do not count."""
        title = str(result.get("title") or "").lower()
        url = str(result.get("url") or "").lower()

        markers = {
            "google": r"\b(?:gemini|google assistant)\b",
            "amazon": r"\b(?:alexa\+?|amazon)\b",
            "apple": r"\b(?:siri|apple intelligence)\b",
            "openai": r"\b(?:chatgpt|openai)\b",
            "samsung": r"\b(?:bixby|samsung)\b",
        }
        title_hits = [
            (match.start(), vendor)
            for vendor, pattern in markers.items()
            if (match := re.search(pattern, title))
        ]
        if title_hits:
            return min(title_hits, key=lambda hit: hit[0])[1]

        # Fall back to known publisher/product URLs only when the headline
        # does not identify a product.
        host = urlparse(url).netloc.lower()
        if host == "aboutamazon.com" or host.endswith(".aboutamazon.com"):
            return "amazon"
        if host == "apple.com" or host.endswith(".apple.com"):
            return "apple"
        if host == "openai.com" or host.endswith(".openai.com"):
            return "openai"
        if host == "blog.google" or host.endswith(".google.com"):
            return "google"
        if host.endswith("androidauthority.com"):
            return "google"
        if host.endswith("techcrunch.com") and "alexa" in url:
            return "amazon"
        if host.endswith("theverge.com") and "siri" in url:
            return "apple"
        if host.endswith("engadget.com") and "chatgpt" in url:
            return "openai"
        return None

    @staticmethod
    def _voice_assistant_vendors(result: dict) -> set[str]:
        """Return primary vendor coverage, including vendors explicitly compared."""
        title = str(result.get("title") or "").lower()
        content = str(result.get("content") or "").lower()
        url = str(result.get("url") or "").lower()
        comparison_title = bool(re.search(
            r"\b(?:vs\.?|versus)\s+|"
            r"\b(?:compare[sd]?|comparison|tested|pitting)\b|"
            r"\bwho(?:'s| is)\s+best\b|\bwhich\b.{0,60}\bbest\b",
            title,
        ))

        markers = {
            "google": r"\b(?:gemini|google assistant)\b",
            "amazon": r"\b(?:alexa\+?|amazon)\b",
            "apple": r"\b(?:siri|apple intelligence)\b",
            "openai": r"\b(?:chatgpt|openai)\b",
            "samsung": r"\b(?:bixby|samsung)\b",
        }

        # For ordinary product/news stories, only count the primary subject in
        # the headline. A competitor mention in the body does not establish
        # that the story supports claims about that competitor.
        if not comparison_title:
            primary = WebSearchService._voice_assistant_vendor(result)
            return {primary} if primary else set()

        # A headline explicitly framed as a comparison can support multiple
        # products. Prefer product names in the headline; use the body only
        # when the headline describes a generic multi-product test.
        text = title
        title_vendor_hits = {
            vendor
            for vendor, pattern in markers.items()
            if re.search(pattern, title)
        }
        if len(title_vendor_hits) < 2:
            text = f"{title} {content}"

        vendors = {
            vendor
            for vendor, pattern in markers.items()
            if re.search(pattern, text)
        }
        return vendors

    @staticmethod
    def _publication_datetime(result: dict) -> datetime | None:
        """Parse an explicit provider publication date without inferring one."""
        value = result.get("published_date") or result.get("publishedDate")
        if not value:
            value = WebSearchService._publication_date_from_content(
                str(result.get("content") or "")
            )
        if not value:
            return None
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.strptime(
                    text[:25], "%a, %d %b %Y %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _is_recently_published(
        cls,
        result: dict,
        *,
        max_age_days: int = 90,
    ) -> bool:
        published = cls._publication_datetime(result)
        if published is None:
            return False
        age_days = (
            datetime.now(timezone.utc) - published
        ).total_seconds() / 86400
        return -1 <= age_days <= max_age_days

    @staticmethod
    def _is_openai_news_query(query: str) -> bool:
        normalized = " ".join(str(query or "").lower().split())
        return "openai" in normalized and any(term in normalized for term in ("latest", "news", "recent", "current", "today"))

    @staticmethod
    def _scoped_voice_queries(*, rss: bool = False) -> list[str]:
        if rss:
            # The RSS supplement is specifically for recent independent
            # coverage, rather than undated evergreen help pages.
            return [
                'site:androidauthority.com "Gemini Live" voice 2026',
                'site:techcrunch.com "Alexa+" voice assistant 2026',
                'site:theverge.com Siri AI voice assistant 2026',
                'site:engadget.com "ChatGPT Voice" 2026',
            ]
        return [
            'site:support.google.com/gemini "Gemini Live" voice',
            'site:aboutamazon.com/news/devices "Alexa+" voice assistant',
            'site:apple.com/newsroom "Siri AI" 2026',
            'site:help.openai.com/en/articles "ChatGPT Voice"',
        ]

    @staticmethod
    def _scoped_openai_queries() -> list[str]:
        return [
            "site:openai.com/index OpenAI product update",
            "site:reuters.com/technology OpenAI",
            "site:apnews.com OpenAI artificial intelligence",
            "site:techcrunch.com OpenAI",
        ]

    @staticmethod
    def _open_meteo_weather_code(code: int) -> str:
        labels = {
            0: "clear sky", 1: "mainly clear", 2: "partly cloudy",
            3: "overcast", 45: "fog", 48: "depositing rime fog",
            51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
            61: "slight rain", 63: "moderate rain", 65: "heavy rain",
            71: "slight snow", 73: "moderate snow", 75: "heavy snow",
            80: "rain showers", 81: "moderate rain showers", 82: "violent rain showers",
            95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
        }
        return labels.get(int(code), "unknown conditions")

    def _search_weather(self, query: str) -> list[dict]:
        location_match = re.search(
            r"\b(?:weather|forecast)\s+(?:in|for|at)\s+([A-Za-z][A-Za-z .'-]{1,80}?)(?:[?.!,]|$)",
            query,
            flags=re.IGNORECASE,
        )
        if not location_match:
            location_match = re.search(
                r"\b(?:in|for|at)\s+([A-Za-z][A-Za-z .'-]{1,80}?)(?:[?.!,]|$)",
                query,
                flags=re.IGNORECASE,
            )
        if not location_match:
            raise ValueError("Weather search requires a location.")
        location = location_match.group(1).strip()
        geo_url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode({
            "name": location, "count": 1, "language": "en", "format": "json",
        })
        def read_json(url: str) -> dict:
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "NOVA-AI-Personal-Assistant/1.0"})
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    return self._parse_provider_json(response.read())
            except (HTTPError, OSError, URLError, TimeoutError) as exc:
                raise RuntimeError("Weather provider could not be reached.") from exc
        geo = read_json(geo_url)
        places = geo.get("results") or []
        if not places:
            raise ValueError(f"Could not find a weather location for '{location}'.")
        place = places[0]
        name = str(place.get("name") or location)
        country = str(place.get("country") or "")
        timezone_name = str(place.get("timezone") or "auto")
        forecast_url = "https://api.open-meteo.com/v1/forecast?" + urlencode({
            "latitude": place["latitude"], "longitude": place["longitude"],
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
            "timezone": timezone_name,
        })
        forecast = read_json(forecast_url)
        current = forecast.get("current") or {}
        if not current:
            raise RuntimeError("Weather provider returned no current conditions.")
        temperature = current.get("temperature_2m")
        feels_like = current.get("apparent_temperature")
        humidity = current.get("relative_humidity_2m")
        wind = current.get("wind_speed_10m")
        code = current.get("weather_code", -1)
        content = (
            f"Conditions: {self._open_meteo_weather_code(code)}; "
            f"temperature {temperature}°C; feels like {feels_like}°C; "
            f"humidity {float(humidity):.1f}%; wind {wind} km/h; "
            f"precipitation {current.get('precipitation', 0)} mm. "
            f"Observation time: {current.get('time', 'not provided')} ({timezone_name})."
        )
        return [{
            "title": f"Current weather in {name}{', ' + country if country else ''}",
            "url": "https://open-meteo.com/",
            "content": content,
            "score": None,
            "published_date": None,
        }]

    def _resolve_google_news_article_url(self, url: str) -> str | None:
        """Resolve an RSS intermediary only when Google verifies the publisher URL."""
        if not hasattr(self, "_google_news_url_cache"):
            self._google_news_url_cache = {}
        normalized = str(url or "").strip()
        if normalized in self._google_news_url_cache:
            return self._google_news_url_cache[normalized]
        parsed = urlparse(normalized)
        if parsed.netloc.lower() not in {"news.google.com", "www.news.google.com"} or "/rss/articles/" not in parsed.path:
            self._google_news_url_cache[normalized] = None
            return None
        article_url = f"https://news.google.com{parsed.path}"
        try:
            request = Request(article_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
            with urlopen(request, timeout=min(self.timeout_seconds, 3)) as response:
                html = response.read().decode("utf-8", errors="replace")
            signature = re.search(r'data-n-a-sg="([^"]+)"', html)
            timestamp = re.search(r'data-n-a-ts="(\d+)"', html)
            if not signature or not timestamp:
                self._google_news_url_cache[normalized] = None
                return None
            from urllib.parse import quote_plus
            rpc = [[
                "Fbv4je",
                json.dumps([article_url, signature.group(1), int(timestamp.group(1))], separators=(",", ":")),
                None,
                "generic",
            ]]
            body = "f.req=" + quote_plus(json.dumps([rpc], separators=(",", ":")))
            rpc_request = Request(
                "https://news.google.com/_/DotsSplashUi/data/batchexecute",
                data=body.encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "User-Agent": "Mozilla/5.0", "Referer": article_url},
                method="POST",
            )
            with urlopen(rpc_request, timeout=min(self.timeout_seconds, 3)) as response:
                rpc_body = response.read().decode("utf-8", errors="replace")
            rpc_body = rpc_body.lstrip(")]}'\n")
            parsed_payload = json.loads(rpc_body)
            def find_publisher(value: Any) -> str | None:
                if isinstance(value, str):
                    if value.startswith(("https://", "http://")):
                        host = urlparse(value).netloc.lower()
                        if host and not host.endswith("google.com") and "news.google.com" not in host:
                            return value
                    try:
                        return find_publisher(json.loads(value))
                    except (ValueError, TypeError):
                        return None
                if isinstance(value, list):
                    for child in value:
                        found = find_publisher(child)
                        if found:
                            return found
                return None
            publisher = find_publisher(parsed_payload)
            self._google_news_url_cache[normalized] = publisher
            return publisher
        except Exception:
            self._google_news_url_cache[normalized] = None
            return None

    def _fetch_publisher_excerpt(self, url: str) -> str | None:
        """Fetch a bounded readable excerpt only from known publisher hosts."""
        host = urlparse(url).netloc.lower().split(":", 1)[0]
        allowed_hosts = (
            "blog.google", "support.google.com", "aboutamazon.com",
            "www.aboutamazon.com", "apple.com", "www.apple.com",
            "help.openai.com", "openai.com", "www.openai.com",
        )
        if not any(host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts):
            return None

        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "NOVA-AI-Personal-Assistant/1.0",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=min(self.timeout_seconds, 4)) as response:
                raw = response.read(1_000_000)
            page = raw.decode("utf-8", errors="replace")
        except Exception as exc:
            logger.debug("Publisher excerpt fetch failed (%s): %s", host, type(exc).__name__)
            return None

        descriptions: list[str] = []
        for pattern in (
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
        ):
            match = re.search(pattern, page, flags=re.IGNORECASE)
            if match:
                descriptions.append(unescape(match.group(1)))

        body = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", page)
        body = re.sub(r"(?s)<[^>]+>", " ", body)
        body = " ".join(unescape(body).split())
        excerpt = " ".join(descriptions + ([body[:2200]] if body else []))
        excerpt = " ".join(excerpt.split())
        return excerpt[:2400] or None

    def search(
        self,
        *,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        topic: str = "general",
        time_range: str | None = None,
    ) -> list[dict]:
        normalized_query = self._normalize_query(query)
        normalized_max_results = self._normalize_max_results(max_results)
        normalized_topic = self._normalize_topic(topic)
        normalized_time_range = self._normalize_time_range(time_range)
        is_live_sports_query = self._is_live_sports_query(normalized_query)

        if normalized_topic == "weather":
            return self._search_weather(normalized_query)

        is_voice_comparison = self._is_voice_assistant_comparison_query(normalized_query)
        is_openai_news = self._is_openai_news_query(normalized_query)
        is_ai_news = self._is_ai_news_query(normalized_query)

        def fetch_scoped(provider: str, scoped_query: str) -> list[dict]:
            if provider == "rss":
                response = self._request_google_news_rss(
                    query=scoped_query,
                    time_range=None,
                )
            else:
                response = self._request_searxng(
                    query=scoped_query,
                    topic="general",
                    time_range=None,
                )
            found = response.get("results", [])
            return found if isinstance(found, list) else []

        def normalize_results(
            raw_results: list[dict],
            *,
            rss: bool = False,
            resolve_rss_urls: bool = True,
        ) -> list[dict]:
            normalized: list[dict] = []
            for raw in raw_results:
                if not isinstance(raw, dict):
                    continue
                title = str(raw.get("title") or "").strip()
                url = self._normalize_result_url(raw.get("url") or "")
                content = str(raw.get("content") or "").strip()
                if not title or not url or not content:
                    continue
                short_or_metadata_only = (
                    content.lower().startswith("source:")
                    or len(content) < 180
                )
                has_publication_metadata = bool(
                    raw.get("published_date") or raw.get("publishedDate")
                )
                has_inline_publication_date = bool(
                    self._publication_date_from_content(content)
                )
                if (
                    is_voice_comparison
                    and short_or_metadata_only
                    and not has_publication_metadata
                    and not has_inline_publication_date
                ):
                    excerpt = self._fetch_publisher_excerpt(url)
                    if excerpt:
                        content = excerpt
                published = raw.get("published_date") or raw.get("publishedDate")
                if not published:
                    published = self._publication_date_from_content(content)
                published_text = str(published).strip()[:100] if published else None
                if rss and "news.google.com" in urlparse(url).netloc.lower():
                    resolved = (
                        self._resolve_google_news_article_url(url)
                        if resolve_rss_urls
                        else None
                    )
                    if resolved:
                        url = resolved
                    else:
                        content = f"{content} [Google News intermediary link; publisher URL could not be verified.]"
                normalized.append(WebSearchResult(
                    title=title[:500],
                    url=url[:2000],
                    content=content[:MAX_SNIPPET_LENGTH],
                    score=self._safe_score(raw.get("score")),
                    published_date=published_text,
                ).to_dict())
            return normalized

        def scoped_research(
            *,
            rss: bool,
            openai: bool = False,
            vendors: set[str] | None = None,
        ) -> list[dict]:
            queries = self._scoped_openai_queries() if openai else self._scoped_voice_queries(rss=rss)
            if rss and vendors is not None and not openai:
                query_vendor_hosts = {
                    "google": "androidauthority.com",
                    "amazon": "techcrunch.com",
                    "apple": "theverge.com",
                    "openai": "engadget.com",
                }
                queries = [
                    scoped_query for scoped_query in queries
                    if any(
                        host in scoped_query
                        for vendor, host in query_vendor_hosts.items()
                        if vendor in vendors
                    )
                ]
            found: list[dict] = []
            for scoped_query in queries:
                try:
                    items = fetch_scoped("rss" if rss else "searxng", scoped_query)
                except Exception as exc:
                    logger.warning("Scoped web search failed: %s", type(exc).__name__)
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if openai and not self._matches_openai_news_result(item):
                        continue
                    found.append(item)
            return found

        # Comparisons and OpenAI news are evidence-sensitive: broad roundups
        # are not accepted as substitutes for primary/publisher-scoped pages.
        if is_voice_comparison or is_openai_news:
            provider = "searxng"
            broad: list[dict] = []
            try:
                response = self._request_searxng(
                    query=normalized_query,
                    topic=normalized_topic,
                    time_range=normalized_time_range,
                )
                broad = response.get("results", []) if isinstance(response, dict) else []
            except Exception as exc:
                logger.warning("Primary news search failed; using RSS fallback: %s", type(exc).__name__)
                provider = "rss"
                try:
                    response = self._request_google_news_rss(
                        query=normalized_query,
                        time_range=normalized_time_range,
                    )
                    broad = response.get("results", []) if isinstance(response, dict) else []
                except Exception as rss_exc:
                    logger.warning("Google News RSS search failed: %s", type(rss_exc).__name__)
                    broad = []

            if is_openai_news:
                broad = [item for item in broad if isinstance(item, dict) and self._matches_openai_news_result(item)]
            else:
                broad = [
                    item for item in broad if isinstance(item, dict)
                    and any(term in (str(item.get("title") or "") + " " + str(item.get("content") or "")).lower()
                            for term in ("gemini live", "alexa+", "siri", "chatgpt voice", "voice assistant"))
                ]

            if is_voice_comparison:
                # Use the broad query's relevant reporting. A second set of
                # SearXNG site queries often repeats the same help pages and
                # increases rate-limited requests without improving coverage.
                used_rss = provider == "rss"
                candidates = [
                    item for item in broad
                    if isinstance(item, dict)
                    and self._voice_assistant_vendors(item)
                ]
                if used_rss:
                    candidates.sort(
                        key=lambda item: self._publication_datetime(item)
                        or datetime.min.replace(tzinfo=timezone.utc),
                        reverse=True,
                    )
                    candidates = candidates[:normalized_max_results]

                normalized = normalize_results(candidates, rss=used_rss)
                normalized = [
                    item for item in normalized
                    if self._voice_assistant_vendors(item)
                ]

                expected_vendors = {"google", "amazon", "apple", "openai"}
                recent_vendors: set[str] = set()
                for item in normalized:
                    if self._is_recently_published(item):
                        recent_vendors.update(self._voice_assistant_vendors(item))
                missing_vendors = expected_vendors - recent_vendors

                if missing_vendors:
                    rss_candidates = scoped_research(
                        rss=True,
                        vendors=missing_vendors,
                    )
                    candidates_by_vendor: dict[str, list[dict]] = {
                        vendor: [] for vendor in missing_vendors
                    }
                    for item in rss_candidates:
                        if not self._is_recently_published(item):
                            continue
                        for vendor in self._voice_assistant_vendors(item) & missing_vendors:
                            candidates_by_vendor[vendor].append(item)

                    seen_urls = {str(item.get("url") or "") for item in normalized}
                    for vendor in sorted(list(missing_vendors)):
                        options = candidates_by_vendor.get(vendor, [])
                        options.sort(
                            key=lambda item: self._publication_datetime(item)
                            or datetime.min.replace(tzinfo=timezone.utc),
                            reverse=True,
                        )
                        for raw_item in options:
                            selected = normalize_results([raw_item], rss=True)
                            if not selected:
                                continue
                            result = selected[0]
                            source_vendors = self._voice_assistant_vendors(result)
                            url = str(result.get("url") or "")
                            if url and url not in seen_urls:
                                normalized.append(result)
                                seen_urls.add(url)
                            missing_vendors -= source_vendors
                            break

                if not normalized:
                    return []

                # Fresh, distinct stories should rank before undated evergreen
                # pages. The ranking never fabricates a publication date.
                ranked = self._rank_news_results(normalized_query, normalized)
                remaining = list(ranked)
                diversified: list[dict] = []
                covered_vendors: set[str] = set()
                while remaining and len(diversified) < normalized_max_results:
                    best_index = max(
                        range(len(remaining)),
                        key=lambda index: (
                            len(self._voice_assistant_vendors(remaining[index]) - covered_vendors),
                            -index,
                        ),
                    )
                    item = remaining.pop(best_index)
                    diversified.append(item)
                    covered_vendors.update(self._voice_assistant_vendors(item))
                return diversified[:normalized_max_results]

            # OpenAI news uses publisher-scoped sources only; broad brand
            # directories and generic roundups are not sufficient evidence.
            scoped = scoped_research(rss=provider == "rss", openai=True)
            used_rss = provider == "rss"
            if not scoped and provider != "rss":
                scoped = scoped_research(rss=True, openai=True)
                used_rss = True

            raw_results = scoped or broad
            normalized = normalize_results(
                raw_results,
                rss=used_rss or (not scoped and provider != "rss"),
            )
            normalized = [
                item for item in normalized
                if self._matches_openai_news_result(item)
            ]
            if not normalized:
                return []
            return normalized[:normalized_max_results]

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

        response: dict | None = None
        provider = "tavily" if self.api_key else "searxng"
        searxng_attempted = False
        if self.api_key:
            try:
                response = self._request_tavily(payload)
            except Exception as exc:
                logger.warning("Tavily web search failed; trying SearXNG: %s", type(exc).__name__)
                provider = "searxng"

        if response is None:
            searxng_attempted = True
            try:
                response = self._request_searxng(
                    query=normalized_query,
                    topic=normalized_topic,
                    time_range=normalized_time_range,
                )
            except Exception as exc:
                if normalized_topic != "news" and not is_live_sports_query:
                    raise
                logger.warning(
                    "SearXNG search failed; trying Google News RSS fallback: %s",
                    type(exc).__name__,
                )
                provider = "rss"
                response = None
                last_error: Exception | None = None
                # Live-score requests prefer bounded latency over a second
                # identical feed request. Returning a transparent no-result
                # state is safer than delaying the spoken turn by another timeout.
                max_rss_attempts = 1 if is_live_sports_query else 2
                for attempt in range(max_rss_attempts):
                    try:
                        response = self._request_google_news_rss(
                            query=normalized_query,
                            time_range=normalized_time_range,
                        )
                        last_error = None
                        break
                    except Exception as rss_exc:
                        last_error = rss_exc
                        if attempt == 0 and max_rss_attempts > 1:
                            logger.warning("Google News RSS transient failure; retrying once: %s", type(rss_exc).__name__)
                if response is None:
                    if last_error:
                        raise last_error
                    response = {"results": []}

        raw_results = response.get("results", []) if isinstance(response, dict) else []
        used_rss = provider == "rss"

        if not isinstance(raw_results, list):
            raise RuntimeError("Live web search provider returned invalid results.")

        if not used_rss and not raw_results and is_live_sports_query:
            # Search APIs sometimes return HTTP 200 with zero indexed results.
            # If SearXNG has not already been tried, call it once, then use RSS.
            if not searxng_attempted:
                searxng_attempted = True
                try:
                    response = self._request_searxng(
                        query=normalized_query,
                        topic="general",
                        time_range=normalized_time_range,
                    )
                    raw_results = response.get("results", []) if isinstance(response, dict) else []
                except Exception as exc:
                    logger.warning("Live-sports secondary search failed: %s", type(exc).__name__)
                    raw_results = []

            if not raw_results:
                last_sports_error: Exception | None = None
                for retry_range in (normalized_time_range, None):
                    try:
                        rss_response = self._request_google_news_rss(
                            query=normalized_query,
                            time_range=retry_range,
                        )
                        raw_results = (
                            rss_response.get("results", [])
                            if isinstance(rss_response, dict)
                            else []
                        )
                        if raw_results:
                            provider = "rss"
                            used_rss = True
                            break
                    except Exception as exc:
                        last_sports_error = exc
                        logger.warning(
                            "Live-sports RSS fallback failed: %s",
                            type(exc).__name__,
                        )
                if not raw_results and last_sports_error is not None:
                    logger.warning("No fallback sources returned for live-sports query.")

        if used_rss and not raw_results and not is_live_sports_query:
            # A date-filtered RSS query can be too narrow; retry the same
            # query without a date filter, then simplify it once.
            attempts = [(normalized_query, None)]
            simple_query = re.sub(
                r"\b(?:latest|recent|current|developments?|in|today|this week)\b",
                " ",
                normalized_query,
                flags=re.IGNORECASE,
            )
            simple_query = " ".join(simple_query.split())
            if simple_query and simple_query.lower() != normalized_query.lower():
                attempts.append((simple_query, None))
            for retry_query, retry_range in attempts:
                try:
                    retry_response = self._request_google_news_rss(
                        query=retry_query,
                        time_range=retry_range,
                    )
                    raw_results = retry_response.get("results", [])
                except Exception as exc:
                    logger.warning("Google News RSS retry failed: %s", type(exc).__name__)
                    raw_results = []
                if raw_results:
                    normalized_query = retry_query
                    break

        if not used_rss and not raw_results and normalized_topic == "news":
            try:
                response = self._request_searxng(
                    query=normalized_query,
                    topic="general",
                    time_range=normalized_time_range,
                )
                raw_results = response.get("results", [])
            except Exception as exc:
                logger.warning("General-search fallback failed: %s", type(exc).__name__)
                raw_results = []
            if not raw_results and normalized_time_range is not None:
                try:
                    response = self._request_searxng(
                        query=normalized_query,
                        topic="general",
                        time_range=None,
                    )
                    raw_results = response.get("results", [])
                except Exception as exc:
                    logger.warning("Unfiltered general-search fallback failed: %s", type(exc).__name__)
                    raw_results = []

        normalized = normalize_results(
            raw_results,
            rss=used_rss,
            resolve_rss_urls=not is_live_sports_query,
        )
        if is_live_sports_query:
            normalized = self._rank_live_sports_results(normalized_query, normalized)
        if normalized_topic == "news" and is_ai_news:
            relevant = [item for item in normalized if self._matches_ai_news_query(item)]
            if not relevant and normalized_time_range is not None and not used_rss:
                try:
                    retry = self._request_searxng(
                        query=normalized_query,
                        topic="news",
                        time_range=None,
                    )
                    normalized = normalize_results(retry.get("results", []))
                    relevant = [item for item in normalized if self._matches_ai_news_query(item)]
                except Exception as exc:
                    logger.warning("Unfiltered AI-news retry failed: %s", type(exc).__name__)
            normalized = relevant

        if normalized_topic == "news":
            normalized = self._rank_news_results(normalized_query, normalized)
        return normalized[:normalized_max_results]

    @staticmethod
    def _rank_live_sports_results(query: str, results: list[dict]) -> list[dict]:
        """Prefer actual live scoreboards over previews and generic sports news."""
        normalized_query = " ".join(str(query or "").lower().split())
        requested_teams = [
            team for team in (
                "pakistan", "england", "india", "australia", "new zealand",
                "bangladesh", "sri lanka", "west indies", "afghanistan",
                "manchester city", "manchester united", "liverpool", "arsenal",
                "chelsea", "real madrid", "barcelona",
            )
            if team in normalized_query
        ]
        preferred_hosts = (
            "espncricinfo.com", "cricbuzz.com", "icc-cricket.com", "espn.com",
            "bbc.com", "bbc.co.uk", "premierleague.com", "fifa.com",
            "skysports.com", "livescore.com", "flashscore.com", "soccerway.com",
            "sports.ndtv.com", "olympics.com",
        )
        preview_terms = ("preview", "prediction", "odds", "betting", "pre-match", "lineup prediction")
        live_terms = ("live", "scorecard", "score board", "scoreboard", "scores", "innings", "overs", "wickets", "goals", "match centre", "match center")

        def result_score(item: dict, index: int) -> tuple[float, int]:
            title = str(item.get("title") or "").lower()
            content = str(item.get("content") or "").lower()
            url = str(item.get("url") or "").lower()
            haystack = f"{title} {content}"
            score = 0.0
            if any(term in title for term in ("scorecard", "score board", "scoreboard", "live score", "match centre", "match center")):
                score += 10.0
            if any(term in haystack for term in live_terms):
                score += 4.0
            parsed_host = urlparse(url).hostname or ""
            if any(
                parsed_host == host or parsed_host.endswith("." + host)
                for host in preferred_hosts
            ):
                score += 5.0
            for team in requested_teams:
                if team in haystack:
                    score += 4.0
                else:
                    score -= 1.5
            if re.search(r"\b\d{1,3}\s*/\s*\d{1,2}\b", haystack):
                score += 2.0
            if any(term in title for term in preview_terms):
                score -= 5.0
            try:
                score += max(-1.0, min(1.0, float(item.get("score") or 0.0)))
            except (TypeError, ValueError):
                pass
            return (score, -index)

        return [
            item for _, item in sorted(
                enumerate(results),
                key=lambda pair: result_score(pair[1], pair[0]),
                reverse=True,
            )
        ]

    @staticmethod
    def _safe_score(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
