from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.idempotency_record import IdempotencyRecord


class IdempotencyService:
    """
    Durable idempotency coordinator for authenticated APIs.

    Completed requests can be replayed safely. Concurrent requests
    using the same key are rejected until the original request
    completes or its processing lease expires.
    """

    DEFAULT_LEASE_SECONDS = 3600
    DEFAULT_RETENTION_SECONDS = 86400

    def __init__(
        self,
        *,
        db_engine: Any | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        retention_seconds: int = DEFAULT_RETENTION_SECONDS,
    ):
        if lease_seconds < 1:
            raise ValueError(
                "lease_seconds must be at least 1"
            )

        if retention_seconds < lease_seconds:
            raise ValueError(
                "retention_seconds must be at least lease_seconds"
            )

        self.engine = (
            db_engine
            if db_engine is not None
            else default_engine
        )

        self.lease_seconds = int(
            lease_seconds
        )

        self.retention_seconds = int(
            retention_seconds
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

    @staticmethod
    def build_request_hash(
        payload: Any,
    ) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
            default=str,
        )

        return hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()

    def claim_or_replay(
        self,
        *,
        user_id: str,
        endpoint: str,
        idempotency_key: str,
        request_hash: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        cleaned_user_id = self._normalize(
            user_id,
            "user_id",
        )

        cleaned_endpoint = self._normalize(
            endpoint,
            "endpoint",
        ).lower()

        cleaned_key = self._normalize(
            idempotency_key,
            "idempotency_key",
        )

        cleaned_hash = self._normalize(
            request_hash,
            "request_hash",
        ).lower()

        if len(cleaned_key) > 255:
            raise ValueError(
                "idempotency_key cannot exceed 255 characters."
            )

        if len(cleaned_hash) != 64:
            raise ValueError(
                "request_hash must be a SHA-256 hexadecimal digest."
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

        lease_until = (
            reference_now
            + timedelta(
                seconds=self.lease_seconds
            )
        )

        expires_at = (
            reference_now
            + timedelta(
                seconds=self.retention_seconds
            )
        )

        for _ in range(2):
            claim_token = uuid4().hex

            with Session(self.engine) as session:
                record = session.scalar(
                    select(IdempotencyRecord)
                    .where(
                        IdempotencyRecord.user_id
                        == cleaned_user_id,
                        IdempotencyRecord.endpoint
                        == cleaned_endpoint,
                        IdempotencyRecord.idempotency_key
                        == cleaned_key,
                    )
                    .with_for_update()
                )

                if record is None:
                    record = IdempotencyRecord(
                        user_id=cleaned_user_id,
                        endpoint=cleaned_endpoint,
                        idempotency_key=cleaned_key,
                        request_hash=cleaned_hash,
                        status="processing",
                        response_status=None,
                        response_body=None,
                        claim_token=claim_token,
                        lease_until=lease_until,
                        expires_at=expires_at,
                        last_error=None,
                        created_at=reference_now,
                        updated_at=reference_now,
                    )

                    try:
                        session.add(record)
                        session.commit()
                        session.refresh(record)
                    except IntegrityError:
                        session.rollback()
                        continue

                    return {
                        "status": "claimed",
                        "record_id": record.id,
                        "claim_token": claim_token,
                    }

                if record.request_hash != cleaned_hash:
                    return {
                        "status": "conflict",
                        "record_id": record.id,
                    }

                if (
                    record.status == "completed"
                    and record.expires_at > reference_now
                ):
                    return {
                        "status": "replay",
                        "record_id": record.id,
                        "response_status": record.response_status,
                        "response_body": record.response_body,
                    }

                if (
                    record.status == "processing"
                    and record.lease_until is not None
                    and record.lease_until > reference_now
                ):
                    return {
                        "status": "in_progress",
                        "record_id": record.id,
                    }

                record.status = "processing"
                record.claim_token = claim_token
                record.lease_until = lease_until
                record.last_error = None
                record.response_status = None
                record.response_body = None
                record.updated_at = reference_now
                record.expires_at = expires_at

                session.commit()
                session.refresh(record)

                return {
                    "status": "reclaimed",
                    "record_id": record.id,
                    "claim_token": claim_token,
                }

        raise RuntimeError(
            "Could not claim idempotent request."
        )

    def complete(
        self,
        *,
        record_id: int,
        claim_token: str,
        response_status: int,
        response_body: dict[str, Any],
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
            record = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.id
                    == record_id,
                    IdempotencyRecord.status
                    == "processing",
                    IdempotencyRecord.claim_token
                    == token,
                )
            )

            if record is None:
                return False

            record.status = "completed"
            record.response_status = int(
                response_status
            )
            record.response_body = dict(
                response_body
            )
            record.claim_token = None
            record.lease_until = None
            record.last_error = None
            record.updated_at = reference_now

            session.commit()
            return True

    def fail(
        self,
        *,
        record_id: int,
        claim_token: str,
        error: str,
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

        cleaned_error = str(
            error
        ).strip() or "Request processing failed."

        with Session(self.engine) as session:
            record = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.id
                    == record_id,
                    IdempotencyRecord.status
                    == "processing",
                    IdempotencyRecord.claim_token
                    == token,
                )
            )

            if record is None:
                return False

            record.status = "failed"
            record.claim_token = None
            record.lease_until = None
            record.last_error = cleaned_error[:2000]
            record.updated_at = reference_now

            session.commit()
            return True
