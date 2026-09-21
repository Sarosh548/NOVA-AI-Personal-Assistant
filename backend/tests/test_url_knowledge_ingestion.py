from __future__ import annotations

import pytest

from services.knowledge_service import KnowledgeService
from services.url_parser_service import ParsedWebPage


class FakeWebParser:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)

        if self.error is not None:
            raise self.error

        return self.result


def test_create_document_from_url_uses_parsed_page_metadata():
    parsed = ParsedWebPage(
        url="https://example.com/docs",
        title="NOVA Guide",
        text="NOVA is an AI assistant.",
        content_type="text/html",
    )
    parser = FakeWebParser(result=parsed)

    service = KnowledgeService.__new__(
        KnowledgeService
    )
    service.web_parser_service = parser

    calls = []

    def fake_create_document(**kwargs):
        calls.append(kwargs)
        return {
            "id": 7,
            "title": kwargs["title"],
            "source": kwargs["source"],
        }

    service.create_document = fake_create_document

    result = service.create_document_from_url(
        user_id="user-001",
        url="https://example.com/start",
    )

    assert parser.calls == [
        "https://example.com/start"
    ]
    assert calls == [
        {
            "user_id": "user-001",
            "title": "NOVA Guide",
            "content": "NOVA is an AI assistant.",
            "source": "https://example.com/docs",
        }
    ]
    assert result["title"] == "NOVA Guide"


def test_create_document_from_url_propagates_parser_error():
    parser = FakeWebParser(
        error=ValueError(
            "The URL could not be fetched."
        )
    )

    service = KnowledgeService.__new__(
        KnowledgeService
    )
    service.web_parser_service = parser

    def fail_create_document(**kwargs):
        raise AssertionError(
            "create_document should not run"
        )

    service.create_document = fail_create_document

    with pytest.raises(
        ValueError,
        match="could not be fetched",
    ):
        service.create_document_from_url(
            user_id="user-001",
            url="https://example.com",
        )


def test_knowledge_service_accepts_web_parser_dependency():
    parser = FakeWebParser()
    service = KnowledgeService(
        embedding_service=object(),
        web_parser_service=parser,
    )

    assert service.web_parser_service is parser
