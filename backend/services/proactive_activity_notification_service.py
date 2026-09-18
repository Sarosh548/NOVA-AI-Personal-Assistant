from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.activity_digest_delivery import (
    ActivityDigestDelivery,
)
from services.activity_report_service import (
    ActivityReportService,
)
from services.notification_service import (
    NotificationService,
)
from services.proactive_activity_digest_service import (
    ProactiveActivityDigestService,
)


class ProactiveActivityNotificationService:
    """
    Durable proactive activity notification coordinator.

    Responsibilities:
    - build the deterministic daily activity digest
    - claim one user/day delivery slot atomically
    - deliver through NotificationService
    - mark successful delivery durably
    - persist failures for later retry
    - recover abandoned processing claims after lease expiry

    This service does NOT:
    - schedule polling loops
    - execute tools
    - call the LLM
    - change activity-report semantics
    """

    DIGEST_TYPE = "daily_activity"
    DEFAULT_LEASE_SECONDS = 300

    def __init__(
        self,
        *,
        db_engine: Any | None = None,
        activity_digest_service: (
            ProactiveActivityDigestService | None
        ) = None,
        notification_service: (
            NotificationService | None
        ) = None,
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

        self.activity_digest_service = (
            activity_digest_service
            if activity_digest_service is not None
            else ProactiveActivityDigestService(
                activity_report_service=(
                    ActivityReportService(
                        db_engine=self.engine
                    )
                )
            )
        )

        self.notification_service = (
            notification_service
            if notification_service is not None
            else NotificationService()
        )

        self.lease_seconds = lease_seconds

    @staticmethod
    def _utc_now_naive() -> datetime:
        return datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    @staticmethod
    def _normalize_reference_datetime(
        value: datetime | None,
    ) -> datetime:
        if value is None:
            return datetime.now(
                timezone.utc
            ).replace(
                tzinfo=None
            )

        if value.tzinfo is None:
            return value

        return value.astimezone(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    @staticmethod
    def _local_date(
        *,
        reference_datetime: datetime,
        timezone_name: str,
    ):
        timezone_info = ZoneInfo(
            timezone_name
        )

        aware_reference = (
            reference_datetime
        )

        if (
            aware_reference.tzinfo
            is None
        ):
            aware_reference = (
                aware_reference.replace(
                    tzinfo=timezone.utc
                )
            )

        return aware_reference.astimezone(
            timezone_info
        ).date()

    @classmethod
    def build_delivery_key(
        cls,
        *,
        user_id: str,
        digest_date,
        digest_type: str = DIGEST_TYPE,
    ) -> str:
        cleaned_user_id = (
            str(user_id).strip()
        )

        cleaned_type = (
            str(digest_type).strip().lower()
        )

        if not cleaned_user_id:
            raise ValueError(
                "Digest delivery user_id cannot be empty."
            )

        if not cleaned_type:
            raise ValueError(
                "Digest delivery type cannot be empty."
            )

        return (
            f"nova:{cleaned_type}:"
            f"{cleaned_user_id}:"
            f"{digest_date.isoformat()}"
        )

    def claim_daily_digest(
        self,
        *,
        user_id: str,
        digest_date,
        digest_type: str = DIGEST_TYPE,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Atomically claim one daily digest delivery slot.

        A successful claim returns a unique claim token.

        Existing states:
        - sent: never claim again
        - processing + active lease: skip
        - processing + expired lease: reclaim
        - failed: retry
        """

        cleaned_user_id = (
            str(user_id).strip()
        )

        cleaned_type = (
            str(digest_type).strip().lower()
        )

        if not cleaned_user_id:
            raise ValueError(
                "Digest delivery user_id cannot be empty."
            )

        if not cleaned_type:
            raise ValueError(
                "Digest delivery type cannot be empty."
            )

        reference_now = (
            self._normalize_reference_datetime(
                now
            )
        )

        delivery_key = (
            self.build_delivery_key(
                user_id=cleaned_user_id,
                digest_date=digest_date,
                digest_type=cleaned_type,
            )
        )

        for _ in range(2):
            claim_token = uuid4().hex
            lease_until = (
                reference_now
                + timedelta(
                    seconds=self.lease_seconds
                )
            )

            with Session(
                self.engine
            ) as session:
                delivery = session.scalar(
                    select(
                        ActivityDigestDelivery
                    )
                    .where(
                        ActivityDigestDelivery.user_id
                        == cleaned_user_id,
                        ActivityDigestDelivery.digest_date
                        == digest_date,
                        ActivityDigestDelivery.digest_type
                        == cleaned_type,
                    )
                    .with_for_update()
                )

                if delivery is None:
                    delivery = ActivityDigestDelivery(
                        user_id=cleaned_user_id,
                        digest_date=digest_date,
                        digest_type=cleaned_type,
                        delivery_key=delivery_key,
                        status="processing",
                        attempt_count=1,
                        claim_token=claim_token,
                        lease_until=lease_until,
                        last_attempt_at=reference_now,
                        sent_at=None,
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

                        return {
                            "claimed": True,
                            "reason": "claimed",
                            "delivery_id": delivery.id,
                            "delivery_key": delivery.delivery_key,
                            "claim_token": claim_token,
                            "status": delivery.status,
                            "attempt_count": (
                                delivery.attempt_count
                            ),
                            "digest_date": delivery.digest_date,
                            "digest_type": delivery.digest_type,
                        }

                    except IntegrityError:
                        session.rollback()
                        continue

                if delivery.status == "sent":
                    return {
                        "claimed": False,
                        "reason": "already_sent",
                        "delivery_id": delivery.id,
                        "delivery_key": delivery.delivery_key,
                        "claim_token": None,
                        "status": delivery.status,
                        "attempt_count": (
                            delivery.attempt_count
                        ),
                        "digest_date": delivery.digest_date,
                        "digest_type": delivery.digest_type,
                    }

                if (
                    delivery.status == "processing"
                    and delivery.lease_until is not None
                    and delivery.lease_until
                    > reference_now
                ):
                    return {
                        "claimed": False,
                        "reason": "in_progress",
                        "delivery_id": delivery.id,
                        "delivery_key": delivery.delivery_key,
                        "claim_token": None,
                        "status": delivery.status,
                        "attempt_count": (
                            delivery.attempt_count
                        ),
                        "digest_date": delivery.digest_date,
                        "digest_type": delivery.digest_type,
                    }

                delivery.status = "processing"
                delivery.attempt_count = (
                    int(
                        delivery.attempt_count
                    )
                    + 1
                )
                delivery.claim_token = claim_token
                delivery.lease_until = lease_until
                delivery.last_attempt_at = (
                    reference_now
                )
                delivery.last_error = None
                delivery.updated_at = (
                    reference_now
                )

                session.commit()

                return {
                    "claimed": True,
                    "reason": "reclaimed"
                    if delivery.status
                    == "processing"
                    else "retry_claimed",
                    "delivery_id": delivery.id,
                    "delivery_key": delivery.delivery_key,
                    "claim_token": claim_token,
                    "status": delivery.status,
                    "attempt_count": (
                        delivery.attempt_count
                    ),
                    "digest_date": delivery.digest_date,
                    "digest_type": delivery.digest_type,
                }

        raise RuntimeError(
            "Could not claim activity digest delivery "
            "after concurrent insertion retry."
        )

    def mark_sent(
        self,
        *,
        delivery_id: int,
        claim_token: str,
        sent_at: datetime | None = None,
    ) -> bool:
        reference_time = (
            self._normalize_reference_datetime(
                sent_at
            )
        )

        with Session(
            self.engine
        ) as session:
            statement = (
                update(
                    ActivityDigestDelivery
                )
                .where(
                    ActivityDigestDelivery.id
                    == delivery_id,
                    ActivityDigestDelivery.claim_token
                    == claim_token,
                    ActivityDigestDelivery.status
                    == "processing",
                )
                .values(
                    status="sent",
                    lease_until=None,
                    sent_at=reference_time,
                    last_error=None,
                    updated_at=reference_time,
                )
            )

            result = session.execute(
                statement
            )

            session.commit()

            return (
                result.rowcount == 1
            )

    def mark_failed(
        self,
        *,
        delivery_id: int,
        claim_token: str,
        error: str,
        failed_at: datetime | None = None,
    ) -> bool:
        reference_time = (
            self._normalize_reference_datetime(
                failed_at
            )
        )

        cleaned_error = str(
            error
        ).strip()

        if not cleaned_error:
            cleaned_error = (
                "Notification delivery failed."
            )

        with Session(
            self.engine
        ) as session:
            statement = (
                update(
                    ActivityDigestDelivery
                )
                .where(
                    ActivityDigestDelivery.id
                    == delivery_id,
                    ActivityDigestDelivery.claim_token
                    == claim_token,
                    ActivityDigestDelivery.status
                    == "processing",
                )
                .values(
                    status="failed",
                    lease_until=None,
                    last_error=cleaned_error[
                        :2000
                    ],
                    updated_at=reference_time,
                )
            )

            result = session.execute(
                statement
            )

            session.commit()

            return (
                result.rowcount == 1
            )

    def get_delivery(
        self,
        *,
        user_id: str,
        digest_date,
        digest_type: str = DIGEST_TYPE,
    ) -> dict[str, Any] | None:
        with Session(
            self.engine
        ) as session:
            delivery = session.scalar(
                select(
                    ActivityDigestDelivery
                ).where(
                    ActivityDigestDelivery.user_id
                    == str(
                        user_id
                    ).strip(),
                    ActivityDigestDelivery.digest_date
                    == digest_date,
                    ActivityDigestDelivery.digest_type
                    == str(
                        digest_type
                    ).strip().lower(),
                )
            )

            if delivery is None:
                return None

            return self._delivery_to_dict(
                delivery
            )

    def deliver_daily_activity_digest(
        self,
        *,
        user_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Build, claim, and deliver one daily activity digest.
        """

        digest = (
            self.activity_digest_service
            .build_daily_digest(
                user_id=user_id,
                now=now,
            )
        )

        if not digest.get(
            "should_notify",
            False,
        ):
            return {
                "delivered": False,
                "skipped": True,
                "reason": digest.get(
                    "reason",
                    "not_required",
                ),
                "digest": digest,
                "delivery": None,
            }

        timezone_name = str(
            digest.get(
                "metadata",
                {},
            ).get(
                "timezone",
                "Asia/Karachi",
            )
        )

        reference_now = (
            self._normalize_reference_datetime(
                now
            )
        )

        digest_date = self._local_date(
            reference_datetime=reference_now,
            timezone_name=timezone_name,
        )

        claim = self.claim_daily_digest(
            user_id=user_id,
            digest_date=digest_date,
            digest_type=self.DIGEST_TYPE,
            now=reference_now,
        )

        if not claim["claimed"]:
            return {
                "delivered": False,
                "skipped": True,
                "reason": claim["reason"],
                "digest": digest,
                "delivery": claim,
            }

        metadata = dict(
            digest.get(
                "metadata",
                {},
            )
        )

        metadata.update(
            {
                "delivery_key": claim[
                    "delivery_key"
                ],
                "digest_date": (
                    digest_date.isoformat()
                ),
                "attempt_count": claim[
                    "attempt_count"
                ],
            }
        )

        try:
            delivered = (
                self.notification_service.notify(
                    user_id=user_id,
                    title=digest["title"],
                    body=digest["body"],
                    notification_type=(
                        digest[
                            "notification_type"
                        ]
                    ),
                    metadata=metadata,
                )
            )

        except Exception as exc:
            self.mark_failed(
                delivery_id=claim[
                    "delivery_id"
                ],
                claim_token=claim[
                    "claim_token"
                ],
                error=str(exc),
                failed_at=reference_now,
            )

            return {
                "delivered": False,
                "skipped": False,
                "reason": (
                    "notification_exception"
                ),
                "digest": digest,
                "delivery": {
                    **claim,
                    "status": "failed",
                },
            }

        if not delivered:
            self.mark_failed(
                delivery_id=claim[
                    "delivery_id"
                ],
                claim_token=claim[
                    "claim_token"
                ],
                error=(
                    "Notification service "
                    "reported delivery failure."
                ),
                failed_at=reference_now,
            )

            return {
                "delivered": False,
                "skipped": False,
                "reason": "notification_failed",
                "digest": digest,
                "delivery": {
                    **claim,
                    "status": "failed",
                },
            }

        marked_sent = self.mark_sent(
            delivery_id=claim[
                "delivery_id"
            ],
            claim_token=claim[
                "claim_token"
            ],
            sent_at=reference_now,
        )

        if not marked_sent:
            return {
                "delivered": True,
                "skipped": False,
                "reason": (
                    "delivered_but_state_not_confirmed"
                ),
                "digest": digest,
                "delivery": {
                    **claim,
                    "status": "processing",
                },
            }

        return {
            "delivered": True,
            "skipped": False,
            "reason": "delivered",
            "digest": digest,
            "delivery": {
                **claim,
                "status": "sent",
            },
        }

    @staticmethod
    def _delivery_to_dict(
        delivery: ActivityDigestDelivery,
    ) -> dict[str, Any]:
        return {
            "id": delivery.id,
            "user_id": delivery.user_id,
            "digest_date": delivery.digest_date,
            "digest_type": delivery.digest_type,
            "delivery_key": delivery.delivery_key,
            "status": delivery.status,
            "attempt_count": delivery.attempt_count,
            "lease_until": delivery.lease_until,
            "last_attempt_at": delivery.last_attempt_at,
            "sent_at": delivery.sent_at,
            "last_error": delivery.last_error,
            "created_at": delivery.created_at,
            "updated_at": delivery.updated_at,
        }