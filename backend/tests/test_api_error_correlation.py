from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel

from main import (
    http_exception_handler,
    request_id_middleware,
    request_validation_exception_handler,
    unhandled_exception_handler,
)


def build_client():
    app = FastAPI()

    app.middleware("http")(
        request_id_middleware
    )

    app.add_exception_handler(
        HTTPException,
        http_exception_handler,
    )

    app.add_exception_handler(
        RequestValidationError,
        request_validation_exception_handler,
    )

    app.add_exception_handler(
        Exception,
        unhandled_exception_handler,
    )

    class Payload(BaseModel):
        message: str

    @app.get("/http-error")
    def http_error():
        raise HTTPException(
            status_code=409,
            detail="Conflict",
        )

    @app.post("/validation-error")
    def validation_error(
        payload: Payload,
    ):
        return payload

    @app.get("/unexpected-error")
    def unexpected_error():
        raise RuntimeError(
            "secret internal failure"
        )

    return app


def test_http_error_preserves_body_and_request_id():
    client = TestClient(build_client())

    response = client.get(
        "/http-error",
        headers={
            "X-Request-ID": "req-http-123"
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Conflict"
    }
    assert response.headers["X-Request-ID"] == "req-http-123"


def test_validation_error_preserves_body_and_request_id():
    client = TestClient(build_client())

    response = client.post(
        "/validation-error",
        json={},
        headers={
            "X-Request-ID": "req-validation-123"
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]
    assert response.headers["X-Request-ID"] == "req-validation-123"


def test_unexpected_error_returns_safe_response_and_request_id():
    client = TestClient(
        build_client(),
        raise_server_exceptions=False,
    )

    response = client.get(
        "/unexpected-error",
        headers={
            "X-Request-ID": "req-unexpected-123"
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal Server Error"
    }
    assert response.headers["X-Request-ID"] == "req-unexpected-123"
    assert "secret internal failure" not in response.text
