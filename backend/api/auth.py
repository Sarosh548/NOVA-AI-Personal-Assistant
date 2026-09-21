from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.security import (
    OAuth2PasswordBearer,
    OAuth2PasswordRequestFormStrict,
)

from config import (
    RateLimitSettings,
    get_rate_limit_settings,
)

from models.user import User
from models.user_session import UserSession
from services.audit_service import AuditService
from services.rate_limit_service import (
    RateLimitService,
)
from services.auth_service import (
    AuthService,
    RefreshTokenReplayDetected,
)
from services.token_service import TokenService
from services.user_service import UserService

from api.schemas.auth import (
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)


logger = logging.getLogger(__name__)

audit_service = AuditService()

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login",
    refreshUrl="/auth/refresh",
)


def get_auth_service() -> AuthService:
    return AuthService()


def get_token_service() -> TokenService:
    return TokenService()


def get_user_service() -> UserService:
    return UserService()

def get_rate_limit_service() -> RateLimitService:
    return RateLimitService()



def _set_rate_limit_headers(
    response: Response,
    decision,
) -> None:
    response.headers["RateLimit-Limit"] = str(
        decision.limit
    )
    response.headers["RateLimit-Remaining"] = str(
        decision.remaining
    )
    response.headers["RateLimit-Reset"] = str(
        decision.reset_after_seconds
    )


def _rate_limit_exception(
    decision,
) -> HTTPException:
    headers = {
        "RateLimit-Limit": str(
            decision.limit
        ),
        "RateLimit-Remaining": str(
            decision.remaining
        ),
        "RateLimit-Reset": str(
            decision.reset_after_seconds
        ),
        "Retry-After": str(
            decision.reset_after_seconds
        ),
    }

    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded. Try again later.",
        headers=headers,
    )


def enforce_auth_endpoint_rate_limit(
    request: Request,
    response: Response,
    rate_limit_service: Annotated[
        RateLimitService,
        Depends(get_rate_limit_service),
    ],
    rate_limit_settings: Annotated[
        RateLimitSettings,
        Depends(get_rate_limit_settings),
    ],
) -> None:
    if not rate_limit_settings.api_rate_limit_enabled:
        return

    client_host = (
        request.client.host
        if request.client is not None
        else "unknown"
    )

    decision = rate_limit_service.check_and_consume(
        principal_key=f"ip:{client_host}",
        scope=f"authentication:{request.url.path}",
        limit=(
            rate_limit_settings
            .api_auth_rate_limit_requests_per_window
        ),
        window_seconds=(
            rate_limit_settings
            .api_auth_rate_limit_window_seconds
        ),
    )

    _set_rate_limit_headers(
        response,
        decision,
    )

    if not decision.allowed:
        raise _rate_limit_exception(
            decision
        )


def _record_auth_audit(
    *,
    action: str,
    status_value: str,
    user_id: str | None = None,
    resource_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """
    Best-effort security audit recording.

    Authentication must remain available even if the audit
    subsystem is temporarily unavailable.
    """
    try:
        audit_service.record_event(
            event_type="authentication",
            action=action,
            status=status_value,
            user_id=user_id,
            resource_type="session",
            resource_id=resource_id,
            metadata=metadata,
        )
    except Exception:
        logger.exception(
            "Could not persist authentication audit event."
        )


def _utc_now_naive() -> datetime:
    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


def _unauthorized(
    detail: str = "Authentication required.",
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={
            "WWW-Authenticate": "Bearer",
        },
    )


@dataclass(frozen=True)
class AuthenticatedContext:
    user: User
    session: UserSession


def get_current_auth_context(
    token: Annotated[
        str,
        Depends(oauth2_scheme),
    ],
    token_service: Annotated[
        TokenService,
        Depends(get_token_service),
    ],
    auth_service: Annotated[
        AuthService,
        Depends(get_auth_service),
    ],
    user_service: Annotated[
        UserService,
        Depends(get_user_service),
    ],
    response: Response,
    rate_limit_service: Annotated[
        RateLimitService,
        Depends(get_rate_limit_service),
    ],
    rate_limit_settings: Annotated[
        RateLimitSettings,
        Depends(get_rate_limit_settings),
    ],
) -> AuthenticatedContext:
    """
    Resolve the authenticated NOVA user and active session from
    the Authorization: Bearer header.
    """
    try:
        claims = token_service.decode_access_token(
            token
        )
    except ValueError as exc:
        raise _unauthorized(
            "Invalid or expired access token."
        ) from exc

    user_id = claims.get("sub")
    session_id = claims.get("sid")

    if not isinstance(user_id, str):
        raise _unauthorized(
            "Access token has no valid user identity."
        )

    if not isinstance(session_id, str):
        raise _unauthorized(
            "Access token has no valid session identity."
        )

    user_session = auth_service.get_session(
        session_id
    )

    if user_session is None:
        raise _unauthorized(
            "Authentication session not found."
        )

    now = _utc_now_naive()

    if user_session.revoked_at is not None:
        raise _unauthorized(
            "Authentication session has been revoked."
        )

    if user_session.expires_at <= now:
        raise _unauthorized(
            "Authentication session has expired."
        )

    if user_session.user_id != user_id:
        raise _unauthorized(
            "Authentication session does not match the user."
        )

    user = user_service.get(
        user_id=user_id
    )

    if user is None:
        raise _unauthorized(
            "Authenticated user not found."
        )

    if not user.is_active:
        raise _unauthorized(
            "Authenticated user is inactive."
        )

    if rate_limit_settings.api_rate_limit_enabled:
        decision = rate_limit_service.check_and_consume(
            principal_key=f"user:{user.id}",
            scope="authenticated_api",
            limit=(
                rate_limit_settings
                .api_rate_limit_requests_per_window
            ),
            window_seconds=(
                rate_limit_settings
                .api_rate_limit_window_seconds
            ),
        )

        _set_rate_limit_headers(
            response,
            decision,
        )

        if not decision.allowed:
            raise _rate_limit_exception(
                decision
            )

    return AuthenticatedContext(
        user=user,
        session=user_session,
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(enforce_auth_endpoint_rate_limit)
    ],
)
def register(
    request: RegisterRequest,
    auth_service: Annotated[
        AuthService,
        Depends(get_auth_service),
    ],
    token_service: Annotated[
        TokenService,
        Depends(get_token_service),
    ],
) -> TokenResponse:
    """
    Register a local-password NOVA account and create its first
    authenticated session.
    """
    try:
        user, _identity = (
            auth_service.register_password_user(
                identifier=request.identifier,
                password=request.password,
                display_name=request.display_name,
            )
        )

        user_session, refresh_token = (
            auth_service.create_session(
                user.id,
            )
        )

    except ValueError as exc:
        _record_auth_audit(
            action="register",
            status_value="failure",
            metadata={
                "reason": "registration_failed"
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    _record_auth_audit(
        action="register",
        status_value="success",
        user_id=user.id,
        resource_id=user_session.id,
    )

    access_token = (
        token_service.create_access_token(
            user_id=user.id,
            session_id=user_session.id,
        )
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=(
            token_service.settings
            .auth_access_token_expire_minutes
            * 60
        ),
        session_id=user_session.id,
        user=UserResponse.model_validate(
            user
        ),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[
        Depends(enforce_auth_endpoint_rate_limit)
    ],
)
def login(
    form_data: Annotated[
        OAuth2PasswordRequestFormStrict,
        Depends(),
    ],
    auth_service: Annotated[
        AuthService,
        Depends(get_auth_service),
    ],
    token_service: Annotated[
        TokenService,
        Depends(get_token_service),
    ],
) -> TokenResponse:
    """
    Authenticate an existing local-password NOVA account.
    """
    try:
        user = (
            auth_service.authenticate_password(
                identifier=form_data.username,
                password=form_data.password,
            )
        )
    except ValueError as exc:
        _record_auth_audit(
            action="login",
            status_value="failure",
            metadata={
                "reason": "invalid_login_request"
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if user is None:
        _record_auth_audit(
            action="login",
            status_value="failure",
            metadata={
                "reason": "invalid_credentials"
            },
        )
        raise _unauthorized(
            "Incorrect username or password."
        )

    try:
        user_session, refresh_token = (
            auth_service.create_session(
                user.id,
            )
        )
    except ValueError as exc:
        _record_auth_audit(
            action="login",
            status_value="failure",
            user_id=user.id,
            metadata={
                "reason": "session_creation_failed"
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    _record_auth_audit(
        action="login",
        status_value="success",
        user_id=user.id,
        resource_id=user_session.id,
    )

    access_token = (
        token_service.create_access_token(
            user_id=user.id,
            session_id=user_session.id,
        )
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=(
            token_service.settings
            .auth_access_token_expire_minutes
            * 60
        ),
        session_id=user_session.id,
        user=UserResponse.model_validate(
            user
        ),
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[
        Depends(enforce_auth_endpoint_rate_limit)
    ],
)
def refresh(
    request: RefreshRequest,
    auth_service: Annotated[
        AuthService,
        Depends(get_auth_service),
    ],
    token_service: Annotated[
        TokenService,
        Depends(get_token_service),
    ],
    user_service: Annotated[
        UserService,
        Depends(get_user_service),
    ],
) -> TokenResponse:
    """
    Rotate an existing refresh token and issue a new access token.
    """
    try:
        user_session, refresh_token = (
            auth_service.rotate_session(
                request.refresh_token,
            )
        )
    except RefreshTokenReplayDetected as exc:
        _record_auth_audit(
            action="refresh",
            status_value="failure",
            user_id=exc.user_id,
            resource_id=exc.session_id,
            metadata={
                "reason": "refresh_token_replay"
            },
        )
        raise _unauthorized(
            "Invalid or expired refresh token."
        ) from exc
    except ValueError as exc:
        _record_auth_audit(
            action="refresh",
            status_value="failure",
            metadata={
                "reason": "invalid_or_expired_refresh_token"
            },
        )
        raise _unauthorized(
            str(exc)
        ) from exc

    try:
        user = user_service.get(
            user_id=user_session.user_id
        )
    except ValueError as exc:
        _record_auth_audit(
            action="refresh",
            status_value="failure",
            metadata={
                "reason": "user_lookup_failed"
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if user is None or not user.is_active:
        _record_auth_audit(
            action="refresh",
            status_value="failure",
            user_id=user_session.user_id,
            resource_id=user_session.id,
            metadata={
                "reason": "user_unavailable"
            },
        )
        raise _unauthorized(
            "Authenticated user is unavailable."
        )

    _record_auth_audit(
        action="refresh",
        status_value="success",
        user_id=user.id,
        resource_id=user_session.id,
    )

    access_token = (
        token_service.create_access_token(
            user_id=user.id,
            session_id=user_session.id,
        )
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=(
            token_service.settings
            .auth_access_token_expire_minutes
            * 60
        ),
        session_id=user_session.id,
        user=UserResponse.model_validate(
            user
        ),
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
def logout(
    context: Annotated[
        AuthenticatedContext,
        Depends(get_current_auth_context),
    ],
    auth_service: Annotated[
        AuthService,
        Depends(get_auth_service),
    ],
) -> Response:
    """
    Revoke the current authenticated session.
    """
    revoked = auth_service.revoke_session(
        context.session.id
    )

    if not revoked:
        _record_auth_audit(
            action="logout",
            status_value="failure",
            user_id=context.user.id,
            resource_id=context.session.id,
            metadata={
                "reason": "session_already_inactive"
            },
        )
        raise _unauthorized(
            "Authentication session is no longer active."
        )

    _record_auth_audit(
        action="logout",
        status_value="success",
        user_id=context.user.id,
        resource_id=context.session.id,
    )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )


@router.get(
    "/me",
    response_model=UserResponse,
)
def me(
    context: Annotated[
        AuthenticatedContext,
        Depends(get_current_auth_context),
    ],
) -> UserResponse:
    """
    Return the canonical NOVA user associated with the current
    authenticated session.
    """
    return UserResponse.model_validate(
        context.user
    )
