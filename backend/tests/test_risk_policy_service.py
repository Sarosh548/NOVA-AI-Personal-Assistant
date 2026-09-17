from services.risk_policy_service import (
    RiskLevel,
    RiskPolicyService,
)


def test_read_only_task_is_low_risk():
    service = RiskPolicyService()

    result = service.assess(
        tool="task",
        action="list",
        data={},
    )

    assert result.level == RiskLevel.LOW.value
    assert result.flags == ()


def test_state_changing_task_is_medium_risk():
    service = RiskPolicyService()

    result = service.assess(
        tool="task",
        action="create",
        data={
            "task": "Study LangGraph",
        },
    )

    assert result.level == RiskLevel.MEDIUM.value
    assert result.flags == ()


def test_finance_tool_is_high_risk():
    service = RiskPolicyService()

    result = service.assess(
        tool="finance",
        action="create",
        data={},
    )

    assert result.level == RiskLevel.HIGH.value
    assert "high_risk_tool" in result.flags


def test_sensitive_data_is_high_risk():
    service = RiskPolicyService()

    result = service.assess(
        tool="task",
        action="create",
        data={
            "password": "secret-value",
        },
    )

    assert result.level == RiskLevel.HIGH.value
    assert "sensitive_data" in result.flags


def test_financial_data_is_high_risk():
    service = RiskPolicyService()

    result = service.assess(
        tool="task",
        action="create",
        data={
            "amount": 5000,
            "currency": "PKR",
        },
    )

    assert result.level == RiskLevel.HIGH.value
    assert "financial_data" in result.flags


def test_external_communication_is_high_risk():
    service = RiskPolicyService()

    result = service.assess(
        tool="email",
        action="create",
        data={
            "recipient": "client@example.com",
            "body": "Project update",
        },
    )

    assert result.level == RiskLevel.HIGH.value
    assert "external_communication" in result.flags


def test_broad_destructive_scope_is_high_risk():
    service = RiskPolicyService()

    result = service.assess(
        tool="task",
        action="delete",
        data={
            "scope": "all",
        },
    )

    assert result.level == RiskLevel.HIGH.value
    assert "destructive_scope" in result.flags


def test_nested_sensitive_data_is_detected():
    service = RiskPolicyService()

    result = service.assess(
        tool="task",
        action="update",
        data={
            "profile": {
                "credentials": {
                    "api_key": "hidden",
                }
            }
        },
    )

    assert result.level == RiskLevel.HIGH.value
    assert "sensitive_data" in result.flags


def test_high_risk_action_is_detected():
    service = RiskPolicyService()

    result = service.assess(
        tool="email",
        action="send",
        data={},
    )

    assert result.level == RiskLevel.HIGH.value
    assert "high_risk_action" in result.flags