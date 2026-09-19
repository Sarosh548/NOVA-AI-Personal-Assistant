from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from fastapi import status

from api.auth import AuthenticatedContext
from api.dependencies import (
    authorize_user_scope,
    get_current_user,
    get_current_user_id,
)
from models.user import User
from models.user_session import UserSession


def _user(
    user_id: str = "user-123",
) -> User:
    now = datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )

    return User(
        id=user_id,
        display_name="Authorization Test User",
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _session(
    user_id: str = "user-123",
) -> UserSession:
    now = datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )

    return UserSession(
        id="session-123",
        user_id=user_id,
        refresh_token_hash="a" * 64,
        expires_at=(
            now.replace(
                year=now.year + 1
            )
        ),
        last_used_at=now,
        revoked_at=None,
        created_at=now,
        updated_at=now,
    )


def test_get_current_user_returns_authenticated_user():
    user = _user()

    context = AuthenticatedContext(
        user=user,
        session=_session(user.id),
    )

    result = get_current_user(
        context
    )

    assert result is user
    assert result.id == "user-123"


def test_get_current_user_id_returns_canonical_identity():
    user = _user(
        "canonical-user-456"
    )

    context = AuthenticatedContext(
        user=user,
        session=_session(user.id),
    )

    result = get_current_user_id(
        context
    )

    assert result == "canonical-user-456"


def test_user_id_is_derived_from_authenticated_user():
    user = _user(
        "authenticated-user"
    )

    context = AuthenticatedContext(
        user=user,
        session=_session(
            user.id
        ),
    )

    assert (
        get_current_user_id(context)
        == context.user.id
    )


def test_session_identity_matches_authenticated_user():
    user = _user(
        "user-789"
    )

    context = AuthenticatedContext(
        user=user,
        session=_session(
            "user-789"
        ),
    )

    assert (
        context.session.user_id
        == context.user.id
    )


def test_mismatched_context_is_not_silently_rewritten():
    user = _user(
        "real-user"
    )

    context = AuthenticatedContext(
        user=user,
        session=_session(
            "different-user"
        ),
    )

    assert get_current_user_id(
        context
    ) == "real-user"


def test_current_user_dependency_has_expected_annotation():
    annotation = get_current_user.__annotations__["context"]

    assert annotation is not None


def test_current_user_id_dependency_has_expected_annotation():
    annotation = get_current_user_id.__annotations__["context"]

    assert annotation is not None


def test_authorize_user_scope_allows_same_user():
    result = authorize_user_scope(
        requested_user_id="user-123",
        current_user_id="user-123",
    )

    assert result is None


def test_authorize_user_scope_rejects_different_user():
    try:
        authorize_user_scope(
            requested_user_id="user-456",
            current_user_id="user-123",
        )
    except HTTPException as exc:
        assert exc.status_code == (
            status.HTTP_403_FORBIDDEN
        )
        assert exc.detail == (
            "You cannot access another user's resources."
        )
    else:
        raise AssertionError(
            "Expected HTTPException."
        )
