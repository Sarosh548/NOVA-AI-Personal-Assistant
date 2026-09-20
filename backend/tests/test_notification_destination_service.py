from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.notification_destination import (
    NotificationDestination,
)
from models.user import User
from services.notification_destination_service import (
    NotificationDestinationService,
)


def build_runtime():
    engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    User.__table__.create(
        bind=engine
    )

    NotificationDestination.__table__.create(
        bind=engine
    )

    return (
        engine,
        NotificationDestinationService(
            engine=engine
        ),
    )


def teardown_runtime(
    engine,
):
    NotificationDestination.__table__.drop(
        bind=engine
    )

    User.__table__.drop(
        bind=engine
    )

    engine.dispose()


def test_first_destination_becomes_default():
    engine, service = build_runtime()

    try:
        result = service.create_destination(
            user_id="user-001",
            channel="email",
            destination="sarosh@example.com",
        )

        assert result["is_default"] is True
        assert result["is_enabled"] is True
        assert result["channel"] == "email"

    finally:
        teardown_runtime(
            engine
        )


def test_second_destination_is_not_default_unless_requested():
    engine, service = build_runtime()

    try:
        first = service.create_destination(
            user_id="user-001",
            channel="email",
            destination="first@example.com",
        )

        second = service.create_destination(
            user_id="user-001",
            channel="email",
            destination="second@example.com",
        )

        assert first["is_default"] is True
        assert second["is_default"] is False

    finally:
        teardown_runtime(
            engine
        )


def test_explicit_default_replaces_previous_default():
    engine, service = build_runtime()

    try:
        first = service.create_destination(
            user_id="user-001",
            channel="email",
            destination="first@example.com",
        )

        second = service.create_destination(
            user_id="user-001",
            channel="email",
            destination="second@example.com",
            is_default=True,
        )

        assert first["is_default"] is True
        assert second["is_default"] is True

        destinations = service.list_destinations(
            user_id="user-001"
        )

        defaults = [
            item
            for item in destinations
            if item["is_default"]
        ]

        assert len(defaults) == 1
        assert defaults[0]["id"] == second["id"]

    finally:
        teardown_runtime(
            engine
        )


def test_get_default_returns_current_enabled_default():
    engine, service = build_runtime()

    try:
        created = service.create_destination(
            user_id="user-001",
            channel="email",
            destination="default@example.com",
        )

        default = service.get_default_destination(
            user_id="user-001",
            channel="email",
        )

        assert default is not None
        assert default["id"] == created["id"]

    finally:
        teardown_runtime(
            engine
        )


def test_set_default_switches_destinations():
    engine, service = build_runtime()

    try:
        first = service.create_destination(
            user_id="user-001",
            channel="email",
            destination="first@example.com",
        )

        second = service.create_destination(
            user_id="user-001",
            channel="email",
            destination="second@example.com",
        )

        updated = service.set_default_destination(
            user_id="user-001",
            destination_id=second["id"],
        )

        assert updated is not None
        assert updated["id"] == second["id"]
        assert updated["is_default"] is True

        current = service.get_default_destination(
            user_id="user-001",
            channel="email",
        )

        assert current is not None
        assert current["id"] == second["id"]

        assert first["id"] != current["id"]

    finally:
        teardown_runtime(
            engine
        )


def test_delete_default_promotes_next_destination():
    engine, service = build_runtime()

    try:
        first = service.create_destination(
            user_id="user-001",
            channel="email",
            destination="first@example.com",
        )

        second = service.create_destination(
            user_id="user-001",
            channel="email",
            destination="second@example.com",
        )

        assert service.delete_destination(
            user_id="user-001",
            destination_id=first["id"],
        )

        default = service.get_default_destination(
            user_id="user-001",
            channel="email",
        )

        assert default is not None
        assert default["id"] == second["id"]
        assert default["is_default"] is True

    finally:
        teardown_runtime(
            engine
        )


def test_duplicate_destination_is_rejected():
    engine, service = build_runtime()

    try:
        service.create_destination(
            user_id="user-001",
            channel="email",
            destination="same@example.com",
        )

        try:
            service.create_destination(
                user_id="user-001",
                channel="email",
                destination="same@example.com",
            )
        except ValueError as exc:
            assert str(exc) == (
                "This notification destination already exists."
            )
        else:
            raise AssertionError(
                "Expected duplicate destination to be rejected."
            )

    finally:
        teardown_runtime(
            engine
        )


def test_unsupported_channel_is_rejected():
    engine, service = build_runtime()

    try:
        try:
            service.create_destination(
                user_id="user-001",
                channel="webhook",
                destination="https://example.com",
            )
        except ValueError as exc:
            assert "Unsupported notification destination channel" in str(
                exc
            )
        else:
            raise AssertionError(
                "Expected unsupported channel to be rejected."
            )

    finally:
        teardown_runtime(
            engine
        )


def test_invalid_email_destination_is_rejected():
    engine, service = build_runtime()

    try:
        try:
            service.create_destination(
                user_id="user-001",
                channel="email",
                destination="not-an-email",
            )
        except ValueError as exc:
            assert (
                str(exc)
                == "Invalid email notification destination."
            )
        else:
            raise AssertionError(
                "Expected invalid email to be rejected."
            )

    finally:
        teardown_runtime(
            engine
        )