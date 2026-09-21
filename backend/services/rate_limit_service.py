from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any

from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from database.connection import engine as default_engine
from models.rate_limit_counter import RateLimitCounter


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_after_seconds: int


class RateLimitService:
    """
    Durable fixed-window rate limiter.

    The counter is stored in PostgreSQL/SQLite and updated with an
    atomic upsert, making the decision consistent across application
    workers that share the same database.
    """

    def __init__(
        self,
        *,
        db_engine: Any | None = None,
    ):
        self.engine = (
            db_engine
            if db_engine is not None
            else default_engine
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
    def _window_start(
        reference_now: datetime,
        window_seconds: int,
    ) -> datetime:
        epoch_seconds = int(
            reference_now.replace(
                tzinfo=timezone.utc
            ).timestamp()
        )

        window_epoch = (
            epoch_seconds
            // window_seconds
        ) * window_seconds

        return datetime.fromtimestamp(
            window_epoch,
            tz=timezone.utc,
        ).replace(
            tzinfo=None
        )

    def _build_upsert(
        self,
        *,
        principal_key: str,
        scope: str,
        window_start: datetime,
        now: datetime,
        limit: int,
    ):
        values = {
            "principal_key": principal_key,
            "scope": scope,
            "window_start": window_start,
            "request_count": 1,
            "updated_at": now,
        }

        dialect_name = self.engine.dialect.name

        if dialect_name == "postgresql":
            statement = postgres_insert(
                RateLimitCounter
            ).values(**values)
        elif dialect_name == "sqlite":
            statement = sqlite_insert(
                RateLimitCounter
            ).values(**values)
        else:
            raise ValueError(
                "RateLimitService supports only "
                "PostgreSQL and SQLite."
            )

        excluded = statement.excluded

        next_count = case(
            (
                RateLimitCounter.window_start
                != excluded.window_start,
                1,
            ),
            (
                RateLimitCounter.request_count
                < limit,
                RateLimitCounter.request_count
                + 1,
            ),
            else_=RateLimitCounter.request_count,
        )

        return (
            statement.on_conflict_do_update(
                index_elements=[
                    RateLimitCounter.principal_key,
                    RateLimitCounter.scope,
                ],
                set_={
                    "window_start": (
                        excluded.window_start
                    ),
                    "request_count": next_count,
                    "updated_at": now,
                },
            )
            .returning(
                RateLimitCounter.window_start,
                RateLimitCounter.request_count,
            )
        )

    def check_and_consume(
        self,
        *,
        principal_key: str,
        scope: str,
        limit: int,
        window_seconds: int,
        now: datetime | None = None,
    ) -> RateLimitDecision:
        cleaned_principal = self._normalize(
            principal_key,
            "principal_key",
        )

        cleaned_scope = self._normalize(
            scope,
            "scope",
        ).lower()

        if limit < 1:
            raise ValueError(
                "limit must be at least 1."
            )

        if window_seconds < 1:
            raise ValueError(
                "window_seconds must be at least 1."
            )

        reference_now = self._normalize_now(
            now
        )

        window_start = self._window_start(
            reference_now,
            window_seconds,
        )

        statement = self._build_upsert(
            principal_key=cleaned_principal,
            scope=cleaned_scope,
            window_start=window_start,
            now=reference_now,
            limit=limit,
        )

        with Session(self.engine) as session:
            row = session.execute(
                statement
            ).one()
            session.commit()

        current_window_start = row.window_start
        request_count = int(
            row.request_count
        )

        reset_at = (
            current_window_start
            + timedelta(
                seconds=window_seconds
            )
        )

        reference_aware = reference_now.replace(
            tzinfo=timezone.utc
        )

        reset_after_seconds = max(
            1,
            int(
                math.ceil(
                    (
                        reset_at.replace(
                            tzinfo=timezone.utc
                        )
                        - reference_aware
                    ).total_seconds()
                )
            ),
        )

        return RateLimitDecision(
            allowed=request_count <= limit,
            limit=limit,
            remaining=max(
                0,
                limit - request_count,
            ),
            reset_after_seconds=(
                reset_after_seconds
            ),
        )
