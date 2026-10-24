# NOVA — Interview Preparation Guide

This guide explains the desktop/web application tracked in this repository. It is split into a spoken pitch, the technical request flow, design questions, a demo plan, and honest production-readiness boundaries.

## 1. A 30–45 second pitch

> NOVA is a personal AI assistant built as a full-stack system rather than a single chat prompt. Its React and TypeScript workspace talks to a FastAPI backend. LangGraph coordinates conversation state, planning, tool routing and retrieval. PostgreSQL stores application state, while pgvector supports semantic retrieval for user memory and the knowledge base. The project also includes task/reminder management, Google Calendar OAuth, read-only web research, streaming voice adapters, durable workflows, permissions, confirmations, activity/audit records, and CI checks. My main design goal is to separate model reasoning from authorized execution so that sensitive actions, provider failures and persistence are handled at explicit service boundaries.

Only describe a feature as working in your demo when it is actually configured and verified in that environment. Voice, web research, Calendar, SMTP and other integrations depend on credentials, network access, quota and user consent.

## 2. Two-minute architecture walkthrough

1. **Frontend:** React and TypeScript render the Home, Conversation, Voice, Tasks, Reminders, Calendar, Knowledge, Memory, Activity, Settings and Control Center surfaces. Typed API clients isolate request code from presentation.
2. **API boundary:** FastAPI exposes routes and OpenAPI schemas. Pydantic validates payloads. Authentication dependencies establish the current user and user-scoped access.
3. **Orchestration:** the LangGraph graph manages request state and routes work between conversation, tools, memory/knowledge retrieval and workflow paths.
4. **Domain services:** service classes implement authentication, tasks, reminders, knowledge, memory, web search, Calendar, notifications, workflow lifecycle, risk checks and voice orchestration.
5. **Persistence:** SQLAlchemy and Alembic manage PostgreSQL state and schema. pgvector stores/searches embeddings. Durable workflow state is separate from in-memory agent state.
6. **Safety:** request authorization, permission rules, confirmations, idempotency and workflow safety re-checks constrain execution.
7. **Operations:** health endpoints, config validation, provider timeouts/limits, automated tests and Docker Compose make local setup and failure diagnosis explicit.

## 3. Request flow

~~~text
User request
   |
   v
React UI / supported voice client
   |
   v
FastAPI route -> authenticate + validate + enforce user scope
   |
   v
LangGraph state / plan / route
   |                        \
   |                         -> memory / knowledge / web retrieval
   v
Tool registry / domain service
   |
   v
Risk + permission check ---> explicit confirmation when required
   |
   v
Provider or database operation
   |
   v
Verify result -> persist state/activity/audit -> respond to UI
~~~

The important distinction is that planning is not execution. A reliable design has an explicit boundary between what an LLM proposes and what the application is permitted to do.

## 4. Interview questions and sample answers

### What problem does NOVA solve?

It brings conversational assistance, saved context, knowledge retrieval and structured tools into one workspace. Supported requests can lead to persisted records such as tasks, reminders, Calendar events or workflow state instead of returning only generated text.

### Why LangGraph rather than one long prompt?

A graph makes state and transitions explicit. Conditional routing can choose between answering, retrieving context, calling a tool or entering a workflow path. It also supports testing and debugging at node/service boundaries.

### Explain RAG in NOVA.

Retrieval-augmented generation supplies relevant source content to the language model. The application parses and stores knowledge, computes embeddings, retrieves semantically relevant candidates with pgvector and ranking services, then provides the retrieved context to the response path. Quality depends on extraction, chunk boundaries, embeddings, user filters, ranking and source quality. RAG is not a guarantee of correctness.

### How are memory and the knowledge base different?

Memory is user-centric context meant to personalize later interactions. The knowledge base stores source material that should be retrieved for a question. They can share embedding/search infrastructure, but have different meaning and management expectations. User-scoped queries are essential to avoid cross-account data exposure.

### Why PostgreSQL plus pgvector?

PostgreSQL stores relational records and provides transactions, constraints, indexes and migrations. pgvector adds vector similarity without requiring every workflow to be split across a separate vector service. Relational user filters remain near the semantic query. A separate vector store can be evaluated later if measured scale or operating requirements justify it.

### What happens when the LLM suggests an action?

The request passes through the agent/tool architecture, but domain services own execution. They validate input, authorize the operation, apply domain rules, and require explicit confirmation where the policy says so. Persisted workflows have a dedicated safety re-check before background execution. A plan or spoken acknowledgement is not proof that an action succeeded.

### What are permissions and confirmations?

Permissions define which operations a user or workflow is allowed to perform. A confirmation represents an explicit user decision on a pending action when required. The Control Center exposes permission and approval workflows. Checking authority again at execution time prevents a previously created plan from retaining permission after the rules change.

### Explain idempotency.

Networks fail and clients retry. An idempotency key and request hash can allow a repeated create request to reuse an earlier result or reject a key reused with a different payload. This helps prevent accidental duplicate mutations. It is endpoint-specific and should be tested with same-key/same-payload and same-key/different-payload cases.

### How does the tracked voice pipeline work?

The repository exposes a streaming WebSocket voice API and separates speech-to-text and text-to-speech behind adapters/orchestrators. The configured baseline uses Deepgram STT and ElevenLabs TTS. Payload limits, queue sizes, timeouts, finalization and session lifecycle settings help bound resource use. Actual voice behavior still depends on valid keys, network, microphone access, provider quota and device audio routing.

Do not claim that a local, uncommitted LiveKit/Gemini experiment is shipped in the public repository unless that implementation is added, reviewed, tested and pushed.

### How is web research implemented?

The Tavily adapter defines an HTTPS endpoint, timeout and result limits, then normalizes provider-specific output into a stable shape. The rest of the application can work with a consistent result model. A search result is evidence to evaluate—not an instruction to execute.

### Tasks, reminders and workflows: what is the difference?

Tasks and reminders are individual user-facing records. A workflow is a persisted multi-step plan with a lifecycle. Workflow services, scheduling, durable execution, worker leases and safety checks support coordinated execution. Durable records and leases help manage work, but do not remove all distributed-system failure modes.

### How do you prevent one user from accessing another user's data?

The API uses authentication dependencies and passes user identity into scoped queries/services. Hiding a button in the frontend is not access control: each relevant backend read/write needs proper user scoping. The repository includes authentication and user/memory/knowledge/workflow isolation tests.

### How is NOVA tested?

Backend CI sets up Python 3.12 and PostgreSQL/pgvector, installs dependencies, runs dependency consistency checks, validates Compose config, enables the vector extension, applies migrations, runs pytest and performs a Compose runtime smoke test. Frontend CI runs TypeScript typechecking and a production build. Mock-based unit tests validate local logic; real-provider integration tests are still needed to prove a real account/credential works.

### What happens when a provider is unavailable?

Service boundaries and configured timeouts/queues help constrain failures. Health routes distinguish basic liveness from database-aware readiness. The application should report a failed or uncertain result instead of inventing success. Real external-provider availability also needs monitoring and integration tests.

### Is NOVA production-ready?

A responsible answer is: “The code includes production-oriented controls—typed API contracts, authentication/user scoping, migrations, idempotency, permissions/confirmations, health endpoints, Docker, and CI. I would not call the deployment production-certified until the target environment passes live-provider end-to-end tests, a security review, load/performance checks, backup/restore drills, monitoring/alerts and incident/recovery exercises.” Then explain exactly which tests were run on the commit under discussion.

## 5. A 3–5 minute desktop demo

Use a dedicated demo account and non-sensitive test data.

1. Show Home and explain frontend/API navigation.
2. Create a new conversation and ask a representative question.
3. Create a harmless sample task and reminder; refresh the UI to demonstrate persistence.
4. Add a short knowledge document and ask a question grounded in it.
5. Open Memory and Activity; explain personal context versus source knowledge and activity traces.
6. Open Control Center; explain permissions, approvals, workflows and notification settings.
7. If Tavily or Google Calendar is configured, demonstrate one search or a disposable Calendar event and verify it in the real provider UI.
8. Only demo voice when credentials, microphone access, quota and session state are ready.

Narrate what is happening and show the resulting state. If a provider is disconnected, explain the dependency rather than pretending the operation succeeded.

## 6. Read the code in this order

1. <code>frontend/src/app/AppRoot.tsx</code> and <code>frontend/src/layout/AppShell.tsx</code> — entry point and navigation.
2. <code>frontend/src/api/client.ts</code> and <code>frontend/src/api/workspace.ts</code> — API/auth handling and workspace calls.
3. <code>backend/main.py</code> and <code>backend/api/dependencies.py</code> — app lifecycle and authenticated API boundary.
4. <code>backend/agent/graph.py</code> and <code>backend/agent/state.py</code> — agent state, graph routing and tool nodes.
5. <code>backend/services/tool_registry.py</code>, <code>tool_router.py</code> and <code>execution_service.py</code> — tool selection and execution.
6. <code>memory_service.py</code>, <code>knowledge_service.py</code>, <code>embedding_service.py</code> and <code>reranker_service.py</code> — retrieval path.
7. <code>confirmation_service.py</code>, <code>confirmation_execution_service.py</code>, <code>risk_policy_service.py</code>, <code>plan_permission_service.py</code> and <code>workflow_execution_safety_service.py</code> — action authorization.
8. <code>idempotency_service.py</code>, <code>durable_workflow_execution_service.py</code> and <code>autonomous_workflow_scheduler.py</code> — retries, duplication and durable work.
9. <code>backend/api/voice.py</code>, voice STT/TTS orchestrators and provider adapters — streaming voice.
10. <code>backend/tests/</code> and <code>.github/workflows/</code> — behavior contracts and quality checks.

## 7. Glossary

- **API contract:** request/response schema shared by frontend and backend.
- **JWT:** signed claims commonly used to represent an authenticated session.
- **OAuth:** delegated authorization used for Google Calendar.
- **RAG:** retrieve relevant source content and provide it to generation.
- **Embedding:** vector representation of text used for semantic similarity.
- **pgvector:** PostgreSQL extension for vector storage and distance operations.
- **Idempotency key:** request key used to make supported mutation retries safer.
- **Lease:** time-limited ownership claim used to coordinate a worker's execution.
- **Backpressure:** producer/queue behavior when a consumer cannot keep up.
- **Liveness/readiness:** liveness checks that the process is up; readiness checks whether required dependencies (such as the database) are usable.

## 8. Interview honesty checklist

- Know which provider credentials are configured in your demo environment.
- Separate code committed to GitHub from local experiments.
- State which tests passed and on which commit.
- Do not call an action “verified” until the resulting database/provider state has been checked.
- Be ready to describe one failure, its reproduction, the regression test, and the verification steps.
- Discuss security, operations, provider dependencies, monitoring and restore plans rather than saying a complex AI system is perfect.
