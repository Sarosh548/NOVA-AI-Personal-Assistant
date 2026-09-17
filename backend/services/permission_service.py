from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.connection import engine
from models.permission import Permission
from services.risk_policy_service import (
    RiskAssessment,
    RiskPolicyService,
)


@dataclass(frozen=True)
class PermissionDecision:
    """
    Result of a permission check.

    allowed:
        Whether the action may proceed.

    requires_confirmation:
        Whether NOVA should ask for confirmation
        before execution.

    reason:
        Human-readable explanation for the decision.

    risk_level:
        Risk classification produced by RiskPolicyService.

    risk_flags:
        Deterministic risk factors that caused elevation.
    """

    allowed: bool
    requires_confirmation: bool
    reason: str
    risk_level: str = "low"
    risk_flags: tuple[str, ...] = ()


class PermissionService:
    """
    Generic permission and safety policy layer for NOVA.

    Persistent permission modes:

        allow:
            Action may execute without confirmation unless the
            risk policy classifies it as high risk.

        confirm:
            Confirmation is required for autonomous/background
            execution. An explicit user request is sufficient
            for normal medium/low risk work.

        deny:
            Action is blocked.

    Risk policy:

        low:
            Normal read-only work.

        medium:
            Normal state-changing work.

        high:
            Sensitive, financial, destructive broad-scope,
            credential-related, or external-target operations.

            High-risk operations ALWAYS require explicit
            confirmation and cannot be bypassed by:
                - interactive execution
                - persisted "allow"
                - autonomous execution

    If no persistent permission exists:

        Read-only actions:
            allowed when risk policy allows.

        Medium-risk state-changing actions:
            explicitly requested by the user -> allowed.
            otherwise -> confirmation required.

        High-risk actions:
            confirmation always required.

    Unknown tools/actions are denied safely.
    """

    READ_ONLY_ACTIONS = {
        "list",
        "get",
        "search",
    }

    STATE_CHANGING_ACTIONS = {
        "create",
        "update",
        "start",
        "complete",
        "cancel",
        "delete",
    }

    VALID_MODES = {
        "allow",
        "confirm",
        "deny",
    }

    def __init__(
        self,
        risk_policy_service: RiskPolicyService | None = None,
    ):
        self.risk_policy_service = (
            risk_policy_service
            if risk_policy_service is not None
            else RiskPolicyService()
        )

    def _normalize(
        self,
        value: str,
    ) -> str:
        return str(
            value
        ).strip().lower()

    def get_permission(
        self,
        user_id: str,
        tool: str,
        action: str,
    ) -> str | None:
        """
        Return the persisted permission mode for a
        user/tool/action combination.
        """

        normalized_tool = self._normalize(
            tool
        )

        normalized_action = self._normalize(
            action
        )

        if (
            not normalized_tool
            or not normalized_action
        ):
            return None

        with Session(engine) as session:
            permission = session.scalar(
                select(Permission).where(
                    Permission.user_id == user_id,
                    Permission.tool == normalized_tool,
                    Permission.action
                    == normalized_action,
                )
            )

            if permission is None:
                return None

            return permission.mode

    def set_permission(
        self,
        user_id: str,
        tool: str,
        action: str,
        mode: str,
    ) -> bool:
        """
        Create or update a persistent permission.
        """

        normalized_tool = self._normalize(
            tool
        )

        normalized_action = self._normalize(
            action
        )

        normalized_mode = self._normalize(
            mode
        )

        if not normalized_tool:
            raise ValueError(
                "Tool name is missing."
            )

        if not normalized_action:
            raise ValueError(
                "Action name is missing."
            )

        if normalized_mode not in self.VALID_MODES:
            raise ValueError(
                "Invalid permission mode."
            )

        if (
            normalized_action
            not in self.READ_ONLY_ACTIONS
            and normalized_action
            not in self.STATE_CHANGING_ACTIONS
        ):
            raise ValueError(
                "Unknown permission action."
            )

        with Session(engine) as session:
            permission = session.scalar(
                select(Permission).where(
                    Permission.user_id == user_id,
                    Permission.tool == normalized_tool,
                    Permission.action
                    == normalized_action,
                )
            )

            if permission is None:
                permission = Permission(
                    user_id=user_id,
                    tool=normalized_tool,
                    action=normalized_action,
                    mode=normalized_mode,
                )

                session.add(
                    permission
                )

            else:
                permission.mode = normalized_mode

            session.commit()

            return True

    def list_permissions(
        self,
        user_id: str,
    ) -> list[dict]:
        """
        Return all persisted permissions for a user.
        """

        with Session(engine) as session:
            permissions = session.scalars(
                select(Permission)
                .where(
                    Permission.user_id == user_id
                )
                .order_by(
                    Permission.tool.asc(),
                    Permission.action.asc(),
                )
            ).all()

            return [
                {
                    "id": permission.id,
                    "tool": permission.tool,
                    "action": permission.action,
                    "mode": permission.mode,
                    "created_at": permission.created_at,
                    "updated_at": permission.updated_at,
                }
                for permission in permissions
            ]

    def delete_permission(
        self,
        user_id: str,
        tool: str,
        action: str,
    ) -> bool:
        """
        Remove a persisted permission.

        Returning False means the permission did not exist.
        """

        normalized_tool = self._normalize(
            tool
        )

        normalized_action = self._normalize(
            action
        )

        if (
            not normalized_tool
            or not normalized_action
        ):
            return False

        with Session(engine) as session:
            permission = session.scalar(
                select(Permission).where(
                    Permission.user_id == user_id,
                    Permission.tool == normalized_tool,
                    Permission.action
                    == normalized_action,
                )
            )

            if permission is None:
                return False

            session.delete(
                permission
            )

            session.commit()

            return True

    def check(
        self,
        user_id: str,
        tool: str,
        action: str,
        user_requested: bool = False,
        data: dict | None = None,
    ) -> PermissionDecision:
        """
        Check whether NOVA may execute a tool/action.

        The risk policy is evaluated before the final execution
        decision.

        High-risk operations always require confirmation unless
        the action is explicitly denied by persistent permission.
        """

        normalized_tool = self._normalize(
            tool
        )

        normalized_action = self._normalize(
            action
        )

        if not normalized_tool:
            return PermissionDecision(
                allowed=False,
                requires_confirmation=False,
                reason="Tool name is missing.",
            )

        if not normalized_action:
            return PermissionDecision(
                allowed=False,
                requires_confirmation=False,
                reason="Action name is missing.",
            )

        if (
            normalized_action
            not in self.READ_ONLY_ACTIONS
            and normalized_action
            not in self.STATE_CHANGING_ACTIONS
        ):
            return PermissionDecision(
                allowed=False,
                requires_confirmation=False,
                reason=(
                    f"Unknown action '{normalized_action}' "
                    f"for tool '{normalized_tool}'."
                ),
            )

        risk = self.risk_policy_service.assess(
            tool=normalized_tool,
            action=normalized_action,
            data=data,
        )

        persisted_mode = self.get_permission(
            user_id=user_id,
            tool=normalized_tool,
            action=normalized_action,
        )

        # -------------------------------------------------
        # Explicit persistent deny always wins.
        # -------------------------------------------------

        if persisted_mode == "deny":
            return PermissionDecision(
                allowed=False,
                requires_confirmation=False,
                reason=(
                    f"Action '{normalized_action}' on tool "
                    f"'{normalized_tool}' is denied by the "
                    "user's saved permission."
                ),
                risk_level=risk.level,
                risk_flags=risk.flags,
            )

        # -------------------------------------------------
        # High-risk safety boundary.
        #
        # Neither "allow" nor interactive execution can
        # bypass this confirmation requirement.
        # -------------------------------------------------

        if risk.level == "high":
            return PermissionDecision(
                allowed=False,
                requires_confirmation=True,
                reason=(
                    f"High-risk action '{normalized_action}' "
                    f"on tool '{normalized_tool}' requires "
                    "explicit confirmation under NOVA's "
                    f"safety policy. {risk.reason}"
                ),
                risk_level=risk.level,
                risk_flags=risk.flags,
            )

        # -------------------------------------------------
        # Persisted allow.
        # -------------------------------------------------

        if persisted_mode == "allow":
            return PermissionDecision(
                allowed=True,
                requires_confirmation=False,
                reason=(
                    f"Action '{normalized_action}' on tool "
                    f"'{normalized_tool}' is allowed by the "
                    "user's saved permission."
                ),
                risk_level=risk.level,
                risk_flags=risk.flags,
            )

        # -------------------------------------------------
        # Persisted confirm.
        # -------------------------------------------------

        if persisted_mode == "confirm":
            if user_requested:
                return PermissionDecision(
                    allowed=True,
                    requires_confirmation=False,
                    reason=(
                        f"Action '{normalized_action}' on tool "
                        f"'{normalized_tool}' was explicitly "
                        "requested by the user."
                    ),
                    risk_level=risk.level,
                    risk_flags=risk.flags,
                )

            return PermissionDecision(
                allowed=False,
                requires_confirmation=True,
                reason=(
                    f"Action '{normalized_action}' on tool "
                    f"'{normalized_tool}' requires confirmation "
                    "under the user's saved permission."
                ),
                risk_level=risk.level,
                risk_flags=risk.flags,
            )

        # -------------------------------------------------
        # Read-only action.
        # -------------------------------------------------

        if normalized_action in self.READ_ONLY_ACTIONS:
            return PermissionDecision(
                allowed=True,
                requires_confirmation=False,
                reason=(
                    f"Read-only action '{normalized_action}' "
                    "is allowed."
                ),
                risk_level=risk.level,
                risk_flags=risk.flags,
            )

        # -------------------------------------------------
        # Explicitly requested medium-risk action.
        # -------------------------------------------------

        if user_requested:
            return PermissionDecision(
                allowed=True,
                requires_confirmation=False,
                reason=(
                    f"Action '{normalized_action}' on tool "
                    f"'{normalized_tool}' was explicitly "
                    "requested by the user."
                ),
                risk_level=risk.level,
                risk_flags=risk.flags,
            )

        # -------------------------------------------------
        # Autonomous/background medium-risk action.
        # -------------------------------------------------

        return PermissionDecision(
            allowed=False,
            requires_confirmation=True,
            reason=(
                f"Action '{normalized_action}' on tool "
                f"'{normalized_tool}' changes user state "
                "and requires confirmation."
            ),
            risk_level=risk.level,
            risk_flags=risk.flags,
        )