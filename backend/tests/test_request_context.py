from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.request_context import (
    get_request_id,
    normalize_request_id,
    reset_request_id,
    set_request_id,
)


def test_normalize_request_id_preserves_safe_value():
    assert (
        normalize_request_id("client-123")
        == "client-123"
    )


def test_normalize_request_id_rejects_unsafe_value():
    value = normalize_request_id(
        "bad request\nvalue"
    )

    assert value != "bad request\nvalue"
    assert len(value) == 32


def test_request_context_set_and_reset():
    token = set_request_id(
        "request-123"
    )

    try:
        assert get_request_id() == "request-123"
    finally:
        reset_request_id(token)

    assert get_request_id() is None


def test_request_id_middleware_returns_correlation_header():
    app = FastAPI()

    @app.middleware("http")
    async def request_id_middleware(
        request,
        call_next,
    ):
        from services.request_context import (
            normalize_request_id,
            reset_request_id,
            set_request_id,
        )

        request_id = normalize_request_id(
            request.headers.get("X-Request-ID")
        )

        token = set_request_id(
            request_id
        )

        try:
            response = await call_next(
                request
            )
        finally:
            reset_request_id(
                token
            )

        response.headers["X-Request-ID"] = request_id
        return response

    @app.get("/")
    def endpoint():
        return {
            "request_id": get_request_id()
        }

    client = TestClient(app)

    response = client.get(
        "/",
        headers={
            "X-Request-ID": "client-abc"
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "client-abc"
    assert response.json() == {
        "request_id": "client-abc"
    }
