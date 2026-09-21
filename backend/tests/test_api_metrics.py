from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
)

import main
from services.api_metrics import (
    APIMetrics,
    generate_metrics,
)
from fastapi.testclient import TestClient


def _metrics_text(metrics: APIMetrics) -> str:
    body, _content_type = (
        generate_metrics_for_registry(
            metrics
        )
    )
    return body.decode("utf-8")


def generate_metrics_for_registry(
    metrics: APIMetrics,
) -> tuple[bytes, str]:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        generate_latest,
    )

    return (
        generate_latest(
            metrics.requests._metrics[
                (
                    "GET",
                    "/health/live",
                    "200",
                )
            ]._name
            if False
            else metrics.registry
        ),
        CONTENT_TYPE_LATEST,
    )


def test_metrics_record_requests_latency_errors_and_rate_limits():
    registry = CollectorRegistry()
    metrics = APIMetrics(
        registry=registry,
    )

    metrics.observe_request(
        method="GET",
        route="/health/live",
        status_code=200,
        duration_seconds=0.125,
    )

    metrics.observe_request(
        method="POST",
        route="/auth/login",
        status_code=429,
        duration_seconds=0.25,
    )

    body = _metrics_text(
        metrics
    )

    assert (
        'nova_api_requests_total{method="GET",route="/health/live",status_code="200"} 1.0'
        in body
    )
    assert (
        'nova_api_requests_total{method="POST",route="/auth/login",status_code="429"} 1.0'
        in body
    )
    assert (
        'nova_api_errors_total{method="POST",route="/auth/login",status_class="4xx"} 1.0'
        in body
    )
    assert (
        'nova_api_rate_limit_exceeded_total{method="POST",route="/auth/login"} 1.0'
        in body
    )


def test_metrics_never_use_request_identity_as_a_label():
    registry = CollectorRegistry()
    metrics = APIMetrics(
        registry=registry,
    )

    metrics.observe_request(
        method="GET",
        route="/users/{user_id}",
        status_code=200,
        duration_seconds=0.01,
    )

    body = _metrics_text(
        metrics
    )

    assert "user-001" not in body
    assert "Authorization" not in body
    assert "?" not in body


def test_metrics_endpoint_returns_prometheus_payload():
    client = TestClient(
        main.app
    )

    response = client.get(
        "/metrics"
    )

    assert response.status_code == 200
    assert (
        "text/plain"
        in response.headers[
            "content-type"
        ]
    )
    assert (
        "nova_api_requests_total"
        in response.text
    )


def test_request_middleware_updates_metrics():
    client = TestClient(
        main.app
    )

    response = client.get(
        "/health/live"
    )

    assert response.status_code == 200

    body, _content_type = generate_metrics()
    text = body.decode(
        "utf-8"
    )

    assert (
        'nova_api_requests_total{method="GET",route="/health/live",status_code="200"}'
        in text
    )


def test_metrics_endpoint_does_not_count_itself():
    registry = CollectorRegistry()
    metrics = APIMetrics(
        registry=registry,
    )

    metrics.observe_request(
        method="GET",
        route="/metrics",
        status_code=200,
        duration_seconds=0.01,
    )

    body = _metrics_text(
        metrics
    )

    assert "nova_api_requests_total" not in body
