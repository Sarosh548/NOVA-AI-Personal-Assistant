from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from html import unescape
from html.parser import HTMLParser
import json
import logging
import re
from secrets import token_urlsafe
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import Settings, get_settings
from database.connection import engine as default_engine
from models.email_connection import EmailConnection
from models.oauth_state import OAuthState
from services.token_encryption_service import TokenEncryptionService


logger = logging.getLogger(__name__)


class _HTMLTextExtractor(HTMLParser):
    """Convert untrusted HTML email bodies to text without rendering markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._suppressed_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "head"}:
            self._suppressed_depth += 1
        elif tag.lower() in {"p", "div", "br", "li", "tr"} and self._suppressed_depth == 0:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "head"} and self._suppressed_depth > 0:
            self._suppressed_depth -= 1
        elif tag.lower() in {"p", "div", "li", "tr"} and self._suppressed_depth == 0:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._suppressed_depth == 0 and data.strip():
            self._chunks.append(data)

    def get_text(self) -> str:
        return "\n".join(" ".join(self._chunks).splitlines()).strip()


class GoogleMailOAuthService:
    """Per-user Gmail authorization and outbound delivery using OAuth 2.0."""

    PROVIDER = "google-mail"
    AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
    USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
    API_BASE_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me"
    SEND_ENDPOINT = API_BASE_ENDPOINT + "/messages/send"
    MESSAGES_ENDPOINT = API_BASE_ENDPOINT + "/messages"
    SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
    READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
    IDENTITY_SCOPES = ("openid", "https://www.googleapis.com/auth/userinfo.email")
    MAX_LIST_RESULTS = 10
    MAX_MESSAGE_BODY_CHARS = 12000
    STATE_TTL_SECONDS = 600
    HTTP_TIMEOUT_SECONDS = 15

    def __init__(
        self,
        *,
        engine: Any | None = None,
        settings: Settings | None = None,
        encryption_service: TokenEncryptionService | None = None,
    ):
        self.engine = engine if engine is not None else default_engine
        self.settings = settings if settings is not None else get_settings()
        self.encryption_service = encryption_service
        if self.encryption_service is None and self.settings.integration_token_encryption_key:
            self.encryption_service = TokenEncryptionService(
                self.settings.integration_token_encryption_key
            )

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.calendar_google_client_id
            and self.settings.calendar_google_client_secret
            and self.settings.calendar_google_redirect_uri
            and self.encryption_service is not None
        )

    def build_authorization_url(self, *, user_id: str) -> str:
        self._validate_user_id(user_id)
        self._require_configuration()
        state_value = token_urlsafe(32)
        now = self._utc_now_naive()
        with Session(self.engine) as session:
            session.add(
                OAuthState(
                    user_id=user_id,
                    provider=self.PROVIDER,
                    state_hash=self._hash_state(state_value),
                    expires_at=now + timedelta(seconds=self.STATE_TTL_SECONDS),
                    used_at=None,
                    created_at=now,
                )
            )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError("Could not create the Google Mail authorization state.") from exc

        # Reading email is a separate sensitive scope from sending. Request both
        # explicitly so inbox summaries can work only after the user consents.
        scopes = " ".join((self.SEND_SCOPE, self.READ_SCOPE, *self.IDENTITY_SCOPES))
        return self.AUTHORIZATION_ENDPOINT + "?" + urlencode({
            "client_id": self.settings.calendar_google_client_id,
            "redirect_uri": self.settings.calendar_google_redirect_uri,
            "response_type": "code",
            "scope": scopes,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state_value,
        })

    def is_authorization_state(self, state: str) -> bool:
        if not state or not isinstance(state, str):
            return False
        # The shared Google OAuth callback dispatches by the state provider.
        # Expiry/use validation is performed atomically by the consuming method.
        statement = select(OAuthState.id).where(
            OAuthState.provider == self.PROVIDER,
            OAuthState.state_hash == self._hash_state(state),
        )
        with Session(self.engine) as session:
            return session.scalar(statement) is not None

    def cancel_authorization(self, *, state: str) -> None:
        normalized = self._validate_state(state)
        now = self._utc_now_naive()
        with Session(self.engine) as session:
            result = session.execute(
                update(OAuthState)
                .where(
                    OAuthState.provider == self.PROVIDER,
                    OAuthState.state_hash == self._hash_state(normalized),
                    OAuthState.used_at.is_(None),
                    OAuthState.expires_at > now,
                )
                .values(used_at=now)
            )
            if result.rowcount != 1:
                session.rollback()
                raise ValueError("Invalid or expired Google Mail authorization state.")
            session.commit()

    def complete_authorization(self, *, state: str, code: str) -> dict[str, Any]:
        self._require_configuration()
        normalized_state = self._validate_state(state)
        if not isinstance(code, str) or not code.strip() or len(code) > 4096:
            raise ValueError("Google Mail authorization code is invalid.")

        user_id = self._consume_state(normalized_state)
        token_payload = self._post_form(
            self.TOKEN_ENDPOINT,
            {
                "code": code.strip(),
                "client_id": self.settings.calendar_google_client_id,
                "client_secret": self.settings.calendar_google_client_secret,
                "redirect_uri": self.settings.calendar_google_redirect_uri,
                "grant_type": "authorization_code",
            },
            context="Google Mail authorization",
        )
        access_token = token_payload.get("access_token")
        refresh_token = token_payload.get("refresh_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Google Mail authorization did not return an access token.")
        expires_in = self._parse_expires_in(token_payload.get("expires_in"))
        granted_scopes = token_payload.get("scope")
        if not isinstance(granted_scopes, str) or not granted_scopes.strip():
            raise ValueError(
                "Google did not report the mailbox permissions it granted. "
                "Reconnect Gmail and explicitly approve the send permission."
            )
        scopes = granted_scopes.strip()
        if self.SEND_SCOPE not in scopes.split():
            raise ValueError("Google did not grant the Gmail send permission. Reconnect and approve the requested access.")

        identity = self._get_user_info(access_token)
        email_address = identity.get("email")
        if not isinstance(email_address, str) or not email_address.strip() or identity.get("email_verified") is not True:
            raise ValueError("Google did not confirm the connected mailbox email address.")

        with Session(self.engine) as session:
            existing = session.scalar(
                select(EmailConnection).where(
                    EmailConnection.user_id == user_id,
                    EmailConnection.provider == "google",
                )
            )
            if refresh_token is None and existing is None:
                raise ValueError("Google did not return a refresh token. Reconnect and approve offline access.")
            encrypted_refresh = (
                self._get_encryption_service().encrypt(refresh_token)
                if isinstance(refresh_token, str) and refresh_token
                else existing.encrypted_refresh_token
            )
            now = self._utc_now_naive()
            if existing is None:
                connection = EmailConnection(
                    user_id=user_id,
                    provider="google",
                    email_address=email_address.strip().lower(),
                    encrypted_access_token=self._get_encryption_service().encrypt(access_token),
                    encrypted_refresh_token=encrypted_refresh,
                    token_expires_at=(now + timedelta(seconds=expires_in)) if expires_in else None,
                    scopes=scopes,
                    created_at=now,
                    updated_at=now,
                )
                session.add(connection)
            else:
                existing.email_address = email_address.strip().lower()
                existing.encrypted_access_token = self._get_encryption_service().encrypt(access_token)
                existing.encrypted_refresh_token = encrypted_refresh
                existing.token_expires_at = (now + timedelta(seconds=expires_in)) if expires_in else None
                existing.token_refresh_claim_token = None
                existing.token_refresh_lease_until = None
                existing.scopes = scopes
                existing.updated_at = now
                connection = existing
            try:
                session.commit()
                session.refresh(connection)
            except IntegrityError as exc:
                session.rollback()
                raise ValueError("Could not save the connected Google mailbox.") from exc
            return self._to_public_dict(connection)

    def get_connection(self, *, user_id: str) -> dict[str, Any] | None:
        normalized_user_id = self._validate_user_id(user_id)
        with Session(self.engine) as session:
            connection = session.scalar(
                select(EmailConnection).where(
                    EmailConnection.user_id == normalized_user_id,
                    EmailConnection.provider == "google",
                )
            )
            if connection is None:
                return None
            try:
                self._get_encryption_service().decrypt(connection.encrypted_access_token)
                self._get_encryption_service().decrypt(connection.encrypted_refresh_token)
            except (ValueError, AttributeError):
                return None
            return self._to_public_dict(connection)

    def disconnect(self, *, user_id: str) -> bool:
        normalized_user_id = self._validate_user_id(user_id)
        with Session(self.engine) as session:
            connection = session.scalar(
                select(EmailConnection).where(
                    EmailConnection.user_id == normalized_user_id,
                    EmailConnection.provider == "google",
                )
            )
            if connection is None:
                return False
            encrypted_token = connection.encrypted_access_token
            session.delete(connection)
            session.commit()
        try:
            token = self._get_encryption_service().decrypt(encrypted_token)
            self._post_form(
                "https://oauth2.googleapis.com/revoke",
                {"token": token},
                context="Google Mail disconnection",
            )
        except Exception:
            # Local credential removal is the security boundary. Revocation is best effort.
            logger.info("Google Mail token revocation could not be confirmed for user=%s.", normalized_user_id)
        return True

    def _require_readable_mailbox(self, *, user_id: str) -> dict[str, Any]:
        connection = self.get_connection(user_id=user_id)
        if connection is None:
            raise ValueError(
                "Connect your Google/Gmail account in Control Center → Notifications "
                "before reading email."
            )
        scopes = set(str(connection.get("scopes") or "").split())
        if self.READ_SCOPE not in scopes:
            raise ValueError(
                "Gmail inbox access has not been granted. Reconnect Google/Gmail from "
                "Control Center → Notifications and approve the requested read-only email permission."
            )
        return connection

    def _gmail_get_json(self, url: str, *, access_token: str, context: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.HTTP_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
        except HTTPError as exc:
            if exc.code == 401:
                raise ValueError(
                    "Google rejected mailbox authorization. Reconnect your Google account and retry."
                ) from exc
            if exc.code == 403:
                reason = self._extract_gmail_error_reason(exc)
                logger.warning(
                    "Gmail read request was denied (context=%s, reason=%s).",
                    context,
                    reason or "unknown",
                )
                if (reason or "").lower() in {"insufficientpermissions", "autherror"}:
                    raise ValueError(
                        "Google has not granted NOVA read-only Gmail access. Reconnect Gmail "
                        "and approve the requested inbox permission."
                    ) from exc
                raise ValueError(
                    "Google denied this Gmail read request. Check Gmail API access and the connected account."
                ) from exc
            if exc.code == 404:
                raise ValueError("That Gmail message could not be found.") from exc
            if exc.code == 429:
                raise ValueError("Gmail rate limit reached. Wait briefly and retry.") from exc
            logger.warning("Gmail read request failed (context=%s, HTTP %s).", context, exc.code)
            raise ValueError(f"Gmail could not complete the read request (HTTP {exc.code}).") from exc
        except (URLError, TimeoutError, OSError) as exc:
            logger.warning("Gmail read request could not reach Google (context=%s).", context)
            raise ValueError("Could not reach Gmail. Check the connection and try again.") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Gmail returned an unreadable response.") from exc

        if not isinstance(payload, dict):
            raise ValueError("Gmail returned an invalid response.")
        return payload

    @staticmethod
    def _gmail_message_headers(payload: dict[str, Any]) -> dict[str, str]:
        raw_headers = payload.get("payload", {}).get("headers", [])
        if not isinstance(raw_headers, list):
            return {}
        headers: dict[str, str] = {}
        for item in raw_headers:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip().lower()
            value = str(item.get("value") or "").strip()
            if name and value and name not in headers:
                headers[name] = value
        return headers

    @staticmethod
    def _decode_gmail_body_data(value: Any) -> str:
        if not isinstance(value, str) or not value:
            return ""
        try:
            padded = value + ("=" * (-len(value) % 4))
            decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
            return decoded.decode("utf-8", errors="replace")
        except (ValueError, UnicodeEncodeError):
            return ""

    @classmethod
    def _extract_gmail_body(cls, payload: Any) -> str:
        plain_parts: list[str] = []
        html_parts: list[str] = []

        def visit(part: Any) -> None:
            if not isinstance(part, dict):
                return
            mime_type = str(part.get("mimeType") or "").lower()
            body = part.get("body")
            if isinstance(body, dict):
                decoded = cls._decode_gmail_body_data(body.get("data"))
                if decoded:
                    if mime_type == "text/plain":
                        plain_parts.append(decoded)
                    elif mime_type == "text/html":
                        html_parts.append(decoded)
            children = part.get("parts")
            if isinstance(children, list):
                for child in children:
                    visit(child)

        visit(payload)
        if plain_parts:
            body_text = "\n\n".join(plain_parts)
        elif html_parts:
            parser = _HTMLTextExtractor()
            try:
                parser.feed("\n".join(html_parts))
                body_text = unescape(parser.get_text())
            except Exception:
                body_text = ""
        else:
            body_text = ""
        body_text = "\n".join(line.rstrip() for line in body_text.splitlines()).strip()
        return body_text[:cls.MAX_MESSAGE_BODY_CHARS]

    @staticmethod
    def _validate_message_id(message_id: str) -> str:
        normalized = str(message_id or "").strip()
        if not normalized or len(normalized) > 200 or not re.fullmatch(r"[A-Za-z0-9_-]+", normalized):
            raise ValueError("Gmail message ID is invalid.")
        return normalized

    def list_messages(
        self,
        *,
        user_id: str,
        query: str | None = None,
        max_results: int = 5,
        include_body: bool = False,
    ) -> dict[str, Any]:
        """List bounded mailbox metadata; fetch body text only when the user asks to read/summarize."""
        if isinstance(max_results, bool) or not isinstance(max_results, int):
            raise ValueError("max_results must be an integer.")
        if not isinstance(include_body, bool):
            raise ValueError("include_body must be a boolean.")
        if not 1 <= max_results <= self.MAX_LIST_RESULTS:
            raise ValueError(f"max_results must be between 1 and {self.MAX_LIST_RESULTS}.")

        normalized_query = str(query or "").strip()
        if len(normalized_query) > 500 or any(ord(ch) < 32 for ch in normalized_query):
            raise ValueError("Gmail search query is invalid or too long.")
        if not normalized_query:
            normalized_query = "in:inbox"

        self._require_readable_mailbox(user_id=user_id)
        access_token = self._get_valid_access_token(user_id=user_id)
        url = self.MESSAGES_ENDPOINT + "?" + urlencode([
            ("q", normalized_query),
            ("maxResults", str(max_results)),
        ])
        listing = self._gmail_get_json(
            url,
            access_token=access_token,
            context="message list",
        )
        raw_messages = listing.get("messages", [])
        if not isinstance(raw_messages, list):
            raise ValueError("Gmail returned an invalid message list.")

        messages: list[dict[str, Any]] = []
        for item in raw_messages[:max_results]:
            if not isinstance(item, dict):
                continue
            message_id = self._validate_message_id(str(item.get("id") or ""))
            message_params = (
                [("format", "full")]
                if include_body
                else [
                    ("format", "metadata"),
                    ("metadataHeaders", "From"),
                    ("metadataHeaders", "To"),
                    ("metadataHeaders", "Subject"),
                    ("metadataHeaders", "Date"),
                ]
            )
            metadata_url = self.MESSAGES_ENDPOINT + "/" + message_id + "?" + urlencode(message_params)
            message = self._gmail_get_json(
                metadata_url,
                access_token=access_token,
                context="message content" if include_body else "message metadata",
            )
            headers = self._gmail_message_headers(message)
            normalized_message = {
                "id": message_id,
                "thread_id": str(message.get("threadId") or ""),
                "from": headers.get("from"),
                "to": headers.get("to"),
                "subject": headers.get("subject") or "(No subject)",
                "date": headers.get("date"),
                "snippet": str(message.get("snippet") or "")[:1000],
                "labels": [
                    str(label) for label in message.get("labelIds", [])
                    if isinstance(label, str)
                ] if isinstance(message.get("labelIds", []), list) else [],
            }
            if include_body:
                normalized_message["body"] = self._extract_gmail_body(
                    message.get("payload")
                )
            messages.append(normalized_message)

        return {
            "provider": "gmail",
            "query": normalized_query,
            "count": len(messages),
            "estimated_total": listing.get("resultSizeEstimate"),
            "next_page_token": listing.get("nextPageToken"),
            "messages": messages,
        }

    def get_message(self, *, user_id: str, message_id: str) -> dict[str, Any]:
        """Read one Gmail message body as plain text; never return raw HTML."""
        normalized_id = self._validate_message_id(message_id)
        self._require_readable_mailbox(user_id=user_id)
        access_token = self._get_valid_access_token(user_id=user_id)
        payload = self._gmail_get_json(
            self.MESSAGES_ENDPOINT + "/" + normalized_id + "?format=full",
            access_token=access_token,
            context="message content",
        )
        headers = self._gmail_message_headers(payload)
        return {
            "provider": "gmail",
            "id": normalized_id,
            "thread_id": str(payload.get("threadId") or ""),
            "from": headers.get("from"),
            "to": headers.get("to"),
            "cc": headers.get("cc"),
            "subject": headers.get("subject") or "(No subject)",
            "date": headers.get("date"),
            "snippet": str(payload.get("snippet") or "")[:1000],
            "body": self._extract_gmail_body(payload.get("payload")),
            "labels": [
                str(label) for label in payload.get("labelIds", [])
                if isinstance(label, str)
            ] if isinstance(payload.get("labelIds", []), list) else [],
        }

    def send_email(
        self,
        *,
        user_id: str,
        to: str | list[str] | tuple[str, ...],
        subject: str,
        body: str,
        cc: str | list[str] | tuple[str, ...] | None = None,
        bcc: str | list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        connection = self.get_connection(user_id=user_id)
        if connection is None:
            raise ValueError(
                "Connect your Google/Gmail account in Control Center → Notifications "
                "before sending email. NOVA login alone does not grant mailbox sending access."
            )

        access_token = self._get_valid_access_token(user_id=user_id)
        to_list = self._normalize_recipients(to, "to")
        cc_list = self._normalize_recipients(cc, "cc")
        bcc_list = self._normalize_recipients(bcc, "bcc")
        if not to_list:
            raise ValueError("Email recipient is missing. Tell NOVA who to send the email to.")
        if not subject or not subject.strip():
            raise ValueError("Email subject is missing.")
        if not body or not body.strip():
            raise ValueError("Email body is missing.")

        message = EmailMessage()
        message["From"] = connection["email"]
        message["To"] = ", ".join(to_list)
        if cc_list:
            message["Cc"] = ", ".join(cc_list)
        if bcc_list:
            message["Bcc"] = ", ".join(bcc_list)
        message["Subject"] = subject.strip()
        message.set_content(body.strip())
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        request_body = json.dumps({"raw": raw_message}).encode("utf-8")
        request = Request(
            self.SEND_ENDPOINT,
            data=request_body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.HTTP_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("Gmail returned an invalid send response; delivery could not be verified.")
            message_id = payload.get("id")
            if not isinstance(message_id, str) or not message_id.strip():
                raise ValueError(
                    "Gmail did not return a message ID, so NOVA cannot verify that it accepted this email. "
                    "Check Gmail Sent before retrying to avoid sending a duplicate."
                )
            label_ids = payload.get("labelIds")
            return {
                "status": "sent",
                "provider": "gmail",
                "message_id": message_id,
                "sent_label_confirmed": isinstance(label_ids, list) and "SENT" in label_ids,
                "from": connection["email"],
                "to": to_list,
                "cc": cc_list,
                "bcc": bcc_list,
                "subject": subject.strip()[:200],
            }
        except HTTPError as exc:
            if exc.code == 401:
                raise ValueError(
                    "Google rejected the mailbox authorization. Reconnect your Google account and retry."
                ) from exc
            if exc.code == 403:
                reason = self._extract_gmail_error_reason(exc)
                message = self._describe_gmail_403(reason)
                logger.warning(
                    "Gmail API rejected send request with HTTP 403 (reason=%s) for user=%s.",
                    reason or "unknown",
                    user_id,
                )
                raise ValueError(message) from exc
            if exc.code == 429:
                raise ValueError("Google Gmail rate limit was reached. Wait briefly and retry.") from exc
            logger.warning("Gmail send request failed with HTTP %s for user=%s.", exc.code, user_id)
            raise ValueError(f"Gmail could not send the email (HTTP {exc.code}). Check the connected account and retry.") from exc
        except (URLError, TimeoutError, OSError) as exc:
            logger.warning("Gmail network request failed for user=%s.", user_id)
            raise ValueError(
                "Could not confirm Gmail accepted the email because the network request failed. "
                "Check Gmail Sent before retrying to avoid a duplicate."
            ) from exc
        except (TypeError, json.JSONDecodeError) as exc:
            logger.warning("Gmail returned an invalid response for user=%s.", user_id)
            raise ValueError("Gmail returned an unreadable response; delivery could not be verified.") from exc

    @staticmethod
    def _extract_gmail_error_reason(exc: HTTPError) -> str | None:
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        error = payload.get("error")
        if not isinstance(error, dict):
            return None
        errors = error.get("errors")
        if isinstance(errors, list):
            for item in errors:
                if isinstance(item, dict) and isinstance(item.get("reason"), str):
                    return item["reason"][:100]
        details = error.get("details")
        if isinstance(details, list):
            for item in details:
                if isinstance(item, dict) and isinstance(item.get("reason"), str):
                    return item["reason"][:100]
        return None

    @staticmethod
    def _describe_gmail_403(reason: str | None) -> str:
        normalized = (reason or "").strip().lower()
        if normalized in {"accessnotconfigured", "servicedisabled"}:
            return (
                "Google has disabled the Gmail API for the Cloud project used by NOVA's OAuth client. "
                "Enable 'Gmail API' in that same Google Cloud project, wait for it to activate, "
                "then reconnect Gmail in NOVA → Control Center → Notifications."
            )
        if normalized in {"insufficientpermissions", "autherror"}:
            return (
                "Google rejected the granted Gmail permissions. Disconnect Gmail in NOVA → Control Center "
                "→ Notifications, reconnect it, and approve the requested Gmail send permission."
            )
        if normalized in {"dailylimitexceeded", "userratelimitexceeded", "ratelimitexceeded"}:
            return (
                "Google rejected the send because a Gmail API quota or rate limit was reached. "
                "Wait and retry; repeated failures require checking the Google Cloud quota for this project."
            )
        if normalized in {"domainpolicy", "admin_policy_enforced"}:
            return (
                "Your Google Workspace administrator's policy blocked Gmail sending for this app. "
                "Ask the administrator to allow the NOVA OAuth client and Gmail send scope."
            )
        reason_suffix = f" (Google reason: {reason})" if reason else ""
        return (
            "Google denied this Gmail send request"
            f"{reason_suffix}. Verify Gmail API is enabled in the same Google Cloud project as NOVA's "
            "OAuth client, reconnect Gmail, and check any Google Workspace restrictions. NOVA has not "
            "reported this email as sent."
        )

    def _get_valid_access_token(self, *, user_id: str) -> str:
        normalized_user_id = self._validate_user_id(user_id)
        with Session(self.engine) as session:
            connection = session.scalar(
                select(EmailConnection).where(
                    EmailConnection.user_id == normalized_user_id,
                    EmailConnection.provider == "google",
                )
            )
            if connection is None:
                raise ValueError("Google/Gmail account is not connected. Connect it from Control Center → Notifications.")
            if connection.token_expires_at and connection.token_expires_at > self._utc_now_naive() + timedelta(seconds=60):
                return self._get_encryption_service().decrypt(connection.encrypted_access_token)
            refresh_token = self._get_encryption_service().decrypt(connection.encrypted_refresh_token)

        payload = self._post_form(
            self.TOKEN_ENDPOINT,
            {
                "client_id": self.settings.calendar_google_client_id,
                "client_secret": self.settings.calendar_google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            context="Google Mail token refresh",
        )
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Google could not refresh the mailbox authorization. Reconnect your Google account.")
        expires_in = self._parse_expires_in(payload.get("expires_in"))
        with Session(self.engine) as session:
            connection = session.scalar(
                select(EmailConnection).where(
                    EmailConnection.user_id == normalized_user_id,
                    EmailConnection.provider == "google",
                )
            )
            if connection is None:
                raise ValueError("Google/Gmail account was disconnected during token refresh. Reconnect and retry.")
            connection.encrypted_access_token = self._get_encryption_service().encrypt(access_token)
            connection.token_expires_at = (self._utc_now_naive() + timedelta(seconds=expires_in)) if expires_in else None
            replacement_refresh = payload.get("refresh_token")
            if isinstance(replacement_refresh, str) and replacement_refresh:
                connection.encrypted_refresh_token = self._get_encryption_service().encrypt(replacement_refresh)
            connection.updated_at = self._utc_now_naive()
            session.commit()
        return access_token

    def _get_user_info(self, access_token: str) -> dict[str, Any]:
        request = Request(
            self.USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.HTTP_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ValueError("Google could not confirm the connected mailbox identity.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Google returned an invalid mailbox identity response.")
        return payload

    def _post_form(self, endpoint: str, payload: dict[str, str], *, context: str) -> dict[str, Any]:
        request = Request(
            endpoint,
            data=urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.HTTP_TIMEOUT_SECONDS) as response:
                result = json.loads(response.read().decode("utf-8") or "{}")
        except HTTPError as exc:
            message = f"{context} failed (HTTP {exc.code})."
            if exc.code in {400, 401} and "refresh" in context.lower():
                message = "Google mailbox authorization expired. Reconnect the Google account from Control Center → Notifications."
            logger.warning("%s", message)
            raise ValueError(message) from exc
        except (URLError, TimeoutError, OSError) as exc:
            logger.warning("%s could not reach the Google OAuth endpoint.", context)
            raise ValueError(f"{context} could not reach Google. Check the network and try again.") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"{context} returned an invalid response from Google.") from exc
        if not isinstance(result, dict):
            raise ValueError(f"{context} returned an invalid response from Google.")
        if result.get("error"):
            err = result.get("error")
            if context.lower().endswith("refresh") and err in {"invalid_grant", "unauthorized_client"}:
                raise ValueError("Google mailbox authorization expired. Reconnect the Google account from Control Center → Notifications.")
            raise ValueError(f"{context} was rejected by Google ({str(err)[:80]}).")
        return result

    def _consume_state(self, state: str) -> str:
        now = self._utc_now_naive()
        with Session(self.engine) as session:
            result = session.execute(
                update(OAuthState)
                .where(
                    OAuthState.provider == self.PROVIDER,
                    OAuthState.state_hash == self._hash_state(state),
                    OAuthState.used_at.is_(None),
                    OAuthState.expires_at > now,
                )
                .values(used_at=now)
                .returning(OAuthState.user_id)
            )
            row = result.first()
            if row is None:
                session.rollback()
                raise ValueError("Invalid or expired Google Mail authorization state.")
            session.commit()
            return row[0]

    def _require_configuration(self) -> None:
        if not self.is_configured:
            raise ValueError("Google Mail connection is not configured. NOVA needs the Google OAuth client ID, client secret, callback URL, and integration-token encryption key.")

    def _get_encryption_service(self) -> TokenEncryptionService:
        if self.encryption_service is None:
            raise ValueError("External token encryption is not configured.")
        return self.encryption_service

    @staticmethod
    def _normalize_recipients(
        value: str | list[str] | tuple[str, ...] | None,
        field_name: str,
    ) -> list[str]:
        if value is None:
            return []
        raw_values = value.split(",") if isinstance(value, str) else list(value) if isinstance(value, (list, tuple)) else []
        results: list[str] = []
        for item in raw_values:
            address = str(item).strip()
            if not address:
                continue
            _, parsed = parseaddr(address)
            local, separator, domain = parsed.rpartition("@")
            if parsed != address or not separator or not local or "." not in domain or any(ch.isspace() for ch in address):
                raise ValueError(f"Invalid email address in {field_name}.")
            results.append(parsed)
        return results

    @staticmethod
    def _validate_user_id(user_id: str) -> str:
        normalized = str(user_id).strip()
        if not normalized or len(normalized) > 100:
            raise ValueError("Invalid user identity.")
        return normalized

    @staticmethod
    def _validate_state(state: str) -> str:
        if not isinstance(state, str) or not state.strip() or len(state) > 512:
            raise ValueError("Invalid Google Mail authorization state.")
        return state.strip()

    @staticmethod
    def _hash_state(state: str) -> str:
        import hashlib
        return hashlib.sha256(state.encode("utf-8")).hexdigest()

    @staticmethod
    def _utc_now_naive() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _parse_expires_in(value: Any) -> int | None:
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    @staticmethod
    def _to_public_dict(connection: EmailConnection) -> dict[str, Any]:
        return {
            "id": connection.id,
            "user_id": connection.user_id,
            "provider": connection.provider,
            "email": connection.email_address,
            "scopes": connection.scopes,
            "token_expires_at": connection.token_expires_at,
            "created_at": connection.created_at,
            "updated_at": connection.updated_at,
        }
