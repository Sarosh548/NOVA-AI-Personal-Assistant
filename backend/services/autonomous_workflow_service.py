from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from database.connection import engine as default_engine
from services.workflow_service import WorkflowService


class AutonomousWorkflowService:
    """
    Application-level service for creating scheduled autonomous workflows.

    Responsibilities:
    - validate scheduled workflow input
    - require timezone-aware scheduled datetime
    - accept datetime or ISO 8601 string input
    - normalize scheduled datetime to naive UTC
    - reject scheduled times that are not in the future
    - persist an autonomous pending workflow

    This service does NOT:
    - perform permission checks
    - create confirmations
    - execute tools
    - run schedulers
    """

    def __init__(
        self,
        db_engine: Any | None = None,
        workflow_service: WorkflowService | None = None,
    ):
        self.engine = (
            db_engine
            if db_engine is not None
            else default_engine
        )

        self.workflow_service = (
            workflow_service
            if workflow_service is not None
            else WorkflowService(
                db_engine=self.engine
            )
        )

    @staticmethod
    def _utc_now() -> datetime:
        """
        Return the current time as timezone-aware UTC.
        """
        return datetime.now(
            timezone.utc
        )

    @staticmethod
    def _parse_scheduled_at(
        scheduled_at: datetime | str,
    ) -> datetime:
        """
        Convert supported scheduled_at input into a datetime.

        Supported input:
        - timezone-aware datetime
        - ISO 8601 datetime string

        Naive datetime values are rejected because NOVA must not
        guess the timezone of a scheduled autonomous operation.
        """

        if isinstance(
            scheduled_at,
            datetime,
        ):
            return scheduled_at

        if isinstance(
            scheduled_at,
            str,
        ):
            normalized_value = scheduled_at.strip()

            if not normalized_value:
                raise ValueError(
                    "scheduled_at must be a datetime."
                )

            # Support the common UTC ISO 8601 "Z" suffix.
            if normalized_value.endswith(
                "Z"
            ):
                normalized_value = (
                    normalized_value[:-1]
                    + "+00:00"
                )

            try:
                parsed = datetime.fromisoformat(
                    normalized_value
                )
            except ValueError as exc:
                raise ValueError(
                    "scheduled_at must be a valid ISO 8601 datetime."
                ) from exc

            return parsed

        raise ValueError(
            "scheduled_at must be a datetime."
        )

    @classmethod
    def _normalize_scheduled_at(
        cls,
        scheduled_at: datetime | str,
    ) -> datetime:
        """
        Validate timezone awareness and normalize to naive UTC.

        The rest of NOVA's workflow persistence layer stores
        internal timestamps as naive UTC.
        """

        parsed = cls._parse_scheduled_at(
            scheduled_at
        )

        if parsed.tzinfo is None:
            raise ValueError(
                "scheduled_at must be timezone-aware."
            )

        try:
            normalized = parsed.astimezone(
                timezone.utc
            )
        except (OverflowError, ValueError) as exc:
            raise ValueError(
                "scheduled_at contains an invalid timezone-aware datetime."
            ) from exc

        return normalized.replace(
            tzinfo=None
        )

    def validate_scheduled_at(
        self,
        scheduled_at: datetime | str,
    ) -> datetime:
        """
        Validate a scheduled datetime and return normalized naive UTC.

        Validation rules:
        - input must be a datetime or ISO 8601 string
        - timezone must be explicitly provided
        - scheduled time must be in the future

        This method does not persist or execute anything.
        """

        normalized_scheduled_at = (
            self._normalize_scheduled_at(
                scheduled_at
            )
        )

        now_utc = self._utc_now()

        scheduled_at_aware_utc = (
            normalized_scheduled_at.replace(
                tzinfo=timezone.utc
            )
        )

        if scheduled_at_aware_utc <= now_utc:
            raise ValueError(
                "Scheduled datetime must be in the future."
            )

        return normalized_scheduled_at

    def create_scheduled_workflow(
        self,
        *,
        user_id: str,
        conversation_id: int | None,
        plan: dict[str, Any],
        steps: list[dict[str, Any]],
        scheduled_at: datetime | str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a future scheduled autonomous workflow.

        The workflow is persisted as:

            execution_mode = "autonomous"
            status = "pending"

        The workflow is NOT executed by this method.

        Permission and confirmation decisions must happen upstream
        before this method is called.
        """

        normalized_user_id = str(
            user_id
        ).strip()

        if not normalized_user_id:
            raise ValueError(
                "Workflow user_id is missing."
            )

        if not isinstance(
            plan,
            dict,
        ):
            raise ValueError(
                "Workflow plan must be a dictionary."
            )

        if not isinstance(
            steps,
            list,
        ):
            raise ValueError(
                "Workflow steps must be a list."
            )

        normalized_scheduled_at = (
            self.validate_scheduled_at(
                scheduled_at
            )
        )

        return self.workflow_service.create_workflow(
            user_id=normalized_user_id,
            conversation_id=conversation_id,
            plan=plan,
            steps=steps,
            execution_mode="autonomous",
            status="pending",
            scheduled_at=normalized_scheduled_at,
            idempotency_key=idempotency_key,
        )