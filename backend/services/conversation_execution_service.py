from __future__ import annotations

from typing import Any

from services.conversation_service import ConversationService
from services.execution_context import ExecutionContext
from services.execution_service import NOVAExecutionService
from services.llm_service import LLMService
from services.memory_service import MemoryService


class ConversationExecutionService:
    """
    Shared conversational execution boundary for NOVA.

    This service owns the orchestration around the existing NOVA graph:
    conversation lookup, bounded history, execution, persistence, and
    memory extraction. Transport layers such as HTTP and realtime voice
    remain responsible only for protocol concerns.
    """

    def __init__(
        self,
        *,
        conversation_service: ConversationService,
        execution_service: NOVAExecutionService,
        llm_service: LLMService,
        memory_service: MemoryService,
        context_max_messages: int = 12,
        context_max_characters: int = 12_000,
    ):
        if context_max_messages < 1:
            raise ValueError(
                "context_max_messages must be greater than 0."
            )

        if context_max_characters < 1:
            raise ValueError(
                "context_max_characters must be greater than 0."
            )

        self.conversation_service = conversation_service
        self.execution_service = execution_service
        self.llm_service = llm_service
        self.memory_service = memory_service
        self.context_max_messages = context_max_messages
        self.context_max_characters = context_max_characters

    def execute_message(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: int | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> dict[str, Any]:
        user_message = str(message).strip()

        if not user_message:
            return {
                "error": "message cannot be empty"
            }

        resolved_context = (
            execution_context
            if execution_context is not None
            else ExecutionContext.interactive()
        )

        conversation_id = (
            self.conversation_service
            .get_or_create_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
            )
        )

        history = (
            self.conversation_service
            .get_context_history(
                user_id=user_id,
                conversation_id=conversation_id,
                max_messages=self.context_max_messages,
                max_characters=self.context_max_characters,
            )
        )

        if not history:
            title = (
                self.llm_service
                .generate_conversation_title(
                    user_message
                )
            )

            self.conversation_service.update_conversation_title(
                conversation_id=conversation_id,
                user_id=user_id,
                title=title,
            )

        result = self.execution_service.execute(
            user_id=user_id,
            conversation_id=conversation_id,
            user_message=user_message,
            history=history,
            execution_context=resolved_context,
        )

        response = result["response"]

        understanding = result["understanding"]
        plan = result.get("plan", {})
        permission = result.get("permission", {})
        confirmation = result.get("confirmation", {})
        tool_result = result["tool_result"]
        workflow_result = result.get("workflow_result", {})
        knowledge_sources = result.get("knowledge_sources", [])
        web_sources = result.get("web_sources", [])

        self.conversation_service.save_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="user",
            content=user_message,
        )

        self.conversation_service.save_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="assistant",
            content=response,
        )

        new_memory = self.llm_service.extract_memory(
            user_message
        )

        memory_action = None

        if new_memory:
            memory_action = (
                self.memory_service.add_memory(
                    user_id=user_id,
                    memory_text=new_memory["memory_text"],
                    category=new_memory["category"],
                    importance=new_memory["importance"],
                    user_message=user_message,
                )
            )

        return {
            "response": response,
            "conversation_id": conversation_id,
            "understanding": understanding,
            "plan": plan,
            "permission": permission,
            "confirmation": confirmation,
            "tool_result": tool_result,
            "workflow_result": workflow_result,
            "memory_action": memory_action,
            "knowledge_sources": knowledge_sources,
            "web_sources": web_sources,
        }
