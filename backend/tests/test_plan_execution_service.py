from services.plan_execution_service import (
    PlanExecutionService,
)


class FakeToolRouter:
    """
    Safe in-memory router for execution service tests.

    No database or real NOVA tools are executed.
    """

    def __init__(
        self,
        failures=None,
    ):
        self.calls = []
        self.failures = set(
            failures or []
        )

    def execute(
        self,
        intent,
        user_id,
        data=None,
    ):
        step_id = data.get(
            "test_step_id"
        )

        self.calls.append(
            {
                "intent": intent,
                "user_id": user_id,
                "data": data,
            }
        )

        if step_id in self.failures:
            return {
                "success": False,
                "tool": intent,
                "action": data.get("action"),
                "result": None,
                "error": (
                    f"Simulated failure for {step_id}."
                ),
            }

        return {
            "success": True,
            "tool": intent,
            "action": data.get("action"),
            "result": {
                "step_id": step_id,
                "message": (
                    f"Executed {step_id}."
                ),
            },
            "error": None,
        }


def test_execution_service_runs_steps_in_dependency_order():
    router = FakeToolRouter()

    service = PlanExecutionService(
        tool_router=router
    )

    result = service.execute(
        user_id="user-001",
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {
                    "test_step_id": "step-1",
                },
                "depends_on": [],
            },
            {
                "step_id": "step-2",
                "tool": "task",
                "action": "list",
                "data": {
                    "test_step_id": "step-2",
                },
                "depends_on": [
                    "step-1"
                ],
            },
            {
                "step_id": "step-3",
                "tool": "reminder",
                "action": "list",
                "data": {
                    "test_step_id": "step-3",
                },
                "depends_on": [
                    "step-2"
                ],
            },
        ],
    )

    assert result.success is True
    assert result.status == "completed"
    assert result.error is None

    assert [
        item["data"]["test_step_id"]
        for item in router.calls
    ] == [
        "step-1",
        "step-2",
        "step-3",
    ]

    assert [
        item.step_id
        for item in result.steps
    ] == [
        "step-1",
        "step-2",
        "step-3",
    ]

    assert all(
        item.status == "completed"
        for item in result.steps
    )


def test_execution_service_runs_independent_steps_in_list_order():
    router = FakeToolRouter()

    service = PlanExecutionService(
        tool_router=router
    )

    result = service.execute(
        user_id="user-001",
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {
                    "test_step_id": "step-1",
                },
                "depends_on": [],
            },
            {
                "step_id": "step-2",
                "tool": "reminder",
                "action": "list",
                "data": {
                    "test_step_id": "step-2",
                },
                "depends_on": [],
            },
            {
                "step_id": "step-3",
                "tool": "task",
                "action": "list",
                "data": {
                    "test_step_id": "step-3",
                },
                "depends_on": [],
            },
        ],
    )

    assert result.success is True
    assert result.status == "completed"

    assert [
        item["data"]["test_step_id"]
        for item in router.calls
    ] == [
        "step-1",
        "step-2",
        "step-3",
    ]


def test_failed_step_skips_dependent_steps():
    router = FakeToolRouter(
        failures={"step-1"}
    )

    service = PlanExecutionService(
        tool_router=router
    )

    result = service.execute(
        user_id="user-001",
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {
                    "test_step_id": "step-1",
                },
                "depends_on": [],
            },
            {
                "step_id": "step-2",
                "tool": "task",
                "action": "list",
                "data": {
                    "test_step_id": "step-2",
                },
                "depends_on": [
                    "step-1"
                ],
            },
        ],
    )

    assert result.success is False
    assert result.status == "partial"

    assert [
        item["data"]["test_step_id"]
        for item in router.calls
    ] == [
        "step-1"
    ]

    assert result.steps[0].step_id == "step-1"
    assert result.steps[0].status == "failed"

    assert result.steps[1].step_id == "step-2"
    assert result.steps[1].status == "skipped"

    assert (
        "dependencies"
        in result.steps[1].error
    )


def test_failed_step_does_not_block_independent_step():
    router = FakeToolRouter(
        failures={"step-1"}
    )

    service = PlanExecutionService(
        tool_router=router
    )

    result = service.execute(
        user_id="user-001",
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {
                    "test_step_id": "step-1",
                },
                "depends_on": [],
            },
            {
                "step_id": "step-2",
                "tool": "reminder",
                "action": "list",
                "data": {
                    "test_step_id": "step-2",
                },
                "depends_on": [],
            },
            {
                "step_id": "step-3",
                "tool": "task",
                "action": "list",
                "data": {
                    "test_step_id": "step-3",
                },
                "depends_on": [
                    "step-1"
                ],
            },
        ],
    )

    assert result.success is False
    assert result.status == "partial"

    assert [
        item["data"]["test_step_id"]
        for item in router.calls
    ] == [
        "step-1",
        "step-2",
    ]

    assert [
        item.status
        for item in result.steps
    ] == [
        "failed",
        "completed",
        "skipped",
    ]


def test_empty_plan_completes_without_execution():
    router = FakeToolRouter()

    service = PlanExecutionService(
        tool_router=router
    )

    result = service.execute(
        user_id="user-001",
        steps=[],
    )

    assert result.success is True
    assert result.status == "completed"
    assert result.steps == ()
    assert result.error is None
    assert router.calls == []


def test_invalid_step_structure_is_blocked():
    router = FakeToolRouter()

    service = PlanExecutionService(
        tool_router=router
    )

    result = service.execute(
        user_id="user-001",
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": "invalid",
                "depends_on": [],
            }
        ],
    )

    assert result.success is False
    assert result.status == "blocked"
    assert result.steps == ()
    assert (
        "must be a dictionary"
        in result.error
    )
    assert router.calls == []


def test_unknown_dependency_is_blocked():
    router = FakeToolRouter()

    service = PlanExecutionService(
        tool_router=router
    )

    result = service.execute(
        user_id="user-001",
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {},
                "depends_on": [
                    "missing"
                ],
            }
        ],
    )

    assert result.success is False
    assert result.status == "blocked"
    assert result.steps == ()
    assert (
        "unknown step"
        in result.error
    )
    assert router.calls == []


def test_self_dependency_is_blocked():
    router = FakeToolRouter()

    service = PlanExecutionService(
        tool_router=router
    )

    result = service.execute(
        user_id="user-001",
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {},
                "depends_on": [
                    "step-1"
                ],
            }
        ],
    )

    assert result.success is False
    assert result.status == "blocked"
    assert result.steps == ()
    assert (
        "cannot depend on itself"
        in result.error
    )
    assert router.calls == []


def test_tool_exception_marks_step_failed():
    class ExceptionRouter:
        def execute(
            self,
            intent,
            user_id,
            data=None,
        ):
            raise RuntimeError(
                "Simulated exception."
            )

    service = PlanExecutionService(
        tool_router=ExceptionRouter()
    )

    result = service.execute(
        user_id="user-001",
        steps=[
            {
                "step_id": "step-1",
                "tool": "task",
                "action": "list",
                "data": {},
                "depends_on": [],
            }
        ],
    )

    assert result.success is False
    assert result.status == "partial"
    assert len(result.steps) == 1
    assert result.steps[0].status == "failed"
    assert (
        result.steps[0].error
        == "Tool execution failed."
    )