from __future__ import annotations

from datetime import datetime
from typing import Any

from services.activity_report_service import (
    ActivityReportService,
)


class ProactiveActivityDigestService:
    """
    Build deterministic notification payloads from NOVA's
    daily activity report.

    Responsibilities:
    - request the deterministic daily activity report
    - decide whether a proactive digest is useful
    - build the notification title/body/metadata
    - preserve the activity report as the source of truth

    This service does NOT:
    - schedule background execution
    - send notifications
    - execute tools
    - call the LLM
    """

    NOTIFICATION_TYPE = "activity"

    def __init__(
        self,
        activity_report_service: (
            ActivityReportService | None
        ) = None,
        highlight_limit: int = 5,
    ):
        if highlight_limit < 1:
            raise ValueError(
                "highlight_limit must be at least 1"
            )

        self.activity_report_service = (
            activity_report_service
            if activity_report_service is not None
            else ActivityReportService()
        )

        self.highlight_limit = highlight_limit

    def build_daily_digest(
        self,
        *,
        user_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Build one deterministic proactive activity digest.

        Returns a stable payload that a future scheduler can pass
        to NotificationService.

        No notification is delivered by this method.
        """

        report = (
            self.activity_report_service
            .get_daily_report(
                user_id=user_id,
                now=now,
                highlight_limit=self.highlight_limit,
            )
        )

        if report.get("error"):
            return {
                "should_notify": False,
                "reason": "report_unavailable",
                "user_id": user_id,
                "notification_type": (
                    self.NOTIFICATION_TYPE
                ),
                "title": None,
                "body": None,
                "metadata": {
                    "timezone": report.get(
                        "timezone",
                        "Asia/Karachi",
                    ),
                    "total_events": report.get(
                        "total_events",
                        0,
                    ),
                    "important_event_count": report.get(
                        "important_event_count",
                        0,
                    ),
                },
                "report": report,
            }

        total_events = int(
            report.get(
                "total_events",
                0,
            )
        )

        if total_events <= 0:
            return {
                "should_notify": False,
                "reason": "no_activity",
                "user_id": user_id,
                "notification_type": (
                    self.NOTIFICATION_TYPE
                ),
                "title": None,
                "body": None,
                "metadata": {
                    "timezone": report.get(
                        "timezone",
                        "Asia/Karachi",
                    ),
                    "total_events": 0,
                    "important_event_count": 0,
                },
                "report": report,
            }

        body = self._build_body(
            report
        )

        title = (
            "NOVA daily activity update"
        )

        metadata = {
            "timezone": report.get(
                "timezone",
                "Asia/Karachi",
            ),
            "total_events": total_events,
            "important_event_count": int(
                report.get(
                    "important_event_count",
                    len(
                        report.get(
                            "important_events",
                            [],
                        )
                    ),
                )
            ),
            "successful_count": int(
                report.get(
                    "successful_count",
                    0,
                )
            ),
            "pending_count": int(
                report.get(
                    "pending_count",
                    0,
                )
            ),
            "partial_count": int(
                report.get(
                    "partial_count",
                    0,
                )
            ),
            "failed_count": int(
                report.get(
                    "failed_count",
                    0,
                )
            ),
            "blocked_count": int(
                report.get(
                    "blocked_count",
                    0,
                )
            ),
        }

        return {
            "should_notify": True,
            "reason": "activity_available",
            "user_id": user_id,
            "notification_type": (
                self.NOTIFICATION_TYPE
            ),
            "title": title,
            "body": body,
            "metadata": metadata,
            "report": report,
        }

    @staticmethod
    def _build_body(
        report: dict[str, Any],
    ) -> str:
        report_text = str(
            report.get(
                "report_text"
            )
            or ""
        ).strip()

        important_events = report.get(
            "important_events",
            [],
        )

        lines = []

        if report_text:
            lines.append(
                report_text
            )

        for event in important_events:
            if not isinstance(
                event,
                dict,
            ):
                continue

            title = str(
                event.get(
                    "title"
                )
                or ""
            ).strip()

            summary = str(
                event.get(
                    "summary"
                )
                or ""
            ).strip()

            if not title:
                continue

            if summary:
                lines.append(
                    f"{title}: {summary}"
                )
            else:
                lines.append(
                    title
                )

        return "\n".join(lines).strip()