from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import main
from main import ChatRequest
from models.idempotency_record import IdempotencyRecord
from services.idempotency_service import IdempotencyService


def test_chat_replays_completed_idempotent_response(
    monkeypatch,
):
    db_engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    IdempotencyRecord.__table__.create(
        bind=db_engine
    )

    service = IdempotencyService(
        db_engine=db_engine
    )

    calls = []

    def fake_execute_chat(
        *,
        request,
        current_user_id,
    ):
        calls.append(
            (
                current_user_id,
                request.message,
            )
        )
        return {
            "response": "cached answer",
            "conversation_id": 7,
        }

    monkeypatch.setattr(
        main,
        "_execute_chat",
        fake_execute_chat,
    )
    monkeypatch.setattr(
        main,
        "idempotency_service",
        service,
    )

    request = ChatRequest(
        message="Hello NOVA",
        conversation_id=7,
    )

    first = main.chat(
        request,
        "user-001",
        "chat-key-1",
    )

    second = main.chat(
        request,
        "user-001",
        "chat-key-1",
    )

    try:
        assert first == second
        assert calls == [
            (
                "user-001",
                "Hello NOVA",
            )
        ]
    finally:
        IdempotencyRecord.__table__.drop(
            bind=db_engine
        )
        db_engine.dispose()


def test_chat_rejects_idempotency_key_reuse_for_different_request(
    monkeypatch,
):
    db_engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    IdempotencyRecord.__table__.create(
        bind=db_engine
    )

    service = IdempotencyService(
        db_engine=db_engine
    )

    monkeypatch.setattr(
        main,
        "_execute_chat",
        lambda **kwargs: {
            "response": "answer",
        },
    )
    monkeypatch.setattr(
        main,
        "idempotency_service",
        service,
    )

    main.chat(
        ChatRequest(
            message="one",
        ),
        "user-001",
        "chat-key-2",
    )

    try:
        response = None

        try:
            main.chat(
                ChatRequest(
                    message="two",
                ),
                "user-001",
                "chat-key-2",
            )
        except Exception as exc:
            response = exc

        assert response is not None
        assert getattr(
            response,
            "status_code",
            None,
        ) == 409

    finally:
        IdempotencyRecord.__table__.drop(
            bind=db_engine
        )
        db_engine.dispose()
