from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from config import (
    VoiceSettings,
    get_voice_settings,
)
from database.connection import engine as default_engine
from models.voice_session_lease import VoiceSessionLease


@dataclass(frozen=True)
class VoiceSessionLeaseDecision:
    acquired: bool
    lease_until: datetime | None
    retry_after_seconds: int


class VoiceSessionLeaseService:
    """
    Durable per-user realtime voice session ownership.

    The database is the source of truth so multiple application workers
    cannot each accept a voice session for the same user independently.
    """

    def __init__(
        self,
        *,
        db_engine: Any | None = None,
        lease_seconds: int | None = None,
    ):
        self.engine = (
            db_engine
            if db_engine is not None
            else default_engine
        )

        configured = (
            get_voice_settings()
            if lease_seconds is None
            else None
        )

        self.lease_seconds = int(
            lease_seconds
            if lease_seconds is not None
            else configured.voice_session_lease_duration_seconds
        )

        if self.lease_seconds < 1:
            raise ValueError(
                "lease_seconds must be at least 1."
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

        if len(normalized) > 100:
            raise ValueError(
                f"{field_name} cannot exceed 100 characters."
            )

        return normalized

    @staticmethod
    def _normalize_now(
        value: datetime | None,
    ) -> datetime:
        reference = (
            value
            if value is not None
            else datetime.now(timezone.utc)
        )

        if reference.tzinfo is not None:
            return reference.astimezone(
                timezone.utc
            ).replace(
                tzinfo=None
            )

        return reference

    @staticmethod
    def _retry_after_seconds(
        lease_until: datetime | None,
        reference_now: datetime,
    ) -> int:
        if lease_until is None:
            return 1

        return max(
            1,
            int(
                math.ceil(
                    (
                        lease_until
                        - reference_now
                    ).total_seconds()
                )
            ),
        )

    def acquire(
        self,
        *,
        user_id: str,
        session_id: str,
        now: datetime | None = None,
    ) -> VoiceSessionLeaseDecision:
        cleaned_user_id = self._normalize(
            user_id,
            "user_id",
        )
        cleaned_session_id = self._normalize(
            session_id,
            "session_id",
        )

        reference_now = self._normalize_now(
            now
        )
        lease_until = (
            reference_now
            + timedelta(
                seconds=self.lease_seconds
            )
        )

        values = {
            "id": cleaned_session_id,
            "user_id": cleaned_user_id,
            "lease_until": lease_until,
            "heartbeat_at": reference_now,
            "created_at": reference_now,
            "updated_at": reference_now,
        }

        dialect_name = self.engine.dialect.name

        if dialect_name == "postgresql":
            statement = postgres_insert(
                VoiceSessionLease
            ).values(**values)
        elif dialect_name == "sqlite":
            statement = sqlite_insert(
                VoiceSessionLease
            ).values(**values)
        else:
            raise ValueError(
                "VoiceSessionLeaseService supports only "
                "PostgreSQL and SQLite."
            )

        statement = statement.on_conflict_do_update(
            index_elements=[
                VoiceSessionLease.user_id,
            ],
            set_={
                "id": cleaned_session_id,
                "lease_until": lease_until,
                "heartbeat_at": reference_now,
                "updated_at": reference_now,
            },
            where=(
                VoiceSessionLease.lease_until
                <= reference_now
            ),
        ).returning(
            VoiceSessionLease.lease_until,
        )

        with Session(self.engine) as session:
            row = session.execute(
                statement
            ).one_or_none()

            if row is not None:
                session.commit()
                return VoiceSessionLeaseDecision(
                    acquired=True,
                    lease_until=row.lease_until,
                    retry_after_seconds=0,
                )

            current_lease_until = session.execute(
                select(
                    VoiceSessionLease.lease_until
                ).where(
                    VoiceSessionLease.user_id
                    == cleaned_user_id
                )
            ).scalar_one_or_none()

        return VoiceSessionLeaseDecision(
            acquired=False,
            lease_until=current_lease_until,
            retry_after_seconds=self._retry_after_seconds(
                current_lease_until,
                reference_now,
            ),
        )

    def heartbeat(
        self,
        *,
        user_id: str,
        session_id: str,
        now: datetime | None = None,
    ) -> bool:
        cleaned_user_id = self._normalize(
            user_id,
            "user_id",
        )
        cleaned_session_id = self._normalize(
            session_id,
            "session_id",
        )

        reference_now = self._normalize_now(
            now
        )
        lease_until = (
            reference_now
            + timedelta(
                seconds=self.lease_seconds
            )
        )

        statement = (
            update(VoiceSessionLease)
            .where(
                VoiceSessionLease.user_id
                == cleaned_user_id,
                VoiceSessionLease.id
                == cleaned_session_id,
                VoiceSessionLease.lease_until
                > reference_now,
            )
            .values(
                lease_until=lease_until,
                heartbeat_at=reference_now,
                updated_at=reference_now,
            )
            .returning(
                VoiceSessionLease.id
            )
        )

        with Session(self.engine) as session:
            row = session.execute(
                statement
            ).one_or_none()
            session.commit()

        return row is not None

    def release(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> bool:
        cleaned_user_id = self._normalize(
            user_id,
            "user_id",
        )
        cleaned_session_id = self._normalize(
            session_id,
            "session_id",
        )

        statement = delete(
            VoiceSessionLease
        ).where(
            VoiceSessionLease.user_id
            == cleaned_user_id,
            VoiceSessionLease.id
            == cleaned_session_id,
        )

        with Session(self.engine) as session:
            result = session.execute(
                statement
            )
            session.commit()

        return bool(
            result.rowcount
        )
