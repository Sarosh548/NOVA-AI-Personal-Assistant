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
        lambda *handlers: opener,
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
        lambda *handlers: opener,
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
        lambda *handlers: opener,
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
        lambda *handlers: opener,
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
        lambda *handlers: opener,
    )

    with pytest.raises(
        ValueError,
        match="could not be fetched",
    ):
        WebPageParserService().fetch(
            "https://example.com"
        )


@pytest.mark.parametrize(
    "address",
    [
        "100.64.0.1",
        "100.127.255.254",
        "192.0.0.8",
        "198.18.0.1",
        "198.51.100.25",
        "203.0.113.9",
        "2001:db8::1",
        "64:ff9b::a00:1",
    ],
)
def test_url_validation_rejects_shared_and_special_use_addresses(address):
    with pytest.raises(ValueError, match="restricted network address"):
        WebPageParserService._validate_hostname(address)


def test_url_validation_rejects_dns_answer_if_any_resolved_ip_is_not_public(
    monkeypatch,
):
    answers = [
        (url_module.socket.AF_INET, url_module.socket.SOCK_STREAM,
         url_module.socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
        (url_module.socket.AF_INET, url_module.socket.SOCK_STREAM,
         url_module.socket.IPPROTO_TCP, "", ("100.64.0.7", 443)),
    ]
    monkeypatch.setattr(
        url_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: answers,
    )

    with pytest.raises(ValueError, match="restricted network address"):
        WebPageParserService._validate_hostname("public-looking.example")


def test_pinned_http_connection_uses_the_validated_numeric_sockaddr(monkeypatch):
    class FakeSocket:
        def __init__(self, family, socktype, proto):
            self.family = family
            self.socktype = socktype
            self.proto = proto
            self.connected_to = None
            self.options = []

        def settimeout(self, value):
            self.timeout = value

        def setsockopt(self, *values):
            self.options.append(values)

        def connect(self, sockaddr):
            self.connected_to = sockaddr

        def close(self):
            self.closed = True

    fake_socket = FakeSocket(
        url_module.socket.AF_INET,
        url_module.socket.SOCK_STREAM,
        url_module.socket.IPPROTO_TCP,
    )
    monkeypatch.setattr(
        url_module,
        "_resolve_public_addresses",
        lambda host, port: [
            (
                url_module.socket.AF_INET,
                url_module.socket.SOCK_STREAM,
                url_module.socket.IPPROTO_TCP,
                "",
                ("8.8.8.8", port),
            )
        ],
    )
    monkeypatch.setattr(
        url_module.socket,
        "socket",
        lambda family, socktype, proto: fake_socket,
    )

    connection = url_module._PinnedHTTPConnection(
        "public-looking.example",
        port=443,
        timeout=3,
    )
    connection.connect()

    assert fake_socket.connected_to == ("8.8.8.8", 443)
    assert connection.sock is fake_socket


def test_dns_rebinding_to_private_ip_is_blocked_at_connection_time(monkeypatch):
    answers = iter(
        [
            [
                (url_module.socket.AF_INET, url_module.socket.SOCK_STREAM,
                 url_module.socket.IPPROTO_TCP, "", ("8.8.8.8", 0)),
            ],
            [
                (url_module.socket.AF_INET, url_module.socket.SOCK_STREAM,
                 url_module.socket.IPPROTO_TCP, "", ("127.0.0.1", 80)),
            ],
        ]
    )
    monkeypatch.setattr(
        url_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: next(answers),
    )

    # The preflight lookup is public, but DNS changes before TCP connect.
    WebPageParserService._validate_hostname("rebinding.example")

    def unexpected_socket(*args, **kwargs):
        raise AssertionError("A socket must not be created for the private answer.")

    monkeypatch.setattr(url_module.socket, "socket", unexpected_socket)
    connection = url_module._PinnedHTTPConnection(
        "rebinding.example",
        port=80,
        timeout=3,
    )
    with pytest.raises(ValueError, match="restricted network address"):
        connection.connect()


def test_redirect_handler_rejects_private_destination_before_following(
    monkeypatch,
):
    monkeypatch.setattr(
        url_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                url_module.socket.AF_INET,
                url_module.socket.SOCK_STREAM,
                url_module.socket.IPPROTO_TCP,
                "",
                ("10.0.0.8", 80),
            )
        ],
    )

    handler = url_module._SafeRedirectHandler()
    request = url_module.Request("https://public.example/start")

    with pytest.raises(ValueError, match="restricted network address"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {"Location": "http://internal.example/"},
            "http://internal.example/",
        )



def test_fetch_opener_ignores_environment_proxies_and_uses_pinned_handlers(
    monkeypatch,
):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7777")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7777")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:7777")

    opener = WebPageParserService()._build_opener()

    # urllib omits ProxyHandler({}) from the final handler chain entirely.
    # Crucially, it also does not install the environment-derived default
    # ProxyHandler, so every request goes through our pinned TCP handlers.
    assert not any(
        isinstance(handler, url_module.ProxyHandler)
        for handler in opener.handlers
    )
    assert any(
        isinstance(handler, url_module._PinnedHTTPHandler)
        for handler in opener.handlers
    )
    assert any(
        isinstance(handler, url_module._PinnedHTTPSHandler)
        for handler in opener.handlers
    )
