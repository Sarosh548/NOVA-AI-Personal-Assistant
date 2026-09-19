from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status

from api.auth import (
    AuthenticatedContext,
    get_current_auth_context,
)
from models.user import User


CurrentAuthContext = Annotated[
    AuthenticatedContext,
    Depends(get_current_auth_context),
]


def get_current_user(
    context: CurrentAuthContext,
) -> User:
    """
    Return the canonical NOVA User established by the
    authenticated session.
    """
    return context.user


CurrentUser = Annotated[
    User,
    Depends(get_current_user),
]


def get_current_user_id(
    context: CurrentAuthContext,
) -> str:
    """
    Return the canonical NOVA user ID established by the
    authenticated session.

    Callers must never supply or override this identity.
    """
    return context.user.id


CurrentUserId = Annotated[
    str,
    Depends(get_current_user_id),
]


def authorize_user_scope(
    requested_user_id: str,
    current_user_id: str,
) -> None:
    """
    Enforce ownership of a user-scoped resource.

    The authenticated identity is authoritative. A caller cannot
    access another user's resource simply by changing a path
    parameter or other user identifier.
    """
    if requested_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You cannot access another user's resources."
            ),
        )
