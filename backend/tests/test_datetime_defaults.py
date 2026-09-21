from datetime import datetime, timezone

from models.conversation import _utc_now_naive as conversation_now
from models.knowledge_chunk import _utc_now_naive as knowledge_chunk_now
from models.knowledge_document import _utc_now_naive as knowledge_document_now
from models.memory import _utc_now_naive as memory_now
from models.task import _utc_now_naive as task_now


def test_model_utc_helpers_return_naive_utc_datetimes():
    helpers = [
        task_now,
        conversation_now,
        memory_now,
        knowledge_document_now,
        knowledge_chunk_now,
    ]

    before = datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )

    values = [
        helper()
        for helper in helpers
    ]

    after = datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )

    assert all(
        value.tzinfo is None
        for value in values
    )

    assert all(
        before <= value <= after
        for value in values
    )
