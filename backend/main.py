

def _execute_chat(
    *,
    request: ChatRequest,
    current_user_id: str,
) -> dict:
    conversation_execution_service.bind_dependencies(
        conversation_service=conversation_service,
        execution_service=execution_service,
        llm_service=llm_service,
        memory_service=memory_service,
    )

    return conversation_execution_service.execute_message(
        user_id=current_user_id,
        message=request.message,
        conversation_id=request.conversation_id,
        execution_context=ExecutionContext.interactive(),
    )


@app.post("/chat")
def chat(
    request: ChatRequest,
    current_user_id: CurrentUserId,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
):
    normalized_message = request.message.strip()
