from agent import graph
from agent.graph import agent_node


class FakeKnowledgeService:
    def __init__(self, matches=None, error=None):
        self.matches = list(matches or [])
        self.error = error
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)

        if self.error is not None:
            raise self.error

        return list(self.matches)


class FakeLLMService:
    def __init__(self):
        self.prompts = []

    def generate_response(self, prompt):
        self.prompts.append(prompt)
        return "Grounded test response."


def make_state(**overrides):
    state = {
        "user_id": "user-001",
        "conversation_id": 10,
        "user_message": "What does my Python guide say about AI development?",
        "history": [],
        "understanding": {
            "intent": "question",
            "requires_tool": False,
        },
        "plan": {
            "requires_tool": False,
            "execution_mode": "single",
            "tool": None,
            "action": None,
            "data": {},
            "scheduled_at": None,
            "reason": "No tool required.",
            "steps": [],
        },
        "permission": {
            "allowed": False,
            "requires_confirmation": False,
            "reason": "No permission check was required.",
        },
        "user_requested": True,
        "execution_context": None,
        "confirmation": {
            "id": None,
            "status": None,
            "tool": None,
            "action": None,
            "reason": None,
        },
        "tool_result": {
            "success": False,
            "tool": None,
            "action": None,
            "result": None,
            "error": None,
        },
        "workflow_result": {
            "success": False,
            "status": None,
            "workflow_id": None,
            "scheduled_at": None,
            "steps": [],
            "error": None,
        },
        "memory_context": "No relevant long-term memory found.",
        "response": "",
    }
    state.update(overrides)
    return state


def test_agent_node_retrieves_user_knowledge_for_conversational_request(
    monkeypatch,
):
    knowledge_service = FakeKnowledgeService(
        matches=[
            {
                "document_id": 7,
                "title": "Python Guide",
                "source": "manual",
                "chunk_index": 0,
                "content": "Python is useful for AI development.",
                "similarity": 0.91,
            },
        ]
    )
    llm_service = FakeLLMService()

    monkeypatch.setattr(
        graph,
        "knowledge_service",
        knowledge_service,
    )
    monkeypatch.setattr(
        graph,
        "llm_service",
        llm_service,
    )

    result = agent_node(make_state())

    assert result["response"] == "Grounded test response."
    assert "Python Guide" in result["knowledge_context"]
    assert "Python is useful for AI development." in result["knowledge_context"]

    assert knowledge_service.calls == [
        {
            "user_id": "user-001",
            "query": "What does my Python guide say about AI development?",
            "threshold": 0.65,
            "limit": 8,
        }
    ]

    assert len(llm_service.prompts) == 1
    assert "Relevant knowledge from NOVA's personal knowledge base:" in llm_service.prompts[0]
    assert "Python is useful for AI development." in llm_service.prompts[0]


def test_agent_node_skips_knowledge_for_tool_requests(
    monkeypatch,
):
    knowledge_service = FakeKnowledgeService(
        matches=[
            {
                "document_id": 7,
                "title": "Python Guide",
                "source": "manual",
                "chunk_index": 0,
                "content": "This must not be used for tool execution.",
                "similarity": 0.99,
            },
        ]
    )
    llm_service = FakeLLMService()

    monkeypatch.setattr(
        graph,
        "knowledge_service",
        knowledge_service,
    )
    monkeypatch.setattr(
        graph,
        "llm_service",
        llm_service,
    )

    state = make_state(
        user_message="Create a task to practice Python",
        understanding={
            "intent": "task",
            "requires_tool": True,
        },
        plan={
            "requires_tool": True,
            "execution_mode": "single",
            "tool": "task",
            "action": "create",
            "data": {"task": "Practice Python"},
            "scheduled_at": None,
            "reason": "Task tool selected.",
            "steps": [],
        },
    )

    result = agent_node(state)

    assert knowledge_service.calls == []
    assert result["knowledge_context"] == (
        "Knowledge retrieval was not used for this request."
    )
    assert result["response"] == "Grounded test response."


def test_agent_node_skips_knowledge_for_rejected_confirmation(
    monkeypatch,
):
    knowledge_service = FakeKnowledgeService()
    llm_service = FakeLLMService()

    monkeypatch.setattr(
        graph,
        "knowledge_service",
        knowledge_service,
    )
    monkeypatch.setattr(
        graph,
        "llm_service",
        llm_service,
    )

    state = make_state(
        user_message="No",
        understanding={},
        plan={},
        confirmation={
            "id": 15,
            "status": "rejected",
            "tool": "task",
            "action": "delete",
            "reason": "User rejected the action.",
        },
    )

    result = agent_node(state)

    assert knowledge_service.calls == []
    assert result["knowledge_context"] == (
        "Knowledge retrieval was not used for this request."
    )


def test_agent_node_continues_when_knowledge_retrieval_fails(
    monkeypatch,
):
    knowledge_service = FakeKnowledgeService(
        error=RuntimeError("database unavailable")
    )
    llm_service = FakeLLMService()

    monkeypatch.setattr(
        graph,
        "knowledge_service",
        knowledge_service,
    )
    monkeypatch.setattr(
        graph,
        "llm_service",
        llm_service,
    )

    result = agent_node(make_state())

    assert knowledge_service.calls
    assert result["knowledge_context"] == (
        "Knowledge retrieval is temporarily unavailable."
    )
    assert result["response"] == "Grounded test response."
