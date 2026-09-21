from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.notification_delivery import (
    NotificationDelivery,
)


class NotificationDeliveryService:
    """
    Durable coordinator for idempotent notification delivery.
    """

    DEFAULT_LEASE_SECONDS = 300

    def __init__(
        self,
        *,
        db_engine: Any | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ):
        if lease_seconds < 1:
            raise ValueError(
                "lease_seconds must be at least 1"
            )

        self.engine = (
            db_engine
            if db_engine is not None
            else default_engine
        )

        self.lease_seconds = int(
            lease_seconds
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    @staticmethod
    def _normalize(
        value: str,
        field_name: str,
    ) -> str:
        normalized = str(
            value
        ).strip()

        if not normalized:
            raise ValueError(
                f"{field_name} cannot be empty."
            )

        return normalized

    def claim_delivery(
        self,
        *,
        user_id: str,
        channel: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        cleaned_user_id = self._normalize(
            user_id,
            "user_id",
        )

        cleaned_channel = self._normalize(
            channel,
            "channel",
        ).lower()

        cleaned_key = self._normalize(
            idempotency_key,
            "idempotency_key",
        )

        if len(cleaned_key) > 255:
            raise ValueError(
                "idempotency_key cannot exceed 255 characters."
            )

        reference_now = (
            now
            if now is not None
            else self._now()
        )

        if reference_now.tzinfo is not None:
            reference_now = (
                reference_now
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )

        for _ in range(2):
            claim_token = uuid4().hex
            lease_until = (
                reference_now
                + timedelta(
                    seconds=self.lease_seconds
                )
            )

            with Session(self.engine) as session:
                delivery = session.scalar(
                    select(
                        NotificationDelivery
                    )
                    .where(
                        NotificationDelivery.user_id
                        == cleaned_user_id,
                        NotificationDelivery.channel
                        == cleaned_channel,
                        NotificationDelivery.idempotency_key
                        == cleaned_key,
                    )
                    .with_for_update()
                )

                if delivery is None:
                    delivery = NotificationDelivery(
                        user_id=cleaned_user_id,
                        channel=cleaned_channel,
                        idempotency_key=cleaned_key,
                        status="processing",
                        attempt_count=1,
                        claim_token=claim_token,
                        lease_until=lease_until,
                        sent_at=None,
                        last_attempt_at=reference_now,
                        last_error=None,
                        created_at=reference_now,
                        updated_at=reference_now,
                    )

                    try:
                        session.add(
                            delivery
                        )
                        session.commit()
                        session.refresh(
                            delivery
                        )
                    except IntegrityError:
                        session.rollback()
                        continue

                    return {
                        "claimed": True,
                        "reason": "claimed",
                        "delivery_id": delivery.id,
                        "claim_token": claim_token,
                        "status": delivery.status,
                        "attempt_count": delivery.attempt_count,
                    }

                if delivery.status == "sent":
                    return {
                        "claimed": False,
                        "reason": "already_sent",
                        "delivery_id": delivery.id,
                        "status": delivery.status,
                        "attempt_count": delivery.attempt_count,
                    }

                if (
                    delivery.status == "processing"
                    and delivery.lease_until is not None
                    and delivery.lease_until > reference_now
                ):
                    return {
                        "claimed": False,
                        "reason": "in_progress",
                        "delivery_id": delivery.id,
                        "status": delivery.status,
                        "attempt_count": delivery.attempt_count,
                    }

                delivery.status = "processing"
                delivery.attempt_count += 1
                delivery.claim_token = claim_token
                delivery.lease_until = lease_until
                delivery.last_attempt_at = reference_now
                delivery.last_error = None
                delivery.updated_at = reference_now
                delivery.sent_at = None

                session.commit()
                session.refresh(
                    delivery
                )

                return {
                    "claimed": True,
                    "reason": "reclaimed",
                    "delivery_id": delivery.id,
                    "claim_token": claim_token,
                    "status": delivery.status,
                    "attempt_count": delivery.attempt_count,
                }

        raise RuntimeError(
            "Could not claim notification delivery."
        )

    def mark_sent(
        self,
        *,
        delivery_id: int,
        claim_token: str,
        now: datetime | None = None,
    ) -> bool:
        reference_now = (
            now
            if now is not None
            else self._now()
        )

        if reference_now.tzinfo is not None:
            reference_now = (
                reference_now
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )

        token = str(
            claim_token
        ).strip()

        if not token:
            return False

        with Session(self.engine) as session:
            result = session.execute(
                update(NotificationDelivery)
                .where(
                    NotificationDelivery.id
                    == delivery_id,
                    NotificationDelivery.status
                    == "processing",
                    NotificationDelivery.claim_token
                    == token,
                )
                .values(
                    status="sent",
                    sent_at=reference_now,
                    updated_at=reference_now,
                    claim_token=None,
                    lease_until=None,
                    last_error=None,
                )
            )

            if result.rowcount != 1:
                session.rollback()
                return False

            session.commit()
            return True

    def mark_failed(
        self,
        *,
        delivery_id: int,
        claim_token: str,
        error: str,
        now: datetime | None = None,
    ) -> bool:
        cleaned_error = str(
            error
        ).strip()

        if not cleaned_error:
            cleaned_error = (
                "Notification delivery failed."
            )

        reference_now = (
            now
            if now is not None
            else self._now()
        )

        if reference_now.tzinfo is not None:
            reference_now = (
                reference_now
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )

        token = str(
            claim_token
        ).strip()

        if not token:
            return False

        with Session(self.engine) as session:
            result = session.execute(
                update(NotificationDelivery)
                .where(
                    NotificationDelivery.id
                    == delivery_id,
                    NotificationDelivery.status
                    == "processing",
                    NotificationDelivery.claim_token
                    == token,
                )
                .values(
                    status="failed",
                    updated_at=reference_now,
                    claim_token=None,
                    lease_until=None,
                    last_error=cleaned_error[:2000],
                )
            )

            if result.rowcount != 1:
                session.rollback()
                return False

            session.commit()
            return True

    def get_delivery(
        self,
        *,
        user_id: str,
        channel: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            delivery = session.scalar(
                select(NotificationDelivery)
                .where(
                    NotificationDelivery.user_id
                    == user_id,
                    NotificationDelivery.channel
                    == str(channel).strip().lower(),
                    NotificationDelivery.idempotency_key
                    == idempotency_key,
                )
            )

            if delivery is None:
                return None

            return {
                "id": delivery.id,
                "user_id": delivery.user_id,
                "channel": delivery.channel,
                "idempotency_key": delivery.idempotency_key,
                "status": delivery.status,
                "attempt_count": delivery.attempt_count,
                "last_error": delivery.last_error,
                "sent_at": delivery.sent_at,
            }
