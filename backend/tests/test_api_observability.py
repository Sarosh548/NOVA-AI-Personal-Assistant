from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

import main
from config import ObservabilitySettings
from services.api_observability import (
    JsonLogFormatter,
    configure_api_logging,
    log_api_request,
    log_voice_event,
)


def test_json_log_formatter_emits_structured_context():
    formatter = JsonLogFormatter()

    record = logging.LogRecord(
        name="nova.api",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="API request completed",
        args=(),
        exc_info=None,
    )

    record.nova_context = {
        "request_id": "req-123",
        "method": "GET",
        "route": "/health/live",
        "status_code": 200,
        "duration_ms": 1.25,
    }

    payload = json.loads(
        formatter.format(record)
    )

    assert payload["level"] == "INFO"
    assert payload["logger"] == "nova.api"
    assert payload["message"] == (
        "API request completed"
    )
    assert payload["request_id"] == "req-123"
    assert payload["route"] == "/health/live"
    assert payload["status_code"] == 200


def test_api_logging_configuration_is_idempotent():
    configure_api_logging(
        ObservabilitySettings(
            api_log_level="INFO",
            api_log_format="json",
        )
    )

    root_logger = logging.getLogger()
    marked_handlers = [
        handler
        for handler in root_logger.handlers
        if getattr(
            handler,
            "_nova_api_handler",
            False,
        )
    ]

    assert len(marked_handlers) == 1


def test_api_request_log_contains_safe_metadata(
    caplog,
):
    with caplog.at_level(
        logging.INFO,
        logger="nova.api",
    ):
        log_api_request(
            request_id="req-safe",
            method="GET",
            route="/users/{user_id}",
            status_code=200,
            duration_ms=4.5,
        )

    record = next(
        item
        for item in caplog.records
        if item.name == "nova.api"
        and item.getMessage()
        == "API request completed"
    )

    assert record.nova_context == {
        "request_id": "req-safe",
        "method": "GET",
        "route": "/users/{user_id}",
        "status_code": 200,
        "duration_ms": 4.5,
    }


def test_main_request_middleware_emits_request_id_and_request_log(
    caplog,
):
    client = TestClient(
        main.app
    )

    with caplog.at_level(
        logging.INFO,
        logger="nova.api",
    ):
        response = client.get(
            "/health/live",
            headers={
                "X-Request-ID": "observability-test"
            },
        )

    assert response.status_code == 200
    assert (
        response.headers["X-Request-ID"]
        == "observability-test"
    )

    matching = [
        record
        for record in caplog.records
        if record.name == "nova.api"
        and record.getMessage()
        == "API request completed"
    ]

    assert matching

    context = matching[-1].nova_context

    assert context["request_id"] == (
        "observability-test"
    )
    assert context["method"] == "GET"
    assert context["route"] == "/health/live"
    assert context["status_code"] == 200
    assert context["duration_ms"] >= 0


def test_observability_settings_are_environment_driven(
    monkeypatch,
):
    monkeypatch.setenv(
        "API_LOG_LEVEL",
        "DEBUG",
    )
    monkeypatch.setenv(
        "API_LOG_FORMAT",
        "text",
    )

    settings = ObservabilitySettings()

    assert settings.api_log_level == "DEBUG"
    assert settings.api_log_format == "text"


def test_voice_lifecycle_log_contains_only_safe_operational_metadata(
    caplog,
):
    with caplog.at_level(
        logging.INFO,
        logger="nova.voice",
    ):
        log_voice_event(
            event="assistant_response_completed",
            session_id="session-safe",
            turn_id="turn-safe",
            provider="elevenlabs",
            code="ok",
            recoverable=False,
            duration_ms=-3.25,
        )

    record = next(
        item
        for item in caplog.records
        if item.name == "nova.voice"
        and item.getMessage()
        == "Voice lifecycle event"
    )

    assert record.nova_context == {
        "event": "assistant_response_completed",
        "session_id": "session-safe",
        "turn_id": "turn-safe",
        "provider": "elevenlabs",
        "code": "ok",
        "recoverable": False,
        "duration_ms": 0.0,
    }
    assert "user_id" not in record.nova_context
    assert "transcript" not in record.nova_context
    assert "access_token" not in record.nova_context
