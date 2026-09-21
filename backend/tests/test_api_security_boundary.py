from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main
from config import SecuritySettings
from security import configure_api_security


def _client_for(
    settings: SecuritySettings,
) -> TestClient:
    app = FastAPI()

    @app.get("/probe")
    def probe():
        return {"status": "ok"}

    @app.post("/probe")
    async def post_probe(
        request: Request,
    ):
        body = await request.body()
        return {"size": len(body)}

    configure_api_security(
        app,
        settings,
    )

    return TestClient(app)


def test_security_headers_are_added_without_hsts_by_default():
    client = _client_for(
        SecuritySettings()
    )

    response = client.get(
        "/probe"
    )

    assert response.status_code == 200
    assert (
        response.headers[
            "X-Content-Type-Options"
        ]
        == "nosniff"
    )
    assert (
        response.headers[
            "X-Frame-Options"
        ]
        == "DENY"
    )
    assert (
        response.headers[
            "Referrer-Policy"
        ]
        == "strict-origin-when-cross-origin"
    )
    assert (
        "Strict-Transport-Security"
        not in response.headers
    )


def test_hsts_is_enabled_and_configurable():
    client = _client_for(
        SecuritySettings(
            security_hsts_enabled=True,
            security_hsts_max_age_seconds=31536000,
            security_hsts_include_subdomains=True,
            security_hsts_preload=True,
        )
    )

    response = client.get(
        "/probe"
    )

    assert response.status_code == 200
    assert (
        response.headers[
            "Strict-Transport-Security"
        ]
        == (
            "max-age=31536000; "
            "includeSubDomains; preload"
        )
    )


def test_cors_requires_explicit_origin():
    client = _client_for(
        SecuritySettings(
            api_cors_allowed_origins=(
                "https://app.example.com,"
                "https://admin.example.com"
            )
        )
    )

    response = client.options(
        "/probe",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert (
        response.headers[
            "Access-Control-Allow-Origin"
        ]
        == "https://app.example.com"
    )
    assert (
        "*"
        not in response.headers.get(
            "Access-Control-Allow-Origin",
            "",
        )
    )
    assert "POST" in response.headers[
        "Access-Control-Allow-Methods"
    ]


def test_cors_rejects_unconfigured_origin():
    client = _client_for(
        SecuritySettings(
            api_cors_allowed_origins=(
                "https://app.example.com"
            )
        )
    )

    response = client.get(
        "/probe",
        headers={
            "Origin": "https://evil.example.com"
        },
    )

    assert response.status_code == 200
    assert (
        "Access-Control-Allow-Origin"
        not in response.headers
    )


def test_trusted_host_rejects_unlisted_host():
    client = _client_for(
        SecuritySettings(
            api_trusted_hosts="api.example.com"
        )
    )

    response = client.get(
        "/probe",
        headers={
            "Host": "evil.example.com"
        },
    )

    assert response.status_code == 400


def test_trusted_host_accepts_configured_host():
    client = _client_for(
        SecuritySettings(
            api_trusted_hosts="api.example.com"
        )
    )

    response = client.get(
        "/probe",
        headers={
            "Host": "api.example.com"
        },
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "field_name",
    [
        "api_cors_allowed_origins",
        "api_trusted_hosts",
    ],
)
def test_wildcard_security_configuration_is_rejected(
    field_name,
):
    with pytest.raises(ValidationError):
        SecuritySettings(
            **{
                field_name: "*",
            }
        )


def test_security_configuration_reads_environment_values(
    monkeypatch,
):
    monkeypatch.setenv(
        "API_CORS_ALLOWED_ORIGINS",
        "https://app.example.com",
    )
    monkeypatch.setenv(
        "API_TRUSTED_HOSTS",
        "api.example.com",
    )
    monkeypatch.setenv(
        "SECURITY_HSTS_ENABLED",
        "true",
    )
    monkeypatch.setenv(
        "API_MAX_REQUEST_BODY_BYTES",
        "2048",
    )

    settings = SecuritySettings()

    assert settings.cors_allowed_origins() == (
        "https://app.example.com",
    )
    assert settings.trusted_hosts() == (
        "api.example.com",
    )
    assert (
        settings.security_hsts_enabled
        is True
    )
    assert (
        settings.api_max_request_body_bytes
        == 2048
    )


def test_request_body_size_limit_has_bounded_default():
    settings = SecuritySettings()

    assert (
        settings.api_max_request_body_bytes
        == 10_485_760
    )


@pytest.mark.parametrize(
    "value",
    [1023, 52_428_801],
)
def test_request_body_size_limit_rejects_invalid_values(
    value,
):
    with pytest.raises(ValidationError):
        SecuritySettings(
            api_max_request_body_bytes=value
        )


def test_request_body_size_limit_rejects_large_requests():
    client = _client_for(
        SecuritySettings(
            api_max_request_body_bytes=8
        )
    )

    response = client.post(
        "/probe",
        content=b"123456789",
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": "Request body is too large."
    }


def test_request_body_size_limit_allows_requests_within_limit():
    client = _client_for(
        SecuritySettings(
            api_max_request_body_bytes=8
        )
    )

    response = client.post(
        "/probe",
        content=b"12345678",
    )

    assert response.status_code == 200
    assert response.json() == {
        "size": 8
    }


def test_main_application_uses_security_boundary():
    client = TestClient(main.app)

    response = client.get("/")

    assert response.status_code == 200
    assert (
        response.headers[
            "X-Content-Type-Options"
        ]
        == "nosniff"
    )
    assert (
        response.headers[
            "X-Frame-Options"
        ]
        == "DENY"
    )
    assert (
        response.headers[
            "Referrer-Policy"
        ]
        == "strict-origin-when-cross-origin"
    )
