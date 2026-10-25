from __future__ import annotations

from types import SimpleNamespace

from services.llm_service import (
    MODEL_NAME,
    LLMService,
)


class FakeCompletions:
    def __init__(
        self,
        stream,
    ):
        self.stream = stream
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return iter(self.stream)

        raise AssertionError(
            "This fake only supports streaming completions."
        )


class FakeChat:
    def __init__(
        self,
        stream,
    ):
        self.completions = FakeCompletions(stream)


class FakeClient:
    def __init__(
        self,
        stream,
    ):
        self.chat = FakeChat(stream)


def _chunk(
    content=None,
):
    return SimpleNamespace(
        choices=(
            [
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=content
                    )
                )
            ]
            if content != "__no_choices__"
            else []
        )
    )


def test_generate_with_instructions_stream_yields_non_empty_deltas_in_order():
    client = FakeClient(
        [
            _chunk("Hello"),
            SimpleNamespace(
                choices=[]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=None
                    )
                ]
            ),
            _chunk(None),
            _chunk(" world"),
            _chunk("!"),
        ]
    )
    service = LLMService(
        client=client
    )

    chunks = list(
        service.generate_with_instructions_stream(
            instructions="Be concise.",
            user_input="Say hello.",
        )
    )

    assert chunks == [
        "Hello",
        " world",
        "!",
    ]

    call = client.chat.completions.calls[0]

    assert call["model"] == MODEL_NAME
    assert call["stream"] is True
    assert call["messages"] == [
        {
            "role": "system",
            "content": "Be concise.",
        },
        {
            "role": "user",
            "content": "Say hello.",
        },
    ]


def test_generate_with_instructions_stream_preserves_whitespace():
    client = FakeClient(
        [
            _chunk(" Hello "),
            _chunk("\nworld"),
        ]
    )
    service = LLMService(
        client=client
    )

    chunks = list(
        service.generate_with_instructions_stream(
            instructions="Preserve output.",
            user_input="Continue.",
        )
    )

    assert chunks == [
        " Hello ",
        "\nworld",
    ]


def test_generate_response_stream_uses_normal_nova_prompt():
    client = FakeClient(
        [
            _chunk("Hi"),
            _chunk(" there"),
        ]
    )
    service = LLMService(
        client=client
    )

    chunks = list(
        service.generate_response_stream(
            "Hello NOVA"
        )
    )

    assert chunks == [
        "Hi",
        " there",
    ]

    call = client.chat.completions.calls[0]

    assert call["model"] == MODEL_NAME
    assert call["stream"] is True

    messages = call["messages"]

    assert messages[0]["role"] == "system"
    assert "You are generating NOVA's conversational response." in (
        messages[0]["content"]
    )
    assert messages[1] == {
        "role": "user",
        "content": "Hello NOVA",
    }


def test_generate_response_stream_is_lazy():
    client = FakeClient(
        [
            _chunk("first"),
            _chunk("second"),
        ]
    )
    service = LLMService(
        client=client
    )

    stream = service.generate_response_stream(
        "Hello"
    )

    assert client.chat.completions.calls == []

    assert next(stream) == "first"
    assert len(client.chat.completions.calls) == 1


def test_generate_voice_response_stream_uses_realtime_settings():
    client = FakeClient(
        [
            _chunk("Hi"),
            _chunk(" there"),
        ]
    )
    service = LLMService(
        client=client
    )

    assert list(service.generate_voice_response_stream(
        message="Hello NOVA",
        history=[],
        memory_context="",
    )) == ["Hi", " there"]

    call = client.chat.completions.calls[0]
    assert call["stream"] is True
    assert call["max_completion_tokens"] == 512
    assert call["reasoning_effort"] == "low"
    instructions = call["messages"][0]["content"]
    assert "transcribed from live microphone speech" in instructions
    assert "Do not claim you cannot hear or receive the user's voice" in instructions
    assert "include_reasoning" not in call
