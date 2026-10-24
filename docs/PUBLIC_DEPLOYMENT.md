# NOVA Public Deployment (Render)

This repository includes a Render Blueprint in the root `render.yaml`. It describes a public static frontend, FastAPI Docker service, and PostgreSQL database. **Adding this file does not deploy the application**; a Render account must connect to the repository, configure the required credentials, create the services, and complete the health checks.

## Important: preview versus real use

The Blueprint deliberately uses Render's free plans so the first cloud smoke test does not silently choose a paid plan. This is a **temporary public preview**, not a production hosting recommendation:

- Free web services can spin down when idle, which makes the first request slower.
- Render's free PostgreSQL database expires after 30 days. Do not put real personal memories, credentials, calendar data, or other important user information into this preview.
- Before using NOVA as a persistent personal assistant or inviting real users, upgrade PostgreSQL to a paid persistent plan, review the service plans/costs in Render, and confirm backup/restore needs. Do not select a paid plan unless you approve its recurring cost.
- The production configuration intentionally fails closed when required provider credentials and security settings are missing. Do not work around that validation by switching the public service to development mode.

Render's current plan limitations are documented in [Deploy for Free](https://render.com/docs/free). PostgreSQL supports pgvector; the startup script enables the extension, initializes the legacy schema baseline required by the migration chain, and runs Alembic before starting FastAPI: [Supported PostgreSQL extensions](https://render.com/docs/postgresql-extensions).

## Deploy it

1. Sign in to Render and create a **Blueprint** from this public repository: `Sarosh548/NOVA-AI-Personal-Assistant`. Use the Blueprint from the `main` branch and review the services from `render.yaml` before confirming resource creation.
2. During initial creation, Render asks for values marked `sync: false`. Enter them in Render's protected environment-variable form only. Never add them to GitHub, frontend source, a screenshot, or a chat message.
3. The generated `nova-api` and `nova-web` service URLs may differ if a hostname is unavailable. After the services are created, use their **actual** URLs for:
   - API service: `API_CORS_ALLOWED_ORIGINS` must be the exact HTTPS frontend origin, such as `https://nova-web.onrender.com`.
   - Frontend service: `VITE_NOVA_API_BASE_URL` must be the API's HTTPS origin, such as `https://nova-api.onrender.com`.
   - Google OAuth: `CALENDAR_GOOGLE_REDIRECT_URI` must be `<API-origin>/integrations/google/calendar/callback`. Add that exact URI to the OAuth client's allowed redirect URIs in Google Cloud.
4. Save the environment changes and redeploy the API and frontend so the static build uses the correct API URL.
5. Check the actual public API endpoints. Both should return HTTP 200 after a successful deployment:
   - `https://<api-host>/health/live` — process liveness.
   - `https://<api-host>/health/ready` — database readiness.
6. Open the actual public frontend in a private/incognito browser window, register a dedicated demo user, and test sign-in, conversation, task/reminder persistence, memory/knowledge, web research, voice, and Google Calendar only when their providers are configured. Verify external changes in the real provider account. Do not use your personal Calendar or real recipient list for initial tests.
7. Only after those tests pass, capture real screenshots using [Screenshot Capture Guide](SCREENSHOT_CAPTURE_GUIDE.md). Keep them from the deployed UI, use harmless demo data, and redact email addresses, tokens, connection IDs, private records, and personal information.

## Required settings and secrets

Render generates `AUTH_JWT_SECRET_KEY` automatically. `INTEGRATION_TOKEN_ENCRYPTION_KEY` must be a valid Fernet key, so generate it locally and enter it in Render's protected environment-variable form (never in chat or GitHub):

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep both values private and do not rotate the encryption key without a deliberate plan for existing encrypted integration tokens.

The production guard requires the following actual provider settings before the API starts:

| Render variable | Where it comes from |
|---|---|
| `GROQ_API_KEY` | Groq API account |
| `TAVILY_API_KEY` | Tavily web-search account |
| `DEEPGRAM_API_KEY` | Deepgram speech-to-text account |
| `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` | ElevenLabs account and selected voice |
| `CALENDAR_GOOGLE_CLIENT_ID` and `CALENDAR_GOOGLE_CLIENT_SECRET` | Google Cloud OAuth client |
| `CALENDAR_GOOGLE_REDIRECT_URI` | Exact HTTPS API callback URL described above |
| `NOTIFICATION_SMTP_HOST`, `NOTIFICATION_SMTP_USERNAME`, `NOTIFICATION_SMTP_PASSWORD`, `NOTIFICATION_EMAIL_FROM_ADDRESS` | SMTP service; the Blueprint uses port 2525 because Render free services block common SMTP ports 25, 465, and 587 |
| `API_CORS_ALLOWED_ORIGINS` | Exact HTTPS origin of the deployed frontend |
| `VITE_NOVA_API_BASE_URL` | Exact HTTPS origin of the deployed API |

The Blueprint sets the least-privilege Calendar scope to `https://www.googleapis.com/auth/calendar.events` and enables HSTS/rate-limiting validation for production. Keep all environment secrets in Render, not in this repository.

## Deployment acceptance checklist

- [ ] Render services are deployed from the intended `main` commit.
- [ ] API logs show the database baseline and migrations completed without error.
- [ ] `/health/live` and `/health/ready` return HTTP 200.
- [ ] A fresh browser can load the frontend and reach the API over HTTPS.
- [ ] Registration/sign-in and user-scoped reads/writes work.
- [ ] Task/reminder and memory records remain after a service restart.
- [ ] Real provider actions are verified at the provider, not just by assistant text.
- [ ] Actual screenshots and test results are added to the repo after successful testing.
- [ ] Database plan, costs, backups, and retention are appropriate before inviting real users.

Until those checks are completed, describe this as a deployment blueprint or preview—not a live, verified NOVA service.
