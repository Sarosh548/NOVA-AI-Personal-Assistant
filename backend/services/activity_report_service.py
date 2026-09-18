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
    - select important daily highlights
    - avoid redundant highlights for the same entity/workflow
    - expose recent activity
    - build a concise deterministic daily report

    The service does NOT:
    - execute tools
    - create events
    - modify event records
    - call an LLM
    """

    DEFAULT_TIMEZONE = "Asia/Karachi"

    HIGHLIGHT_LIMIT = 5

    STATUS_PRIORITY = {
        "blocked": 400,
        "failed": 350,
        "partial": 300,
        "pending": 200,
        "success": 100,
        "info": 50,
    }

    TERMINAL_WORKFLOW_STATUSES = {
        "completed",
        "partial",
        "failed",
        "blocked",
    }

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
        highlight_limit: int = HIGHLIGHT_LIMIT,
    ) -> dict[str, Any]:
        """
        Build a deterministic daily activity report.

        The report covers the user's current local calendar day.

        `recent_events` preserves chronological recency.

        `important_events` contains de-duplicated highlights selected
        deterministically from the stored events.
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
            if event["created_at"] < utc_end
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

        highlight_limit = max(
            1,
            min(
                int(highlight_limit),
                20,
            ),
        )

        important_events = (
            self._select_important_events(
                day_events,
                limit=highlight_limit,
            )
        )

        successful_count = status_counts.get(
            "success",
            0,
        )

        pending_count = status_counts.get(
            "pending",
            0,
        )

        partial_count = status_counts.get(
            "partial",
            0,
        )

        failed_count = status_counts.get(
            "failed",
            0,
        )

        blocked_count = status_counts.get(
            "blocked",
            0,
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
            "important_events": important_events,
            "important_event_count": len(
                important_events
            ),
            "report_text": report_text,
        }

    def _select_important_events(
        self,
        events: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        Select deterministic daily highlights.

        Rules:
        1. Higher-severity statuses rank first.
        2. Terminal workflow events outrank normal workflow info.
        3. The latest event for the same task/reminder is preferred.
        4. A terminal workflow suppresses that workflow's scheduled
           event as a duplicate highlight.
        5. Original event dictionaries are never modified.
        """

        if not events:
            return []

        newest_events = list(events)

        terminal_workflows = {
            self._workflow_identifier(event)
            for event in newest_events
            if (
                self._workflow_identifier(event)
                is not None
                and self._is_terminal_workflow_event(
                    event
                )
            )
        }

        candidates: list[dict[str, Any]] = []

        seen_entities: set[tuple[str, str]] = set()
        seen_workflows: set[int] = set()

        for event in newest_events:
            workflow_id = (
                self._workflow_identifier(
                    event
                )
            )

            if (
                workflow_id is not None
                and workflow_id in terminal_workflows
                and event.get("event_type")
                == "workflow_scheduled"
            ):
                continue

            entity_key = self._entity_key(
                event
            )

            if entity_key is not None:
                if entity_key in seen_entities:
                    continue

                seen_entities.add(
                    entity_key
                )

            if workflow_id is not None:
                terminal_event = (
                    self._is_terminal_workflow_event(
                        event
                    )
                )

                if terminal_event:
                    seen_workflows.add(
                        workflow_id
                    )

                elif (
                    workflow_id in seen_workflows
                ):
                    continue

            candidates.append(event)

        ranked = sorted(
            candidates,
            key=self._highlight_sort_key,
            reverse=True,
        )

        return [
            dict(event)
            for event in ranked[:limit]
        ]

    def _highlight_sort_key(
        self,
        event: dict[str, Any],
    ) -> tuple[int, int, float, int]:
        """
        Build a stable deterministic highlight ranking key.

        Created timestamps are already newest-first in the source,
        but timestamp/id are included as a final deterministic tie-break.
        """

        status = str(
            event.get("status")
            or "info"
        ).strip().lower()

        status_priority = self.STATUS_PRIORITY.get(
            status,
            0,
        )

        event_type = str(
            event.get("event_type")
            or ""
        ).strip().lower()

        type_priority = 0

        if (
            event_type.startswith(
                "workflow_"
            )
            and event_type != "workflow_scheduled"
        ):
            type_priority += 20

        elif event_type.startswith(
            "reminder_"
        ):
            type_priority += 10

        elif event_type.startswith(
            "task_"
        ):
            type_priority += 10

        created_at = event.get(
            "created_at"
        )

        timestamp_value = 0.0

        if isinstance(
            created_at,
            datetime,
        ):
            timestamp_value = (
                created_at.replace(
                    tzinfo=timezone.utc
                ).timestamp()
            )

        event_id = event.get(
            "id"
        )

        try:
            normalized_event_id = int(
                event_id
            )
        except (
            TypeError,
            ValueError,
        ):
            normalized_event_id = 0

        return (
            status_priority,
            type_priority,
            timestamp_value,
            normalized_event_id,
        )

    @staticmethod
    def _entity_key(
        event: dict[str, Any],
    ) -> tuple[str, str] | None:
        """
        Return a stable task/reminder entity key when available.
        """

        source = str(
            event.get("source")
            or ""
        ).strip().lower()

        metadata = event.get(
            "metadata"
        )

        if not isinstance(
            metadata,
            dict,
        ):
            metadata = {}

        tool = str(
            metadata.get("tool")
            or ""
        ).strip().lower()

        entity_id = metadata.get(
            "entity_id"
        )

        if tool not in {
            "task",
            "reminder",
        }:
            if source == "tool_router":
                event_type = str(
                    event.get("event_type")
                    or ""
                ).strip().lower()

                if event_type.startswith(
                    "task_"
                ):
                    tool = "task"

                elif event_type.startswith(
                    "reminder_"
                ):
                    tool = "reminder"

        if tool not in {
            "task",
            "reminder",
        }:
            return None

        if entity_id is None:
            return None

        return (
            tool,
            str(entity_id),
        )

    @staticmethod
    def _workflow_identifier(
        event: dict[str, Any],
    ) -> int | None:
        """
        Resolve workflow ID from the event's linkage or metadata.
        """

        workflow_id = event.get(
            "workflow_id"
        )

        if workflow_id is None:
            metadata = event.get(
                "metadata"
            )

            if isinstance(
                metadata,
                dict,
            ):
                workflow_id = metadata.get(
                    "workflow_id"
                )

        if workflow_id is None:
            return None

        try:
            return int(
                workflow_id
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

    def _is_terminal_workflow_event(
        self,
        event: dict[str, Any],
    ) -> bool:
        """
        Return True for autonomous workflow terminal events.
        """

        event_type = str(
            event.get("event_type")
            or ""
        ).strip().lower()

        if not event_type.startswith(
            "workflow_"
        ):
            return False

        suffix = event_type[
            len("workflow_") :
        ]

        return suffix in (
            self.TERMINAL_WORKFLOW_STATUSES
        )

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