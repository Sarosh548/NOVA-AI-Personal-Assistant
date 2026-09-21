from __future__ import annotations

from dataclasses import dataclass

from services.rag_evaluation_service import (
    RAGEvaluationCase,
)


@dataclass(frozen=True)
class RAGBenchmarkDocument:
    source_id: str
    title: str
    content: str


RAG_BENCHMARK_DOCUMENTS: tuple[
    RAGBenchmarkDocument,
    ...
] = (
    RAGBenchmarkDocument(
        source_id="nova-auth",
        title="NOVA Authentication",
        content=(
            "NOVA authentication exposes register, login, refresh, "
            "logout, and me routes. Authenticated requests use the "
            "current authenticated user identity instead of a client "
            "supplied user identifier."
        ),
    ),
    RAGBenchmarkDocument(
        source_id="nova-memory",
        title="NOVA Long-Term Memory",
        content=(
            "NOVA stores user-scoped long-term memories and retrieves "
            "semantically similar memories for relevant context. "
            "Memory retrieval uses embeddings and a similarity threshold."
        ),
    ),
    RAGBenchmarkDocument(
        source_id="nova-rag-grounding",
        title="NOVA RAG Grounding",
        content=(
            "NOVA can retrieve knowledge chunks from the user's "
            "knowledge base and expose source metadata as grounded "
            "knowledge sources in chat responses."
        ),
    ),
    RAGBenchmarkDocument(
        source_id="nova-url-ingestion",
        title="NOVA URL Knowledge Ingestion",
        content=(
            "URL knowledge ingestion validates and safely fetches web "
            "pages, extracts visible HTML text, and persists the parsed "
            "content through KnowledgeService. The API endpoint is "
            "POST /knowledge/urls."
        ),
    ),
    RAGBenchmarkDocument(
        source_id="nova-document-parsing",
        title="NOVA PDF and DOCX Parsing",
        content=(
            "NOVA has a document parsing foundation for PDF and DOCX "
            "files. Parsing extracts normalized text before the content "
            "is passed into knowledge ingestion."
        ),
    ),
    RAGBenchmarkDocument(
        source_id="nova-permission",
        title="NOVA Permission and Confirmation",
        content=(
            "NOVA evaluates permission and risk before state-changing "
            "actions. High-risk operations require explicit confirmation, "
            "and approved confirmations use one-time replay-protected "
            "execution."
        ),
    ),
    RAGBenchmarkDocument(
        source_id="nova-planner",
        title="NOVA Planner",
        content=(
            "NOVA converts user intent into structured executable plans. "
            "Planning requests can contain multiple ordered steps with "
            "dependencies, while execution happens after policy checks."
        ),
    ),
    RAGBenchmarkDocument(
        source_id="nova-calendar",
        title="NOVA Calendar Integration",
        content=(
            "NOVA can route supported calendar operations through its "
            "calendar tool service. Calendar actions remain subject to "
            "the same planning, permission, and confirmation controls."
        ),
    ),
)


RAG_BENCHMARK_CASES: tuple[RAGEvaluationCase, ...] = (
    RAGEvaluationCase(
        query="Which routes are available for NOVA authentication?",
        relevant_ids=frozenset({"nova-auth"}),
    ),
    RAGEvaluationCase(
        query="How does NOVA retrieve long-term memories?",
        relevant_ids=frozenset({"nova-memory"}),
    ),
    RAGEvaluationCase(
        query="Does NOVA return sources for grounded RAG answers?",
        relevant_ids=frozenset({"nova-rag-grounding"}),
    ),
    RAGEvaluationCase(
        query="How can I add a web page to NOVA knowledge?",
        relevant_ids=frozenset({"nova-url-ingestion"}),
    ),
    RAGEvaluationCase(
        query="What file formats have a parsing foundation in NOVA?",
        relevant_ids=frozenset({"nova-document-parsing"}),
    ),
    RAGEvaluationCase(
        query="When does NOVA require explicit confirmation?",
        relevant_ids=frozenset({"nova-permission"}),
    ),
    RAGEvaluationCase(
        query="How does NOVA represent multi-step plans?",
        relevant_ids=frozenset({"nova-planner"}),
    ),
    RAGEvaluationCase(
        query="How are calendar operations routed?",
        relevant_ids=frozenset({"nova-calendar"}),
    ),
    RAGEvaluationCase(
        query=(
            "What controls apply before a calendar operation is executed?"
        ),
        relevant_ids=frozenset({
            "nova-calendar",
            "nova-permission",
            "nova-planner",
        }),
    ),
    RAGEvaluationCase(
        query=(
            "How does NOVA move web content into its grounded knowledge "
            "answers?"
        ),
        relevant_ids=frozenset({
            "nova-url-ingestion",
            "nova-rag-grounding",
        }),
    ),
)


DEFAULT_BENCHMARK_K_VALUES: tuple[int, ...] = (
    1,
    3,
    5,
    8,
)
