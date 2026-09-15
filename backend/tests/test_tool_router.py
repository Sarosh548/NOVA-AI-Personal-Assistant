from services.tool_router import ToolRouter


class FakeTaskService:
    def __init__(self, matches=None):
        self.matches = matches or []
        self.completed = []
        self.started = []
        self.cancelled = []
        self.deleted = []

    def find_matching_tasks(
        self,
        user_id: str,
        reference: str,
    ):
        return self.matches

    def create_task(
        self,
        user_id,
        title,
        description=None,
        priority="medium",
        due_at=None,
    ):
        return 101

    def get_tasks(self, user_id, status=None):
        return []

    def complete_task(self, task_id, user_id):
        self.completed.append(
            (task_id, user_id)
        )
        return True

    def start_task(self, task_id, user_id):
        self.started.append(
            (task_id, user_id)
        )
        return True

    def cancel_task(self, task_id, user_id):
        self.cancelled.append(
            (task_id, user_id)
        )
        return True

    def delete_task(self, task_id, user_id):
        self.deleted.append(
            (task_id, user_id)
        )
        return True


def test_task_create_routes_to_task_service():
    task_service = FakeTaskService()
    router = ToolRouter(
        task_service=task_service
    )

    result = router.execute(
        intent="task",
        user_id="test-user",
        data={
            "task_action": "create",
            "task": "Test task",
            "priority": "high",
        },
    )

    assert result["success"] is True
    assert result["tool"] == "task"
    assert result["action"] == "create"
    assert result["result"]["task_id"] == 101


def test_task_complete_uses_natural_reference():
    task_service = FakeTaskService(
        matches=[
            {
                "id": 7,
                "title": "Finish CV",
                "description": None,
                "status": "pending",
                "priority": "high",
                "due_at": None,
            }
        ]
    )

    router = ToolRouter(
        task_service=task_service
    )

    result = router.execute(
        intent="task",
        user_id="user-001",
        data={
            "task_action": "complete",
            "task_reference": "CV",
            "task_id": None,
        },
    )

    assert result["success"] is True
    assert result["result"]["task_id"] == 7
    assert result["result"]["status"] == "completed"

    assert task_service.completed == [
        (7, "user-001")
    ]


def test_task_action_requires_reference_when_id_missing():
    task_service = FakeTaskService()
    router = ToolRouter(
        task_service=task_service
    )

    result = router.execute(
        intent="task",
        user_id="user-001",
        data={
            "task_action": "complete",
            "task_reference": None,
            "task_id": None,
        },
    )

    assert result["success"] is False
    assert (
        result["error"]
        == "Task reference is missing."
    )


def test_task_action_rejects_ambiguous_reference():
    task_service = FakeTaskService(
        matches=[
            {
                "id": 5,
                "title": "Study Python",
                "description": None,
                "status": "pending",
                "priority": "medium",
                "due_at": None,
            },
            {
                "id": 6,
                "title": "Study Python for AI",
                "description": None,
                "status": "pending",
                "priority": "medium",
                "due_at": None,
            },
        ]
    )

    router = ToolRouter(
        task_service=task_service
    )

    result = router.execute(
        intent="task",
        user_id="user-001",
        data={
            "task_action": "cancel",
            "task_reference": "Python study",
            "task_id": None,
        },
    )

    assert result["success"] is False
    assert (
        result["error"]
        == (
            "Multiple matching tasks found. "
            "Task selection is ambiguous."
        )
    )

    assert result["result"]["count"] == 2
    assert task_service.cancelled == []


def test_task_wrong_user_never_gets_a_match():
    task_service = FakeTaskService(
        matches=[]
    )

    router = ToolRouter(
        task_service=task_service
    )

    result = router.execute(
        intent="task",
        user_id="user-002",
        data={
            "task_action": "complete",
            "task_reference": "Finish CV",
            "task_id": None,
        },
    )

    assert result["success"] is False
    assert (
        result["error"]
        == (
            "Could not find a matching "
            "pending task."
        )
    )
    assert task_service.completed == []