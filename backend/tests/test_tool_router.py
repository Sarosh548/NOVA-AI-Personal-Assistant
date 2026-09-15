from services.tool_router import ToolRouter


class FakeTaskService:
    def __init__(
        self,
        matches=None,
    ):
        self.matches = matches or []
        self.updated_calls = []

    def create_task(
        self,
        user_id,
        title,
        description=None,
        priority="medium",
        due_at=None,
    ):
        return 1

    def find_matching_tasks(
        self,
        user_id,
        reference,
    ):
        return self.matches

    def start_task(
        self,
        task_id,
        user_id,
    ):
        return True

    def complete_task(
        self,
        task_id,
        user_id,
    ):
        return True

    def cancel_task(
        self,
        task_id,
        user_id,
    ):
        return True

    def delete_task(
        self,
        task_id,
        user_id,
    ):
        return True

    def get_tasks(
        self,
        user_id,
    ):
        return []

    def update_task(
        self,
        task_id,
        user_id,
        priority=None,
        due_at=None,
    ):
        self.updated_calls.append(
            {
                "task_id": task_id,
                "user_id": user_id,
                "priority": priority,
                "due_at": due_at,
            }
        )

        return True


def test_task_create_routes_to_task_service():
    fake_service = FakeTaskService()

    router = ToolRouter(
        task_service=fake_service
    )

    result = router.execute(
        intent="task",
        user_id="test-user",
        data={
            "task_action": "create",
            "task": "prepare AI CV",
            "priority": "medium",
            "scheduled_at": None,
        },
    )

    assert result["success"] is True
    assert result["tool"] == "task"
    assert result["action"] == "create"


def test_task_complete_uses_natural_reference():
    fake_service = FakeTaskService(
        matches=[
            {
                "id": 7,
                "title": "practice LangGraph",
                "description": None,
                "status": "pending",
                "priority": "medium",
                "due_at": None,
            }
        ]
    )

    router = ToolRouter(
        task_service=fake_service
    )

    result = router.execute(
        intent="task",
        user_id="test-user",
        data={
            "task_action": "complete",
            "task_id": None,
            "task_reference": "LangGraph",
        },
    )

    assert result["success"] is True
    assert result["action"] == "complete"
    assert result["result"]["task_id"] == 7
    assert result["result"]["status"] == "completed"


def test_task_action_requires_reference_when_id_missing():
    fake_service = FakeTaskService()

    router = ToolRouter(
        task_service=fake_service
    )

    result = router.execute(
        intent="task",
        user_id="test-user",
        data={
            "task_action": "complete",
            "task_id": None,
            "task_reference": None,
            "task": None,
        },
    )

    assert result["success"] is False
    assert result["error"] == (
        "Task reference is missing."
    )


def test_task_action_rejects_ambiguous_reference():
    fake_service = FakeTaskService(
        matches=[
            {
                "id": 1,
                "title": "study Python",
            },
            {
                "id": 2,
                "title": "study Python interview",
            },
        ]
    )

    router = ToolRouter(
        task_service=fake_service
    )

    result = router.execute(
        intent="task",
        user_id="test-user",
        data={
            "task_action": "complete",
            "task_id": None,
            "task_reference": "Python",
        },
    )

    assert result["success"] is False
    assert result["error"] == (
        "Multiple matching tasks found. "
        "Task selection is ambiguous."
    )


def test_task_wrong_user_never_gets_a_match():
    fake_service = FakeTaskService(
        matches=[]
    )

    router = ToolRouter(
        task_service=fake_service
    )

    result = router.execute(
        intent="task",
        user_id="wrong-user",
        data={
            "task_action": "complete",
            "task_id": None,
            "task_reference": "LangGraph",
        },
    )

    assert result["success"] is False
    assert result["error"] == (
        "Could not find a matching "
        "pending task."
    )


def test_task_update_routes_to_task_service():
    fake_service = FakeTaskService()

    router = ToolRouter(
        task_service=fake_service
    )

    result = router.execute(
        intent="task",
        user_id="test-user",
        data={
            "task_action": "update",
            "task_id": 7,
            "task_reference": None,
            "task": None,
            "priority": "high",
            "scheduled_at": None,
        },
    )

    assert result["success"] is True
    assert result["tool"] == "task"
    assert result["action"] == "update"

    assert result["result"]["task_id"] == 7
    assert result["result"]["priority"] == "high"

    assert (
        fake_service.updated_calls[0]["task_id"]
        == 7
    )

    assert (
        fake_service.updated_calls[0]["priority"]
        == "high"
    )


def test_task_update_uses_natural_reference():
    fake_service = FakeTaskService(
        matches=[
            {
                "id": 9,
                "title": "study LangGraph",
                "description": None,
                "status": "pending",
                "priority": "medium",
                "due_at": None,
            }
        ]
    )

    router = ToolRouter(
        task_service=fake_service
    )

    result = router.execute(
        intent="task",
        user_id="test-user",
        data={
            "task_action": "update",
            "task_id": None,
            "task_reference": "LangGraph",
            "task": None,
            "priority": "high",
            "scheduled_at": None,
        },
    )

    assert result["success"] is True
    assert result["result"]["task_id"] == 9

    assert (
        fake_service.updated_calls[0]["task_id"]
        == 9
    )


def test_task_update_requires_reference_when_id_missing():
    fake_service = FakeTaskService()

    router = ToolRouter(
        task_service=fake_service
    )

    result = router.execute(
        intent="task",
        user_id="test-user",
        data={
            "task_action": "update",
            "task_id": None,
            "task_reference": None,
            "task": None,
            "priority": "high",
            "scheduled_at": None,
        },
    )

    assert result["success"] is False
    assert result["error"] == (
        "Task reference is missing."
    )


def test_task_update_rejects_missing_update_fields():
    fake_service = FakeTaskService()

    router = ToolRouter(
        task_service=fake_service
    )

    result = router.execute(
        intent="task",
        user_id="test-user",
        data={
            "task_action": "update",
            "task_id": 7,
            "priority": None,
            "scheduled_at": None,
        },
    )

    assert result["success"] is False
    assert result["error"] == (
        "No task fields were provided for update."
    )