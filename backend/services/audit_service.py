from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.audit_event import AuditEvent
from services.request_context import get_request_id


class AuditService:
    """
    Durable security audit event service.

    The service is intentionally append-only: callers can record
    audit events, but there is no update/delete API.
    """

    VALID_STATUSES = {
        "success",
        "failure",
        "info",
    }

    def __init__(
        self,
        db_engine: Any | None = None,
    ):
        self.engine = (
            db_engine
            if db_engine is not None
            else default_engine
        )

    @staticmethod
    def _utc_now_naive() -> datetime:
        return datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    @staticmethod
    def _normalize_required(
        value: str,
        field_name: str,
    ) -> str:
        normalized = str(
            value
        ).strip()

        if not normalized:
            raise ValueError(
                f"Audit event {field_name} cannot be empty."
            )

        return normalized

    @staticmethod
    def _json_safe(
        value: Any,
    ) -> Any:
        if value is None:
            return None

        if isinstance(
            value,
            datetime,
        ):
            return value.isoformat()

        if isinstance(
            value,
            dict,
        ):
            return {
                str(key): AuditService._json_safe(
                    item
                )
                for key, item in value.items()
            }

        if isinstance(
            value,
            (list, tuple),
        ):
            return [
                AuditService._json_safe(
                    item
                )
                for item in value
            ]

        if isinstance(
            value,
            (str, int, float, bool),
        ):
            return value

        return str(value)

    def record_event(
        self,
        *,
        event_type: str,
        action: str,
        status: str,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | int | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        normalized_event_type = self._normalize_required(
            event_type,
            "event_type",
        ).lower()

        normalized_action = self._normalize_required(
            action,
            "action",
        ).lower()

        normalized_status = self._normalize_required(
            status,
            "status",
        ).lower()

        if normalized_status not in self.VALID_STATUSES:
            raise ValueError(
                "Invalid audit event status."
            )

        normalized_user_id = (
            None
            if user_id is None
            else str(user_id).strip()
        )

        if normalized_user_id == "":
            normalized_user_id = None

        normalized_resource_type = (
            None
            if resource_type is None
            else str(resource_type).strip().lower()
        )

        if normalized_resource_type == "":
            normalized_resource_type = None

        normalized_resource_id = (
            None
            if resource_id is None
            else str(resource_id).strip()
        )

        if normalized_resource_id == "":
            normalized_resource_id = None

        normalized_request_id = (
            request_id
            if request_id is not None
            else get_request_id()
        )

        if normalized_request_id is not None:
            normalized_request_id = str(
                normalized_request_id
            ).strip()

            if not normalized_request_id:
                normalized_request_id = None

        normalized_created_at = (
            created_at
            if created_at is not None
            else self._utc_now_naive()
        )

        if normalized_created_at.tzinfo is not None:
            normalized_created_at = (
                normalized_created_at
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )

        event = AuditEvent(
            user_id=normalized_user_id,
            event_type=normalized_event_type[:50],
            action=normalized_action[:50],
            status=normalized_status[:30],
            resource_type=(
                normalized_resource_type[:50]
                if normalized_resource_type
                else None
            ),
            resource_id=(
                normalized_resource_id[:100]
                if normalized_resource_id
                else None
            ),
            request_id=(
                normalized_request_id[:128]
                if normalized_request_id
                else None
            ),
            event_metadata=self._json_safe(
                dict(metadata or {})
            ),
            created_at=normalized_created_at,
        )

        with Session(self.engine) as session:
            session.add(event)
            session.commit()
            session.refresh(event)

            return {
                "id": event.id,
                "user_id": event.user_id,
                "event_type": event.event_type,
                "action": event.action,
                "status": event.status,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "request_id": event.request_id,
                "metadata": event.event_metadata,
                "created_at": event.created_at,
            }
