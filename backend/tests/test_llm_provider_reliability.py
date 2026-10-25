from __future__ import annotations

from types import SimpleNamespace

import pytest

import services.llm_service as llm_module
from config import LLMSettings
from services.llm_service import (
    LLMService,
)


def test_llm_settings_have_bounded_production_defaults():
    settings = LLMSettings()

    assert settings.llm_request_timeout_seconds == 10.0
    assert settings.llm_max_retries == 0


def test_llm_settings_are_environment_driven(monkeypatch):
    monkeypatch.setenv(
        "LLM_REQUEST_TIMEOUT_SECONDS",
        "12.5",
    )
    monkeypatch.setenv(
        "LLM_MAX_RETRIES",
        "4",
    )

    settings = LLMSettings()

    assert settings.llm_request_timeout_seconds == 12.5
    assert settings.llm_max_retries == 4


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        (
            "llm_request_timeout_seconds",
            0,
        ),
        (
            "llm_request_timeout_seconds",
            121,
        ),
        (
            "llm_max_retries",
            -1,
        ),
        (
            "llm_max_retries",
            6,
        ),
    ],
)
def test_llm_settings_reject_invalid_bounds(
    field_name,
    value,
):
    with pytest.raises(ValueError):
        LLMSettings(
            **{
                field_name: value,
            }
        )


def test_llm_service_passes_timeout_and_retry_policy_to_provider(
    monkeypatch,
):
    captured = []

    def fake_openai(**kwargs):
        captured.append(dict(kwargs))
        return SimpleNamespace()

    monkeypatch.setattr(
        llm_module,
        "OpenAI",
        fake_openai,
    )
    monkeypatch.setenv(
        "GROQ_API_KEY",
        "test-key",
    )

    settings = LLMSettings(
        llm_request_timeout_seconds=15.0,
        llm_max_retries=3,
    )

    LLMService(
        settings=settings,
    )

    assert captured[0]["api_key"] == "test-key"
    assert (
        captured[0]["base_url"]
        == "https://api.groq.com/openai/v1"
    )
    assert captured[0]["timeout"] == 10.0
    assert captured[0]["max_retries"] == 0

    assert captured[1]["api_key"] == "test-key"
    assert (
        captured[1]["base_url"]
        == "https://api.groq.com/openai/v1"
    )
    assert captured[1]["timeout"] == 10.0
    assert captured[1]["max_retries"] == 0


def test_llm_service_supports_injected_client_without_provider_credentials():
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="hello",
                            )
                        )
                    ]
                )
            )
        )
    )

    service = LLMService(
        client=client,
    )

    assert service.generate_with_instructions(
        instructions="respond with text",
        user_input="hello",
    ) == "hello"


def test_provider_completion_fails_fast_when_another_request_is_in_flight(monkeypatch):
    service = LLMService(client=SimpleNamespace())
    monkeypatch.setattr(llm_module, "_provider_cooldown_until", 0.0)
    calls = {"count": 0}

    def fake_create(**kwargs):
        calls["count"] += 1
        return SimpleNamespace()

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    assert llm_module._PROVIDER_REQUEST_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(llm_module.LLMProviderCoolingDownError, match="busy"):
            service._provider_completion({"model": "test"}, client=client)
    finally:
        llm_module._PROVIDER_REQUEST_LOCK.release()

    assert calls["count"] == 0


def test_provider_completion_fails_fast_and_opens_provider_cooldown(monkeypatch):
    service = LLMService(client=SimpleNamespace())

    class FakeRateLimitError(Exception):
        def __init__(self):
            self.response = SimpleNamespace(headers={"retry-after": "2"})

    calls = {"count": 0}
    sleeps = []

    def fake_create(**kwargs):
        calls["count"] += 1
        raise FakeRateLimitError()

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    monkeypatch.setattr(llm_module, "RateLimitError", FakeRateLimitError)
    monkeypatch.setattr(llm_module, "_provider_cooldown_until", 0.0)
    monkeypatch.setattr(llm_module.time, "sleep", sleeps.append)

    with pytest.raises(FakeRateLimitError):
        service._provider_completion({"model": "test"}, client=client, max_attempts=3)

    assert calls["count"] == 1
    assert sleeps == []

    with pytest.raises(llm_module.LLMProviderCoolingDownError):
        service._provider_completion({"model": "test"}, client=client, max_attempts=3)

    assert calls["count"] == 1


@pytest.mark.parametrize(
    ("headers", "message", "expected_seconds"),
    [
        ({"retry-after": "1085.6"}, "rate limited", 1085.6),
        ({"retry-after": "2", "x-ratelimit-reset-tokens": "18m5.6s"}, "rate limited", 1085.6),
        ({"x-ratelimit-reset-tokens": "18m5.6s"}, "rate limited", 1085.6),
        ({}, "Rate limit reached. Please try again in 18m5.616s.", 1085.616),
    ],
)
def test_provider_cooldown_respects_long_daily_quota_reset_hints(
    monkeypatch,
    headers,
    message,
    expected_seconds,
):
    monkeypatch.setattr(llm_module, "_provider_cooldown_until", 0.0)
    monkeypatch.setattr(llm_module.time, "monotonic", lambda: 100.0)

    class FakeRateLimitError(Exception):
        def __init__(self, text, response_headers):
            super().__init__(text)
            self.response = SimpleNamespace(headers=response_headers)

    error = FakeRateLimitError(message, headers)
    llm_module.record_llm_rate_limit(error)

    assert llm_module._provider_cooldown_until == pytest.approx(
        100.0 + expected_seconds
    )
    assert llm_module.LLMService(client=SimpleNamespace())._retry_after_seconds(
        error
    ) == pytest.approx(expected_seconds)


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (413, True),
        (500, True),
        (400, False),
        (404, False),
    ],
)
def test_llm_provider_error_classifies_payload_budget_rejection(
    monkeypatch,
    status_code,
    expected,
):
    class FakeAPIStatusError(Exception):
        def __init__(self, code):
            self.status_code = code

    monkeypatch.setattr(
        llm_module,
        "APIStatusError",
        FakeAPIStatusError,
    )

    assert llm_module.is_llm_provider_error(
        FakeAPIStatusError(status_code)
    ) is expected


def test_prompt_budget_keeps_opening_and_latest_context(monkeypatch):
    monkeypatch.setattr(
        llm_module,
        "MAX_LLM_PROMPT_CHARACTERS",
        240,
    )
    instructions = "System instructions."
    user_input = "START " + ("old context " * 40) + "LATEST USER MESSAGE"

    bounded_instructions, bounded_input = llm_module._bound_prompt(
        instructions,
        user_input,
    )

    assert len(bounded_instructions) + len(bounded_input) <= 240
    assert bounded_instructions == instructions
    assert bounded_input.startswith("START")
    assert bounded_input.endswith("LATEST USER MESSAGE")
    assert "Middle context omitted" in bounded_input


def test_llm_completion_budget_is_capped_even_when_caller_requests_more(
    monkeypatch,
):
    service = LLMService(client=SimpleNamespace())
    captured = {}

    def fake_provider_completion(kwargs, **options):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="bounded response")
                )
            ]
        )

    monkeypatch.setattr(
        service,
        "_provider_completion",
        fake_provider_completion,
    )

    assert service._chat_completion(
        instructions="Be concise.",
        user_input="Hello.",
        max_completion_tokens=20_000,
    ) == "bounded response"
    assert (
        captured["max_completion_tokens"]
        == llm_module.DEFAULT_MAX_COMPLETION_TOKENS
    )


def test_empty_llm_completion_is_a_recoverable_provider_failure(monkeypatch):
    service = LLMService(client=SimpleNamespace())

    def fake_provider_completion(*args, **kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="   ")
                )
            ]
        )

    monkeypatch.setattr(
        service,
        "_provider_completion",
        fake_provider_completion,
    )

    with pytest.raises(llm_module.LLMEmptyResponseError) as exc_info:
        service._chat_completion(
            instructions="Be concise.",
            user_input="Return a short reply.",
        )

    assert llm_module.is_llm_provider_error(exc_info.value)
