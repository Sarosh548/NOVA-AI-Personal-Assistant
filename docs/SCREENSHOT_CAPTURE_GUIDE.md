# Capturing genuine NOVA desktop screenshots

The public repository did not contain verified desktop UI screenshots when this guide was prepared. The SVG images in the README are architecture diagrams, not product screenshots. Follow this guide so the portfolio shows the application honestly.

## Before capturing

1. Start PostgreSQL, migrations and the backend using the README setup.
2. Start the frontend and confirm the UI is calling the intended API rather than a stale/disconnected URL.
3. Sign in with a dedicated demo account and seed generic, non-sensitive task/reminder/knowledge data.
4. Confirm <code>/health/ready</code> returns HTTP 200.
5. If sign-in says the service is not connected, fix the API endpoint configuration before capturing a product screenshot.

For a public static deployment, <code>localhost</code> refers to the visitor's machine. A public demo needs a reachable backend, HTTPS, correct CORS/trusted-host settings and a build-time <code>VITE_NOVA_API_BASE_URL</code>. Do not expose provider secrets in frontend build variables.

## Suggested screenshot set

Capture these from the same running desktop build:

1. **Home dashboard** — show navigation and a populated overview.
2. **Conversation** — show a representative request and response, with no private data.
3. **Voice workspace** — show controls and connection state; only label voice “working” if the provider session really connects.
4. **Tasks and reminders** — show a generic sample record and its status.
5. **Knowledge / Memory** — show a safe sample document and retrieval result; distinguish source knowledge from personal memory.
6. **Control Center** — show permission/confirmation/workflow states with a demo account.
7. **Calendar** — only if OAuth is connected and private attendees/event details are not visible.

## Save and embed

1. Use Windows Snipping Tool (<code>Win + Shift + S</code>) or another capture utility.
2. Save PNGs under <code>docs/screenshots/</code>, for example <code>01-home.png</code>, <code>02-conversation.png</code>, and <code>03-control-center.png</code>.
3. Crop browser chrome when suitable, but preserve enough context to understand the screen.
4. Redact email addresses, event attendees, tokens, API keys, private reminders and browser-profile details.
5. Do not use error pages as proof that a feature works. If a screenshot documents a failure, label it as a failure.

After the file is committed, embed it in README with:

~~~markdown
![NOVA Home dashboard](docs/screenshots/01-home.png)
~~~

## Pre-publish review

- Does the image come from the current committed build?
- Is the API actually connected?
- Is every visible record safe to publish?
- Does the caption describe what is visible rather than an untested feature?
- Can another developer follow the README to reach a comparable screen?

Use a few clear captures rather than a collage. Every image should support a feature claim made by the README.
