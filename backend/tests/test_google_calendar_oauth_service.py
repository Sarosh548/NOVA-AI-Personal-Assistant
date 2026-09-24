from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from urllib.error import HTTPError
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
    GoogleOAuthTokenError,
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

    from sqlalchemy.orm import Session

    with Session(
        engine
    ) as session:
        session.add(
            User(
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
        session.commit()

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



def test_cancel_authorization_consumes_pending_state(
):
    engine = build_runtime()

    try:
        service = build_service(
            engine
        )
        state = create_state(
            service
        )

        service.cancel_authorization(
            state=state
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


def test_cancel_authorization_rejects_unknown_state(
):
    engine = build_runtime()

    try:
        service = build_service(
            engine
        )

        with pytest.raises(
            ValueError,
            match="Invalid or expired OAuth state",
        ):
            service.cancel_authorization(
                state="unknown-state"
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


def test_complete_authorization_rejects_missing_required_granted_scope(
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
                    "https://www.googleapis.com/auth/calendar.events.readonly"
                ),
            },
        )

        with pytest.raises(
            ValueError,
            match="did not grant the required Calendar scope",
        ):
            service.complete_authorization(
                state=state,
                code="authorization-code",
            )

        from sqlalchemy.orm import Session

        with Session(
            engine
        ) as session:
            assert (
                session.query(
                    CalendarConnection
                ).count()
                == 0
            )

    finally:
        teardown_runtime(
            engine
        )


def test_complete_authorization_uses_requested_scope_when_response_omits_scope(
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
            },
        )

        result = service.complete_authorization(
            state=state,
            code="authorization-code",
        )

        assert (
            result["scopes"]
            == "https://www.googleapis.com/auth/calendar.events"
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



def test_invalid_grant_refresh_invalidates_local_connection(
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
                "refresh_token": "revoked-refresh",
                "expires_in": 1,
            },
        )

        service.complete_authorization(
            state=state,
            code="code",
        )

        def fail_refresh(
            refresh_token,
        ):
            raise GoogleOAuthTokenError(
                "Google access token refresh failed.",
                error_code="invalid_grant",
            )

        monkeypatch.setattr(
            service,
            "_refresh_access_token",
            fail_refresh,
        )

        with pytest.raises(
            ValueError,
            match="access token refresh failed",
        ):
            service.get_valid_access_token(
                user_id="user-001"
            )

        assert service.get_connection(
            user_id="user-001"
        ) is None

    finally:
        teardown_runtime(
            engine
        )


def test_invalid_grant_does_not_delete_a_newer_refresh_claim(
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

        claim = service._claim_token_refresh(
            user_id="user-001"
        )

        assert claim is not None

        service._release_token_refresh(
            user_id="user-001",
            claim_token=claim["claim_token"],
        )

        newer_claim = service._claim_token_refresh(
            user_id="user-001"
        )

        assert newer_claim is not None
        assert newer_claim["claim_token"] != claim["claim_token"]

        assert service._invalidate_connection_after_invalid_grant(
            user_id="user-001",
            claim_token=claim["claim_token"],
        ) is False

        assert service.get_connection(
            user_id="user-001"
        ) is not None

        assert service._release_token_refresh(
            user_id="user-001",
            claim_token=newer_claim["claim_token"],
        ) is True

    finally:
        teardown_runtime(
            engine
        )


def test_post_form_preserves_invalid_grant_error_code(
    monkeypatch,
):
    engine = build_runtime()

    try:
        service = build_service(
            engine
        )

        def fake_urlopen(
            request,
            timeout,
        ):
            raise HTTPError(
                request.full_url,
                400,
                "invalid grant",
                {},
                BytesIO(
                    b'{"error":"invalid_grant","error_description":"Token has been revoked."}'
                ),
            )

        monkeypatch.setattr(
            "services.google_calendar_oauth_service.urlopen",
            fake_urlopen,
        )

        with pytest.raises(
            GoogleOAuthTokenError,
            match="access token refresh failed",
        ) as exc_info:
            service._refresh_access_token(
                "revoked-refresh"
            )

        assert exc_info.value.error_code == (
            "invalid_grant"
        )

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

        monkeypatch.setattr(
            service,
            "_revoke_token",
            lambda refresh_token: None,
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


def test_revoke_token_posts_refresh_token_without_requiring_json_body(
    monkeypatch,
):
    engine = build_runtime()

    try:
        service = build_service(
            engine
        )

        captured = {}

        class FakeResponse:
            status = 200

            def __enter__(
                self,
            ):
                return self

            def __exit__(
                self,
                exc_type,
                exc,
                traceback,
            ):
                return None

            def read(
                self,
            ):
                return b""

        def fake_urlopen(
            request,
            timeout,
        ):
            captured["url"] = request.full_url
            captured["method"] = request.method
            captured["body"] = request.data
            captured["content_type"] = (
                request.headers["Content-type"]
            )
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr(
            "services.google_calendar_oauth_service.urlopen",
            fake_urlopen,
        )

        service._revoke_token(
            "refresh-secret"
        )

        assert captured["url"] == (
            service.REVOCATION_ENDPOINT
        )
        assert captured["method"] == "POST"
        assert captured["body"] == (
            b"token=refresh-secret"
        )
        assert captured["content_type"] == (
            "application/x-www-form-urlencoded"
        )
        assert captured["timeout"] == (
            service.HTTP_TIMEOUT_SECONDS
        )

    finally:
        teardown_runtime(
            engine
        )


def test_disconnect_revokes_refresh_token_before_removing_connection(
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
                "refresh_token": "refresh-secret",
                "expires_in": 3600,
            },
        )

        service.complete_authorization(
            state=state,
            code="code",
        )

        revoked_tokens = []

        monkeypatch.setattr(
            service,
            "_revoke_token",
            lambda refresh_token: revoked_tokens.append(
                refresh_token
            ),
        )

        assert service.disconnect(
            user_id="user-001"
        ) is True

        assert revoked_tokens == [
            "refresh-secret"
        ]

        assert service.get_connection(
            user_id="user-001"
        ) is None

    finally:
        teardown_runtime(
            engine
        )


def test_disconnect_removes_connection_when_google_reports_invalid_token(
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
                "refresh_token": "already-revoked-refresh",
                "expires_in": 3600,
            },
        )

        service.complete_authorization(
            state=state,
            code="code",
        )

        def already_revoked(
            refresh_token,
        ):
            raise HTTPError(
                service.REVOCATION_ENDPOINT,
                400,
                "invalid token",
                {},
                BytesIO(
                    b'{"error":"invalid_token","error_description":"Token expired or revoked"}'
                ),
            )

        monkeypatch.setattr(
            "services.google_calendar_oauth_service.urlopen",
            already_revoked,
        )

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


def test_disconnect_preserves_connection_when_remote_revocation_fails(
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
                "refresh_token": "refresh-secret",
                "expires_in": 3600,
            },
        )

        service.complete_authorization(
            state=state,
            code="code",
        )

        def fail_revocation(
            refresh_token,
        ):
            raise ValueError(
                "Google Calendar access revocation failed."
            )

        monkeypatch.setattr(
            service,
            "_revoke_token",
            fail_revocation,
        )

        with pytest.raises(
            ValueError,
            match="access revocation failed",
        ):
            service.disconnect(
                user_id="user-001"
            )

        assert service.get_connection(
            user_id="user-001"
        ) is not None

    finally:
        teardown_runtime(
            engine
        )


def test_token_refresh_lease_allows_only_one_claim(
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

        from sqlalchemy.orm import Session

        import sqlalchemy as sa

        with Session(
            engine
        ) as session:
            session.execute(
                sa.update(
                    CalendarConnection
                )
                .where(
                    CalendarConnection.user_id
                    == "user-001"
                )
                .values(
                    token_expires_at=(
                        service._utc_now_naive()
                        - timedelta(
                            seconds=120
                        )
                    )
                )
            )
            session.commit()

        claim_one = service._claim_token_refresh(
            user_id="user-001"
        )
        claim_two = service._claim_token_refresh(
            user_id="user-001"
        )

        assert claim_one is not None
        assert claim_two is None

        assert service._release_token_refresh(
            user_id="user-001",
            claim_token=claim_one["claim_token"],
        ) is True

    finally:
        teardown_runtime(
            engine
        )


def test_successful_token_refresh_clears_refresh_lease(
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

        monkeypatch.setattr(
            service,
            "_refresh_access_token",
            lambda refresh_token: {
                "access_token": "refreshed-access",
                "expires_in": 3600,
            },
        )

        assert service.get_valid_access_token(
            user_id="user-001"
        ) == "refreshed-access"

        from sqlalchemy.orm import Session

        with Session(
            engine
        ) as session:
            connection = session.query(
                CalendarConnection
            ).one()

            assert (
                connection.token_refresh_claim_token
                is None
            )
            assert (
                connection.token_refresh_lease_until
                is None
            )

    finally:
        teardown_runtime(
            engine
        )


def test_failed_token_refresh_releases_refresh_lease(
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

        def fail_refresh(
            refresh_token,
        ):
            raise ValueError(
                "refresh failed"
            )

        monkeypatch.setattr(
            service,
            "_refresh_access_token",
            fail_refresh,
        )

        with pytest.raises(
            ValueError,
            match="refresh failed",
        ):
            service.get_valid_access_token(
                user_id="user-001"
            )

        from sqlalchemy.orm import Session

        with Session(
            engine
        ) as session:
            connection = session.query(
                CalendarConnection
            ).one()

            assert (
                connection.token_refresh_claim_token
                is None
            )
            assert (
                connection.token_refresh_lease_until
                is None
            )

    finally:
        teardown_runtime(
            engine
        )
