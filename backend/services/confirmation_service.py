from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database.connection import engine
from models.confirmation import Confirmation


class ConfirmationService:

    VALID_STATUSES = {
        "pending",
        "approved",
        "rejected",
        "expired",
        "processing",
        "consumed",
        "failed",
    }

    APPROVAL_RESPONSES = {
        "yes",
        "yes please",
        "yeah",
        "yeah please",
        "yep",
        "yup",
        "sure",
        "sure thing",
        "go ahead",
        "do it",
        "approve",
        "approved",
        "confirm",
        "confirmed",
        "haan",
        "han",
        "jee",
        "ji",
        "ji haan",
    }

    REJECTION_RESPONSES = {
        "no",
        "no thanks",
        "no thank you",
        "nope",
        "don't",
        "do not",
        "cancel",
        "reject",
        "rejected",
        "deny",
        "denied",
        "nah",
        "nahin",
        "nahi",
    }

    def _utc_now_naive(self) -> datetime:
        """
        Return current UTC time as a naive datetime.

        NOVA currently stores database timestamps as naive UTC.
        """

        return datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

    def parse_response(
        self,
        message: str,
    ) -> str | None:
        """
        Detect a clear confirmation response.

        Returns:

            "approve"
            "reject"
            None

        Only clear, intentionally short confirmation phrases
        are recognized.
        """

        normalized = " ".join(
            str(message)
            .strip()
            .lower()
            .split()
        )

        if not normalized:
            return None

        if normalized in self.APPROVAL_RESPONSES:
            return "approve"

        if normalized in self.REJECTION_RESPONSES:
            return "reject"

        return None

    def create_confirmation(
        self,
        user_id: str,
        conversation_id: int | None,
        tool: str,
        action: str,
        data: dict[str, Any],
        reason: str,
        expires_in_seconds: int = 300,
    ) -> int:
        """
        Create a new pending confirmation request.

        The exact tool/action/data are stored so that a later
        approval can execute the exact approved request.
        """

        normalized_tool = str(tool).strip().lower()
        normalized_action = str(action).strip().lower()
        cleaned_reason = str(reason).strip()

        if not normalized_tool:
            raise ValueError(
                "Tool name is missing."
            )

        if not normalized_action:
            raise ValueError(
                "Action name is missing."
            )

        if not cleaned_reason:
            raise ValueError(
                "Confirmation reason is missing."
            )

        if not isinstance(data, dict):
            raise ValueError(
                "Confirmation data must be a dictionary."
            )

        if expires_in_seconds <= 0:
            raise ValueError(
                "Confirmation expiry must be greater than zero."
            )

        now = self._utc_now_naive()

        confirmation = Confirmation(
            user_id=user_id,
            conversation_id=conversation_id,
            tool=normalized_tool,
            action=normalized_action,
            data=data,
            reason=cleaned_reason,
            status="pending",
            created_at=now,
            expires_at=(
                now
                + timedelta(
                    seconds=expires_in_seconds
                )
            ),
            resolved_at=None,
        )

        with Session(engine) as session:
            session.add(confirmation)
            session.commit()
            session.refresh(confirmation)

            return confirmation.id

    def _expire_if_needed(
        self,
        confirmation: Confirmation,
        now: datetime | None = None,
    ) -> bool:
        """
        Mark a pending confirmation as expired when its
        expiration time has passed.

        Returns True when the record was changed.
        """

        if confirmation.status != "pending":
            return False

        current_time = (
            now
            if now is not None
            else self._utc_now_naive()
        )

        if confirmation.expires_at <= current_time:
            confirmation.status = "expired"
            confirmation.resolved_at = current_time
            return True

        return False

    def get_confirmation(
        self,
        user_id: str,
        confirmation_id: int,
    ) -> dict | None:
        """
        Return a confirmation owned by the specified user.

        Expired pending confirmations are automatically marked
        as expired before returning.
        """

        with Session(engine) as session:
            confirmation = session.scalar(
                select(Confirmation).where(
                    Confirmation.id == confirmation_id,
                    Confirmation.user_id == user_id,
                )
            )

            if confirmation is None:
                return None

            changed = self._expire_if_needed(
                confirmation
            )

            if changed:
                session.commit()
                session.refresh(confirmation)

            return self._to_dict(
                confirmation
            )

    def get_latest_pending_confirmation(
        self,
        user_id: str,
        conversation_id: int | None = None,
    ) -> dict | None:
        """
        Return the latest still-pending confirmation.

        ID is used as a deterministic tie-breaker when multiple
        confirmations have the same created_at timestamp.
        """

        with Session(engine) as session:
            statement = (
                select(Confirmation)
                .where(
                    Confirmation.user_id == user_id,
                    Confirmation.status == "pending",
                )
                .order_by(
                    Confirmation.created_at.desc(),
                    Confirmation.id.desc(),
                )
            )

            if conversation_id is not None:
                statement = statement.where(
                    Confirmation.conversation_id
                    == conversation_id
                )

            confirmations = session.scalars(
                statement
            ).all()

            now = self._utc_now_naive()
            changed = False

            for confirmation in confirmations:
                if self._expire_if_needed(
                    confirmation,
                    now=now,
                ):
                    changed = True

            if changed:
                session.commit()

            for confirmation in confirmations:
                if confirmation.status == "pending":
                    return self._to_dict(
                        confirmation
                    )

            return None

    def list_pending_confirmations(
        self,
        user_id: str,
        conversation_id: int | None = None,
    ) -> list[dict]:
        """
        Return all currently pending confirmations for a user.

        Results are ordered newest-first with ID as a
        deterministic tie-breaker.
        """

        with Session(engine) as session:
            statement = (
                select(Confirmation)
                .where(
                    Confirmation.user_id == user_id,
                    Confirmation.status == "pending",
                )
                .order_by(
                    Confirmation.created_at.desc(),
                    Confirmation.id.desc(),
                )
            )

            if conversation_id is not None:
                statement = statement.where(
                    Confirmation.conversation_id
                    == conversation_id
                )

            confirmations = session.scalars(
                statement
            ).all()

            now = self._utc_now_naive()
            changed = False

            for confirmation in confirmations:
                if self._expire_if_needed(
                    confirmation,
                    now=now,
                ):
                    changed = True

            if changed:
                session.commit()

            return [
                self._to_dict(
                    confirmation
                )
                for confirmation in confirmations
                if confirmation.status == "pending"
            ]

    def approve_and_claim_confirmation(
        self,
        user_id: str,
        confirmation_id: int,
    ) -> dict | None:
        """
        Atomically approve and claim a pending confirmation.

        The database transition is:

            pending -> processing

        Only an unexpired pending confirmation can make this
        transition. A second caller cannot claim the same
        confirmation because the SQL WHERE clause requires the
        current status to still be pending.
        """

        with Session(engine) as session:
            now = self._utc_now_naive()

            statement = (
                update(Confirmation)
                .where(
                    Confirmation.id == confirmation_id,
                    Confirmation.user_id == user_id,
                    Confirmation.status == "pending",
                    Confirmation.expires_at > now,
                )
                .values(
                    status="processing",
                    resolved_at=now,
                )
            )

            result = session.execute(
                statement
            )

            if result.rowcount != 1:
                confirmation = session.scalar(
                    select(Confirmation).where(
                        Confirmation.id == confirmation_id,
                        Confirmation.user_id == user_id,
                    )
                )

                if (
                    confirmation is not None
                    and confirmation.status == "pending"
                    and confirmation.expires_at <= now
                ):
                    confirmation.status = "expired"
                    confirmation.resolved_at = now
                    session.commit()

                return None

            session.commit()

            confirmation = session.scalar(
                select(Confirmation).where(
                    Confirmation.id == confirmation_id,
                    Confirmation.user_id == user_id,
                )
            )

            if confirmation is None:
                return None

            return self._to_dict(
                confirmation
            )


    def approve_confirmation(
        self,
        user_id: str,
        confirmation_id: int,
    ) -> dict | None:
        """
        Approve a pending confirmation.

        Approval resolves the user's confirmation decision,
        but the actual tool execution happens separately.
        """

        with Session(engine) as session:
            confirmation = session.scalar(
                select(Confirmation).where(
                    Confirmation.id == confirmation_id,
                    Confirmation.user_id == user_id,
                )
            )

            if confirmation is None:
                return None

            now = self._utc_now_naive()

            if self._expire_if_needed(
                confirmation,
                now=now,
            ):
                session.commit()
                return self._to_dict(
                    confirmation
                )

            if confirmation.status != "pending":
                return self._to_dict(
                    confirmation
                )

            confirmation.status = "approved"
            confirmation.resolved_at = now

            session.commit()
            session.refresh(confirmation)

            return self._to_dict(
                confirmation
            )

    def reject_confirmation(
        self,
        user_id: str,
        confirmation_id: int,
    ) -> dict | None:
        """
        Reject a pending confirmation.
        """

        with Session(engine) as session:
            confirmation = session.scalar(
                select(Confirmation).where(
                    Confirmation.id == confirmation_id,
                    Confirmation.user_id == user_id,
                )
            )

            if confirmation is None:
                return None

            now = self._utc_now_naive()

            if self._expire_if_needed(
                confirmation,
                now=now,
            ):
                session.commit()
                return self._to_dict(
                    confirmation
                )

            if confirmation.status != "pending":
                return self._to_dict(
                    confirmation
                )

            confirmation.status = "rejected"
            confirmation.resolved_at = now

            session.commit()
            session.refresh(confirmation)

            return self._to_dict(
                confirmation
            )

    def claim_confirmation(
        self,
        user_id: str,
        confirmation_id: int,
    ) -> dict | None:
        """
        Atomically claim an approved confirmation for
        one-time execution.

        Only an approved confirmation can be claimed.

        Returns the claimed confirmation or None when the
        confirmation is no longer executable.
        """

        with Session(engine) as session:
            statement = (
                update(Confirmation)
                .where(
                    Confirmation.id == confirmation_id,
                    Confirmation.user_id == user_id,
                    Confirmation.status == "approved",
                )
                .values(
                    status="processing",
                )
            )

            result = session.execute(
                statement
            )

            if result.rowcount != 1:
                return None

            session.commit()

            confirmation = session.scalar(
                select(Confirmation).where(
                    Confirmation.id == confirmation_id,
                    Confirmation.user_id == user_id,
                )
            )

            if confirmation is None:
                return None

            return self._to_dict(
                confirmation
            )

    def finish_confirmation(
        self,
        user_id: str,
        confirmation_id: int,
        success: bool,
    ) -> dict | None:
        """
        Finalize a claimed confirmation.

        Successful execution:
            processing -> consumed

        Failed execution:
            processing -> failed

        Neither state can be claimed again.
        """

        with Session(engine) as session:
            confirmation = session.scalar(
                select(Confirmation).where(
                    Confirmation.id == confirmation_id,
                    Confirmation.user_id == user_id,
                )
            )

            if confirmation is None:
                return None

            if confirmation.status != "processing":
                return self._to_dict(
                    confirmation
                )

            confirmation.status = (
                "consumed"
                if success
                else "failed"
            )

            confirmation.resolved_at = (
                self._utc_now_naive()
            )

            session.commit()
            session.refresh(confirmation)

            return self._to_dict(
                confirmation
            )

    def _to_dict(
        self,
        confirmation: Confirmation,
    ) -> dict:
        return {
            "id": confirmation.id,
            "user_id": confirmation.user_id,
            "conversation_id": (
                confirmation.conversation_id
            ),
            "tool": confirmation.tool,
            "action": confirmation.action,
            "data": confirmation.data,
            "reason": confirmation.reason,
            "status": confirmation.status,
            "created_at": confirmation.created_at,
            "expires_at": confirmation.expires_at,
            "resolved_at": confirmation.resolved_at,
        }