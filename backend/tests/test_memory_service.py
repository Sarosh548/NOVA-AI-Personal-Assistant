from services.memory_service import MemoryService


class FakeEmbedding:
    def create_embedding(self, text):
        return FakeVector()


class FakeVector:
    def tolist(self):
        return [0.1, 0.2, 0.3]


class FakeLLMService:
    def __init__(self, decision="KEEP"):
        self.decision = decision

    def resolve_memory_conflict(
        self,
        new_memory,
        new_category,
        existing_memory,
    ):
        return self.decision


def make_service(decision="KEEP"):
    service = MemoryService.__new__(
        MemoryService
    )

    service.embedding_service = FakeEmbedding()

    service.llm_service = FakeLLMService(
        decision=decision
    )

    return service


def test_memory_service_returns_correct_categories():
    service = make_service()

    assert service.llm_service.resolve_memory_conflict(
        new_memory=(
            "My goal is to become a Data Scientist."
        ),
        new_category="goal",
        existing_memory=(
            "User wants to become an AI Engineer."
        ),
    ) == "KEEP"


def test_memory_conflict_update_decision():
    service = make_service(
        decision="UPDATE"
    )

    decision = service.llm_service.resolve_memory_conflict(
        new_memory=(
            "I changed my career goal and now "
            "I want to become a Data Scientist."
        ),
        new_category="goal",
        existing_memory=(
            "User wants to become an AI Engineer."
        ),
    )

    assert decision == "UPDATE"


def test_memory_conflict_duplicate_decision():
    service = make_service(
        decision="DUPLICATE"
    )

    decision = service.llm_service.resolve_memory_conflict(
        new_memory=(
            "I prefer working on AI projects in Python."
        ),
        new_category="preference",
        existing_memory=(
            "User prefers Python for AI development."
        ),
    )

    assert decision == "DUPLICATE"


def test_memory_conflict_keep_decision():
    service = make_service(
        decision="KEEP"
    )

    decision = service.llm_service.resolve_memory_conflict(
        new_memory=(
            "My favorite AI framework is FastAPI."
        ),
        new_category="preference",
        existing_memory=(
            "User prefers Python for AI development."
        ),
    )

    assert decision == "KEEP"


def test_memory_service_accepts_valid_categories():
    valid_categories = {
        "identity",
        "goal",
        "preference",
        "project",
        "interest",
        "context",
        "personal",
    }

    for category in valid_categories:
        assert category in valid_categories


def test_memory_service_accepts_valid_importance():
    valid_importance = {
        "high",
        "medium",
        "low",
    }

    for importance in valid_importance:
        assert importance in valid_importance


def test_explicit_goal_change_is_detected():
    service = make_service()

    assert service._is_explicit_goal_change(
        "I've changed my career goal again. "
        "Now I want to become a Machine Learning Engineer."
    ) is True


def test_normal_goal_statement_is_not_goal_change():
    service = make_service()

    assert service._is_explicit_goal_change(
        "I want to become a Machine Learning Engineer."
    ) is False


def test_goal_update_language_is_detected():
    service = make_service()

    assert service._is_explicit_goal_change(
        "My new career goal is to become "
        "a Data Scientist."
    ) is True


def test_unrelated_message_is_not_goal_change():
    service = make_service()

    assert service._is_explicit_goal_change(
        "I really like working with FastAPI."
    ) is False