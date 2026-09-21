from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from config import (
    SecuritySettings,
    get_security_settings,
)


API_ALLOWED_METHODS = [
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
]

API_ALLOWED_HEADERS = [
    "Authorization",
    "Content-Type",
    "Idempotency-Key",
    "X-Request-ID",
]


def _build_hsts_value(
    settings: SecuritySettings,
) -> str:
    value = (
        "max-age="
        f"{settings.security_hsts_max_age_seconds}"
    )

    if settings.security_hsts_include_subdomains:
        value += "; includeSubDomains"

    if settings.security_hsts_preload:
        value += "; preload"

    return value


def configure_api_security(
    app: FastAPI,
    settings: SecuritySettings | None = None,
) -> None:
    security_settings = (
        settings
        if settings is not None
        else get_security_settings()
    )

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(
            security_settings.trusted_hosts()
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(
            security_settings.cors_allowed_origins()
        ),
        allow_credentials=False,
        allow_methods=API_ALLOWED_METHODS,
        allow_headers=API_ALLOWED_HEADERS,
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def security_headers_middleware(
        request: Request,
        call_next,
    ):
        response = await call_next(request)

        response.headers[
            "X-Content-Type-Options"
        ] = "nosniff"

        response.headers[
            "X-Frame-Options"
        ] = "DENY"

        response.headers[
            "Referrer-Policy"
        ] = "strict-origin-when-cross-origin"

        if security_settings.security_hsts_enabled:
            response.headers[
                "Strict-Transport-Security"
            ] = _build_hsts_value(
                security_settings
            )

        return response
