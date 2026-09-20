from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class RiskAssessment:
    """
    Result of NOVA's risk assessment.

    level:
        low
        medium
        high

    flags:
        Deterministic reasons why the risk level was elevated.

    reason:
        Human-readable explanation.
    """

    level: str
    flags: tuple[str, ...] = ()
    reason: str = ""


class RiskPolicyService:
    """
    Risk classification layer for NOVA.

    The service does not:
    - execute tools
    - create confirmations
    - modify permissions
    - access the database

    It only evaluates the requested tool/action/data and
    classifies the operational risk.

    Policy:

        LOW
            Read-only or otherwise non-sensitive work.

        MEDIUM
            Normal state-changing work or controlled external
            capabilities.

        HIGH
            Financial operations, sensitive data, destructive
            broad-scope operations, credentials/secrets, or
            external communication to a target.

    High-risk actions are intentionally treated as a safety
    boundary by PermissionService and cannot be bypassed by
    an "allow" permission or by merely being interactive.
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

    HIGH_RISK_TOOLS = {
        "bank",
        "banking",
        "finance",
        "financial",
        "payment",
        "payments",
        "wallet",
        "crypto",
        "shell",
        "terminal",
        "system_admin",
        "admin",
    }

    COMMUNICATION_TOOLS = {
        "email",
        "messaging",
        "whatsapp",
        "sms",
        "social",
    }

    HIGH_RISK_ACTIONS = {
        "send",
        "transfer",
        "pay",
        "purchase",
        "publish",
        "wipe",
        "delete_all",
        "execute_command",
        "run_command",
    }

    SENSITIVE_DATA_KEYS = {
        "password",
        "passcode",
        "pin",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "token",
        "private_key",
        "credential",
        "credentials",
        "cvv",
        "security_code",
        "card_number",
        "credit_card",
        "debit_card",
        "cnic",
        "passport",
        "ssn",
    }

    FINANCIAL_DATA_KEYS = {
        "amount",
        "currency",
        "price",
        "payment_method",
        "bank_account",
        "account_number",
        "iban",
        "routing_number",
        "card_number",
        "credit_card",
        "debit_card",
    }

    EXTERNAL_TARGET_KEYS = {
        "recipient",
        "recipients",
        "to",
        "cc",
        "bcc",
        "external_recipient",
        "phone_number",
        "email",
    }

    CALENDAR_INVITATION_ACTIONS = {
        "create",
        "update",
    }

    DESTRUCTIVE_SCOPE_KEYS = {
        "scope",
        "target_scope",
        "recursive",
        "force",
        "permanent",
        "all",
    }

    def assess(
        self,
        *,
        tool: str,
        action: str,
        data: dict[str, Any] | None = None,
    ) -> RiskAssessment:
        """
        Assess operational risk from tool, action, and data.

        Data values are intentionally not included in the reason
        text. Only field names and structural characteristics are
        inspected so NOVA does not leak secrets into explanations.
        """

        normalized_tool = self._normalize(
            tool
        )

        normalized_action = self._normalize(
            action
        )

        normalized_data = (
            data
            if isinstance(
                data,
                dict,
            )
            else {}
        )

        flags: list[str] = []

        if (
            normalized_tool
            in self.HIGH_RISK_TOOLS
        ):
            flags.append(
                "high_risk_tool"
            )

        if (
            normalized_action
            in self.HIGH_RISK_ACTIONS
        ):
            flags.append(
                "high_risk_action"
            )

        data_keys = self._collect_keys(
            normalized_data
        )

        if data_keys & self.SENSITIVE_DATA_KEYS:
            flags.append(
                "sensitive_data"
            )

        if data_keys & self.FINANCIAL_DATA_KEYS:
            flags.append(
                "financial_data"
            )

        if (
            normalized_tool
            in self.COMMUNICATION_TOOLS
            and data_keys
            & self.EXTERNAL_TARGET_KEYS
        ):
            flags.append(
                "external_communication"
            )

        if (
            normalized_tool == "calendar"
            and normalized_action
            in self.CALENDAR_INVITATION_ACTIONS
            and self._has_calendar_attendees(
                normalized_data
            )
        ):
            flags.append(
                "external_communication"
            )

        if self._has_broad_destructive_scope(
            normalized_data
        ):
            flags.append(
                "destructive_scope"
            )

        unique_flags = tuple(
            dict.fromkeys(flags)
        )

        if unique_flags:
            return RiskAssessment(
                level=RiskLevel.HIGH.value,
                flags=unique_flags,
                reason=(
                    "High-risk safety factors detected: "
                    + ", ".join(
                        unique_flags
                    )
                    + "."
                ),
            )

        if (
            normalized_action
            in self.STATE_CHANGING_ACTIONS
            or normalized_tool
            in self.COMMUNICATION_TOOLS
        ):
            return RiskAssessment(
                level=RiskLevel.MEDIUM.value,
                flags=(),
                reason=(
                    "The operation can change state or "
                    "interact with an external capability."
                ),
            )

        return RiskAssessment(
            level=RiskLevel.LOW.value,
            flags=(),
            reason=(
                "The operation is considered low risk "
                "under the current NOVA safety policy."
            ),
        )

    def _collect_keys(
        self,
        value: Any,
    ) -> set[str]:
        """
        Recursively collect dictionary keys.

        This allows nested tool payloads to be assessed while
        avoiding inspection of sensitive values.
        """

        keys: set[str] = set()

        if isinstance(
            value,
            dict,
        ):
            for key, item in value.items():
                normalized_key = self._normalize(
                    str(key)
                )

                if normalized_key:
                    keys.add(
                        normalized_key
                    )

                keys.update(
                    self._collect_keys(
                        item
                    )
                )

        elif isinstance(
            value,
            (list, tuple),
        ):
            for item in value:
                keys.update(
                    self._collect_keys(
                        item
                    )
                )

        return keys

    def _has_calendar_attendees(
        self,
        data: dict[str, Any],
    ) -> bool:
        """
        Detect non-empty Calendar attendee structures.

        Attendee values are never included in the risk reason;
        only the presence of a non-empty attendee collection is
        relevant to the classification.
        """

        def contains_attendees(
            value: Any,
        ) -> bool:
            if isinstance(value, dict):
                for key, item in value.items():
                    if self._normalize(str(key)) == "attendees":
                        if isinstance(item, (list, tuple)):
                            if len(item) > 0:
                                return True
                        elif isinstance(item, dict):
                            if bool(item):
                                return True
                        elif isinstance(item, str):
                            if item.strip():
                                return True
                        elif item:
                            return True

                    if contains_attendees(item):
                        return True

            elif isinstance(value, (list, tuple)):
                for item in value:
                    if contains_attendees(item):
                        return True

            return False

        return contains_attendees(data)

    def _has_broad_destructive_scope(
        self,
        data: dict[str, Any],
    ) -> bool:
        """
        Detect explicit broad/destructive scope signals.

        This deliberately looks for structural scope indicators
        rather than arbitrary natural-language text.
        """

        for key, value in data.items():
            normalized_key = self._normalize(
                str(key)
            )

            if (
                normalized_key
                not in self.DESTRUCTIVE_SCOPE_KEYS
            ):
                if isinstance(
                    value,
                    dict,
                ):
                    if self._has_broad_destructive_scope(
                        value
                    ):
                        return True

                elif isinstance(
                    value,
                    list,
                ):
                    if any(
                        isinstance(
                            item,
                            dict,
                        )
                        and self._has_broad_destructive_scope(
                            item
                        )
                        for item in value
                    ):
                        return True

                continue

            if self._is_broad_value(
                value
            ):
                return True

        return False

    def _is_broad_value(
        self,
        value: Any,
    ) -> bool:
        if value is True:
            return True

        if isinstance(
            value,
            str,
        ):
            normalized = self._normalize(
                value
            )

            return normalized in {
                "all",
                "everything",
                "global",
                "recursive",
                "permanent",
                "force",
                "true",
                "*",
            }

        return False

    @staticmethod
    def _normalize(
        value: str,
    ) -> str:
        return str(
            value
        ).strip().lower()