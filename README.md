# NOVA — Personal AI Executive Assistant

NOVA is a local-first personal AI workspace for natural conversation, saved user context, planning, research, reminders, calendar workflows, and permission-aware actions. The product goal is an assistant that **understands a request, selects an appropriate tool, executes it, verifies the real result, and reports honestly**—not one that merely gives instructions or claims an action succeeded.

> Development status: the working tree contains active, uncommitted implementation work. Test and build results in chat refer to the exact run reported there; do not assume every external integration or every application has passed live acceptance.

## Product principles

- Voice and text should share conversation history and user-scoped memory.
- Use direct integrations where reliable APIs exist; use bounded Windows UI Automation where a real UI is required.
- Verify execution results before saying an action succeeded.
- Use explicit approval for consequential actions such as sending email, destructive changes, payments, or public posting.
- Treat timeouts as an unknown outcome until checked. Never blindly repeat an action that may already have executed.
- Preserve the user's existing work and report unavailable providers, permissions, or network access accurately.

## Current architecture

- **Backend:** FastAPI, Python 3.12 virtual environment, SQLAlchemy, PostgreSQL, Alembic, pgvector, and a shared conversation execution graph.
- **Agent/execution:** intent parsing, planning, permission and confirmation policies, a tool router, task/reminder/calendar/workflow services, memory, and activity/audit records.
- **Voice:** LiveKit WebRTC room transport with a Gemini Live realtime model; classic voice and optional OpenAI Realtime paths remain available for provider testing. The Windows startup script loads provider settings from the current user's Windows environment.
- **Frontend:** React, TypeScript, and Vite; the local development server runs on port 5173.
- **Research:** local SearXNG plus optional external search providers.
- **Local data/services:** PostgreSQL database `nova_db`, normally mapped to host port 5433; API port 8000; local LiveKit signaling port 7880 and media ports 7881/7882 when self-hosted.

Main code locations:

| Path | Purpose |
| --- | --- |
| `backend/main.py` | FastAPI application, service setup, lifecycle |
| `backend/agent/graph.py` | Shared planning/execution graph and verified tool-result responses |
| `backend/services/intent_service.py` | Intent classification and deterministic command routing |
| `backend/services/conversation_execution_service.py` | Shared text/voice execution entry point |
| `backend/services/tool_router.py` | Registration and invocation of tools |
| `backend/services/desktop_control_service.py` | Opt-in, allowlisted local Windows desktop controls |
| `backend/livekit_voice_agent.py` | LiveKit voice worker, Gemini realtime recovery, voice execution bridge |
| `backend/api/voice.py`, `backend/api/livekit_voice.py`, `backend/api/gemini_live_voice.py` | Voice/session API routes |
| `backend/services/memory_service.py` | User-scoped persistent memory |
| `backend/migrations/versions/` | Alembic schema migrations |
| `frontend/src/surfaces/LiveKitVoiceSurface.tsx` | LiveKit voice interface and bounded reconnect behavior |
| `frontend/src/surfaces/VoiceSurface.tsx` | Voice surface selector |
| `scripts/nova_startup.py` | Windows development startup orchestration |
| `docker-compose.local.yml` | Local PostgreSQL, SearXNG, and containerized backend/migration configuration |

## Windows development setup

Prerequisites: Windows, Python 3.12, Node.js/npm compatible with `frontend/package.json`, Docker Desktop for the local database/Search/LiveKit services, and the provider credentials required by the features being tested.

1. Open PowerShell and go to the repository:

   ```powershell
   Set-Location D:\NOVA
   ```

2. Create your private local `.env` from `.env.example` if you use environment-file configuration. Never commit credentials. The current startup script also reads supported values from the **current user's Windows environment**.

3. Start the local database and search service if they are not already running:

   ```powershell
   docker compose -f docker-compose.local.yml up -d postgres searxng
   ```

4. Install Python dependencies in the project's Python 3.12 environment if needed:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
   ```

5. Apply the current database migrations:

   ```powershell
   Set-Location D:\NOVA\backend
   ..\.venv\Scripts\python.exe -m alembic upgrade head
   Set-Location D:\NOVA
   ```

6. Start NOVA with the repository's Windows orchestration script:

   ```powershell
   .\.venv\Scripts\python.exe scripts\nova_startup.py
   ```

   The script starts missing local services and avoids launching duplicate backend, frontend, or voice-agent processes when it finds an existing one. It loads the selected Gemini/LiveKit and desktop-control configuration from the current user's Windows environment. If the LiveKit agent was already running, editing its Python source does not itself reload that running process; start a fresh voice session with the latest worker loaded when testing code changes.

7. Open the local workspace at [http://127.0.0.1:5173](http://127.0.0.1:5173). The API readiness endpoint is [http://127.0.0.1:8000/health/ready](http://127.0.0.1:8000/health/ready).

### Provider configuration

- **Gemini Live voice:** set `GEMINI_API_KEY`; `GEMINI_LIVE_MODEL` and `GEMINI_LIVE_VOICE` select the provider model/voice. Provider free-tier access, model availability, quotas, DNS, and network stability are external dependencies.
- **Chat and intent model:** configure `GROQ_API_KEY` for the current local setup.
- **LiveKit:** leave `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` blank for local development when the startup script is using its local defaults. Hosted LiveKit requires matching URL/key/secret values.
- **Web research:** local SearXNG is available via the local Compose setup; `TAVILY_API_KEY` is optional where that provider is enabled.
- **Google Calendar and Gmail:** configure the relevant Google OAuth client settings and complete authorization in NOVA. Use the exact redirect URI registered with Google. Mail and calendar scopes are separate; verify each integration's granted scopes in its own setup.
- **Optional providers:** Deepgram, ElevenLabs, Azure Speech, and OpenAI Realtime are configured only if their feature path is used. OpenAI Realtime may require available API quota.
- **Database security:** development defaults are not production secrets. Use unique, sufficiently long secrets and strong database credentials outside an isolated local machine. Keep provider API keys server-side; do not expose them as `VITE_*` frontend variables.

## Desktop automation and security boundary

Windows desktop control is opt-in. The `DesktopControlService` requires Windows and `NOVA_ENV=development`; enable it only for a trusted local desktop session using `NOVA_DESKTOP_CONTROL_ENABLED=true` in the current user's Windows environment before starting the app.

Current bounded desktop capabilities include:

- Open allowlisted apps and HTTP(S) URLs; perform a Google web search; open standard user folders and the allowlisted Local Disk C root.
- Search approved user locations for file names, including bounded CV/resume discovery; open only supported file types after resolving a safe match.
- Inspect visible Windows accessibility labels, click one uniquely matched safe control, type into a uniquely matched non-sensitive field, and use an allowlisted keyboard shortcut.
- Attempt YouTube/Spotify playback for a specifically named title and report success only if the actual player state is verified.

Generic UI clicks do not authorize sending/deleting emails or messages, payments, public posting, approval, installation, credential entry, or other consequential external changes. Those require a dedicated authenticated integration and the application's confirmation policy. Never expose unrestricted OS control over a public API server. Windows UI Automation is not Android/mobile automation; mobile control needs a separate device-side integration, permission model, and end-to-end tests.

## Tests and quality checks

Run commands from PowerShell. Use the repository's venv Python rather than a global Python/pytest installation.

**Full backend tests**

```powershell
Set-Location D:\NOVA\backend
..\.venv\Scripts\python.exe -m pytest tests -q
```

**Focused voice/desktop regression tests**

```powershell
..\.venv\Scripts\python.exe -m pytest tests\test_intent_service.py tests\test_conversation_execution_service.py tests\test_desktop_control_service.py tests\test_livekit_voice_agent.py tests\test_livekit_voice.py tests\test_voice_api.py tests\test_voice_session_lease_service.py -q
```

**Frontend type-check and production build**

```powershell
Set-Location D:\NOVA\frontend
npm ci
npm run build
```

**Diff and Python syntax check**

```powershell
Set-Location D:\NOVA
git diff --check
Set-Location D:\NOVA\backend
..\.venv\Scripts\python.exe -m py_compile livekit_voice_agent.py services\intent_service.py services\conversation_execution_service.py services\desktop_control_service.py agent\graph.py
```

A green unit-test suite is not live acceptance. For each voice action, inspect the finalized transcript, tool route/result, resulting application state, database/activity audit trail, and the spoken response. Test network-loss, Gemini session expiry, opening-handshake/DNS failures, duplicate-action prevention, user cancellation, and reconnect behavior. Do not report an action as complete based solely on the assistant's generated text or a LiveKit room/lease heartbeat.

## Troubleshooting

- **Voice stuck or message delivery timeout:** check `logs/livekit_agent.log` and `logs/backend_start.log`, distinguish LiveKit room/lease health from the actual Gemini realtime model connection, and verify whether the action executed before retrying.
- **Gemini `1008` / session-resumption errors:** inspect whether the stale-handle guard ran and whether the provider established a fresh model session. A successful retry requires a fresh response/audio/transcript, not just a healthy WebRTC room.
- **Opening handshake timeout or `getaddrinfo failed`:** test network/DNS and the provider endpoint separately from local LiveKit; these failures cannot be solved by UI routing alone.
- **Voice app opens login unexpectedly:** use an authenticated NOVA tab and confirm the expected session is still available. Do not bypass login or share credentials.
- **Desktop command says it succeeded but nothing happened:** inspect the tool's exact `success/error/result` object and the visible Windows state. A claimed response is not evidence of execution.
- **Migration mismatch:** check `alembic current` and `alembic heads` before applying schema changes. Do not reset the database to resolve a revision mismatch.

## Development and repository safety

The repository may contain uncommitted work from the current development session. Before making changes, inspect `git status --short`, the relevant diff, tests, active runtime processes, and current database state. Do not use destructive reset/clean/checkout/discard commands and do not stage, commit, push, or merge without explicit permission. Keep secrets, OAuth callback codes, personal email contents, and private user data out of logs and documentation.

## Honest completion standard

NOVA is complete only when critical workflows have passed live end-to-end acceptance with durable persistence, correct permissions/approvals, honest errors, duplicate prevention, and recovery from real provider/network failures. Passing tests and a production frontend build are strong verification evidence, but they do not mean that every desktop application, every external integration, or mobile device control is already implemented and accepted.
