from __future__ import annotations

import os
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)


class APIMetrics:
    """
    Prometheus metrics for NOVA's HTTP API.

    Labels intentionally use low-cardinality route templates and
    status codes only. User identifiers, request bodies, tokens,
    query strings, and other request data are never metric labels.
    """

    METRICS_ROUTE = "/metrics"

    def __init__(
        self,
        *,
        registry=None,
    ):
        active_registry = (
            registry
            if registry is not None
            else REGISTRY
        )

        self.requests = Counter(
            "nova_api_requests_total",
            "Total number of API requests.",
            labelnames=(
                "method",
                "route",
                "status_code",
            ),
            registry=active_registry,
        )

        self.request_duration = Histogram(
            "nova_api_request_duration_seconds",
            "API request duration in seconds.",
            labelnames=(
                "method",
                "route",
            ),
            registry=active_registry,
        )

        self.errors = Counter(
            "nova_api_errors_total",
            "Total number of API client and server errors.",
            labelnames=(
                "method",
                "route",
                "status_class",
            ),
            registry=active_registry,
        )

        self.rate_limit_exceeded = Counter(
            "nova_api_rate_limit_exceeded_total",
            "Total number of API rate-limit rejections.",
            labelnames=(
                "method",
                "route",
            ),
            registry=active_registry,
        )

        self.requests_in_progress = Gauge(
            "nova_api_requests_in_progress",
            "Number of API requests currently in progress.",
            registry=active_registry,
            multiprocess_mode="livesum",
        )

    def start_request(self) -> None:
        self.requests_in_progress.inc()

    def end_request(self) -> None:
        self.requests_in_progress.dec()

    def observe_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        normalized_method = str(
            method
        ).strip().upper() or "UNKNOWN"

        normalized_route = str(
            route
        ).strip() or "__unmatched__"

        code = int(
            status_code
        )

        if normalized_route == self.METRICS_ROUTE:
            return

        self.requests.labels(
            method=normalized_method,
            route=normalized_route,
            status_code=str(code),
        ).inc()

        self.request_duration.labels(
            method=normalized_method,
            route=normalized_route,
        ).observe(
            max(
                0.0,
                float(duration_seconds),
            )
        )

        if 400 <= code <= 599:
            self.errors.labels(
                method=normalized_method,
                route=normalized_route,
                status_class=f"{code // 100}xx",
            ).inc()

        if code == 429:
            self.rate_limit_exceeded.labels(
                method=normalized_method,
                route=normalized_route,
            ).inc()


api_metrics = APIMetrics()


def generate_metrics() -> tuple[bytes, str]:
    """
    Generate the Prometheus exposition payload.

    In multiprocess deployments the collector reads the shared
    PROMETHEUS_MULTIPROC_DIR from a fresh registry, matching the
    Prometheus Python client's worker-safe collection pattern.
    """

    if os.getenv(
        "PROMETHEUS_MULTIPROC_DIR"
    ):
        registry = CollectorRegistry(
            support_collectors_without_names=True
        )

        multiprocess.MultiProcessCollector(
            registry
        )

    else:
        registry = REGISTRY

    return (
        generate_latest(
            registry
        ),
        CONTENT_TYPE_LATEST,
    )
