from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)


MAX_URL_LENGTH = 2048
MAX_RESPONSE_BYTES = 5_000_000
REQUEST_TIMEOUT_SECONDS = 10
MAX_REDIRECTS = 5

SUPPORTED_SCHEMES = {"http", "https"}
SUPPORTED_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
}

DEFAULT_USER_AGENT = (
    "NOVA-AI-Personal-Assistant/1.0 "
    "(web knowledge ingestion)"
)

_IGNORED_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
}

_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "div",
    "dl",
    "dt",
    "dd",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}


@dataclass(frozen=True)
class ParsedWebPage:
    url: str
    title: str
    text: str
    content_type: str


class _WebPageHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )
        self._ignored_depth = 0
        self._in_title = False
        self._text_parts: list[str] = []
        self._title_parts: list[str] = []

    @property
    def title(self) -> str:
        return _normalize_text(
            "".join(self._title_parts)
        )

    @property
    def text(self) -> str:
        return _normalize_text(
            "".join(self._text_parts)
        )

    def handle_starttag(
        self,
        tag: str,
        attrs,
    ) -> None:
        normalized_tag = tag.lower()

        if normalized_tag in _IGNORED_TAGS:
            self._ignored_depth += 1
            return

        if self._ignored_depth > 0:
            return

        if normalized_tag == "title":
            self._in_title = True
            return

        if normalized_tag in _BLOCK_TAGS:
            self._text_parts.append("\n")

    def handle_startendtag(
        self,
        tag: str,
        attrs,
    ) -> None:
        normalized_tag = tag.lower()

        if (
            self._ignored_depth == 0
            and normalized_tag in _BLOCK_TAGS
        ):
            self._text_parts.append("\n")

    def handle_endtag(
        self,
        tag: str,
    ) -> None:
        normalized_tag = tag.lower()

        if normalized_tag in _IGNORED_TAGS:
            if self._ignored_depth > 0:
                self._ignored_depth -= 1
            return

        if self._ignored_depth > 0:
            return

        if normalized_tag == "title":
            self._in_title = False
            return

        if normalized_tag in _BLOCK_TAGS:
            self._text_parts.append("\n")

    def handle_data(
        self,
        data: str,
    ) -> None:
        if self._ignored_depth > 0:
            return

        normalized_data = re.sub(
            r"\s+",
            " ",
            data,
        )

        if self._in_title:
            self._title_parts.append(
                normalized_data
            )
            return

        self._text_parts.append(
            normalized_data
        )


class _SafeRedirectHandler(
    HTTPRedirectHandler
):
    max_redirections = MAX_REDIRECTS

    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        WebPageParserService._validate_url(
            newurl
        )

        return super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            newurl,
        )


def _normalize_text(
    value: str,
) -> str:
    lines = [
        " ".join(line.split())
        for line in str(value).splitlines()
    ]

    return "\n".join(
        line
        for line in lines
        if line
    ).strip()


class WebPageParserService:
    """
    Safe URL fetching and visible HTML text extraction.

    This foundation is intentionally limited to fetching and parsing.
    Knowledge persistence, chunking, embeddings, and retrieval remain
    in KnowledgeService and the knowledge API boundary.
    """

    def __init__(
        self,
        *,
        timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be greater than 0"
            )

        normalized_user_agent = str(
            user_agent
        ).strip()

        if not normalized_user_agent:
            raise ValueError(
                "user_agent cannot be empty"
            )

        self.timeout_seconds = timeout_seconds
        self.user_agent = normalized_user_agent

    @staticmethod
    def _validate_url(
        url: str,
    ) -> str:
        normalized = str(url).strip()

        if not normalized:
            raise ValueError(
                "url cannot be empty."
            )

        if len(normalized) > MAX_URL_LENGTH:
            raise ValueError(
                f"url exceeds the maximum length of "
                f"{MAX_URL_LENGTH} characters."
            )

        parsed = urlsplit(normalized)

        if parsed.scheme.lower() not in SUPPORTED_SCHEMES:
            raise ValueError(
                "url must use http or https."
            )

        if (
            parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(
                "url must not contain embedded credentials."
            )

        hostname = parsed.hostname

        if not hostname:
            raise ValueError(
                "url must contain a valid hostname."
            )

        WebPageParserService._validate_hostname(
            hostname
        )

        canonical = urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc,
                parsed.path,
                parsed.query,
                "",
                "",
            )
        )

        return canonical

    @staticmethod
    def _validate_hostname(
        hostname: str,
    ) -> None:
        normalized_host = hostname.strip().lower()

        if (
            normalized_host == "localhost"
            or normalized_host.endswith(
                ".localhost"
            )
            or normalized_host.endswith(
                ".local"
            )
        ):
            raise ValueError(
                "url hostname resolves to a local network name."
            )

        try:
            addresses = socket.getaddrinfo(
                normalized_host,
                None,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise ValueError(
                "url hostname could not be resolved."
            ) from exc

        for address in addresses:
            ip_text = address[4][0]

            try:
                ip_address = ipaddress.ip_address(
                    ip_text
                )
            except ValueError as exc:
                raise ValueError(
                    "url hostname resolved to an invalid address."
                ) from exc

            if (
                ip_address.is_private
                or ip_address.is_loopback
                or ip_address.is_link_local
                or ip_address.is_multicast
                or ip_address.is_reserved
                or ip_address.is_unspecified
            ):
                raise ValueError(
                    "url hostname resolves to a restricted network address."
                )

    def _build_opener(self):
        return build_opener(
            _SafeRedirectHandler()
        )

    def fetch(
        self,
        url: str,
    ) -> ParsedWebPage:
        normalized_url = self._validate_url(
            url
        )

        request = Request(
            normalized_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": (
                    "text/html,application/xhtml+xml"
                ),
            },
            method="GET",
        )

        try:
            with self._build_opener().open(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                final_url = self._validate_url(
                    response.geturl()
                )

                content_type = (
                    response.headers.get_content_type()
                )

                if (
                    content_type
                    not in SUPPORTED_CONTENT_TYPES
                ):
                    raise ValueError(
                        "The URL does not contain "
                        "an HTML document."
                    )

                content_length = (
                    response.headers.get(
                        "Content-Length"
                    )
                )

                if content_length:
                    try:
                        declared_size = int(
                            content_length
                        )
                    except ValueError:
                        declared_size = None

                    if (
                        declared_size is not None
                        and declared_size
                        > MAX_RESPONSE_BYTES
                    ):
                        raise ValueError(
                            "The web page exceeds the "
                            "maximum response size."
                        )

                content = response.read(
                    MAX_RESPONSE_BYTES + 1
                )

        except ValueError:
            raise
        except HTTPError as exc:
            raise ValueError(
                f"The URL returned HTTP {exc.code}."
            ) from exc
        except (
            OSError,
            URLError,
            TimeoutError,
        ) as exc:
            raise ValueError(
                "The URL could not be fetched."
            ) from exc

        if len(content) > MAX_RESPONSE_BYTES:
            raise ValueError(
                "The web page exceeds the "
                "maximum response size."
            )

        charset = (
            response.headers.get_content_charset()
            or "utf-8"
        )

        try:
            html = content.decode(
                charset,
                errors="replace",
            )
        except LookupError:
            html = content.decode(
                "utf-8",
                errors="replace",
            )

        return self.parse_html(
            url=final_url,
            html=html,
            content_type=content_type,
        )

    def parse_html(
        self,
        *,
        url: str,
        html: str,
        content_type: str = "text/html",
    ) -> ParsedWebPage:
        normalized_url = self._validate_url(
            url
        )

        if (
            content_type
            not in SUPPORTED_CONTENT_TYPES
        ):
            raise ValueError(
                "content_type must be an HTML content type."
            )

        if not str(html).strip():
            raise ValueError(
                "The web page does not contain any usable text."
            )

        parser = _WebPageHTMLParser()
        parser.feed(html)
        parser.close()

        text = parser.text

        if not text:
            raise ValueError(
                "The web page does not contain any usable text."
            )

        title = (
            parser.title
            or normalized_url
        )

        return ParsedWebPage(
            url=normalized_url,
            title=title,
            text=text,
            content_type=content_type,
        )
