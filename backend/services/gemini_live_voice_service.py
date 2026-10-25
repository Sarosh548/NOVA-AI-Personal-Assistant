from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx


logger = logging.getLogger(__name__)
GEMINI_TOKEN_URL = "https://generativelanguage.googleapis.com/v1beta/auth_tokens"
GeminiLiveLanguage = Literal["multi", "en-US", "ur", "hi"]


class GeminiLiveVoiceNotConfigured(RuntimeError):
    """Raised when no server-side Gemini API key is configured."""


class GeminiLiveVoiceProviderError(RuntimeError):
    """Raised when Gemini refuses to mint a short-lived Live API token."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        provider_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider_code = provider_code


def build_gemini_live_session_config(
    *,
    language: GeminiLiveLanguage = "multi",
    history: list[dict[str, str]] | None = None,
) -> dict:
    """Build the constrained server-approved Gemini Live session config."""
    language_rules = {
        "en-US": "Speak natural English and keep the user's language unless asked to switch.",
        "ur": (
            "Speak Pakistani Urdu, not Hindi. Use natural Pakistani Urdu pronunciation, "
            "cadence, and vocabulary. Avoid an English-speaker accent when speaking Urdu."
        ),
        "hi": "Speak natural Hindi; use Devanagari when displaying Hindi text.",
        "multi": (
            "Mirror the user's language and script. English gets English; Urdu script gets "
            "Urdu; Roman Urdu/Hinglish gets the same Roman Urdu or Hinglish style and natural "
            "Pakistani Urdu pronunciation (not an English-speaker accent); Devanagari gets Hindi."
        ),
    }
    instructions = (
        "You are NOVA, a natural personal AI executive assistant. Speak warmly and naturally, "
        "with concise answers by default, human pacing, and no robotic narration. Complete each "
        "answer as one continuous spoken turn, usually in one to three concise sentences; do not "
        "stop after only a few words unless the user asks for a very short answer. Listen for the "
        "whole thought and allow natural pauses. Stop speaking when the user interrupts. "
        + language_rules[language]
        + "\n\nUse the nova_execute_request function for NOVA tasks, reminders, calendar events, "
        "email, web/current-information queries, private knowledge, saved memories, user-specific "
        "facts, or actions that must be executed or persisted by NOVA. Call this function at "
        "most once for each user turn. Never issue multiple function calls for the same turn or "
        "retry a state-changing request after a result; use the returned result to answer. The "
        "backend receives the user's finalized transcript as the source of truth for exact titles, "
        "names, dates, and recipients. Do not claim an action happened until the backend tool result "
        "confirms it. If the tool requires confirmation, explain that and wait for explicit user "
        "confirmation. Never bypass NOVA's permission or approval rules. For ordinary small talk or "
        "general knowledge that does not need personal context or fresh facts, answer directly. "
        "Never fabricate live facts, tool results, or errors."
    )

    # Do not inject NOVA's saved private conversation history into the external
    # free-tier provider configuration. In-session context stays in the Live
    # session; user-specific or persisted work should use NOVA's authenticated
    # /chat tool bridge, which applies NOVA's own memory and permission rules.

    # This is the raw BidiGenerateContentSetup config used by the current
    # REST token constraint schema. WebSocket setup uses the same raw shape.
    return {
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": os.getenv("GEMINI_LIVE_VOICE", "Aoede").strip() or "Aoede"
                    }
                }
            },
        },
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
        "realtimeInputConfig": {
            "automaticActivityDetection": {
                "disabled": False,
                "startOfSpeechSensitivity": "START_SENSITIVITY_LOW",
                "endOfSpeechSensitivity": "END_SENSITIVITY_LOW",
                # Filter very short speaker-echo bursts without removing the
                # audio immediately before detected speech; this keeps real barge-in.
                "prefixPaddingMs": 500,
                "silenceDurationMs": 800,
            }
        },
        "systemInstruction": {"parts": [{"text": instructions}]},
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "nova_execute_request",
                        "description": (
                            "Route a user request through NOVA's authenticated backend for actions, "
                            "user-specific information, saved knowledge/memory, or current external "
                            "information. NOVA enforces permissions and confirmation requirements."
                        ),
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "request": {
                                    "type": "STRING",
                                    "description": (
                                        "The complete user request including relevant conversation context."
                                    ),
                                }
                            },
                            "required": ["request"],
                        },
                    }
                ]
            }
        ],
    }



async def create_gemini_live_ephemeral_token(
    *,
    user_id: str,
    language: GeminiLiveLanguage = "multi",
    history: list[dict[str, str]] | None = None,
) -> dict:
    """Create a single-use short-lived token; never send the long-lived API key to the browser."""
    api_key = (
        os.getenv("GEMINI_API_KEY", "").strip()
        or os.getenv("GOOGLE_API_KEY", "").strip()
    )
    if not api_key:
        raise GeminiLiveVoiceNotConfigured(
            "GEMINI_API_KEY is not configured on the NOVA backend."
        )

    model_name = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live").strip()
    if model_name.startswith("models/"):
        model_name = model_name[len("models/"):]
    if not model_name or any(char.isspace() for char in model_name):
        raise ValueError("Invalid Gemini Live model configuration.")

    session_config = build_gemini_live_session_config(
        language=language,
        history=history,
    )
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=15)
    new_session_expires_at = now + timedelta(seconds=50)
    body = {
        "uses": 1,
        "expireTime": expires_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "newSessionExpireTime": (
            new_session_expires_at.isoformat(timespec="seconds").replace("+00:00", "Z")
        ),
        # Constrain the ephemeral token to the approved model only. A non-empty
        # field mask lets the WebSocket's first setup frame supply the session's
        # generation, transcription, VAD, instructions, and tool configuration.
        "fieldMask": "model",
        "bidiGenerateContentSetup": {
            "model": "models/" + model_name,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                GEMINI_TOKEN_URL,
                headers={
                    "x-goog-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except httpx.TimeoutException as exc:
        logger.warning("Gemini Live ephemeral-token request timed out.")
        raise GeminiLiveVoiceProviderError(
            "Gemini Live token provisioning timed out."
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("Gemini Live ephemeral-token request failed at transport.")
        raise GeminiLiveVoiceProviderError(
            "Gemini Live token provisioning could not reach Google."
        ) from exc

    if response.is_error:
        provider_code = None
        provider_fields: list[str] = []
        try:
            payload = response.json()
            if isinstance(payload, dict):
                err = payload.get("error")
                if isinstance(err, dict):
                    raw_code = err.get("status") or err.get("code")
                    if isinstance(raw_code, (str, int)):
                        provider_code = str(raw_code)[:100]
                    # Keep only field paths from Google's validation details.
                    # Never log the provider message, submitted config, or API key.
                    details = err.get("details")
                    if isinstance(details, list):
                        for detail in details:
                            if not isinstance(detail, dict):
                                continue
                            violations = detail.get("fieldViolations")
                            if not isinstance(violations, list):
                                continue
                            for violation in violations:
                                if not isinstance(violation, dict):
                                    continue
                                field = violation.get("field")
                                if isinstance(field, str) and field:
                                    provider_fields.append(field[:160])
                    # Some Google validation responses put the rejected field
                    # only in error.message. Extract field identifiers, never
                    # the original message or value text.
                    message = err.get("message")
                    if isinstance(message, str):
                        unknown = re.search(
                            r"""Unknown name ["']([^"']+)["'] at ["']([^"']+)["']""",
                            message,
                        )
                        if unknown:
                            provider_fields.extend([
                                "unknown_field:" + unknown.group(1)[:100],
                                "request_path:" + unknown.group(2)[:180],
                            ])
                        else:
                            invalid_path = re.search(
                                r"""(?:Invalid value|Missing field|Cannot find field) at ["']([^"']+)["']""",
                                message,
                            )
                            if invalid_path:
                                provider_fields.append(
                                    "request_path:" + invalid_path.group(1)[:180]
                                )
        except (ValueError, json.JSONDecodeError):
            pass
        safe_fields = ",".join(dict.fromkeys(provider_fields))[:400] or "none"
        logger.warning(
            "Gemini Live rejected token provisioning: upstream_status=%s upstream_code=%s upstream_fields=%s",
            response.status_code,
            provider_code or "unknown",
            safe_fields,
        )
        raise GeminiLiveVoiceProviderError(
            "Gemini Live refused token provisioning.",
            status_code=response.status_code,
            provider_code=provider_code,
        )

    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise GeminiLiveVoiceProviderError(
            "Gemini Live returned an unreadable token response."
        ) from exc

    token_name = payload.get("name") if isinstance(payload, dict) else None
    if not isinstance(token_name, str) or not token_name.strip():
        raise GeminiLiveVoiceProviderError(
            "Gemini Live returned no ephemeral token."
        )

    # The constrained token is single-use for starting the specified model/config.
    # Return only the short-lived token and the exact config needed for setup.
    return {
        "token": token_name,
        "model": "models/" + model_name,
        "config": session_config,
        "expires_at": body["expireTime"],
        "new_session_expires_at": body["newSessionExpireTime"],
        "provider": "gemini-live",
    }
