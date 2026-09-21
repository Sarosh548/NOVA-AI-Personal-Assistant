from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.idempotency_record import (
    IdempotencyRecord,
)
from services.idempotency_service import (
    IdempotencyService,
)


def build_runtime():
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

    return db_engine


def teardown_runtime(
    db_engine,
):
    IdempotencyRecord.__table__.drop(
        bind=db_engine
    )
    db_engine.dispose()


def test_completed_idempotency_request_is_replayed():
    db_engine = build_runtime()

    try:
        service = IdempotencyService(
            db_engine=db_engine
        )

        request_hash = service.build_request_hash(
            {
                "message": "Hello",
                "conversation_id": 10,
            }
        )

        first = service.claim_or_replay(
            user_id="user-001",
            endpoint="/chat",
            idempotency_key="request-1",
            request_hash=request_hash,
        )

        assert first["status"] == "claimed"

        payload = {
            "response": "Hello back.",
            "conversation_id": 10,
        }

        assert service.complete(
            record_id=first["record_id"],
            claim_token=first["claim_token"],
            response_status=200,
            response_body=payload,
        )

        replay = service.claim_or_replay(
            user_id="user-001",
            endpoint="/chat",
            idempotency_key="request-1",
            request_hash=request_hash,
        )

        assert replay["status"] == "replay"
        assert replay["response_status"] == 200
        assert replay["response_body"] == payload

    finally:
        teardown_runtime(
            db_engine
        )


def test_idempotency_key_conflict_is_rejected():
    db_engine = build_runtime()

    try:
        service = IdempotencyService(
            db_engine=db_engine
        )

        first_hash = service.build_request_hash(
            {"message": "one"}
        )
        second_hash = service.build_request_hash(
            {"message": "two"}
        )

        first = service.claim_or_replay(
            user_id="user-001",
            endpoint="/chat",
            idempotency_key="request-2",
            request_hash=first_hash,
        )

        assert first["status"] == "claimed"

        conflict = service.claim_or_replay(
            user_id="user-001",
            endpoint="/chat",
            idempotency_key="request-2",
            request_hash=second_hash,
        )

        assert conflict["status"] == "conflict"

    finally:
        teardown_runtime(
            db_engine
        )


def test_active_idempotency_request_is_in_progress():
    db_engine = build_runtime()

    try:
        service = IdempotencyService(
            db_engine=db_engine
        )

        request_hash = service.build_request_hash(
            {"message": "active"}
        )

        first = service.claim_or_replay(
            user_id="user-001",
            endpoint="/chat",
            idempotency_key="request-3",
            request_hash=request_hash,
        )

        second = service.claim_or_replay(
            user_id="user-001",
            endpoint="/chat",
            idempotency_key="request-3",
            request_hash=request_hash,
        )

        assert first["status"] == "claimed"
        assert second["status"] == "in_progress"

    finally:
        teardown_runtime(
            db_engine
        )
