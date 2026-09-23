from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import sys
from typing import Any

from config import (
    ObservabilitySettings,
    get_observability_settings,
)


class JsonLogFormatter(logging.Formatter):
    """
    Serialize NOVA application logs as safe JSON records.

    Only explicit structured context fields are emitted alongside
    standard log metadata. Callers must never pass secrets,
    authorization headers, request bodies, or query strings.
    """

    def format(
        self,
        record: logging.LogRecord,
    ) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        context = getattr(
            record,
            "nova_context",
            None,
        )

        if isinstance(context, dict):
            payload.update(
                context
            )

        if record.exc_info:
            payload["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(
                    record.exc_info[1]
                ),
                "traceback": self.formatException(
                    record.exc_info
                ),
            }

        return json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        )


def configure_api_logging(
    settings: ObservabilitySettings | None = None,
) -> None:
    """
    Configure a single marked root logging handler.

    Reconfiguration is idempotent so FastAPI startup and tests can
    initialize logging more than once without duplicate handlers.
    """

    active_settings = (
        settings
        if settings is not None
        else get_observability_settings()
    )

    level = getattr(
        logging,
        active_settings.api_log_level,
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(
        level
    )

    for handler in list(
        root_logger.handlers
    ):
        if getattr(
            handler,
            "_nova_api_handler",
            False,
        ):
            root_logger.removeHandler(
                handler
            )
            handler.close()

    handler = logging.StreamHandler(
        sys.stdout
    )
    handler._nova_api_handler = True

    handler.setLevel(
        level
    )

    if active_settings.api_log_format == "json":
        handler.setFormatter(
            JsonLogFormatter()
        )
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s "
                "%(name)s %(message)s"
            )
        )

    root_logger.addHandler(
        handler
    )


def _log_context(
    *,
    request_id: str,
    method: str,
    route: str,
    duration_ms: float,
    status_code: int | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "request_id": request_id,
        "method": method,
        "route": route,
        "duration_ms": round(
            duration_ms,
            3,
        ),
    }

    if status_code is not None:
        context["status_code"] = int(
            status_code
        )

    return context


def log_api_request(
    *,
    request_id: str,
    method: str,
    route: str,
    status_code: int,
    duration_ms: float,
) -> None:
    """
    Record a completed API request without sensitive request data.
    """

    logging.getLogger(
        "nova.api"
    ).info(
        "API request completed",
        extra={
            "nova_context": _log_context(
                request_id=request_id,
                method=method,
                route=route,
                status_code=status_code,
                duration_ms=duration_ms,
            )
        },
    )


def log_api_exception(
    *,
    request_id: str,
    method: str,
    route: str,
    duration_ms: float,
) -> None:
    """
    Record an unhandled API exception without request contents.

    The caller must invoke this inside an active exception handler.
    """

    logging.getLogger(
        "nova.api"
    ).exception(
        "API request failed",
        extra={
            "nova_context": _log_context(
                request_id=request_id,
                method=method,
                route=route,
                duration_ms=duration_ms,
                status_code=500,
            )
        },
    )

def log_voice_event(
    *,
    event: str,
    session_id: str,
    turn_id: str | None = None,
    provider: str | None = None,
    code: str | None = None,
    recoverable: bool | None = None,
    duration_ms: float | None = None,
) -> None:
    """
    Record a structured realtime voice lifecycle event.

    Only safe operational metadata is accepted. User identifiers,
    transcripts, authorization data, request bodies, provider secrets,
    and provider payloads must never be passed here.
    """

    context: dict[str, Any] = {
        "event": str(event).strip() or "unknown",
        "session_id": str(session_id).strip() or "unknown",
    }

    if turn_id is not None:
        context["turn_id"] = (
            str(turn_id).strip() or "unknown"
        )

    if provider is not None:
        context["provider"] = (
            str(provider).strip() or "unknown"
        )

    if code is not None:
        context["code"] = (
            str(code).strip() or "unknown"
        )

    if recoverable is not None:
        context["recoverable"] = bool(
            recoverable
        )

    if duration_ms is not None:
        context["duration_ms"] = round(
            max(0.0, float(duration_ms)),
            3,
        )

    logging.getLogger(
        "nova.voice"
    ).info(
        "Voice lifecycle event",
        extra={
            "nova_context": context
        },
    )
