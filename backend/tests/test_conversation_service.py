from services.conversation_service import ConversationService


def test_get_context_history_limits_messages(
    monkeypatch,
):
    service = ConversationService()

    fake_history = [
        {
            "role": "user",
            "content": f"message-{index}",
        }
        for index in range(1, 21)
    ]

    monkeypatch.setattr(
        service,
        "get_history",
        lambda user_id, conversation_id, limit: fake_history,
    )

    result = service.get_context_history(
        user_id="user-001",
        conversation_id=33,
        max_messages=5,
        max_characters=12000,
    )

    assert len(result) == 5

    assert result[0]["content"] == "message-16"
    assert result[-1]["content"] == "message-20"


def test_get_context_history_preserves_chronological_order(
    monkeypatch,
):
    service = ConversationService()

    fake_history = [
        {
            "role": "user",
            "content": "first",
        },
        {
            "role": "assistant",
            "content": "second",
        },
        {
            "role": "user",
            "content": "third",
        },
        {
            "role": "assistant",
            "content": "fourth",
        },
    ]

    monkeypatch.setattr(
        service,
        "get_history",
        lambda user_id, conversation_id, limit: fake_history,
    )

    result = service.get_context_history(
        user_id="user-001",
        conversation_id=33,
        max_messages=4,
        max_characters=12000,
    )

    assert [
        message["content"]
        for message in result
    ] == [
        "first",
        "second",
        "third",
        "fourth",
    ]


def test_get_context_history_respects_character_limit(
    monkeypatch,
):
    service = ConversationService()

    fake_history = [
        {
            "role": "user",
            "content": "A" * 100,
        },
        {
            "role": "assistant",
            "content": "B" * 100,
        },
        {
            "role": "user",
            "content": "C" * 100,
        },
    ]

    monkeypatch.setattr(
        service,
        "get_history",
        lambda user_id, conversation_id, limit: fake_history,
    )

    result = service.get_context_history(
        user_id="user-001",
        conversation_id=33,
        max_messages=10,
        max_characters=220,
    )

    assert len(result) == 1
    assert result[0]["content"] == "CCCC" * 25


def test_get_context_history_rejects_invalid_message_limit():
    service = ConversationService()

    try:
        service.get_context_history(
            user_id="user-001",
            conversation_id=33,
            max_messages=0,
        )
        assert False
    except ValueError as exc:
        assert (
            str(exc)
            == "max_messages must be greater than 0"
        )


def test_get_context_history_rejects_invalid_character_limit():
    service = ConversationService()

    try:
        service.get_context_history(
            user_id="user-001",
            conversation_id=33,
            max_characters=0,
        )
        assert False
    except ValueError as exc:
        assert (
            str(exc)
            == "max_characters must be greater than 0"
        )