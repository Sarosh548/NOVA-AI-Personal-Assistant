from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from services.activity_event_service import (
    ActivityEventService,
)


class ActivityReportService:
    """
    Deterministic activity reporting service for NOVA.

    Responsibilities:
    - calculate a user's local reporting window
    - retrieve durable activity events
    - aggregate activity by status and event type
    - expose recent important events
    - build a concise deterministic daily report

    The service does NOT:
    - execute tools
    - create events
    - modify event records
    - call an LLM
    """

    DEFAULT_TIMEZONE = "Asia/Karachi"

    def __init__(
        self,
        activity_event_service: (
            ActivityEventService | None
        ) = None,
        timezone_name: str = DEFAULT_TIMEZONE,
    ):
        self.activity_event_service = (
            activity_event_service
            if activity_event_service is not None
            else ActivityEventService()
        )

        try:
            self.timezone = ZoneInfo(
                timezone_name
            )
        except Exception as exc:
            raise ValueError(
                f"Invalid report timezone '{timezone_name}'."
            ) from exc

    def get_local_day_window(
        self,
        *,
        now: datetime | None = None,
    ) -> tuple[datetime, datetime]:
        """
        Return today's local-day window as naive UTC datetimes.

        Database timestamps are stored as naive UTC, so the returned
        window is:

            local midnight -> next local midnight

        converted to naive UTC.
        """

        if now is None:
            now = datetime.now(
                timezone.utc
            )

        if now.tzinfo is None:
            now = now.replace(
                tzinfo=timezone.utc
            )

        local_now = now.astimezone(
            self.timezone
        )

        local_start = datetime.combine(
            local_now.date(),
            time.min,
            tzinfo=self.timezone,
        )

        local_end = local_start + timedelta(
            days=1
        )

        utc_start = local_start.astimezone(
            timezone.utc
        ).replace(
            tzinfo=None
        )

        utc_end = local_end.astimezone(
            timezone.utc
        ).replace(
            tzinfo=None
        )

        return (
            utc_start,
            utc_end,
        )

    def get_daily_report(
        self,
        *,
        user_id: str,
        now: datetime | None = None,
        recent_limit: int = 10,
    ) -> dict[str, Any]:
        """
        Build a deterministic daily activity report.

        The report covers the user's current local calendar day.
        """

        utc_start, utc_end = (
            self.get_local_day_window(
                now=now
            )
        )

        events = self.activity_event_service.list_events(
            user_id=user_id,
            since=utc_start,
            limit=500,
        )

        # list_events() returns newest-first. Keep only the current
        # local day because its "since" filter is inclusive.
        day_events = [
            event
            for event in events
            if (
                event["created_at"]
                < utc_end
            )
        ]

        status_counts = Counter()
        event_type_counts = Counter()

        for event in day_events:
            status_counts[
                event["status"]
            ] += 1

            event_type_counts[
                event["event_type"]
            ] += 1

        recent_limit = max(
            1,
            min(
                int(recent_limit),
                50,
            ),
        )

        recent_events = day_events[
            :recent_limit
        ]

        successful_count = (
            status_counts.get(
                "success",
                0,
            )
        )

        pending_count = (
            status_counts.get(
                "pending",
                0,
            )
        )

        partial_count = (
            status_counts.get(
                "partial",
                0,
            )
        )

        failed_count = (
            status_counts.get(
                "failed",
                0,
            )
        )

        blocked_count = (
            status_counts.get(
                "blocked",
                0,
            )
        )

        report_text = self._build_report_text(
            total_events=len(
                day_events
            ),
            successful_count=successful_count,
            pending_count=pending_count,
            partial_count=partial_count,
            failed_count=failed_count,
            blocked_count=blocked_count,
        )

        return {
            "user_id": user_id,
            "timezone": self.timezone.key,
            "window_start_utc": utc_start,
            "window_end_utc": utc_end,
            "total_events": len(
                day_events
            ),
            "status_counts": dict(
                status_counts
            ),
            "event_type_counts": dict(
                event_type_counts
            ),
            "successful_count": successful_count,
            "pending_count": pending_count,
            "partial_count": partial_count,
            "failed_count": failed_count,
            "blocked_count": blocked_count,
            "recent_events": recent_events,
            "report_text": report_text,
        }

    @staticmethod
    def _build_report_text(
        *,
        total_events: int,
        successful_count: int,
        pending_count: int,
        partial_count: int,
        failed_count: int,
        blocked_count: int,
    ) -> str:
        """
        Build a deterministic human-readable daily report.
        """

        if total_events == 0:
            return (
                "Aaj abhi koi NOVA activity record nahi hui."
            )

        parts = [
            f"Aaj {total_events} activities hui hain."
        ]

        parts.append(
            f"{successful_count} successfully complete hui."
        )

        unresolved_count = (
            pending_count
            + partial_count
            + failed_count
            + blocked_count
        )

        if unresolved_count:
            parts.append(
                f"{pending_count} pending hain."
            )

            parts.append(
                f"{partial_count} partially complete hui."
            )

            parts.append(
                f"{failed_count} fail hui."
            )

            parts.append(
                f"{blocked_count} blocked hain."
            )

        return " ".join(parts)