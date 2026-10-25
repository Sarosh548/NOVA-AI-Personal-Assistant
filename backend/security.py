from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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


class RequestBodySizeLimitExceeded(Exception):
    pass


class HealthCheckTrustedHostMiddleware(TrustedHostMiddleware):
    """Allow platform probes to reach read-only health endpoints.

    Some managed runtimes probe a container by its internal IP, so the HTTP
    Host header is not the app's public hostname. Keep host validation strict
    for every application route and bypass it only for exact GET/HEAD health
    paths that expose no user data.
    """

    _HEALTH_PATHS = frozenset({"/health/live", "/health/ready"})

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") == "http"
            and scope.get("method") in {"GET", "HEAD"}
            and scope.get("path") in self._HEALTH_PATHS
        ):
            await self.app(scope, receive, send)
            return

        await super().__call__(scope, receive, send)


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
        HealthCheckTrustedHostMiddleware,
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
    async def request_body_size_limit_middleware(
        request: Request,
        call_next,
    ):
        content_length = request.headers.get(
            "content-length"
        )

        if content_length is not None:
            try:
                declared_length = int(
                    content_length
                )
            except ValueError:
                declared_length = None

            if (
                declared_length is not None
                and declared_length
                > security_settings.api_max_request_body_bytes
            ):
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": "Request body is too large."
                    },
                )

        original_receive = request._receive
        bytes_seen = 0

        async def limited_receive():
            nonlocal bytes_seen

            message = await original_receive()

            if message.get("type") == "http.request":
                body = message.get(
                    "body",
                    b"",
                )
                bytes_seen += len(body)

                if (
                    bytes_seen
                    > security_settings.api_max_request_body_bytes
                ):
                    raise RequestBodySizeLimitExceeded()

            return message

        request._receive = limited_receive

        try:
            return await call_next(request)
        except RequestBodySizeLimitExceeded:
            return JSONResponse(
                status_code=413,
                content={
                    "detail": "Request body is too large."
                },
            )
        finally:
            request._receive = original_receive

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
