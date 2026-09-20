from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from models.calendar_connection import (
    CalendarConnection,
)
from models.oauth_state import OAuthState
from models.user import User
from services.google_calendar_oauth_service import (
    GoogleCalendarOAuthService,
)
from services.token_encryption_service import (
    TokenEncryptionService,
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

    CalendarConnection.__table__.create(
        bind=engine
    )

    OAuthState.__table__.create(
        bind=engine
    )

    engine.connect().execute(
        User.__table__.insert().values(
            id="user-001",
            display_name="Test User",
            is_active=True,
            created_at=datetime(
                2026,
                9,
                20,
                0,
                0,
            ),
            updated_at=datetime(
                2026,
                9,
                20,
                0,
                0,
            ),
        )
    )

    return engine


def teardown_runtime(
    engine,
):
    OAuthState.__table__.drop(
        bind=engine
    )

    CalendarConnection.__table__.drop(
        bind=engine
    )

    User.__table__.drop(
        bind=engine
    )

    engine.dispose()


def build_service(
    engine,
):
    from config import Settings

    settings = Settings(
        auth_jwt_secret_key=(
            "a" * 32
        ),
        calendar_google_client_id=(
            "google-client-id"
        ),
        calendar_google_client_secret=(
            "google-client-secret"
        ),
        calendar_google_redirect_uri=(
            "http://localhost:8000/integrations/google/calendar/callback"
        ),
        calendar_google_scopes=(
            "https://www.googleapis.com/auth/calendar.events"
        ),
        integration_token_encryption_key=(
            Fernet.generate_key().decode(
                "utf-8"
            )
        ),
    )

    return GoogleCalendarOAuthService(
        engine=engine,
        settings=settings,
        encryption_service=(
            TokenEncryptionService(
                settings.integration_token_encryption_key
            )
        ),
    )


def create_state(
    service,
    *,
    user_id="user-001",
    expires_delta_seconds=600,
):
    url = service.build_authorization_url(
        user_id=user_id
    )

    state = parse_qs(
        urlparse(url).query
    )["state"][0]

    if expires_delta_seconds != 600:
        from sqlalchemy.orm import Session
        from sqlalchemy import update

        now = service._utc_now_naive()

        with Session(
            service.engine
        ) as session:
            session.execute(
                update(
                    OAuthState
                )
                .where(
                    OAuthState.user_id
                    == user_id
                )
                .values(
                    expires_at=(
                        now
                        + timedelta(
                            seconds=expires_delta_seconds
                        )
                    )
                )
            )
            session.commit()

    return state


def test_build_authorization_url_creates_hashed_one_time_state():
    engine = build_runtime()

    try:
        service = build_service(
            engine
        )

        url = service.build_authorization_url(
            user_id="user-001"
        )

        parsed = parse_qs(
            urlparse(url).query
        )

        assert (
            parsed["client_id"]
            == ["google-client-id"]
        )
        assert (
            parsed["response_type"]
            == ["code"]
        )
        assert (
            parsed["access_type"]
            == ["offline"]
        )
        assert (
            parsed["include_granted_scopes"]
            == ["true"]
        )
        assert (
            parsed["scope"]
            == [
                "https://www.googleapis.com/auth/calendar.events"
            ]
        )

        raw_state = parsed["state"][0]

        from sqlalchemy.orm import Session

        with Session(
            engine
        ) as session:
            record = session.query(
                OAuthState
            ).one()

            assert record.user_id == "user-001"
            assert record.provider == "google"
            assert record.state_hash != raw_state
            assert (
                service._hash_state(
                    raw_state
                )
                == record.state_hash
            )
            assert record.used_at is None

    finally:
        teardown_runtime(
            engine
        )


def test_oauth_state_is_single_use():
    engine = build_runtime()

    try:
        service = build_service(
            engine
        )
        state = create_state(
            service
        )

        assert (
            service._consume_state(
                state
            )
            == "user-001"
        )

        with pytest.raises(
            ValueError,
            match="Invalid or expired OAuth state",
        ):
            service._consume_state(
                state
            )

    finally:
        teardown_runtime(
            engine
        )


def test_expired_oauth_state_is_rejected():
    engine = build_runtime()

    try:
        service = build_service(
            engine
        )
        state = create_state(
            service,
            expires_delta_seconds=-1,
        )

        with pytest.raises(
            ValueError,
            match="Invalid or expired OAuth state",
        ):
            service._consume_state(
                state
            )

    finally:
        teardown_runtime(
            engine
        )


def test_complete_authorization_persists_encrypted_tokens(
    monkeypatch,
):
    engine = build_runtime()

    try:
        service = build_service(
            engine
        )
        state = create_state(
            service
        )

        monkeypatch.setattr(
            service,
            "_exchange_authorization_code",
            lambda code: {
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "expires_in": 3600,
                "scope": (
                    "https://www.googleapis.com/auth/calendar.events"
                ),
            },
        )

        result = service.complete_authorization(
            state=state,
            code="authorization-code",
        )

        assert result["provider"] == "google"
        assert result["calendar_id"] == "primary"
        assert (
            result["scopes"]
            == "https://www.googleapis.com/auth/calendar.events"
        )
        assert (
            "encrypted_access_token"
            not in result
        )
        assert (
            "encrypted_refresh_token"
            not in result
        )

        from sqlalchemy.orm import Session

        with Session(
            engine
        ) as session:
            connection = session.query(
                CalendarConnection
            ).one()

            assert (
                connection.encrypted_access_token
                != "access-secret"
            )
            assert (
                connection.encrypted_refresh_token
                != "refresh-secret"
            )

            access = (
                service.encryption_service.decrypt(
                    connection.encrypted_access_token
                )
            )
            refresh = (
                service.encryption_service.decrypt(
                    connection.encrypted_refresh_token
                )
            )

            assert access == "access-secret"
            assert refresh == "refresh-secret"

    finally:
        teardown_runtime(
            engine
        )


def test_reauthorization_without_refresh_token_preserves_existing_token(
    monkeypatch,
):
    engine = build_runtime()

    try:
        service = build_service(
            engine
        )

        first_state = create_state(
            service
        )

        monkeypatch.setattr(
            service,
            "_exchange_authorization_code",
            lambda code: {
                "access_token": "first-access",
                "refresh_token": "stable-refresh",
                "expires_in": 3600,
            },
        )

        service.complete_authorization(
            state=first_state,
            code="first-code",
        )

        second_state = create_state(
            service
        )

        monkeypatch.setattr(
            service,
            "_exchange_authorization_code",
            lambda code: {
                "access_token": "second-access",
                "expires_in": 3600,
            },
        )

        service.complete_authorization(
            state=second_state,
            code="second-code",
        )

        connection = service.get_connection(
            user_id="user-001"
        )

        assert connection is not None

        from sqlalchemy.orm import Session

        with Session(
            engine
        ) as session:
            record = session.query(
                CalendarConnection
            ).one()

            assert (
                service.encryption_service.decrypt(
                    record.encrypted_access_token
                )
                == "second-access"
            )

            assert (
                service.encryption_service.decrypt(
                    record.encrypted_refresh_token
                )
                == "stable-refresh"
            )

    finally:
        teardown_runtime(
            engine
        )


def test_get_valid_access_token_uses_unexpired_token(
    monkeypatch,
):
    engine = build_runtime()

    try:
        service = build_service(
            engine
        )

        state = create_state(
            service
        )

        monkeypatch.setattr(
            service,
            "_exchange_authorization_code",
            lambda code: {
                "access_token": "valid-access",
                "refresh_token": "stable-refresh",
                "expires_in": 3600,
            },
        )

        service.complete_authorization(
            state=state,
            code="code",
        )

        def unexpected_refresh(
            refresh_token,
        ):
            raise AssertionError(
                "Access token should not be refreshed."
            )

        monkeypatch.setattr(
            service,
            "_refresh_access_token",
            unexpected_refresh,
        )

        assert (
            service.get_valid_access_token(
                user_id="user-001"
            )
            == "valid-access"
        )

    finally:
        teardown_runtime(
            engine
        )


def test_get_valid_access_token_refreshes_expired_token(
    monkeypatch,
):
    engine = build_runtime()

    try:
        service = build_service(
            engine
        )

        state = create_state(
            service
        )

        monkeypatch.setattr(
            service,
            "_exchange_authorization_code",
            lambda code: {
                "access_token": "expired-access",
                "refresh_token": "stable-refresh",
                "expires_in": 1,
            },
        )

        service.complete_authorization(
            state=state,
            code="code",
        )

        refreshed_calls = []

        def refresh(
            refresh_token,
        ):
            refreshed_calls.append(
                refresh_token
            )
            return {
                "access_token": "refreshed-access",
                "expires_in": 3600,
            }

        monkeypatch.setattr(
            service,
            "_refresh_access_token",
            refresh,
        )

        assert (
            service.get_valid_access_token(
                user_id="user-001"
            )
            == "refreshed-access"
        )

        assert refreshed_calls == [
            "stable-refresh"
        ]

    finally:
        teardown_runtime(
            engine
        )


def test_disconnect_is_user_scoped_and_removes_connection(
    monkeypatch,
):
    engine = build_runtime()

    try:
        service = build_service(
            engine
        )

        state = create_state(
            service
        )

        monkeypatch.setattr(
            service,
            "_exchange_authorization_code",
            lambda code: {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
            },
        )

        service.complete_authorization(
            state=state,
            code="code",
        )

        assert service.disconnect(
            user_id="different-user"
        ) is False

        assert service.get_connection(
            user_id="user-001"
        ) is not None

        assert service.disconnect(
            user_id="user-001"
        ) is True

        assert service.get_connection(
            user_id="user-001"
        ) is None

    finally:
        teardown_runtime(
            engine
        )
