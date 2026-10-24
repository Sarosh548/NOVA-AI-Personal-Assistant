<div align="center">
  <img src="docs/architecture.svg" alt="NOVA architecture diagram" width="100%" />
  <h1>NOVA — Personal AI Assistant</h1>
  <p><strong>A PC-first personal AI workspace for conversation, memory, grounded knowledge, research, planning, and controlled execution.</strong></p>
  <p>
    <a href="https://github.com/Sarosh548/NOVA-AI-Personal-Assistant/actions/workflows/backend-ci.yml"><img alt="Backend CI" src="https://github.com/Sarosh548/NOVA-AI-Personal-Assistant/actions/workflows/backend-ci.yml/badge.svg?branch=main"></a>
    <img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
    <img alt="FastAPI" src="https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white">
    <img alt="React" src="https://img.shields.io/badge/UI-React%2019-61DAFB?logo=react&logoColor=111827">
    <img alt="LangGraph" src="https://img.shields.io/badge/Agent-LangGraph-6554C0">
    <img alt="PostgreSQL" src="https://img.shields.io/badge/Data-PostgreSQL%20%2B%20pgvector-4169E1?logo=postgresql&logoColor=white">
    <img alt="Docker" src="https://img.shields.io/badge/Runtime-Docker%20Compose-2496ED?logo=docker&logoColor=white">
  </p>
</div>

NOVA is a personal AI assistant project that combines a web workspace, a Python API, a stateful agent graph, persistent user data, semantic retrieval, provider integrations, and safety checks around actions. Rather than treating every request as a single chat completion, NOVA has separate boundaries for user interaction, orchestration, domain logic, persistence, and external providers.

**Scope:** this README describes the desktop/web application and code tracked in this repository. Mobile Android development is intentionally out of scope here. Optional provider features require their own credentials, quota and account configuration; cloning NOVA does not automatically connect an external service.

## Contents

- [What NOVA can do](#what-nova-can-do)
- [Architecture](#architecture)
- [How a request flows](#how-a-request-flows)
- [Technology stack](#technology-stack)
- [Repository map](#repository-map)
- [Run on Windows](#run-on-windows)
- [Configuration and integrations](#configuration-and-integrations)
- [Health checks and tests](#health-checks-and-tests)
- [Security and reliability design](#security-and-reliability-design)
- [Honest current boundaries](#honest-current-boundaries)
- [Desktop demo walkthrough](#desktop-demo-walkthrough)
- [Interview preparation](#interview-preparation)

## What NOVA can do

| Area | Capability represented in the tracked code | What it depends on |
|---|---|---|
| Conversational agent | Conversation state, planning, conditional graph routing, tool registry and tool execution services | A configured LLM provider and a working backend |
| Long-term memory | User-scoped memory records, semantic similarity retrieval and importance-aware ranking | PostgreSQL, pgvector and the configured embedding/model path |
| Knowledge base / RAG | Knowledge documents, parsing, chunking, embeddings and retrieval of relevant context | Valid source content, database, embedding dependencies and retrieval quality |
| Web research | Read-only search adapter with normalized results, topic support and time filters | A Tavily API key, network access and provider quota |
| Tasks and reminders | APIs and workspace surfaces for creating, listing and updating task/reminder records | Authenticated API and database |
| Google Calendar | OAuth connection/status flows and Calendar event operations | Google Cloud OAuth credentials, consent, redirect URI and scopes |
| Workflows | Persisted workflow definitions/steps, scheduling, worker leases and durable execution services | Database, scheduler/worker lifecycle, permissions and configured integrations |
| Approvals and permissions | Control Center paths for reviewing confirmations and managing permission rules | Authenticated account and the configured execution policy |
| Activity and audit | Activity events/reports and audit records for operational visibility | The operation must pass through the relevant recorded service path |
| Voice | Streaming WebSocket route, separate STT/TTS adapters and voice lifecycle/orchestration services | Deepgram STT, ElevenLabs TTS, microphone access, network and provider quota |
| Notifications | Notification destinations/preferences, delivery services and console/SMTP configuration | A working delivery channel; console is the local example default |
| Authentication | Session APIs, token refresh, email verification and password recovery flows | Correct JWT configuration and SMTP/provider settings for email features |
| Operations | Liveness/readiness endpoints, environment-driven security settings, migrations, idempotency and CI checks | Correct environment configuration and real integration testing |

NOVA is designed around a controlled execution loop: **understand → plan → check permission/risk → confirm when required → execute → verify → persist → report**. This is a design goal, not a guarantee that every natural-language request will be understood or every provider action will succeed.

## Architecture

<img src="docs/architecture.svg" alt="NOVA architecture: React workspace, FastAPI, LangGraph, domain services, PostgreSQL and provider adapters" width="100%">

<img src="docs/request-lifecycle.svg" alt="NOVA execution lifecycle: authenticate, plan, authorize, confirm when required, execute, verify and persist" width="100%">

These are architecture diagrams, not screenshots of a running UI. No verified desktop UI screenshots are currently tracked in the public repository. See the [screenshot capture guide](docs/SCREENSHOT_CAPTURE_GUIDE.md) for how to add genuine, privacy-safe captures from a connected desktop session.

## How a request flows

1. **Frontend:** the React workspace sends a typed API request or opens the supported voice transport.
2. **API boundary:** FastAPI validates the input, authenticates the caller and establishes user scope.
3. **Agent orchestration:** LangGraph coordinates conversation state, planning, retrieval and conditional tool routing.
4. **Domain service:** the selected service owns business logic for the operation rather than embedding every side effect in one large prompt.
5. **Authorization:** permission/risk checks and explicit confirmations constrain sensitive actions. Persisted workflows have a dedicated safety re-check before background execution.
6. **State and response:** the system persists the relevant result where applicable and returns a response/status to the workspace. External actions should be verified against the real provider state.

The key separation is that **the model may propose an action, but the execution boundary decides whether the action is allowed and what result can be reported**.

## Technology stack

| Layer | Technology | Responsibility |
|---|---|---|
| Workspace | React 19, TypeScript, Vite | Home and feature surfaces, auth screens, navigation, forms and UI states |
| API | FastAPI, Pydantic, Uvicorn | REST routes, WebSocket voice route, validation and OpenAPI docs |
| Agent | LangGraph | Stateful graph execution, routing and tool/retrieval branches |
| LLM access | Groq provider configuration and LLM service | Model-backed planning and responses |
| Retrieval | Sentence Transformers, embedding and reranking services, pgvector | Semantic vectors and retrieval for memories/knowledge |
| Persistence | PostgreSQL, SQLAlchemy, Alembic, pgvector | Relational records, vector data, migrations and durable workflow state |
| Voice | Deepgram STT, ElevenLabs TTS, adapters/orchestrators | Audio-to-text, text-to-audio and streaming lifecycle management |
| Web search | Tavily adapter | Read-only search and normalized provider results |
| Calendar | Google OAuth and Calendar API service | Calendar authorization and event operations |
| Local runtime | Docker Compose | PostgreSQL, migrations and backend startup |
| Quality | pytest, pip checks, frontend typecheck/build, Compose smoke tests | Regression, integration and runtime checks |

## Repository map

~~~text
NOVA-AI-Personal-Assistant/
├── backend/
│   ├── agent/                 # LangGraph graph and state
│   ├── api/                   # FastAPI routes and schemas
│   ├── database/              # DB connection and initialization
│   ├── migrations/            # Alembic migrations and legacy baseline
│   ├── models/                # SQLAlchemy models
│   ├── services/              # Domain logic, providers and safety
│   ├── tests/                 # Backend regression/service/API tests
│   ├── config.py              # Environment-backed configuration
│   └── main.py                # FastAPI application/lifecycle
├── frontend/
│   └── src/
│       ├── api/               # Typed API client
│       ├── auth/              # Auth provider and sign-in screens
│       ├── components/        # Reusable UI components
│       ├── layout/            # Workspace shell/navigation
│       └── surfaces/          # Home, conversation, voice, tasks,
│                              # reminders, calendar, memory, knowledge,
│                              # activity, settings and Control Center
├── docs/
│   ├── architecture.svg
│   ├── request-lifecycle.svg
│   ├── INTERVIEW_GUIDE.md
│   └── SCREENSHOT_CAPTURE_GUIDE.md
├── .github/workflows/         # Backend CI, frontend CI, Pages preview
├── .env.example               # Local configuration template
├── docker-compose.local.yml   # Database, migration job, backend
├── Dockerfile                 # Non-root Python backend image
├── requirements.txt
└── README.md
~~~

## Run on Windows

### Prerequisites

- Windows 10/11 and PowerShell
- Docker Desktop with Docker Compose v2
- Python 3.12 for local test/development workflows
- Node.js 20.19+ and npm 10+ for the frontend
- Provider credentials for the features you plan to exercise

### 1. Clone and configure

~~~powershell
git clone https://github.com/Sarosh548/NOVA-AI-Personal-Assistant.git
Set-Location NOVA-AI-Personal-Assistant
Copy-Item .env.example .env
notepad .env
~~~

Set a valid <code>GROQ_API_KEY</code> in the local <code>.env</code> for model-backed agent features. Replace local-only secrets with strong random values. Never commit <code>.env</code>, API keys, refresh tokens, database dumps, or personal data.

Generate a development JWT secret locally with:

~~~powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
~~~

Paste the generated value into <code>AUTH_JWT_SECRET_KEY</code>. Treat the sample database password and any default JWT value as development-only.

### 2. Start the database, migrations and API

~~~powershell
docker compose -f docker-compose.local.yml up --build -d
docker compose -f docker-compose.local.yml ps
docker compose -f docker-compose.local.yml logs -f backend
~~~

The Compose file starts three services:

- **postgres** — PostgreSQL with pgvector available;
- **migrate** — applies Alembic migrations after the database is healthy;
- **backend** — FastAPI, started after the migration job completes.

Local defaults are PostgreSQL host port <code>5433</code> and backend port <code>8000</code>. Override with <code>POSTGRES_HOST_PORT</code> and <code>BACKEND_HOST_PORT</code> in <code>.env</code> if necessary.

### 3. Start the frontend

Open a second PowerShell window from the repository root:

~~~powershell
Set-Location .\frontend
npm install
npm run dev
~~~

Open **http://127.0.0.1:5173**. During Vite development, the frontend defaults to the local API at <code>http://127.0.0.1:8000</code>. For a different backend origin, set <code>VITE_NOVA_API_BASE_URL</code> before starting or building the frontend.

### 4. Verify the runtime

| URL | Purpose |
|---|---|
| <code>http://127.0.0.1:5173</code> | Development frontend |
| <code>http://127.0.0.1:8000/docs</code> | FastAPI OpenAPI docs |
| <code>http://127.0.0.1:8000/health/live</code> | Process liveness |
| <code>http://127.0.0.1:8000/health/ready</code> | Readiness, including database connectivity |

Readiness should return HTTP 200 when the API can reach its database. A successful frontend build alone does not prove the database, provider credentials or external actions work.

### Stop the local stack

~~~powershell
docker compose -f docker-compose.local.yml down
~~~

This stops the containers but preserves the named database volume. Do **not** add <code>-v</code> unless you intentionally want to delete local database data.

## Configuration and integrations

All secrets belong in the backend/runtime environment—not in frontend source or screenshots. <code>.env.example</code> is the reference for the tracked local configuration.

| Variables | Purpose | Needed when |
|---|---|---|
| <code>GROQ_API_KEY</code> | LLM-backed agent responses/planning | Model-backed agent requests |
| <code>TAVILY_API_KEY</code> | Read-only live web search | Web research |
| <code>DEEPGRAM_API_KEY</code> | Speech-to-text | Configured voice STT route |
| <code>ELEVENLABS_API_KEY</code>, <code>ELEVENLABS_VOICE_ID</code> | Text-to-speech | Configured voice TTS route |
| <code>CALENDAR_GOOGLE_CLIENT_ID</code>, <code>CALENDAR_GOOGLE_CLIENT_SECRET</code> | Google OAuth credentials | Calendar connection |
| <code>CALENDAR_GOOGLE_REDIRECT_URI</code>, <code>CALENDAR_GOOGLE_SCOPES</code> | OAuth callback and access scope | Calendar authorization |
| <code>INTEGRATION_TOKEN_ENCRYPTION_KEY</code> | Fernet key for integration-token encryption | When token encryption is enabled |
| <code>NOTIFICATION_SMTP_*</code>, <code>NOTIFICATION_EMAIL_FROM_ADDRESS</code> | SMTP delivery settings | Email notifications/account emails |
| <code>AUTH_JWT_SECRET_KEY</code> | Signs app auth tokens | Authentication |
| <code>DATABASE_URL</code> | SQLAlchemy database URL | Direct backend runs; Compose injects its own |
| <code>VITE_NOVA_API_BASE_URL</code> | API origin used by the frontend build | Non-development deployments |

### Google Calendar

1. Create OAuth credentials in Google Cloud.
2. Register the exact redirect URI for the running backend, for example <code>http://localhost:8000/integrations/google/calendar/callback</code> for local development.
3. Set the client ID and client secret in the backend environment.
4. Complete OAuth using the intended NOVA account.
5. Test with a disposable event and verify the result in the actual Google Calendar account.

### GitHub Pages is a static frontend preview

The frontend can be built and deployed to GitHub Pages, but **Pages does not host the FastAPI backend or PostgreSQL database**. A real sign-in requires a reachable backend endpoint, correct CORS/trusted-host settings, HTTPS for a public deployment, and a build-time <code>VITE_NOVA_API_BASE_URL</code>. In a public deployment, <code>localhost</code> points to the visitor's own machine, not to your development PC. Never put provider secrets in <code>VITE_*</code> variables.

## Health checks and tests

### Backend

The backend CI workflow uses Python 3.12, installs dependencies, runs <code>pip check</code>, validates the Compose configuration, prepares PostgreSQL/pgvector, applies Alembic migrations, runs pytest, performs a Docker Compose smoke test and checks whitespace.

To run backend tests locally, first create the root virtual environment and install the requirements. The tests need a PostgreSQL database with pgvector and the expected migrations; CI sets up a dedicated database explicitly.

~~~powershell
Set-Location <repository-root>
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Start PostgreSQL using the Compose instructions above, then configure the test connection.
$env:DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:5433/nova_db"
$env:GROQ_API_KEY = "local-test-key"
$env:AUTH_JWT_SECRET_KEY = "local-test-auth-jwt-secret-key-32-characters-min"

Set-Location .\backend
..\.venv\Scripts\python.exe -m pytest -q
~~~

Use a disposable local/test database, not a database containing important personal records. Make sure the database URL and migration state match the tests you are running; CI prepares the database, including pgvector and Alembic migrations.

### Frontend

~~~powershell
Set-Location .\frontend
npm install
npm run typecheck
npm run build
~~~

The GitHub workflow definitions are under [.github/workflows](.github/workflows/). CI passing on one commit proves the checks for that commit, not that every provider account or current local process is connected.

## Security and reliability design

- **User-scoped access:** API routes use authenticated-user dependencies and pass user identity into services that read/write private data.
- **Validation:** Pydantic request/response schemas define API contracts and constrain payloads.
- **Permissions and confirmations:** the permission and confirmation paths make authority explicit for supported sensitive actions.
- **Workflow safety re-check:** persisted workflow execution re-evaluates permissions immediately before background execution.
- **Idempotency:** mutating routes use idempotency support where implemented. A key reused with a different request can be rejected as a conflict instead of silently duplicating an operation.
- **Durable state:** PostgreSQL and migrations hold application state across backend restarts. Workflow definitions/steps and leases are stored separately from in-memory agent state.
- **Provider boundaries:** LLM, web search, voice, Calendar and notification integrations are organized behind service/adaptor modules.
- **Bounded voice processing:** the voice configuration includes payload/audio limits, queue limits, finalization timeouts and provider connection/close settings.
- **Operational checks:** liveness and readiness are separate; readiness checks database connectivity. CI adds migration and container smoke checks.
- **Deployment hardening:** CORS, trusted hosts, request-size limits, rate limits, structured logging and a non-root Docker runtime are configuration/code boundaries—not a substitute for deployment-specific security review.

These controls reduce common failure modes. They do not make every generated answer correct or every provider call infallible. Verify consequential operations in the target provider before reporting success.

## Honest current boundaries

- Model-backed responses and optional providers require credentials, quota, network access and correct environment configuration.
- Google Calendar requires a successful OAuth connection and matching redirect URI/scope.
- Voice recognition and synthesis depend on the selected provider, live session, network, microphone access and device audio route.
- The public Pages build is a static frontend preview until configured with a reachable backend; it is not a fully hosted multi-user service by itself.
- The repository contains architecture diagrams but no verified desktop UI screenshots yet. See the [capture guide](docs/SCREENSHOT_CAPTURE_GUIDE.md).
- This README describes committed code. Local experiments that have not been pushed and tested are not part of the public feature contract.
- “Production-ready” should be claimed only after real-provider end-to-end tests, security review, deployment monitoring, backups/restore drills, load tests and incident/recovery procedures are complete.

## Desktop demo walkthrough

Use a dedicated demo account and generic, non-sensitive data.

1. Sign in and show the Home dashboard and workspace navigation.
2. Create a conversation and make a representative request.
3. Create a harmless sample task and reminder; refresh the workspace to demonstrate persistence.
4. Add a small sample knowledge document and ask a question grounded in its content.
5. Open Memory and Activity to explain personalization versus source knowledge and audit/event visibility.
6. Open Control Center and explain permissions, confirmations, workflow status and notification settings.
7. If Tavily or Google Calendar is configured, demonstrate one search or a disposable Calendar event and verify the result in the real provider UI.
8. If voice is configured, state the actual STT/TTS provider and test the live connection in a quiet environment.

Do not show credentials, personal emails, private Calendar details, or destructive/financial operations in a portfolio demo.

## Interview preparation

Read the companion [NOVA Interview Guide](docs/INTERVIEW_GUIDE.md) for a spoken project pitch, the end-to-end request path, technical Q&A, design trade-offs and an honest production-readiness answer. Learn why each boundary exists and be able to point to the code and tests that implement it.

## Contributing

1. Create a focused branch for a small change.
2. Add regression tests for the behavior being changed.
3. Run relevant backend tests and frontend typecheck/build.
4. Run <code>git diff --check</code>.
5. Verify external actions against the real provider during an integration test; mocked unit tests do not prove a provider account is connected.
6. Keep secrets, tokens, local database contents and private screenshots out of commits.
