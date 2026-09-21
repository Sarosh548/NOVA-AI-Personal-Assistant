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

    assert settings.llm_request_timeout_seconds == 20.0
    assert settings.llm_max_retries == 2


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
    captured = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
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

    assert captured["api_key"] == "test-key"
    assert (
        captured["base_url"]
        == "https://api.groq.com/openai/v1"
    )
    assert captured["timeout"] == 15.0
    assert captured["max_retries"] == 3


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
