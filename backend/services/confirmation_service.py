from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database.connection import engine
from models.confirmation import Confirmation
from services.audit_service import AuditService


audit_service = AuditService()
DEFAULT_LEASE_SECONDS = 900


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

    def _record_audit(
        self,
        *,
        user_id: str,
        action: str,
        status: str,
        confirmation: dict | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            event_metadata = dict(metadata or {})

            if confirmation is not None:
                event_metadata.update(
                    {
                        "tool": confirmation.get("tool"),
                        "action": confirmation.get("action"),
                        "confirmation_status": confirmation.get("status"),
                        "attempt_count": confirmation.get("attempt_count"),
                    }
                )

            audit_service.record_event(
                event_type="confirmation",
                action=action,
                status=status,
                user_id=user_id,
                resource_type="confirmation",
                resource_id=(
                    confirmation.get("id")
                    if confirmation is not None
                    else None
                ),
                metadata=event_metadata,
            )
        except Exception:
            return

    @staticmethod
    def _new_claim_token() -> str:
        return uuid4().hex

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
            claim_token=None,
            lease_until=None,
            attempt_count=0,
        )

        with Session(engine) as session:
            session.add(confirmation)
            session.commit()
            session.refresh(confirmation)

            created = self._to_dict(
                confirmation
            )

        self._record_audit(
            user_id=user_id,
            action="create",
            status="success",
            confirmation=created,
        )

        return created["id"]

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
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> dict | None:
        """
        Atomically approve and claim a pending confirmation.

        The transition is pending -> processing and receives a
        unique execution claim token plus a durable lease.
        """
        if lease_seconds <= 0:
            raise ValueError(
                "Confirmation lease must be greater than zero."
            )

        with Session(engine) as session:
            now = self._utc_now_naive()
            claim_token = self._new_claim_token()
            lease_until = (
                now
                + timedelta(
                    seconds=lease_seconds
                )
            )

            result = session.execute(
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
                    claim_token=claim_token,
                    lease_until=lease_until,
                    attempt_count=Confirmation.attempt_count + 1,
                )
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
                    self._record_audit(
                        user_id=user_id,
                        action="approve",
                        status="failure",
                        confirmation=self._to_dict(confirmation),
                        metadata={"reason": "expired"},
                    )

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

            result_dict = self._to_dict(confirmation)

        self._record_audit(
            user_id=user_id,
            action="approve",
            status="success",
            confirmation=result_dict,
        )
        self._record_audit(
            user_id=user_id,
            action="claim",
            status="success",
            confirmation=result_dict,
        )

        return result_dict


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

            result = self._to_dict(
                confirmation
            )

        self._record_audit(
            user_id=user_id,
            action="approve",
            status="success",
            confirmation=result,
        )

        return result

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

            result = self._to_dict(
                confirmation
            )

        self._record_audit(
            user_id=user_id,
            action="reject",
            status="success",
            confirmation=result,
        )

        return result

    def claim_confirmation(
        self,
        user_id: str,
        confirmation_id: int,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> dict | None:
        """
        Atomically claim an approved confirmation or reclaim an
        expired processing lease.
        """
        if lease_seconds <= 0:
            raise ValueError(
                "Confirmation lease must be greater than zero."
            )

        with Session(engine) as session:
            now = self._utc_now_naive()
            claim_token = self._new_claim_token()
            lease_until = (
                now
                + timedelta(
                    seconds=lease_seconds
                )
            )

            result = session.execute(
                update(Confirmation)
                .where(
                    Confirmation.id == confirmation_id,
                    Confirmation.user_id == user_id,
                    Confirmation.status == "approved",
                )
                .values(
                    status="processing",
                    claim_token=claim_token,
                    lease_until=lease_until,
                    attempt_count=Confirmation.attempt_count + 1,
                )
            )

            claim_reason = "approved"

            if result.rowcount != 1:
                result = session.execute(
                    update(Confirmation)
                    .where(
                        Confirmation.id == confirmation_id,
                        Confirmation.user_id == user_id,
                        Confirmation.status == "processing",
                        Confirmation.lease_until.is_not(None),
                        Confirmation.lease_until <= now,
                    )
                    .values(
                        status="processing",
                        claim_token=claim_token,
                        lease_until=lease_until,
                        attempt_count=Confirmation.attempt_count + 1,
                    )
                )
                claim_reason = "reclaimed"

            if result.rowcount != 1:
                self._record_audit(
                    user_id=user_id,
                    action="claim",
                    status="failure",
                    metadata={"reason": "unavailable"},
                )
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

            result_dict = self._to_dict(confirmation)

        self._record_audit(
            user_id=user_id,
            action="claim",
            status="success",
            confirmation=result_dict,
            metadata={"reason": claim_reason},
        )

        return result_dict


    def finish_confirmation(
        self,
        user_id: str,
        confirmation_id: int,
        success: bool,
        claim_token: str | None = None,
    ) -> dict | None:
        """
        Finalize a processing confirmation.

        When a claim token is supplied, only the worker holding
        that token may finalize the confirmation.
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
                return self._to_dict(confirmation)

            if (
                claim_token is not None
                and confirmation.claim_token != claim_token
            ):
                return None

            now = self._utc_now_naive()
            confirmation.status = (
                "consumed"
                if success
                else "failed"
            )
            confirmation.resolved_at = now
            confirmation.lease_until = None
            confirmation.claim_token = None

            session.commit()
            session.refresh(confirmation)

            result = self._to_dict(confirmation)

        self._record_audit(
            user_id=user_id,
            action="finish",
            status="success" if success else "failure",
            confirmation=result,
        )

        return result


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
            "claim_token": confirmation.claim_token,
            "lease_until": confirmation.lease_until,
            "attempt_count": confirmation.attempt_count,
        }