from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.user import User
from services.user_service import UserService


def _build_service():
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

    return (
        UserService(
            engine=engine
        ),
        engine,
    )


def test_create_generates_user_id():
    service, engine = _build_service()

    try:
        user = service.create(
            display_name="Sarosh"
        )

        assert user.id
        UUID(user.id)

        assert user.display_name == "Sarosh"
        assert user.is_active is True
    finally:
        engine.dispose()


def test_create_accepts_existing_nova_user_id():
    service, engine = _build_service()

    try:
        user = service.create(
            user_id="user-001",
            display_name="NOVA User",
        )

        assert user.id == "user-001"
        assert user.display_name == "NOVA User"
        assert user.is_active is True
    finally:
        engine.dispose()


def test_get_returns_none_for_unknown_user():
    service, engine = _build_service()

    try:
        assert (
            service.get(
                user_id="unknown-user"
            )
            is None
        )
    finally:
        engine.dispose()


def test_get_or_create_does_not_overwrite_existing_user():
    service, engine = _build_service()

    try:
        first = service.get_or_create(
            user_id="user-001",
            display_name="Original",
        )

        second = service.get_or_create(
            user_id="user-001",
            display_name="Replacement",
        )

        assert first.id == second.id
        assert second.display_name == "Original"
        assert second.is_active is True
    finally:
        engine.dispose()


def test_update_persists_display_name():
    service, engine = _build_service()

    try:
        service.create(
            user_id="user-001"
        )

        updated = service.update(
            user_id="user-001",
            display_name="Updated User",
        )

        assert updated.display_name == (
            "Updated User"
        )

        loaded = service.get(
            user_id="user-001"
        )

        assert loaded is not None
        assert loaded.display_name == (
            "Updated User"
        )
    finally:
        engine.dispose()


def test_deactivate_and_activate_user():
    service, engine = _build_service()

    try:
        service.create(
            user_id="user-001"
        )

        deactivated = service.deactivate(
            user_id="user-001"
        )

        assert deactivated.is_active is False

        activated = service.activate(
            user_id="user-001"
        )

        assert activated.is_active is True
    finally:
        engine.dispose()


def test_duplicate_user_id_is_rejected():
    service, engine = _build_service()

    try:
        service.create(
            user_id="user-001"
        )

        try:
            service.create(
                user_id="user-001"
            )
        except ValueError as exc:
            assert str(exc) == (
                "User already exists: user-001"
            )
        else:
            raise AssertionError(
                "Expected duplicate user creation to fail."
            )
    finally:
        engine.dispose()


def test_invalid_user_id_is_rejected():
    service, engine = _build_service()

    try:
        try:
            service.get(
                user_id="   "
            )
        except ValueError as exc:
            assert str(exc) == (
                "user_id cannot be empty."
            )
        else:
            raise AssertionError(
                "Expected empty user_id to fail."
            )
    finally:
        engine.dispose()


def test_overlong_display_name_is_rejected():
    service, engine = _build_service()

    try:
        try:
            service.create(
                display_name="x" * 201
            )
        except ValueError as exc:
            assert str(exc) == (
                "display_name cannot exceed 200 characters."
            )
        else:
            raise AssertionError(
                "Expected overlong display name to fail."
            )
    finally:
        engine.dispose()
