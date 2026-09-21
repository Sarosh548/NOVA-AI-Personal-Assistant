from __future__ import annotations

from unittest.mock import Mock
from urllib.error import URLError

import pytest

import services.url_parser_service as url_module
from services.url_parser_service import (
    MAX_RESPONSE_BYTES,
    ParsedWebPage,
    WebPageParserService,
)


class FakeHeaders:
    def __init__(
        self,
        *,
        content_type="text/html",
        charset="utf-8",
        content_length=None,
    ):
        self.content_type = content_type
        self.charset = charset
        self.content_length = content_length

    def get_content_type(self):
        return self.content_type

    def get_content_charset(self):
        return self.charset

    def get(self, name):
        if name == "Content-Length":
            return self.content_length

        return None


class FakeResponse:
    def __init__(
        self,
        content: bytes,
        *,
        url="https://example.com/page",
        content_type="text/html",
        charset="utf-8",
        content_length=None,
    ):
        self._content = content
        self._url = url
        self.headers = FakeHeaders(
            content_type=content_type,
            charset=charset,
            content_length=content_length,
        )

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False

    def geturl(self):
        return self._url

    def read(self, size=-1):
        if size < 0:
            return self._content

        return self._content[:size]


def test_parse_html_extracts_visible_text_and_title(
    monkeypatch,
):
    service = WebPageParserService()

    monkeypatch.setattr(
        url_module.WebPageParserService,
        "_validate_hostname",
        staticmethod(lambda hostname: None),
    )

    result = service.parse_html(
        url="https://example.com/docs#fragment",
        html="""
            <html>
                <head>
                    <title>NOVA Guide</title>
                    <script>alert("ignore");</script>
                </head>
                <body>
                    <h1>NOVA</h1>
                    <p>Agentic assistant.</p>
                    <style>.secret { display: none; }</style>
                    <p>RAG knowledge.</p>
                </body>
            </html>
        """,
    )

    assert isinstance(
        result,
        ParsedWebPage,
    )
    assert result.url == (
        "https://example.com/docs"
    )
    assert result.title == "NOVA Guide"
    assert result.text == (
        "NOVA\n"
        "Agentic assistant.\n"
        "RAG knowledge."
    )


def test_parse_html_normalizes_whitespace(
    monkeypatch,
):
    monkeypatch.setattr(
        url_module.WebPageParserService,
        "_validate_hostname",
        staticmethod(lambda hostname: None),
    )

    result = WebPageParserService().parse_html(
        url="https://example.com",
        html="""
            <p>
                Hello
                <strong>world</strong>
            </p>
            <p> Second   paragraph </p>
        """,
    )

    assert result.text == (
        "Hello world\n"
        "Second paragraph"
    )


def test_parse_html_uses_url_when_title_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        url_module.WebPageParserService,
        "_validate_hostname",
        staticmethod(lambda hostname: None),
    )

    result = WebPageParserService().parse_html(
        url="https://example.com",
        html="<p>Visible content</p>",
    )

    assert result.title == "https://example.com"


def test_parse_html_rejects_empty_content(
    monkeypatch,
):
    monkeypatch.setattr(
        url_module.WebPageParserService,
        "_validate_hostname",
        staticmethod(lambda hostname: None),
    )

    with pytest.raises(
        ValueError,
        match="usable text",
    ):
        WebPageParserService().parse_html(
            url="https://example.com",
            html="<html><script>x</script></html>",
        )


def test_url_validation_accepts_http_and_https(
    monkeypatch,
):
    monkeypatch.setattr(
        url_module.WebPageParserService,
        "_validate_hostname",
        staticmethod(lambda hostname: None),
    )

    assert (
        WebPageParserService._validate_url(
            "HTTPS://Example.com/path#section"
        )
        == "https://Example.com/path"
    )


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://example.com/file",
        "example.com/page",
        "https://user:pass@example.com/page",
        "https:///missing-host",
    ],
)
def test_url_validation_rejects_invalid_urls(
    monkeypatch,
    url,
):
    monkeypatch.setattr(
        url_module.WebPageParserService,
        "_validate_hostname",
        staticmethod(lambda hostname: None),
    )

    with pytest.raises(ValueError):
        WebPageParserService._validate_url(
            url
        )


def test_url_validation_rejects_local_network_name():
    with pytest.raises(
        ValueError,
        match="local network name",
    ):
        WebPageParserService._validate_url(
            "http://localhost:8000/docs"
        )


def test_url_validation_rejects_restricted_ip(
    monkeypatch,
):
    monkeypatch.setattr(
        url_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                2,
                1,
                6,
                "",
                ("192.168.1.20", 0),
            )
        ],
    )

    with pytest.raises(
        ValueError,
        match="restricted network address",
    ):
        WebPageParserService._validate_url(
            "https://example.com"
        )


def test_fetch_parses_html_and_validates_response(
    monkeypatch,
):
    monkeypatch.setattr(
        url_module.WebPageParserService,
        "_validate_hostname",
        staticmethod(lambda hostname: None),
    )

    html = b"""
        <html>
            <head><title>Example</title></head>
            <body><p>Hello NOVA.</p></body>
        </html>
    """

    response = FakeResponse(
        html,
        url="https://example.com/final",
    )

    opener = Mock()
    opener.open.return_value = response

    monkeypatch.setattr(
        url_module,
        "build_opener",
        lambda handler: opener,
    )

    result = WebPageParserService().fetch(
        "https://example.com/start"
    )

    assert result.url == (
        "https://example.com/final"
    )
    assert result.title == "Example"
    assert result.text == "Hello NOVA."
    opener.open.assert_called_once()


def test_fetch_rejects_non_html_response(
    monkeypatch,
):
    monkeypatch.setattr(
        url_module.WebPageParserService,
        "_validate_hostname",
        staticmethod(lambda hostname: None),
    )

    response = FakeResponse(
        b"plain text",
        content_type="application/json",
    )

    opener = Mock()
    opener.open.return_value = response

    monkeypatch.setattr(
        url_module,
        "build_opener",
        lambda handler: opener,
    )

    with pytest.raises(
        ValueError,
        match="HTML document",
    ):
        WebPageParserService().fetch(
            "https://example.com/data"
        )


def test_fetch_rejects_oversized_response(
    monkeypatch,
):
    monkeypatch.setattr(
        url_module.WebPageParserService,
        "_validate_hostname",
        staticmethod(lambda hostname: None),
    )

    response = FakeResponse(
        b"x" * (MAX_RESPONSE_BYTES + 1)
    )

    opener = Mock()
    opener.open.return_value = response

    monkeypatch.setattr(
        url_module,
        "build_opener",
        lambda handler: opener,
    )

    with pytest.raises(
        ValueError,
        match="maximum response size",
    ):
        WebPageParserService().fetch(
            "https://example.com/large"
        )


def test_fetch_rejects_declared_oversized_response(
    monkeypatch,
):
    monkeypatch.setattr(
        url_module.WebPageParserService,
        "_validate_hostname",
        staticmethod(lambda hostname: None),
    )

    response = FakeResponse(
        b"small",
        content_length=str(
            MAX_RESPONSE_BYTES + 1
        ),
    )

    opener = Mock()
    opener.open.return_value = response

    monkeypatch.setattr(
        url_module,
        "build_opener",
        lambda handler: opener,
    )

    with pytest.raises(
        ValueError,
        match="maximum response size",
    ):
        WebPageParserService().fetch(
            "https://example.com/declared-large"
        )


def test_fetch_wraps_network_errors(
    monkeypatch,
):
    monkeypatch.setattr(
        url_module.WebPageParserService,
        "_validate_hostname",
        staticmethod(lambda hostname: None),
    )

    opener = Mock()
    opener.open.side_effect = URLError(
        "connection failed"
    )

    monkeypatch.setattr(
        url_module,
        "build_opener",
        lambda handler: opener,
    )

    with pytest.raises(
        ValueError,
        match="could not be fetched",
    ):
        WebPageParserService().fetch(
            "https://example.com"
        )
