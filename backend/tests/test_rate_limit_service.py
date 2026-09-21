from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.rate_limit_counter import RateLimitCounter
from services.rate_limit_service import RateLimitService


def build_runtime():
    db_engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    RateLimitCounter.__table__.create(
        bind=db_engine
    )

    return db_engine


def teardown_runtime(
    db_engine,
):
    RateLimitCounter.__table__.drop(
        bind=db_engine
    )
    db_engine.dispose()


def test_rate_limit_allows_requests_until_limit():
    db_engine = build_runtime()

    try:
        service = RateLimitService(
            db_engine=db_engine
        )

        first = service.check_and_consume(
            principal_key="user:user-001",
            scope="authenticated_api",
            limit=3,
            window_seconds=60,
        )

        second = service.check_and_consume(
            principal_key="user:user-001",
            scope="authenticated_api",
            limit=3,
            window_seconds=60,
        )

        third = service.check_and_consume(
            principal_key="user:user-001",
            scope="authenticated_api",
            limit=3,
            window_seconds=60,
        )

        assert first.allowed is True
        assert first.remaining == 2
        assert second.remaining == 1
        assert third.remaining == 0

    finally:
        teardown_runtime(
            db_engine
        )


def test_rate_limit_blocks_after_limit():
    db_engine = build_runtime()

    try:
        service = RateLimitService(
            db_engine=db_engine
        )

        service.check_and_consume(
            principal_key="user:user-001",
            scope="authenticated_api",
            limit=1,
            window_seconds=60,
        )

        blocked = service.check_and_consume(
            principal_key="user:user-001",
            scope="authenticated_api",
            limit=1,
            window_seconds=60,
        )

        assert blocked.allowed is False
        assert blocked.limit == 1
        assert blocked.remaining == 0
        assert blocked.reset_after_seconds >= 1

    finally:
        teardown_runtime(
            db_engine
        )


def test_rate_limit_resets_on_new_fixed_window():
    db_engine = build_runtime()

    try:
        service = RateLimitService(
            db_engine=db_engine
        )

        first_time = datetime(
            2026,
            9,
            21,
            12,
            0,
            10,
            tzinfo=timezone.utc,
        )

        second_time = datetime(
            2026,
            9,
            21,
            12,
            1,
            1,
            tzinfo=timezone.utc,
        )

        first = service.check_and_consume(
            principal_key="ip:127.0.0.1",
            scope="authentication:/auth/login",
            limit=1,
            window_seconds=60,
            now=first_time,
        )

        blocked = service.check_and_consume(
            principal_key="ip:127.0.0.1",
            scope="authentication:/auth/login",
            limit=1,
            window_seconds=60,
            now=first_time,
        )

        reset = service.check_and_consume(
            principal_key="ip:127.0.0.1",
            scope="authentication:/auth/login",
            limit=1,
            window_seconds=60,
            now=second_time,
        )

        assert first.allowed is True
        assert blocked.allowed is False
        assert reset.allowed is True
        assert reset.remaining == 0

    finally:
        teardown_runtime(
            db_engine
        )


@pytest.mark.parametrize(
    ("limit", "window_seconds"),
    [
        (0, 60),
        (1, 0),
    ],
)
def test_rate_limit_rejects_invalid_configuration(
    limit,
    window_seconds,
):
    db_engine = build_runtime()

    try:
        service = RateLimitService(
            db_engine=db_engine
        )

        with pytest.raises(
            ValueError
        ):
            service.check_and_consume(
                principal_key="user:user-001",
                scope="authenticated_api",
                limit=limit,
                window_seconds=window_seconds,
            )

    finally:
        teardown_runtime(
            db_engine
        )
