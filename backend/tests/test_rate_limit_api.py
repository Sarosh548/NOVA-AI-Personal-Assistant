from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from api.auth import (
    enforce_auth_endpoint_rate_limit,
    get_auth_service,
    get_rate_limit_service,
    get_token_service,
    get_user_service,
    router,
)
from config import (
    RateLimitSettings,
    get_rate_limit_settings,
)
from models.rate_limit_counter import RateLimitCounter
from services.rate_limit_service import RateLimitService


TEST_USER_ID = "rate-limit-user"
TEST_SESSION_ID = "rate-limit-session"


class FakeTokenService:
    def decode_access_token(
        self,
        _token: str,
    ) -> dict[str, str]:
        return {
            "sub": TEST_USER_ID,
            "sid": TEST_SESSION_ID,
        }


class FakeAuthService:
    def __init__(self):
        self.session = SimpleNamespace(
            id=TEST_SESSION_ID,
            user_id=TEST_USER_ID,
            revoked_at=None,
            expires_at=(
                datetime.now(timezone.utc)
                .replace(tzinfo=None)
                + timedelta(hours=1)
            ),
        )

    def get_session(
        self,
        session_id: str,
    ):
        if session_id == TEST_SESSION_ID:
            return self.session

        return None


class FakeUserService:
    def get(
        self,
        user_id: str,
    ):
        if user_id != TEST_USER_ID:
            return None

        now = datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

        return SimpleNamespace(
            id=TEST_USER_ID,
            is_active=True,
            display_name="Rate Limit User",
            created_at=now,
            updated_at=now,
        )


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


def build_authenticated_app(
    db_engine,
    *,
    requests_per_window: int,
) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[
        get_token_service
    ] = FakeTokenService

    app.dependency_overrides[
        get_auth_service
    ] = FakeAuthService

    app.dependency_overrides[
        get_user_service
    ] = FakeUserService

    app.dependency_overrides[
        get_rate_limit_service
    ] = lambda: RateLimitService(
        db_engine=db_engine
    )

    app.dependency_overrides[
        get_rate_limit_settings
    ] = lambda: RateLimitSettings(
        api_rate_limit_enabled=True,
        api_rate_limit_requests_per_window=(
            requests_per_window
        ),
        api_rate_limit_window_seconds=60,
    )

    return TestClient(app)


def test_authenticated_api_returns_rate_limit_headers_and_429():
    db_engine = build_runtime()

    try:
        client = build_authenticated_app(
            db_engine,
            requests_per_window=2,
        )

        first = client.get(
            "/auth/me",
            headers={
                "Authorization": "Bearer token"
            },
        )

        second = client.get(
            "/auth/me",
            headers={
                "Authorization": "Bearer token"
            },
        )

        blocked = client.get(
            "/auth/me",
            headers={
                "Authorization": "Bearer token"
            },
        )

        assert first.status_code == 200
        assert (
            first.headers["RateLimit-Limit"]
            == "2"
        )
        assert (
            first.headers["RateLimit-Remaining"]
            == "1"
        )

        assert second.status_code == 200
        assert (
            second.headers["RateLimit-Remaining"]
            == "0"
        )

        assert blocked.status_code == 429
        assert (
            blocked.headers["RateLimit-Limit"]
            == "2"
        )
        assert (
            blocked.headers["RateLimit-Remaining"]
            == "0"
        )
        assert blocked.headers[
            "RateLimit-Reset"
        ].isdigit()
        assert blocked.headers[
            "Retry-After"
        ].isdigit()

    finally:
        teardown_runtime(
            db_engine
        )


def test_auth_endpoint_rate_limit_blocks_same_ip_bucket():
    db_engine = build_runtime()

    try:
        app = FastAPI()

        @app.get(
            "/auth/login",
            dependencies=[
                Depends(
                    enforce_auth_endpoint_rate_limit
                )
            ],
        )
        def probe():
            return {"status": "ok"}

        app.dependency_overrides[
            get_rate_limit_service
        ] = lambda: RateLimitService(
            db_engine=db_engine
        )

        app.dependency_overrides[
            get_rate_limit_settings
        ] = lambda: RateLimitSettings(
            api_rate_limit_enabled=True,
            api_auth_rate_limit_requests_per_window=1,
            api_auth_rate_limit_window_seconds=60,
        )

        client = TestClient(app)

        first = client.get(
            "/auth/login"
        )
        blocked = client.get(
            "/auth/login"
        )

        assert first.status_code == 200
        assert blocked.status_code == 429
        assert blocked.headers[
            "Retry-After"
        ].isdigit()

    finally:
        teardown_runtime(
            db_engine
        )


def test_rate_limit_settings_are_environment_driven(
    monkeypatch,
):
    monkeypatch.setenv(
        "API_RATE_LIMIT_REQUESTS_PER_WINDOW",
        "77",
    )
    monkeypatch.setenv(
        "API_RATE_LIMIT_WINDOW_SECONDS",
        "30",
    )
    monkeypatch.setenv(
        "API_AUTH_RATE_LIMIT_REQUESTS_PER_WINDOW",
        "9",
    )

    settings = RateLimitSettings()

    assert (
        settings.api_rate_limit_requests_per_window
        == 77
    )
    assert (
        settings.api_rate_limit_window_seconds
        == 30
    )
    assert (
        settings.api_auth_rate_limit_requests_per_window
        == 9
    )
