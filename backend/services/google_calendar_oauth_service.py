from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from secrets import token_urlsafe
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import Settings, get_settings
from database.connection import engine as default_engine
from models.calendar_connection import CalendarConnection
from models.oauth_state import OAuthState
from services.token_encryption_service import (
    TokenEncryptionService,
)


class GoogleCalendarOAuthService:
    """
    Manage Google Calendar OAuth authorization and token lifecycle.

    This service intentionally owns OAuth and credential persistence.
    Calendar API event operations will be layered on top later.

    Security properties:
    - OAuth state is random, user-bound, persisted, hashed, expiring,
      and atomically single-use.
    - Access/refresh tokens are encrypted at rest.
    - Raw token values are never returned by public service methods.
    - Server configuration supplies OAuth client credentials.
    """

    PROVIDER = "google"

    AUTHORIZATION_ENDPOINT = (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )

    TOKEN_ENDPOINT = (
        "https://oauth2.googleapis.com/token"
    )

    REVOCATION_ENDPOINT = (
        "https://oauth2.googleapis.com/revoke"
    )

    DEFAULT_SCOPES = (
        "https://www.googleapis.com/auth/calendar.events"
    )

    STATE_TTL_SECONDS = 600
    TOKEN_EXPIRY_SKEW_SECONDS = 60
    TOKEN_REFRESH_LEASE_SECONDS = 30
    TOKEN_REFRESH_POLL_SECONDS = 0.25
    TOKEN_REFRESH_WAIT_SECONDS = 12
    HTTP_TIMEOUT_SECONDS = 10

    def __init__(
        self,
        *,
        engine: Any | None = None,
        settings: Settings | None = None,
        encryption_service: TokenEncryptionService | None = None,
    ):
        self.engine = (
            engine
            if engine is not None
            else default_engine
        )

        self.settings = (
            settings
            if settings is not None
            else get_settings()
        )

        self.encryption_service = (
            encryption_service
            if encryption_service is not None
            else TokenEncryptionService(
                self.settings.integration_token_encryption_key
            )
        )

    # =====================================================
    # PUBLIC AUTHORIZATION FLOW
    # =====================================================

    def build_authorization_url(
        self,
        *,
        user_id: str,
    ) -> str:
        """
        Create a one-time OAuth state and return Google's
        authorization URL.
        """
        normalized_user_id = (
            self._validate_user_id(
                user_id
            )
        )

        self._validate_oauth_configuration()

        raw_state = token_urlsafe(32)
        state_hash = self._hash_state(
            raw_state
        )

        now = self._utc_now_naive()
        expires_at = (
            now
            + timedelta(
                seconds=self.STATE_TTL_SECONDS
            )
        )

        with Session(
            self.engine
        ) as session:
            state_record = OAuthState(
                user_id=normalized_user_id,
                provider=self.PROVIDER,
                state_hash=state_hash,
                expires_at=expires_at,
                used_at=None,
                created_at=now,
            )

            session.add(
                state_record
            )

            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError(
                    "Could not create OAuth state."
                ) from exc

        params = {
            "client_id": self.settings.calendar_google_client_id,
            "redirect_uri": self.settings.calendar_google_redirect_uri,
            "response_type": "code",
            "scope": self._get_scopes(),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "state": raw_state,
        }

        return (
            f"{self.AUTHORIZATION_ENDPOINT}?"
            f"{urlencode(params)}"
        )

    def complete_authorization(
        self,
        *,
        state: str,
        code: str,
    ) -> dict[str, Any]:
        """
        Atomically consume OAuth state, exchange the authorization
        code, and persist the encrypted Google credentials.
        """
        normalized_state = self._validate_state(
            state
        )

        normalized_code = self._validate_code(
            code
        )

        user_id = self._consume_state(
            normalized_state
        )

        token_payload = self._exchange_authorization_code(
            normalized_code
        )

        access_token = token_payload.get(
            "access_token"
        )

        if not isinstance(
            access_token,
            str,
        ) or not access_token:
            raise ValueError(
                "Google OAuth response did not contain an access token."
            )

        refresh_token = token_payload.get(
            "refresh_token"
        )

        if refresh_token is not None and (
            not isinstance(
                refresh_token,
                str,
            )
            or not refresh_token
        ):
            refresh_token = None

        expires_in = self._parse_expires_in(
            token_payload.get(
                "expires_in"
            )
        )

        token_expires_at = (
            self._utc_now_naive()
            + timedelta(
                seconds=expires_in
            )
            if expires_in is not None
            else None
        )

        scopes = self._validate_granted_scopes(
            token_payload.get(
                "scope"
            )
        )

        with Session(
            self.engine
        ) as session:
            connection = session.scalar(
                select(
                    CalendarConnection
                ).where(
                    CalendarConnection.user_id
                    == user_id,
                    CalendarConnection.provider
                    == self.PROVIDER,
                )
            )

            if (
                refresh_token is None
                and connection is None
            ):
                raise ValueError(
                    "Google OAuth response did not contain a refresh token."
                )

            encrypted_access_token = (
                self.encryption_service.encrypt(
                    access_token
                )
            )

            if refresh_token is not None:
                encrypted_refresh_token = (
                    self.encryption_service.encrypt(
                        refresh_token
                    )
                )
            else:
                encrypted_refresh_token = (
                    connection.encrypted_refresh_token
                )

            now = self._utc_now_naive()

            if connection is None:
                connection = CalendarConnection(
                    user_id=user_id,
                    provider=self.PROVIDER,
                    calendar_id="primary",
                    encrypted_access_token=(
                        encrypted_access_token
                    ),
                    encrypted_refresh_token=(
                        encrypted_refresh_token
                    ),
                    token_expires_at=(
                        token_expires_at
                    ),
                    scopes=scopes,
                    created_at=now,
                    updated_at=now,
                )

                session.add(
                    connection
                )

            else:
                connection.encrypted_access_token = (
                    encrypted_access_token
                )
                connection.encrypted_refresh_token = (
                    encrypted_refresh_token
                )
                connection.token_expires_at = (
                    token_expires_at
                )
                connection.token_refresh_claim_token = None
                connection.token_refresh_lease_until = None
                connection.scopes = scopes
                connection.updated_at = now

            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError(
                    "Could not persist Google Calendar connection."
                ) from exc

            session.refresh(
                connection
            )

            return self._connection_to_dict(
                connection
            )

    # =====================================================
    # CONNECTION STATUS / DISCONNECT
    # =====================================================

    def get_connection(
        self,
        *,
        user_id: str,
    ) -> dict[str, Any] | None:
        normalized_user_id = (
            self._validate_user_id(
                user_id
            )
        )

        with Session(
            self.engine
        ) as session:
            connection = session.scalar(
                select(
                    CalendarConnection
                ).where(
                    CalendarConnection.user_id
                    == normalized_user_id,
                    CalendarConnection.provider
                    == self.PROVIDER,
                )
            )

            if connection is None:
                return None

            return self._connection_to_dict(
                connection
            )

    def disconnect(
        self,
        *,
        user_id: str,
    ) -> bool:
        normalized_user_id = (
            self._validate_user_id(
                user_id
            )
        )

        with Session(
            self.engine
        ) as session:
            connection = session.scalar(
                select(
                    CalendarConnection
                ).where(
                    CalendarConnection.user_id
                    == normalized_user_id,
                    CalendarConnection.provider
                    == self.PROVIDER,
                )
            )

            if connection is None:
                return False

            refresh_token = (
                self.encryption_service.decrypt(
                    connection.encrypted_refresh_token
                )
            )

            self._revoke_token(
                refresh_token
            )

            session.delete(
                connection
            )
            session.commit()

            return True

    def _revoke_token(
        self,
        refresh_token: str,
    ) -> None:
        encoded_payload = urlencode(
            {
                "token": refresh_token,
            }
        ).encode("utf-8")

        request = Request(
            self.REVOCATION_ENDPOINT,
            data=encoded_payload,
            headers={
                "Content-Type": (
                    "application/x-www-form-urlencoded"
                ),
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self.HTTP_TIMEOUT_SECONDS,
            ) as response:
                if getattr(
                    response,
                    "status",
                    200,
                ) != 200:
                    raise ValueError(
                        "Google Calendar access revocation failed."
                    )

                response.read()

        except ValueError:
            raise
        except (
            HTTPError,
            URLError,
            OSError,
        ) as exc:
            raise ValueError(
                "Google Calendar access revocation failed."
            ) from exc

    # =====================================================
    # ACCESS TOKEN LIFECYCLE
    # =====================================================

    def get_valid_access_token(
        self,
        *,
        user_id: str,
    ) -> str:
        """
        Return a usable Google access token, refreshing it when
        the stored token is near expiry.

        Refresh ownership is coordinated through a short durable
        lease so concurrent API workers do not refresh the same
        Google connection at the same time.
        """
        normalized_user_id = (
            self._validate_user_id(
                user_id
            )
        )

        self._validate_oauth_configuration()

        deadline = (
            time.monotonic()
            + self.TOKEN_REFRESH_WAIT_SECONDS
        )

        while True:
            now = self._utc_now_naive()

            with Session(
                self.engine
            ) as session:
                connection = session.scalar(
                    select(
                        CalendarConnection
                    ).where(
                        CalendarConnection.user_id
                        == normalized_user_id,
                        CalendarConnection.provider
                        == self.PROVIDER,
                    )
                )

                if connection is None:
                    raise ValueError(
                        "Google Calendar is not connected."
                    )

                if (
                    connection.token_expires_at is not None
                    and connection.token_expires_at
                    > now
                    + timedelta(
                        seconds=self.TOKEN_EXPIRY_SKEW_SECONDS
                    )
                ):
                    return self.encryption_service.decrypt(
                        connection.encrypted_access_token
                    )

            claim = self._claim_token_refresh(
                user_id=normalized_user_id
            )

            if claim is None:
                if (
                    time.monotonic()
                    >= deadline
                ):
                    raise ValueError(
                        "Google access token refresh is already in progress."
                    )

                time.sleep(
                    self.TOKEN_REFRESH_POLL_SECONDS
                )
                continue

            claim_token = claim["claim_token"]
            refresh_token = claim["refresh_token"]

            try:
                token_payload = (
                    self._refresh_access_token(
                        refresh_token
                    )
                )

                access_token = token_payload.get(
                    "access_token"
                )

                if not isinstance(
                    access_token,
                    str,
                ) or not access_token:
                    raise ValueError(
                        "Google token refresh did not return an access token."
                    )

                expires_in = self._parse_expires_in(
                    token_payload.get(
                        "expires_in"
                    )
                )

                if expires_in is None:
                    raise ValueError(
                        "Google token refresh did not return token expiry."
                    )

                finalized = (
                    self._finalize_token_refresh(
                        user_id=normalized_user_id,
                        claim_token=claim_token,
                        access_token=access_token,
                        expires_at=(
                            self._utc_now_naive()
                            + timedelta(
                                seconds=expires_in
                            )
                        ),
                    )
                )

                if not finalized:
                    raise ValueError(
                        "Google token refresh lease was lost."
                    )

                return access_token

            except Exception:
                self._release_token_refresh(
                    user_id=normalized_user_id,
                    claim_token=claim_token,
                )
                raise

    # =====================================================
    # TOKEN REFRESH COORDINATION
    # =====================================================

    def _claim_token_refresh(
        self,
        *,
        user_id: str,
    ) -> dict[str, str] | None:
        now = self._utc_now_naive()
        claim_token = token_urlsafe(32)
        lease_until = (
            now
            + timedelta(
                seconds=self.TOKEN_REFRESH_LEASE_SECONDS
            )
        )

        with Session(
            self.engine
        ) as session:
            result = session.execute(
                update(
                    CalendarConnection
                )
                .where(
                    CalendarConnection.user_id
                    == user_id,
                    CalendarConnection.provider
                    == self.PROVIDER,
                    (
                        (
                            CalendarConnection.token_expires_at
                           .is_(None)
                        )
                        | (
                            CalendarConnection.token_expires_at
                            <= now
                            + timedelta(
                                seconds=self.TOKEN_EXPIRY_SKEW_SECONDS
                            )
                        )
                    ),
                    (
                        (
                            CalendarConnection.token_refresh_lease_until
                            .is_(None)
                        )
                        | (
                            CalendarConnection.token_refresh_lease_until
                            <= now
                        )
                    ),
                )
                .values(
                    token_refresh_claim_token=claim_token,
                    token_refresh_lease_until=lease_until,
                )
                .returning(
                    CalendarConnection.encrypted_refresh_token
                )
            )

            row = result.first()

            if row is None:
                session.rollback()
                return None

            session.commit()

            return {
                "claim_token": claim_token,
                "refresh_token": (
                    self.encryption_service.decrypt(
                        row[0]
                    )
                ),
            }

    def _finalize_token_refresh(
        self,
        *,
        user_id: str,
        claim_token: str,
        access_token: str,
        expires_at: datetime,
    ) -> bool:
        now = self._utc_now_naive()

        with Session(
            self.engine
        ) as session:
            result = session.execute(
                update(
                    CalendarConnection
                )
                .where(
                    CalendarConnection.user_id
                    == user_id,
                    CalendarConnection.provider
                    == self.PROVIDER,
                    CalendarConnection.token_refresh_claim_token
                    == claim_token,
                )
                .values(
                    encrypted_access_token=(
                        self.encryption_service.encrypt(
                            access_token
                        )
                    ),
                    token_expires_at=expires_at,
                    token_refresh_claim_token=None,
                    token_refresh_lease_until=None,
                    updated_at=now,
                )
            )

            if result.rowcount != 1:
                session.rollback()
                return False

            session.commit()
            return True

    def _release_token_refresh(
        self,
        *,
        user_id: str,
        claim_token: str,
    ) -> bool:
        with Session(
            self.engine
        ) as session:
            result = session.execute(
                update(
                    CalendarConnection
                )
                .where(
                    CalendarConnection.user_id
                    == user_id,
                    CalendarConnection.provider
                    == self.PROVIDER,
                    CalendarConnection.token_refresh_claim_token
                    == claim_token,
                )
                .values(
                    token_refresh_claim_token=None,
                    token_refresh_lease_until=None,
                )
            )

            if result.rowcount != 1:
                session.rollback()
                return False

            session.commit()
            return True

    # =====================================================
    # OAUTH STATE
    # =====================================================

    def _consume_state(
        self,
        state: str,
    ) -> str:
        state_hash = self._hash_state(
            state
        )

        now = self._utc_now_naive()

        with Session(
            self.engine
        ) as session:
            result = session.execute(
                update(
                    OAuthState
                )
                .where(
                    OAuthState.provider
                    == self.PROVIDER,
                    OAuthState.state_hash
                    == state_hash,
                    OAuthState.used_at.is_(None),
                    OAuthState.expires_at
                    > now,
                )
                .values(
                    used_at=now
                )
                .returning(
                    OAuthState.user_id
                )
            )

            row = result.first()

            if row is None:
                session.rollback()
                raise ValueError(
                    "Invalid or expired OAuth state."
                )

            session.commit()

            return row[0]

    # =====================================================
    # GOOGLE HTTP
    # =====================================================

    def _exchange_authorization_code(
        self,
        code: str,
    ) -> dict[str, Any]:
        payload = {
            "code": code,
            "client_id": self.settings.calendar_google_client_id,
            "client_secret": self.settings.calendar_google_client_secret,
            "redirect_uri": self.settings.calendar_google_redirect_uri,
            "grant_type": "authorization_code",
        }

        return self._post_form(
            endpoint=self.TOKEN_ENDPOINT,
            payload=payload,
            failure_message="Google authorization code exchange failed.",
        )

    def _refresh_access_token(
        self,
        refresh_token: str,
    ) -> dict[str, Any]:
        payload = {
            "client_id": self.settings.calendar_google_client_id,
            "client_secret": self.settings.calendar_google_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        return self._post_form(
            endpoint=self.TOKEN_ENDPOINT,
            payload=payload,
            failure_message="Google access token refresh failed.",
        )

    def _post_form(
        self,
        *,
        endpoint: str,
        payload: dict[str, Any],
        failure_message: str,
    ) -> dict[str, Any]:
        encoded_payload = urlencode(
            payload
        ).encode("utf-8")

        request = Request(
            endpoint,
            data=encoded_payload,
            headers={
                "Content-Type": (
                    "application/x-www-form-urlencoded"
                ),
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self.HTTP_TIMEOUT_SECONDS,
            ) as response:
                raw_body = response.read()

        except (
            HTTPError,
            URLError,
            OSError,
        ) as exc:
            raise ValueError(
                failure_message
            ) from exc

        try:
            body = json.loads(
                raw_body.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                failure_message
            ) from exc

        if not isinstance(
            body,
            dict,
        ):
            raise ValueError(
                failure_message
            )

        if body.get(
            "error"
        ):
            raise ValueError(
                failure_message
            )

        return body

    # =====================================================
    # VALIDATION / HELPERS
    # =====================================================

    def _validate_oauth_configuration(
        self,
    ) -> None:
        required = {
            "calendar_google_client_id": (
                self.settings.calendar_google_client_id
            ),
            "calendar_google_client_secret": (
                self.settings.calendar_google_client_secret
            ),
            "calendar_google_redirect_uri": (
                self.settings.calendar_google_redirect_uri
            ),
            "integration_token_encryption_key": (
                self.settings.integration_token_encryption_key
            ),
        }

        missing = [
            name
            for name, value in required.items()
            if not value
        ]

        if missing:
            raise ValueError(
                "Google Calendar OAuth is not configured: "
                + ", ".join(
                    missing
                )
                + "."
            )

    def _get_scopes(self) -> str:
        raw_scopes = str(
            self.settings.calendar_google_scopes
        ).strip()

        return (
            raw_scopes
            or self.DEFAULT_SCOPES
        )

    def _validate_granted_scopes(
        self,
        scope: Any,
    ) -> str:
        requested_scope = (
            self._normalize_scopes(
                self._get_scopes()
            )
        )

        requested_scopes = set(
            requested_scope.split()
        )

        if isinstance(
            scope,
            str,
        ) and scope.strip():
            granted_scope = self._normalize_scopes(
                scope
            )
        else:
            # OAuth permits omitting the scope response field
            # when the granted scope is identical to the
            # requested scope.
            granted_scope = requested_scope

        granted_scopes = set(
            granted_scope.split()
        )

        missing_scopes = sorted(
            requested_scopes
            - granted_scopes
        )

        if missing_scopes:
            raise ValueError(
                "Google OAuth response did not grant "
                "the required Calendar scope(s): "
                + ", ".join(
                    missing_scopes
                )
                + "."
            )

        return granted_scope

    @staticmethod
    def _normalize_scopes(
        scope: Any,
    ) -> str:
        if isinstance(
            scope,
            str,
        ):
            normalized = " ".join(
                item
                for item in scope.split()
                if item.strip()
            )

            return normalized

        return GoogleCalendarOAuthService.DEFAULT_SCOPES

    @staticmethod
    def _parse_expires_in(
        value: Any,
    ) -> int | None:
        try:
            normalized = int(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

        if normalized <= 0:
            return None

        return normalized

    @staticmethod
    def _hash_state(
        state: str,
    ) -> str:
        return hashlib.sha256(
            state.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _validate_user_id(
        user_id: str,
    ) -> str:
        normalized = str(
            user_id
        ).strip()

        if not normalized:
            raise ValueError(
                "user_id cannot be empty."
            )

        if len(normalized) > 100:
            raise ValueError(
                "user_id cannot exceed 100 characters."
            )

        return normalized

    @staticmethod
    def _validate_state(
        state: str,
    ) -> str:
        normalized = str(
            state
        ).strip()

        if not normalized:
            raise ValueError(
                "OAuth state cannot be empty."
            )

        if len(normalized) > 500:
            raise ValueError(
                "OAuth state is invalid."
            )

        return normalized

    @staticmethod
    def _validate_code(
        code: str,
    ) -> str:
        normalized = str(
            code
        ).strip()

        if not normalized:
            raise ValueError(
                "OAuth authorization code cannot be empty."
            )

        if len(normalized) > 5000:
            raise ValueError(
                "OAuth authorization code is invalid."
            )

        return normalized

    @staticmethod
    def _utc_now_naive() -> datetime:
        return datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    @staticmethod
    def _connection_to_dict(
        connection: CalendarConnection,
    ) -> dict[str, Any]:
        return {
            "id": connection.id,
            "user_id": connection.user_id,
            "provider": connection.provider,
            "calendar_id": connection.calendar_id,
            "scopes": connection.scopes,
            "token_expires_at": connection.token_expires_at,
            "created_at": connection.created_at,
            "updated_at": connection.updated_at,
        }
