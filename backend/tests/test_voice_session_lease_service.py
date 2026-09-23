from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.voice_session_lease import VoiceSessionLease
from services.voice_session_lease_service import (
    VoiceSessionLeaseService,
)


def build_runtime(
    *,
    lease_seconds=60,
):
    db_engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    VoiceSessionLease.__table__.create(
        bind=db_engine
    )

    return (
        db_engine,
        VoiceSessionLeaseService(
            db_engine=db_engine,
            lease_seconds=lease_seconds,
        ),
    )


def teardown_runtime(
    db_engine,
):
    VoiceSessionLease.__table__.drop(
        bind=db_engine
    )
    db_engine.dispose()


def test_voice_session_lease_allows_one_active_session_per_user():
    db_engine, service = build_runtime()

    try:
        now = datetime(
            2026,
            9,
            23,
            6,
            0,
            tzinfo=timezone.utc,
        )

        first = service.acquire(
            user_id="user-001",
            session_id="session-1",
            now=now,
        )

        second = service.acquire(
            user_id="user-001",
            session_id="session-2",
            now=now + timedelta(seconds=5),
        )

        assert first.acquired is True
        assert first.lease_until == datetime(
            2026,
            9,
            23,
            6,
            1,
        )
        assert second.acquired is False
        assert second.retry_after_seconds == 55

    finally:
        teardown_runtime(
            db_engine
        )


def test_voice_session_lease_can_be_reclaimed_after_expiry():
    db_engine, service = build_runtime(
        lease_seconds=30
    )

    try:
        start = datetime(
            2026,
            9,
            23,
            6,
            0,
            tzinfo=timezone.utc,
        )

        first = service.acquire(
            user_id="user-001",
            session_id="session-1",
            now=start,
        )

        reclaimed = service.acquire(
            user_id="user-001",
            session_id="session-2",
            now=start + timedelta(seconds=30),
        )

        assert first.acquired is True
        assert reclaimed.acquired is True
        assert reclaimed.lease_until == datetime(
            2026,
            9,
            23,
            6,
            0,
            30,
        ) + timedelta(seconds=30)

        assert service.release(
            user_id="user-001",
            session_id="session-1",
        ) is False

        assert service.release(
            user_id="user-001",
            session_id="session-2",
        ) is True

    finally:
        teardown_runtime(
            db_engine
        )


def test_voice_session_lease_heartbeat_requires_current_unexpired_owner():
    db_engine, service = build_runtime(
        lease_seconds=60
    )

    try:
        start = datetime(
            2026,
            9,
            23,
            6,
            0,
            tzinfo=timezone.utc,
        )

        service.acquire(
            user_id="user-001",
            session_id="session-1",
            now=start,
        )

        assert service.heartbeat(
            user_id="user-001",
            session_id="wrong-session",
            now=start + timedelta(seconds=10),
        ) is False

        assert service.heartbeat(
            user_id="user-001",
            session_id="session-1",
            now=start + timedelta(seconds=10),
        ) is True

        assert service.heartbeat(
            user_id="user-001",
            session_id="session-1",
            now=start + timedelta(seconds=71),
        ) is False

    finally:
        teardown_runtime(
            db_engine
        )


@pytest.mark.parametrize(
    "lease_seconds",
    [0, -1],
)
def test_voice_session_lease_rejects_invalid_duration(
    lease_seconds,
):
    db_engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    VoiceSessionLease.__table__.create(
        bind=db_engine
    )

    try:
        with pytest.raises(ValueError):
            VoiceSessionLeaseService(
                db_engine=db_engine,
                lease_seconds=lease_seconds,
            )
    finally:
        teardown_runtime(
            db_engine
        )
