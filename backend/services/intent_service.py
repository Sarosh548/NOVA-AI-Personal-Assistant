import json
import os
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus

from openai import OpenAI, RateLimitError

from config import LLMSettings, get_llm_settings
from services.llm_service import (
    acquire_llm_provider_slot,
    is_llm_provider_error,
    record_llm_rate_limit,
    release_llm_provider_slot,
)


MODEL_NAME = "openai/gpt-oss-20b"
USER_TIMEZONE = "Asia/Karachi"


class IntentService:
    def __init__(
        self,
        *,
        settings: LLMSettings | None = None,
    ):
        active_settings = (
            settings
            if settings is not None
            else get_llm_settings()
        )

        groq_api_key = os.getenv("GROQ_API_KEY")

        if not groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set."
            )

        self.client = OpenAI(
            api_key=groq_api_key,
            base_url="https://api.groq.com/openai/v1",
            timeout=min(
                active_settings.llm_request_timeout_seconds,
                10.0,
            ),
            # Retries are disabled: nested retries caused minute-long waits
            # and repeated token consumption on the 8K TPM plan.
            max_retries=0,
        )

        self.settings = active_settings

    def analyze(
        self,
        message: str,
        history: list[dict] | None = None,
    ) -> dict:
        """
        Understand the user's current message.

        Recent conversation history is optionally supplied so the
        understanding layer can resolve follow-up references such
        as "it", "that reminder", "the previous one", etc.
        """

        if not message.strip():
            return self._default_result()

        history = history or []

        task_confirmation = self._resolve_task_creation_confirmation(
            message=message,
            history=history,
        )
        if task_confirmation is not None:
            return task_confirmation

        # Resolve high-confidence executable commands deterministically before
        # contacting the LLM. External provider rate limits must not block
        # obvious Task/Reminder/Calendar/Web commands that NOVA can parse safely.
        deterministic = self._deterministic_fallback(
            message=message,
            history=history,
        )

        if (
            deterministic.get("requires_tool") is True
            or deterministic.get("clarification_required") is True
        ):
            return deterministic

        now = datetime.now(
            ZoneInfo(USER_TIMEZONE)
        )

        current_datetime = now.isoformat(
            timespec="minutes"
        )

        recent_history = history[-5:]
        history_lines = []
        for item in recent_history:
            role = str(item.get("role", "unknown"))[:20]
            content = " ".join(str(item.get("content", "")).split())
            if len(content) > 240:
                content = content[:115] + " […] " + content[-115:]
            history_lines.append(f"{role}: {content}")
        history_context = "\n".join(history_lines) or "No previous conversation available."

        # Bound the classifier payload while preserving the start and end,
        # where a task's intent and important details commonly appear.
        classifier_message = message
        if len(classifier_message) > 3_000:
            classifier_message = (
                classifier_message[:1_450]
                + "\n[Middle of long message omitted for intent classification]\n"
                + classifier_message[-1_450:]
            )

        instructions = f"""
You are NOVA's intent and field extractor. Classify ONLY the current user message. Recent history is context solely for resolving references such as "it" or "that task"; do not repeat or execute an old request. Never invent IDs, emails, dates, attendees, or personal facts. Return only valid JSON.

Current date/time: {current_datetime}
Timezone: Asia/Karachi
Recent conversation:
{history_context}

Choose one intent: chat, question, advice, planning, reminder, task, action, email, calendar, web, desktop.
Use desktop for explicit local-computer requests: open allowlisted apps and HTTP(S) URLs, web search, standard folders and safe files, find filenames, list files in the allowlisted Desktop/Documents/Downloads/Pictures/Music/Videos folders, inspect visible UI labels, click one uniquely named safe control, type into one uniquely named non-sensitive field, press an allowlisted shortcut, or play a specifically named YouTube/Spotify track only when playback can be verified. UI actions must use inspect_screen/click_ui/type_ui/press_key and exact accessible labels, not guessed coordinates. Never use generic UI actions to send/delete/publish/pay/approve or submit an external change; use dedicated confirmation-protected integrations.
Use Roman Urdu/English naturally when extracting the user's wording. Set requires_tool=true for task, reminder, email, calendar, web, desktop, and external action intents; otherwise false unless an action is explicitly requested.
Task fields: task is a NEW title only for task creation; task_reference identifies an existing task for start/complete/cancel/delete/update, using history for "it" only when clear; task_action is create/list/start/complete/cancel/delete/update; task_id only if explicitly stated; priority low/medium/high only when provided.
Reminder fields: task is reminder content; reminder_action create/list/complete/cancel/delete/update; reminder_reference identifies an existing reminder; reminder_id only if explicit.
Time: keep the original time expression in time. Put scheduled_at in ISO 8601 with Asia/Karachi offset only when the time is clear; never invent a time.
Email: use email_action=send only for an explicit outbound-send request; use list for the inbox/recent/unread email list, search for explicit mailbox searches (put the exact search terms in query), and get only when a message_id is explicitly available from a prior email result or the user. Set include_body=true only when the user asks to read or summarize message contents; otherwise keep it false and return only bounded metadata/snippets. Preserve message_id for get. Extract outbound recipient(s) into to/cc/bcc, use recipient_reference="self" only for "myself"/"my own email", and preserve the requested subject/body. Never invent a recipient or email ID.
Calendar: calendar_action=list/get/create/update/delete. Populate only requested event fields. Never invent event IDs, locations, descriptions, or attendees. If a timed event has no duration, use one hour. For date-range listings populate time_min/time_max.
Web: use intent=web for latest/current/recent external facts or explicit web research. web_action=search; web_topic=general/news/finance/weather; web_time_range=day/week/month/year when stated; query is a concise search query; max_results is 1-10 if specified. Weather uses web_topic=weather.
Set emotion to happy/sad/angry/stressed/excited/romantic/playful/neutral; tone to friendly/supportive/playful/romantic/professional/neutral; visual to none/smile/laugh/hearts/sad/concerned/celebration/thinking/listening/reminder. Usually use neutral/friendly/none.
Return the full schema with null for absent values:
{{
  "intent": "chat|question|advice|planning|reminder|task|action|email|calendar|web|desktop",
  "task": null, "task_reference": null, "task_action": null, "task_id": null, "priority": null,
  "reminder_action": null, "reminder_reference": null, "reminder_id": null,
  "time": null, "scheduled_at": null,
  "emotion": "neutral", "tone": "friendly", "visual": "none", "action": null,
  "email_action": null, "message_id": null, "include_body": false, "to": null, "recipient_reference": null, "cc": null, "bcc": null, "subject": null, "body": null,
  "calendar_action": null, "calendar_id": null, "event_id": null, "event": null, "time_min": null, "time_max": null,
  "query": null, "max_results": null, "page_token": null, "single_events": null, "order_by": null, "show_deleted": null, "send_updates": null,
  "web_action": null, "web_topic": null, "web_time_range": null,
  "desktop_operation": "open_app|open_url|search_web|open_folder|open_file|find_files|list_files|inspect_screen|click_ui|type_ui|press_key|play_youtube|play_spotify|null",
  "desktop_target": null, "desktop_query": null,
  "clarification_required": false, "requires_tool": false
}}
"""

        slot_acquired = False
        try:
            acquire_llm_provider_slot()
            slot_acquired = True
            response = self.client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {
                        "role": "system",
                        "content": instructions,
                    },
                    {
                        "role": "user",
                        "content": classifier_message,
                    },
                ],
                max_completion_tokens=384,
            )
        except Exception as exc:
            if isinstance(exc, RateLimitError):
                record_llm_rate_limit(exc)
            if is_llm_provider_error(exc):
                fallback = self._deterministic_fallback(
                    message=message,
                    history=history,
                )
                fallback["llm_provider_unavailable"] = True
                return fallback
            raise
        finally:
            if slot_acquired:
                release_llm_provider_slot()

        content = response.choices[0].message.content

        if not content:
            return self._default_result()

        raw_output = content.strip()

        try:
            result = json.loads(raw_output)
        except json.JSONDecodeError:
            return self._default_result()

        if not isinstance(result, dict):
            return self._default_result()

        validated_result = self._validate_result(
            result
        )

        # -------------------------------------------------
        # Deterministic fresh-information routing.
        #
        # The LLM remains responsible for extracting the search
        # query and other structured fields, but explicit current
        # or recent-information language must not depend on the
        # LLM choosing the "web" intent correctly.
        # -------------------------------------------------

        validated_result = (
            self._force_fresh_web_research(
                message=message,
                result=validated_result,
            )
        )

        # -------------------------------------------------
        # Deterministic recent-context resolution.
        #
        # The LLM understands intent, but for short follow-ups
        # such as "Complete it." we trust the most recent
        # relevant conversation context before allowing a
        # broad semantic task match.
        # -------------------------------------------------

        validated_result = (
            self._resolve_recent_context_reference(
                message=message,
                history=history,
                result=validated_result,
            )
        )

        return validated_result

    def _is_indirect_reference_message(
        self,
        message: str,
    ) -> bool:
        """
        Detect short follow-up messages that refer to an
        object from recent conversation.

        Examples:

            "Complete it."
            "Cancel it."
            "Move it to 8 PM."
            "Update that task."
            "Delete that reminder."
        """

        normalized = message.strip().lower()

        indirect_phrases = {
            "it",
            "that",
            "this",
            "that task",
            "this task",
            "that reminder",
            "this reminder",
            "the previous one",
            "the previous task",
            "the previous reminder",
        }

        if normalized in indirect_phrases:
            return True

        indirect_patterns = (
            "complete it",
            "finish it",
            "cancel it",
            "delete it",
            "start it",
            "update it",
            "move it",
            "change it",
            "reschedule it",
            "complete that",
            "cancel that",
            "delete that",
            "update that",
            "move that",
            "change that",
            "reschedule that",
        )

        return any(
            normalized.startswith(pattern)
            for pattern in indirect_patterns
        )

    def _extract_recent_task_creation_reference(
        self,
        history: list[dict],
    ) -> str | None:
        """
        Find the most recent user message that clearly
        created a task and extract its task title.

        Example:

            "Create a high priority task to practice FastAPI
             for my AI Engineer interview."

        returns:

            "practice FastAPI for my AI Engineer interview"
        """

        task_creation_patterns = (
            r"\bcreate\s+(?:a\s+)?(?:high\s+|medium\s+|low\s+)?"
            r"priority\s+task\s+to\s+(.+)$",

            r"\badd\s+(?:a\s+)?(?:high\s+|medium\s+|low\s+)?"
            r"priority\s+task\s+to\s+(.+)$",

            r"\bcreate\s+(?:a\s+)?task\s+to\s+(.+)$",

            r"\badd\s+(?:a\s+)?task\s+to\s+(.+)$",

            r"\bmake\s+(?:a\s+)?task\s+to\s+(.+)$",
        )

        for item in reversed(history):
            if item.get("role") != "user":
                continue

            content = str(
                item.get("content", "")
            ).strip()

            if not content:
                continue

            normalized = content.lower()

            for pattern in task_creation_patterns:
                match = re.search(
                    pattern,
                    normalized,
                )

                if not match:
                    continue

                reference = match.group(1).strip()

                reference = re.sub(
                    r"[.!?]+$",
                    "",
                    reference,
                ).strip()

                if reference:
                    return reference

        return None

    def _extract_recent_reminder_creation_reference(
        self,
        history: list[dict],
    ) -> str | None:
        """
        Find the most recent user message that clearly
        created a reminder and extract its content/title.

        Example:

            "Remind me tomorrow at 6 PM to practice Python
             decorators."

        returns:

            "practice Python decorators"
        """

        for item in reversed(history):
            if item.get("role") != "user":
                continue

            content = str(
                item.get("content", "")
            ).strip()

            if not content:
                continue

            match = re.search(
                r"\bremind\s+me\b.*?\bto\s+(.+)$",
                content,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            reference = match.group(1).strip()

            reference = re.sub(
                r"[.!?]+$",
                "",
                reference,
            ).strip()

            if reference:
                return reference

        return None

    def _force_fresh_web_research(
        self,
        message: str,
        result: dict,
    ) -> dict:
        """
        Force clearly stated fresh-information requests onto
        the live web-search path even when the LLM misclassifies
        the request as chat/question/advice.

        Personal task/reminder/calendar requests are intentionally
        excluded so words such as "today" or "current" do not
        accidentally trigger a web search.
        """

        intent = result.get("intent")
        normalized = " ".join(
            message.strip().lower().split()
        )

        if not normalized:
            return result

        explicit_source_request = any(
            marker in normalized
            for marker in (
                "web source",
                "reliable source",
                "source link",
                "publication date",
                "cite sources",
                "citation",
            )
        )

        if intent not in {
            "chat",
            "question",
            "advice",
        } and not (
            intent == "planning"
            and explicit_source_request
        ):
            return result

        protected_patterns = (
            r"\bremind me\b",
            r"\b(?:create|add|make)\s+(?:a\s+)?(?:high\s+|medium\s+|low\s+)?priority\s+task\b",
            r"\b(?:create|add|make)\s+(?:a\s+)?task\b",
            r"\b(?:show|list|view)\s+(?:my\s+)?(?:tasks?|reminders?|calendar|schedule)\b",
            r"\b(?:complete|start|cancel|delete|update|move|reschedule)\s+(?:my\s+)?(?:task|reminder|event)\b",
        )

        if any(
            re.search(pattern, normalized)
            for pattern in protected_patterns
        ):
            return result

        fresh_markers = (
            "latest",
            "current",
            "currently",
            "today",
            "today's",
            "aaj",
            "abhi",
            "filhal",
            "recent",
            "recently",
            "newest",
            "this week",
            "this month",
            "this year",
            "as of",
            "up to date",
            "up-to-date",
            "live",
            "real time",
            "realtime",
            "right now",
            "at the moment",
            "now",
            "score",
            "scores",
            "scorecard",
        )

        has_fresh_marker = any(
            re.search(
                rf"\b{re.escape(marker)}\b",
                normalized,
            )
            for marker in fresh_markers
        )

        if not has_fresh_marker:
            return result

        personal_current_patterns = (
            r"\bwhat(?:'s| is) my current (?:task|tasks|reminder|reminders|calendar|schedule)\b",
            r"\bwhat(?:'s| is) my (?:task|tasks|reminder|reminders|calendar|schedule)\b",
            r"\bshow me my current (?:task|tasks|reminder|reminders|calendar|schedule)\b",
        )

        if any(
            re.search(pattern, normalized)
            for pattern in personal_current_patterns
        ):
            return result

        information_markers = (
            "what ",
            "what's",
            "who ",
            "which ",
            "when ",
            "where ",
            "why ",
            "how ",
            "is ",
            "are ",
            "does ",
            "did ",
            "tell me",
            "give me",
            "show me",
            "news",
            "headline",
            "headlines",
            "release",
            "released",
            "announcement",
            "announcements",
            "price",
            "prices",
            "rate",
            "rates",
            "stock",
            "stocks",
            "market",
            "weather",
            "status",
            "version",
            "versions",
            "update",
            "updates",
            "happening",
            "search",
            "research",
            "look up",
            "find ",
            "score",
            "scores",
            "scorecard",
            "match",
            "matches",
            "fixture",
            "fixtures",
            "cricket",
            "football",
            "soccer",
            "sports",
            "playing",
            "wicket",
            "wickets",
            "runs",
            "goal",
            "goals",
            "innings",
            "tournament",
            "league",
            "points table",
            "standings",
        )

        has_information_marker = any(
            marker in normalized
            for marker in information_markers
        )

        if not has_information_marker:
            return result

        topic = result.get("web_topic")

        has_weather = any(
            signal in normalized
            for signal in (
                "weather",
                "temperature",
                "forecast",
                "conditions",
            )
        )
        has_weather_location = bool(
            re.search(
                r"\b(?:weather|temperature|forecast|conditions?)\s+(?:in|for|at)\s+[^?!.,;]+",
                normalized,
            )
        )

        live_sports_terms = (
            "cricket",
            "football",
            "soccer",
            "sports",
            "match",
            "matches",
            "score",
            "scores",
            "scorecard",
            "fixture",
            "fixtures",
            "playing",
            "wicket",
            "wickets",
            "innings",
            "goals",
            "goal",
            "pakistan vs england",
            "pak vs eng",
            "pak vs england",
            "eng vs pak",
            "england vs pakistan",
        )
        has_live_sports_question = any(
            term in normalized
            for term in live_sports_terms
        )

        if has_weather and has_weather_location:
            topic = "weather"
        elif "news" in normalized or "headline" in normalized:
            topic = "news"
        elif has_live_sports_question:
            # Scorecards, fixtures, and live-match status are best searched as
            # general web pages; a news-only search can return commentary but
            # miss the actual scoreboard/scorecard.
            topic = "general"
        elif any(
            marker in normalized
            for marker in (
                "latest developments",
                "latest development",
                "recent developments",
                "recent development",
                "current developments",
                "current development",
            )
        ):
            topic = "news"
        elif any(
            marker in normalized
            for marker in (
                "price",
                "prices",
                "stock",
                "stocks",
                "market",
                "forex",
                "exchange rate",
                "usd",
                "pkr",
                "bitcoin",
            )
        ):
            topic = "finance"
        elif topic not in {
            "general",
            "news",
            "finance",
        }:
            topic = "general"

        time_range = result.get(
            "web_time_range"
        )

        if (
            any(
                marker in normalized
                for marker in (
                    "today",
                    "today's",
                    "aaj",
                    "abhi",
                    "filhal",
                    "right now",
                    "at the moment",
                    "now",
                    "live",
                    "realtime",
                    "real time",
                    "latest developments",
                    "latest development",
                    "recent developments",
                    "recent development",
                    "current developments",
                    "current development",
                )
            )
            or has_live_sports_question
        ):
            time_range = "day"
        elif "this week" in normalized:
            time_range = "week"
        elif "this month" in normalized:
            time_range = "month"
        elif "this year" in normalized:
            time_range = "year"
        elif time_range not in {
            "day",
            "week",
            "month",
            "year",
        }:
            time_range = None

        query = str(
            result.get("query") or ""
        ).strip()

        if not query:
            query = message.strip()

        # The classifier can return an overly broad or unrelated query for
        # short breaking/current-news prompts. Keep explicit AI-news requests
        # anchored to the requested subject rather than trusting that guess.
        if re.search(
            r"\bai\s+(?:news|headlines?)\b|\b(?:news|headlines?)\s+(?:in|about|on)\s+ai\b",
            normalized,
        ):
            query = "latest AI news"
        elif has_live_sports_question:
            # Use canonical team names for common cricket abbreviations, while
            # preserving the user's exact utterance for less common teams/leagues.
            team_aliases = (
                (r"\b(?:pak|pakistan)\b", "Pakistan"),
                (r"\b(?:eng|england)\b", "England"),
                (r"\b(?:ind|india)\b", "India"),
                (r"\b(?:aus|australia)\b", "Australia"),
                (r"\b(?:nz|new zealand)\b", "New Zealand"),
                (r"\b(?:bangladesh|ban)\b", "Bangladesh"),
                (r"\b(?:sri lanka|sl)\b", "Sri Lanka"),
                (r"\b(?:west indies|wi)\b", "West Indies"),
                (r"\b(?:afghanistan|afg)\b", "Afghanistan"),
            )
            detected_teams = [
                canonical for pattern, canonical in team_aliases
                if re.search(pattern, normalized)
            ]
            if len(detected_teams) >= 2:
                sport_label = "cricket" if any(
                    term in normalized
                    for term in ("cricket", "wicket", "wickets", "innings", "odi", "t20", "test match")
                ) or set(detected_teams).issubset({
                    "Pakistan", "England", "India", "Australia", "New Zealand",
                    "Bangladesh", "Sri Lanka", "West Indies", "Afghanistan",
                }) else "sports"
                query = (
                    f"{detected_teams[0]} vs {detected_teams[1]} "
                    f"{sport_label} live score today"
                )
            else:
                query = message.strip()
                if not re.search(
                    r"\b(?:live|score|scores|scorecard|today|aaj|abhi|right now|now)\b",
                    normalized,
                ):
                    query = f"{query} live score today"

        result["intent"] = "web"
        result["web_action"] = "search"
        result["web_topic"] = topic or "general"
        result["web_time_range"] = time_range
        result["query"] = query or None
        result["action"] = "search"
        result["requires_tool"] = True

        return result

    def _resolve_task_creation_confirmation(
        self,
        *,
        message: str,
        history: list[dict],
    ) -> dict | None:
        """Turn a clear yes to a task-creation confirmation into a deterministic action."""

        normalized_reply = re.sub(r"[,.!?;:]+", " ", str(message or "").lower())
        normalized_reply = " ".join(normalized_reply.split())
        if not normalized_reply or len(normalized_reply) > 120:
            return None

        affirmative = re.fullmatch(
            r"(?:(?:okay|ok|yes|yeah|yep|sure|right|go ahead|do it|please do|"
            r"this is what i want|that's what i want|that is what i want|"
            r"haan|han|ji|bilkul|theek hai|haan yehi chahiye|"
            r"\u0939\u093e\u0901|\u0939\u093e\u0902|\u091c\u0940 \u0939\u093e\u0901|"
            r"\u0920\u0940\u0915 \u0939\u0948|\u0915\u0930 \u0926\u094b)\s*)+",
            normalized_reply,
            flags=re.IGNORECASE,
        )
        if not affirmative or not history:
            return None

        recent = history[-8:]
        latest_assistant = next(
            (
                str(item.get("content") or "").strip().lower()
                for item in reversed(recent)
                if item.get("role") == "assistant"
                and str(item.get("content") or "").strip()
            ),
            "",
        )
        if not latest_assistant:
            return None

        has_task_context = re.search(
            r"\btask\b|\btasks\b|\u091f\u093e\u0938\u094d\u0915|\u0915\u093e\u0930\u094d\u092f",
            latest_assistant,
            flags=re.IGNORECASE,
        ) is not None
        has_create_action = re.search(
            r"\b(?:create|add|make)\b|\u0915\u094d\u0930\u093f\u090f\u091f|\u092c\u0928\u093e\s+\u0926\u094b",
            latest_assistant,
            flags=re.IGNORECASE,
        ) is not None
        asks_for_confirmation = re.search(
            r"exactly what you want|let me know if|is that correct|"
            r"is this correct|confirm(?:ation)?|should i create|"
            r"shall i create|do you want me to create",
            latest_assistant,
            flags=re.IGNORECASE,
        ) is not None
        if not (has_task_context and has_create_action and asks_for_confirmation):
            return None

        title_patterns = (
            r"(?:\btitle\b|\u091f\u093e\u0907\u091f\u0932)\s*(?:is|hai|\u0939\u0948|[:=])\s*[\"']([^\"']{1,300})[\"']",
            r"(?:\btitle\b|\u091f\u093e\u0907\u091f\u0932)\s*(?:is|hai|\u0939\u0948|[:=])\s*(.+?)(?=\s*[,;.!?]|$)",
            r"\b(?:task\s+)?(?:called|named|titled)\s+[\"']([^\"']{1,300})[\"']",
            r"\b(?:task\s+)?(?:called|named|titled)\s+(.+?)(?=\s+(?:with|due|priority|and)\b|[,;.!?]|$)",
            r"\btask\s+(?:title|name)\s*[:=]\s*[\"']?(.+?)(?=\s*[,;.!?]|$)",
        )
        for item in reversed(recent):
            if item.get("role") != "user":
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            if not re.search(
                r"\b(?:create|add|make)\b|\btask\b|"
                r"\u091f\u093e\u0938\u094d\u0915|\u0915\u094d\u0930\u093f\u090f\u091f|\u092c\u0928\u093e\s+\u0926\u094b",
                content,
                flags=re.IGNORECASE,
            ):
                continue

            for pattern in title_patterns:
                match = re.search(pattern, content, flags=re.IGNORECASE)
                if not match:
                    continue
                title = match.group(1).strip().strip(" \t\r\n\"'")
                title = re.sub(r"\s+(?:okay|ok|\u0913\u0915\u0947)$", "", title, flags=re.IGNORECASE).strip()
                title = title.rstrip(" .!?;:")
                if not title or len(title) > 300:
                    continue

                result = self._default_result()
                result.update(
                    {
                        "intent": "task",
                        "task": title,
                        "task_reference": None,
                        "task_action": "create",
                        "priority": None,
                        "requires_tool": True,
                        "clarification_required": False,
                    }
                )
                return result

        return None

    def _resolve_recent_context_reference(
        self,
        message: str,
        history: list[dict],
        result: dict,
    ) -> dict:
        """
        Resolve indirect follow-up references deterministically.

        LLMs are useful for understanding intent, but when the
        user explicitly refers to the recent item using
        "it", "that task", etc., recent conversation context
        gets priority over an unrelated semantic match.
        """

        if not history:
            return result

        if not self._is_indirect_reference_message(
            message
        ):
            return result

        intent = result.get("intent")

        if intent == "task":
            recent_task_reference = (
                self._extract_recent_task_creation_reference(
                    history
                )
            )

            if recent_task_reference:
                result["task_reference"] = (
                    recent_task_reference
                )

                result["task"] = None

        elif intent == "reminder":
            recent_reminder_reference = (
                self._extract_recent_reminder_creation_reference(
                    history
                )
            )

            if recent_reminder_reference:
                result["reminder_reference"] = (
                    recent_reminder_reference
                )

                result["task"] = None

        return result

    @staticmethod
    def _deterministic_desktop_fallback(message: str) -> dict | None:
        """Parse a small allowlisted set of local desktop commands without an LLM."""
        original = " ".join(str(message or "").strip().split())

        # When a supported website name and an explicit open/visit verb are
        # both present, treat it as a website request before the app-name
        # parser. Speech recognition may prepend a misheard wake word (for
        # example, "Nava Wikipedia open karna"); that must not become an app
        # search for the combined phrase.
        site_match = re.search(
            r"\b(?P<site>wikipedia|google|youtube|gmail|github|reddit|bing|"
            r"duckduckgo|outlook|facebook|twitter|linkedin|chatgpt)\b",
            original,
            flags=re.IGNORECASE,
        )
        open_website_requested = bool(
            re.search(
                r"\b(?:open|visit|browse|go\s+to|navigate\s+to|kholo|kholna|"
                r"open\s+kar(?:na|o|do)|open\s+kr(?:na|o|do))\b|"
                r"\u0916\u094b\u0932\u094b|"
                r"\u0916\u094b\u0932\s+\u0926\u094b",
                original,
                flags=re.IGNORECASE,
            )
        )
        has_search_flow = re.search(
            r"\b(?:search|find|lookup)\b|\u0938\u0930\u094d\u091a|\u0916\u094b\u091c",
            original,
            flags=re.IGNORECASE,
        ) is not None
        has_youtube_play = (
            site_match is not None
            and site_match.group("site").casefold() == "youtube"
            and re.search(
                r"\b(?:chala\w*|bajao\w*|play\w*|laga\s+(?:do|lo))\b|"
                r"\u091a\u0932\u093e\u0928\u093e|"
                r"\u091a\u0932\u093e\u0913|"
                r"\u092c\u091c\u093e\u0913|"
                r"\u0932\u0917\u093e\s+\u0926\u094b|"
                r"\u0932\u0917\u093e\s+\u0932\u094b",
                original,
                flags=re.IGNORECASE,
            ) is not None
        )
        if (
            site_match
            and open_website_requested
            and not has_search_flow
            and not has_youtube_play
        ):
            site_urls = {
                "wikipedia": "https://www.wikipedia.org",
                "google": "https://www.google.com",
                "youtube": "https://www.youtube.com",
                "gmail": "https://mail.google.com",
                "github": "https://github.com",
                "reddit": "https://www.reddit.com",
                "bing": "https://www.bing.com",
                "duckduckgo": "https://duckduckgo.com",
                "outlook": "https://outlook.live.com",
                "facebook": "https://www.facebook.com",
                "twitter": "https://x.com",
                "linkedin": "https://www.linkedin.com",
                "chatgpt": "https://chatgpt.com",
            }
            site_url = site_urls[site_match.group("site").casefold()]
            result = IntentService.__new__(IntentService)._default_result()
            result.update(
                {
                    "intent": "desktop",
                    "action": "start",
                    "desktop_operation": "open_url",
                    "desktop_target": site_url,
                    "requires_tool": True,
                    "clarification_required": False,
                }
            )
            return result

        # Some speech recognizers duplicate the first syllable of PowerPoint.
        original = re.sub(r"\bpower\s+(powerpoint)\b", r"\1", original, flags=re.IGNORECASE)
        # Normalize mixed-script realtime ASR before the allowlisted parser runs.
        original = re.sub(
            r"^(?:acha|achha|theek hai|okay|ok|haan|han|zara|"
            r"\u0905\u091a\u094d\u091b\u093e|\u0920\u0940\u0915\s+\u0939\u0948|"
            r"\u0939\u093e\u0901|\u0939\u093e\u0902|\u091c\u0940)[,:\s]+",
            "",
            original,
            flags=re.IGNORECASE,
        )
        original = re.sub(
            r"^(?P<site>wikipedia|google|youtube|gmail|github|reddit|bing|"
            r"duckduckgo|microsoft|outlook|facebook|twitter|linkedin|chatgpt)\s+"
            r"(?:\u0913\u092a\u0928\s+(?:\u0915\u0930\u0928\u093e|"
            r"\u0915\u0930\u094b|\u0915\u0930\s+(?:\u0932\u094b|\u0926\u094b))|"
            r"\u0916\u094b\u0932\u094b|\u0916\u094b\u0932\s+\u0926\u094b)"
            r"(?:\s+\u0939\u0948(?:\u0902)?)?\s*[\u0964\u0965.!?]*$",
            r"open \g<site>",
            original,
            flags=re.IGNORECASE,
        )
        # Normalize the known split-transcript alias "Wikimedia. Wikipedia".
        original = re.sub(r"\bwikimedia[.,]\s*wikipedia\b", "wikimedia wikipedia", original, flags=re.IGNORECASE)

        # ASR may return the application name/action in Devanagari even when
        # the conversation itself is mixed-script. Normalize only known,
        # allowlisted application names; never turn arbitrary text into a URL.
        devanagari_app_aliases = (
            (r"(?<!\w)\u0928\u094b\u091f\u092a\u0948\u0921(?!\w)", "notepad"),
            (r"(?<!\w)\u0915\u0948\u0932\u0915\u0941\u0932\u0947\u091f\u0930(?!\w)", "calculator"),
            (r"(?<!\w)\u091f\u0947\u0915\u094d\u0938\u094d\u091f\s+\u090f\u0921\u093f\u091f\u0930(?!\w)", "text editor"),
            (r"(?<!\w)\u092b\u093e\u0907\u0932\s+\u090f\u0915\u094d\u0938\u092a\u094d\u0932\u094b\u0930\u0930(?!\w)", "file explorer"),
            (r"(?<!\w)\u0917\u0942\u0917\u0932\s+\u0915\u094d\u0930\u094b\u092e(?!\w)", "chrome"),
            (r"(?<!\w)\u0915\u094d\u0930\u094b\u092e(?!\w)", "chrome"),
            (r"(?<!\w)\u0917\u0942\u0917\u0932(?!\w)", "google"),
            (r"(?<!\w)\u0935\u093f\u0915\u093f\u092a\u0940\u0921\u093f\u092f\u093e(?!\w)", "wikipedia"),
            (r"(?<!\w)\u092f\u0942\u091f\u094d\u092f\u0942\u092c(?!\w)", "youtube"),
            (r"(?<!\w)\u092c\u094d\u0930\u093e\u0909\u091c\u093c\u0930(?!\w)", "browser"),
        )
        for alias_pattern, alias in devanagari_app_aliases:
            original = re.sub(
                alias_pattern,
                alias,
                original,
                flags=re.IGNORECASE,
            )

        # Realtime ASR may preserve Hindi-script search verbs and fillers even
        # when the website name is transcribed in Latin script. Normalize only
        # known command words so deterministic routing still works in mixed
        # Hindi/Roman-Urdu transcripts.
        devanagari_search_aliases = (
            ("सर्च बार", "search bar"),
            ("जाकर", "ja kar"),
            ("जा कर", "ja kar"),
            ("वहाँ", "wahan"),
            ("वहां", "wahan"),
            ("पर", "par"),
            ("पे", "pe"),
            ("में", "mein"),
            ("सर्च", "search"),
            ("मूवीज", "movies"),
            ("मूवी", "movie"),
            ("करना", "karna"),
            ("करो", "karo"),
            ("कर दो", "kar do"),
            ("लिखो", "likho"),
            ("खुद", "khud"),
        )
        has_allowlisted_browser_search = (
            re.search(
                r"\b(?:wikipedia|google|youtube)\b",
                original,
                flags=re.IGNORECASE,
            )
            is not None
            and any(token in original for token in ("सर्च", "खोज"))
        )
        if has_allowlisted_browser_search:
            for source, replacement in devanagari_search_aliases:
                original = original.replace(source, replacement)

            # Convert Hindi sentence-final punctuation only for the search
            # command we're normalizing; other app commands keep their native
            # Devanagari verb tokens for the existing app parser.
            original = original.replace("\u0964", ".").replace("\u0965", ".")

        media_play_verbs = (
            "चलाओ", "चला दो", "चलाना", "लगाओ", "लगा दो", "बजाओ",
        )
        roman_media_play = re.search(
            r"\b(?:chala\w*|bajao\w*|play\w*|laga\s+do|laga\s+lo)\b",
            original,
            flags=re.IGNORECASE,
        ) is not None
        has_youtube_play_request = (
            re.search(r"\byoutube\b", original, flags=re.IGNORECASE) is not None
            and (any(token in original for token in media_play_verbs) or roman_media_play)
        )
        has_spotify_play_request = (
            re.search(r"\bspotify\b", original, flags=re.IGNORECASE) is not None
            and (any(token in original for token in media_play_verbs) or roman_media_play)
        )
        if has_youtube_play_request or has_spotify_play_request:
            # Normalize command words in mixed-script ASR without touching the
            # actual title. Before this guard the Hindi opener/conjunction
            # ("खोलो और") stayed untranslated, so the play parser missed the
            # command and the request fell through to generic chat.
            original = re.sub(
                r"^(youtube|you tube)\s+(?:\u0916\u094b\u0932\u094b|\u0916\u094b\u0932\s+\u0926\u094b)\s+\u0914\u0930\s+",
                r"\1 kholo aur ",
                original,
                flags=re.IGNORECASE,
            )
            original = re.sub(
                r"^(youtube|you tube)\s+पर\s+",
                r"\1 par ",
                original,
                flags=re.IGNORECASE,
            )
            original = re.sub(
                r"^(youtube|you tube)\s+(?:par|pe)\s+जाओ\s+और\s+",
                r"\1 par ",
                original,
                flags=re.IGNORECASE,
            )
            # Normalize only common Hindi playback verbs after a supported YouTube
            # target was identified; keep the actual song/artist title unchanged.
            # Keep Roman-Urdu playback verb variants deterministic as well.
            original = re.sub(
                r"\b(?:chalana|chalaana|chalayen|chalayein|chalaein)\b",
                "chalao",
                original,
                flags=re.IGNORECASE,
            )
            for source, replacement in (
                ("मेरे लिए", "mere liye"),
                ("में", "mein"),
                ("पर", "par"),
                ("पे", "pe"),
                ("और", "aur"),
                ("चला दो", "chala do"),
                ("चलाओ", "chalao"),
                ("चलाना", "chalao"),
                ("लगाओ", "laga do"),
                ("लगा दो", "laga do"),
                ("बजाओ", "bajao"),
                ("सॉन्ग", "song"),
                ("गाना", "song"),
                ("पल-पल", "Pal Pal"),
                ("पल पल", "Pal Pal"),
            ):
                original = original.replace(source, replacement)
            if has_spotify_play_request:
                for source, replacement in (
                    ("पर", "par"),
                    ("पे", "pe"),
                    ("और", "aur"),
                    ("जाओ", "jao"),
                    ("सॉन्ग", "song"),
                    ("गाना", "song"),
                    ("पल पल", "Pal Pal"),
                ):
                    original = original.replace(source, replacement)
                original = re.sub(
                    r"^(spotify)\s+(?:par|pe)\s+jao\s+aur\s+",
                    r"\1 par ",
                    original,
                    flags=re.IGNORECASE,
                )
            original = original.replace("।", ".").replace("॥", ".")
            # "mere liye" is polite filler, not part of the title or playback verb.
            original = re.sub(
                r"\s+(?:mere\s+liye|for\s+me)[.!?]*$",
                "",
                original,
                flags=re.IGNORECASE,
            )

        # Normalize common Hindi-script commands such as "Notepad ओपन कर दो"
        # into the same allowlisted form as "open Notepad".
        original = re.sub(
            r"(?P<app>calculator|calc|notepad|text editor|file explorer|explorer|"
            r"chrome|edge|firefox|browser|outlook|word|excel|powerpoint)\s+"
            r"(?:\u0913\u092a\u0928\s+(?:\u0915\u0930\u0928\u093e|"
            r"\u0915\u0930\u094b|\u0915\u0930\s+(?:\u0926\u094b|\u0932\u094b))|"
            r"\u0916\u094b\u0932\u094b|\u0916\u094b\u0932\s+(?:\u0926\u094b|\u0932\u094b)|"
            r"\u0932\u0949\u0928\u094d\u091a\s+(?:\u0915\u0930\u094b|"
            r"\u0915\u0930\s+(?:\u0926\u094b|\u0932\u094b)))",
            r"open \g<app>",
            original,
            flags=re.IGNORECASE,
        )

        # "Nikaal do mere liye text editor" is a common spoken equivalent
        # of opening the app; normalize only known application targets.
        original = re.sub(
            r"(?<!\S)(?:abhi\s+)?(?:to\s+)?(?:nikaal|nikal)\s+do\s+"
            r"(?:mere\s+liye\s+)?(?P<app>text editor|notepad|calculator|calc|"
            r"file explorer|chrome|edge|firefox|browser)(?=[.!?,;:]|$)",
            r"open \g<app>",
            original,
            flags=re.IGNORECASE,
        )

        # A voice turn can combine small talk and a desktop command. Keep the
        # actionable tail when it is unmistakably a supported command.
        # Do not split explicit URLs because punctuation belongs to the URL.
        if "://" not in original:
            site_names_for_suffix = (
                r"(?:wikipedia|wikimedia(?:\s*[.,]?\s*wikipedia)?|google|youtube|gmail|"
                r"github|stackoverflow|reddit|bing|duckduckgo|microsoft|outlook|"
                r"facebook|x|twitter|linkedin|chatgpt)"
            )
            original = re.sub(
                rf"^(?:acha|achha|theek hai|okay|ok|haan|han|please|zara|\u0905\u091a\u094d\u091b\u093e|\u0920\u0940\u0915\s+\u0939\u0948|\u0939\u093e\u0901|\u0939\u093e\u0902|\u091c\u0940)[,:\s]+"
                rf"(?=(?:{site_names_for_suffix}|calculator|calc|notepad|file explorer|"
                rf"browser|documents|downloads|desktop)\s+(?:kholo|open\s+(?:karo|kar\s+(?:lo|do))|"
                rf"visit\s+karo|website\s+kholo|chalao|\u0913\u092a\u0928\s+(?:\u0915\u0930\u0928\u093e|\u0915\u0930\u094b|\u0915\u0930\s+(?:\u0932\u094b|\u0926\u094b))|\u0916\u094b\u0932\u094b|\u0916\u094b\u0932\s+\u0926\u094b)\b)",
                "",
                original,
                flags=re.IGNORECASE,
            )
            command_lead = re.compile(
                r"^(?:please\s+)?(?:open|launch|start|visit|go\s+to|navigate\s+to|show|search|find|locate)\b",
                re.IGNORECASE,
            )
            reversed_site_action = re.compile(
                rf"^{site_names_for_suffix}\s+(?:kholo|open\s+karo|open\s+kar\s+(?:lo|do|na)|open\s+karna|visit\s+karo|website\s+kholo|website\s+khol\s+do|\u0913\u092a\u0928\s+(?:\u0915\u0930\u0928\u093e|\u0915\u0930\u094b)|\u0916\u094b\u0932\u094b|\u0916\u094b\u0932\s+\u0926\u094b)$",
                re.IGNORECASE,
            )
            segments = re.split(r"(?<=[.!?])\s+", original)
            if len(segments) > 1:
                for segment in reversed(segments):
                    candidate = segment.strip(" ,;")
                    candidate_normalized = candidate.lower().rstrip(" .!?")
                    if command_lead.search(candidate_normalized) or reversed_site_action.fullmatch(candidate_normalized):
                        original = candidate
                        break

        # Spoken requests often begin with a filler such as "okay". Strip it
        # only when it directly precedes an actionable command so titles like
        # "NOVA task ..." keep their exact wording.
        original = re.sub(
            r"^(?:okay|ok|acha|achha|theek hai|haan|han|zara|hey\s+nova|nova|i\s+said|i\s+told\s+you|maine\s+kaha)[,:\s]+"
            r"(?=(?:please\s+)?(?:open|launch|start|visit|go\s+to|navigate\s+to|show|search|find|locate)\b)",
            "",
            original,
            flags=re.IGNORECASE,
        )
        normalized = original.lower().rstrip(" .!?\u0964\u0965")
        leading_targeted_command = re.match(
            r"^(?:(?:can\s+you|could\s+you|would\s+you|please)\s+)?"
            r"(?P<verb>open|launch|start|visit|go\s+to|navigate\s+to)\s+(?:the\s+)?"
            r"(?P<target>wikimedia(?:\s*[.,]?\s*wikipedia)?|wikipedia|google|youtube|gmail|github|stackoverflow|reddit|bing|duckduckgo|microsoft\s+store|windows\s+store|microsoft|outlook|facebook|x|twitter|linkedin|chatgpt|calculator|calc|notepad|text\s+editor|file\s+explorer|explorer|chrome|edge|firefox|browser|word|excel|powerpoint|documents|downloads|desktop)\b",
            normalized,
            flags=re.IGNORECASE,
        )
        if leading_targeted_command:
            normalized = (
                leading_targeted_command.group("verb").lower()
                + " "
                + leading_targeted_command.group("target").lower()
            )

        if not normalized or len(normalized) > 600:
            return None

        def result(action: str, operation: str, *, target: str | None = None, query: str | None = None) -> dict:
            return {
                "intent": "desktop",
                "action": action,
                "desktop_operation": operation,
                "desktop_target": target,
                "desktop_query": query,
                "requires_tool": True,
                "clarification_required": False,
            }

        # List files only inside one explicitly named, allowlisted user folder.
        # This is a read-only directory listing, never a whole-drive crawl.
        file_list_match = re.fullmatch(
            r"(?:please\s+)?(?:list|show|display)\s+(?:my\s+)?"
            r"(?:files?\s+(?:in|from)\s+(?P<folder>desktop|documents|downloads|pictures|music|videos)"
            r"|(?P<folder_alias>desktop|documents|downloads|pictures|music|videos)(?:\s+(?:files?|folder))?)"
            r"[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        )
        if file_list_match:
            folder = (file_list_match.group("folder") or file_list_match.group("folder_alias") or "").casefold()
            return result("search", "list_files", query=folder)

        # Read-only screen inspection is a first-class desktop action so the assistant
        # can ground later clicks/types in the actual visible accessibility tree.
        spoken_inspect_match = re.fullmatch(
            r"(?:(?:please|zara|mujhe|mujhy)\s+)?(?:(?:meri|mera|my|current)\s+)?"
            r"(?:screen|desktop|window)\s+(?:dikhao|dikha\s+do|check\s+karo|inspect\s+karo|dekh\s+lo|dekho)[.!?]*"
            r"|(?:screen|desktop)\s+(?:par|pe)\s+(?:kya\s+)?(?:hai|dikh\s+raha\s+hai|nazar\s+aa\s+raha\s+hai)[.!?]*"
            r"|(?:स्क्रीन|डेस्कटॉप|विंडो)\s+(?:दिखाओ|दिखा\s+दो|चेक\s+करो|जाँचो|इंस्पेक्ट\s+करो)[।.!?]*"
            r"|(?:स्क्रीन|डेस्कटॉप)\s+पर\s+क्या\s+(?:है|दिख\s+रहा\s+है|नज़र\s+आ\s+रहा\s+है)[।.!?]*"
            r"|(?:मेरे|मेरी)\s+(?:स्क्रीन|डेस्कटॉप)\s+पर\s+(?:अभी\s+)?क्या\s+(?:ओपन|खुला)\s+है[।.!?]*",
            normalized,
            flags=re.IGNORECASE,
        )
        if spoken_inspect_match:
            return result("start", "inspect_screen")

        inspect_match = re.fullmatch(
            r"(?:please\s+)?(?:inspect|check|show|look at|read)\s+"
            r"(?:the\s+)?(?:current\s+)?(?:screen|desktop|windows?)(?:\s+(?:in|for|named|titled)\s+(.+?))?[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"(?:what(?:'s| is)|whats|what)\s+(?:(?:currently|right now)\s+)?(?:open\s+on|on|open in|open)\s+(?:my\s+)?(?:screen|desktop|computer)(?:\s+(?:right now|currently|at the moment|please))?[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"(?:mere|meri|my)\s+(?:screen|desktop|computer)\s+(?:par|pe|mein|me)\s+"
            r"(?:kya\s+)?(?:khula\s+hai|kya\s+hai|kya\s+open\s+hai|kya\s+dikh\s+raha\s+hai|dikhao|dikha\s+do)[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        )
        if inspect_match:
            window = (inspect_match.group(1) or "").strip(" .!?") if inspect_match.lastindex else ""
            return result("start", "inspect_screen", target=window or None)

        # Safe UI automation requires an exact accessibility label, not guessed
        # screen coordinates. Dangerous controls are blocked again in the executor.
        click_match = re.fullmatch(
            r"(?:please\s+)?(?:click|tap|select)\s+(?:on\s+)?(?:the\s+)?"
            r"(?P<control>[^.!?]{1,120}?)"
            r"(?:\s+(?:button|link|tab))?"
            r"(?:\s+(?:in|on|inside)\s+(?:the\s+)?(?P<window>[^.!?]{1,120}?))?[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        )
        if click_match:
            control = re.sub(r"\s+", " ", click_match.group("control")).strip(" ,")
            window = re.sub(r"\s+", " ", click_match.group("window") or "").strip(" ,")
            if control and control.casefold() not in {"it", "that", "this", "there", "here"}:
                return result("start", "click_ui", target=control, query=window or None)

        roman_click_match = re.fullmatch(
            r"(?:(?:please|zara)\s+)?"
            r"(?:(?P<window>.+?)\s+(?:mein|me|ke\s+andar)\s+)?"
            r"(?P<control>[^.!?]{1,120}?)\s+(?:(?:button|link|tab)\s+)?"
            r"(?:par|pe)\s+(?:click|tap)\s+(?:karo|karna|kar\s+(?:do|lo))[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        )
        if roman_click_match:
            control = re.sub(r"\s+", " ", roman_click_match.group("control")).strip(" ,")
            control = re.sub(r"\s+(?:button|link|tab)$", "", control, flags=re.IGNORECASE)
            window = re.sub(r"\s+", " ", roman_click_match.group("window") or "").strip(" ,")
            if control and control.casefold() not in {"it", "that", "this", "there", "here"}:
                return result("start", "click_ui", target=control, query=window or None)

        type_match = re.fullmatch(
            r"(?:please\s+)?(?:type|enter|write)\s+(?P<text>.+?)\s+"
            r"(?:into|in)\s+(?:the\s+)?(?P<field>[^.!?]{1,120}?)[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        )
        if type_match:
            text_to_type = type_match.group("text").strip().strip("\"'")
            field_name = re.sub(r"\s+", " ", type_match.group("field")).strip(" ,")
            if text_to_type and field_name:
                return result("start", "type_ui", target=field_name, query=text_to_type)

        roman_type_match = re.fullmatch(
            r"(?P<field>[^.!?]{1,120}?)\s+(?:mein|me)\s+(?P<text>.+?)\s+"
            r"(?:likho|likh\s+(?:do|dijiye)|type\s+karo|enter\s+karo)[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        )
        if roman_type_match:
            field_name = re.sub(r"\s+", " ", roman_type_match.group("field")).strip(" ,")
            text_to_type = roman_type_match.group("text").strip().strip("\"'")
            if field_name and text_to_type:
                return result("start", "type_ui", target=field_name, query=text_to_type)

        roman_key_match = re.fullmatch(
            r"(?P<key>ctrl\+[lfacv]|tab|shift\+tab|escape|esc|space|backspace|up|down|left|right|home|end|f5|enter)\s+"
            r"(?:dabao|daba\s+do|press\s+karo|press\s+kar\s+do|kar\s+do)[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        )
        if roman_key_match:
            return result("start", "press_key", target=roman_key_match.group("key").strip())

        key_match = re.fullmatch(
            r"(?:please\s+)?(?:press|hit)\s+(?P<key>ctrl\+l|ctrl\+f|ctrl\+a|ctrl\+c|ctrl\+v|"
            r"tab|shift\+tab|escape|esc|space|backspace|up|down|left|right|home|end|f5|enter)"
            r"(?:\s+(?:in|on)\s+(?:the\s+)?(?P<window>[^.!?]{1,120}?))?[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        )
        if key_match:
            key = key_match.group("key").strip()
            window = (key_match.group("window") or "").strip(" ,")
            return result("start", "press_key", target=key, query=window or None)

        # A spoken request for the latest video by a named creator means playback,
        # not opening an app whose name is the whole sentence.
        latest_video_match = re.fullmatch(
            r"(?:please\s+)?(?P<creator>.+?)\s+(?:ki\s+|ka\s+|ke\s+)?"
            r"(?P<recency>latest|newest|most\s+recent|recent)\s+"
            r"(?P<media>video|videos)(?:\s+(?:upload|uploaded))?"
            r"(?:\s+(?:ki\s+)?hai)?(?:\s+na)?(?:\s+(?:usko|isko|ko))?\s+"
            r"(?:zara\s+)?(?:chalao|chala\s+do|laga\s+do|play\s+(?:karo|kar\s+(?:do|lo)))[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        )
        if latest_video_match and not re.match(r"^(?:youtube|you tube)\b", normalized, flags=re.IGNORECASE):
            creator = latest_video_match.group("creator")
            creator = re.sub(
                r"^(?:youtube|you tube)\s+(?:(?:par|pe)\s+)?(?:jao|go\s+to)?\s*(?:(?:aur|and)\s+)?",
                "",
                creator,
                flags=re.IGNORECASE,
            )
            creator = re.sub(
                r"\b(?:ne|jo|like|koi|ki|ka|ke|the|latest|newest|recent|video|videos|upload|uploaded|hai|na|usko|isko|ko)\b",
                " ",
                creator,
                flags=re.IGNORECASE,
            )
            creator = " ".join(creator.split()).strip(" .,!?:;")
            if len(creator) >= 2:
                return result(
                    "start",
                    "play_youtube",
                    target=f"{creator} latest {latest_video_match.group('media').rstrip('s')}",
                )

        # Spotify is routed to its Web Player with a verified-playback attempt;
        # if the account/player cannot play it, NOVA reports that honestly.
        spotify_play_patterns = (
            r"(?:please\s+)?spotify\s+(?:kholo|open\s+karo|open\s+kar\s+(?:lo|do))\s+(?:aur|and)\s+"
            r"(?P<query>.+?)\s+(?:song|track|music|gaana|gana)?\s*"
            r"(?:chalao|chala\s+do|laga\s+do|bajao|play\s+(?:karo|kar\s+(?:do|lo)))[.!?]*",
            r"(?:please\s+)?spotify\s+(?:par|pe|on|in)\s+(?:jao\s+(?:aur|and)\s+)?"
            r"(?P<query>.+?)\s+(?:song|track|music|gaana|gana)?\s*"
            r"(?:chalao|chala\s+do|laga\s+do|bajao|play\s+(?:karo|kar\s+(?:do|lo)))[.!?]*",
            r"(?:please\s+)?(?:play|start|chalao|chala\s+do|laga\s+do|bajao)\s+"
            r"(?P<query>.+?)\s+(?:on|in|par|pe)\s+spotify[.!?]*",
        )
        spotify_play_match = next(
            (
                match for pattern in spotify_play_patterns
                if (match := re.fullmatch(pattern, original, flags=re.IGNORECASE))
            ),
            None,
        )
        if spotify_play_match:
            spotify_query = spotify_play_match.group("query").strip(" .,!?:;")
            spotify_query = re.sub(r"\s+(?:song|track|music|gaana|gana)$", "", spotify_query, flags=re.IGNORECASE).strip()
            spotify_query = re.sub(r"\b(?:the|a|my|please|koi|kuch)\b", " ", spotify_query, flags=re.IGNORECASE)
            spotify_query = " ".join(spotify_query.split()).strip()
            if len(spotify_query) >= 2 and len(spotify_query) <= 180:
                return result("start", "play_spotify", target=spotify_query)

        # A specific YouTube play request is a distinct desktop operation, not
        # merely a search URL. It may report success only after playback is verified.
        youtube_play_patterns = (
            r"(?:please\s+)?(?:play|start|put on)\s+(?P<query>.+?)\s+(?:on|in)\s+(?:youtube|you tube)[.!?]*",
            r"(?:please\s+)?(?:open|launch|go to|navigate to|kholo)\s+(?:youtube|you tube)\s+(?:and|aur)\s+(?:play|start|chalao|chala do|laga do|bajao)\s+(?P<query>.+?)[.!?]*",
            r"(?:youtube|you tube)\s+(?:par|pe|mein|me)\s+(?P<query>.+?)\s+(?:chalao|chala do|laga do|bajao|play\s+(?:karo|kar\s+(?:do|lo)))[.!?]*",
            r"(?:youtube|you tube)\s+(?:kholo|open\s+karo|open\s+kar\s+(?:lo|do))\s+(?:aur|and)\s+(?P<query>.+?)\s+(?:chalao|chala do|laga do|bajao|play\s+(?:karo|kar\s+(?:do|lo)))[.!?]*",
            r"(?P<query>.+?)\s+(?:on\s+)?(?:youtube|you tube)\s+(?:par|pe)\s+(?:chalao|chala do|laga do|bajao)[.!?]*",
        )
        # Normalize the common "YouTube par jao aur..." lead-in before matching
        # the title; otherwise "jao aur" was incorrectly included in the video query.
        youtube_phrase = re.sub(
            r"^(youtube|you tube)\s+(?:par|pe)\s+(?:jao|go\s+to)\s+(?:aur|and)\s+",
            r"\1 par ",
            original,
            flags=re.IGNORECASE,
        )
        youtube_play_match = next(
            (
                match
                for pattern in youtube_play_patterns
                if (match := re.fullmatch(pattern, youtube_phrase, flags=re.IGNORECASE))
            ),
            None,
        )
        if youtube_play_match:
            play_query = re.sub(
                r"^(?:(?:the|a|my|song|track|music)\s+)+",
                "",
                youtube_play_match.group("query").strip(" \t\r\n.,!?;:'\""),
                flags=re.IGNORECASE,
            )
            play_query = re.sub(
                r"\s+(?:song|track|music|gaana|gana)$",
                "",
                play_query,
                flags=re.IGNORECASE,
            ).strip()
            # Repeated English words can arrive hyphenated by realtime ASR.
            play_query = re.sub(
                r"\bpal[\s-]+pal\b",
                "Pal Pal",
                play_query,
                flags=re.IGNORECASE,
            )
            # English song titles are sometimes transcribed phonetically in
            # Devanagari by multilingual speech recognition. Canonicalize the
            # common Interstellar title words so YouTube can match its Latin UI
            # result label and playback verification can identify the right item.
            for source, replacement in (
                (r"\u0907\u0902\u091f\u0930\u0938\u094d\u091f\u0947\u0932\u0930", "Interstellar"),
                (r"\u0938\u093e\u0909\u0902\u0921\u091f\u094d\u0930\u0948\u0915", "soundtrack"),
            ):
                play_query = re.sub(source, replacement, play_query, flags=re.IGNORECASE)
            normalized_play_query = " ".join(play_query.casefold().split())
            vague_queries = {
                "", "song", "songs", "music", "a song", "any song", "some song",
                "my favourite song", "my favorite song", "something", "anything",
                "whatever", "that song", "this song", "it", "that", "this",
                # Title cleanup removes the trailing "song" token, so keep the
                # remaining generic determiners vague as well.
                "koi", "kuch", "any", "some", "koi song", "koi gana", "gaana", "gana", "गाना", "गाने", "गीत", "कोई गाना", "कोई गीत",
            }
            if (
                play_query
                and normalized_play_query not in vague_queries
                and len(play_query) <= 180
            ):
                return result("start", "play_youtube", target=play_query)
            if normalized_play_query in vague_queries or not play_query:
                # Do not reinterpret a vague playback request as a generic YouTube
                # search. Ask for a title and leave the desktop untouched.
                return {
                    "intent": "chat",
                    "action": None,
                    "desktop_operation": None,
                    "desktop_target": None,
                    "desktop_query": None,
                    "requires_tool": False,
                    "clarification_required": True,
                }

        # Route common spoken browser-navigation forms before the LLM classifier.
        # Examples: "Wikipedia par ja kar ... wahan movie search karo",
        # "YouTube pe Interstellar search karo", and "Google par jao aur ... likho".
        # Only three fixed, allowlisted hosts are accepted here.
        spoken_site_match = re.match(
            r"^(?P<site>google|wikipedia|youtube)\s+(?:par|pe|mein|me)\b(?P<rest>.*)$",
            original,
            flags=re.IGNORECASE,
        )
        if spoken_site_match:
            spoken_site = spoken_site_match.group("site").casefold()
            spoken_rest = spoken_site_match.group("rest").strip(" \t\r\n.,!?;:")
            spoken_query = None

            # Query can precede the action ("movies search karo") ...
            before_search = re.search(
                r"(?P<query>.+?)\s+search\s+(?:karo|karna|kar\s+(?:do|lo)|kijiye)(?:\s+na)?[.!?]*$",
                spoken_rest,
                flags=re.IGNORECASE,
            )
            # ... or follow it ("search karo movies").
            after_search = re.search(
                r"\bsearch\s+(?:karo|karna|kar\s+(?:do|lo)|kijiye)(?:\s+na)?\s+(?P<query>.+)$",
                spoken_rest,
                flags=re.IGNORECASE,
            )
            written_query = re.search(
                r"\b(?:aur|and)\s+(?P<query>.+?)\s+(?:likho|likh\s+(?:do|dijiye)|type\s+karo|enter\s+karo)[.!?]*$",
                spoken_rest,
                flags=re.IGNORECASE,
            )

            if before_search:
                spoken_query = before_search.group("query")
                # Drop navigation instructions and search-bar references from
                # the query, retaining only what the user wants searched.
                if re.search(r"\b(?:wahan|udhar|there)\b", spoken_query, re.IGNORECASE):
                    spoken_query = re.split(
                        r"\b(?:wahan|udhar|there)\b",
                        spoken_query,
                        flags=re.IGNORECASE,
                    )[-1]
                if re.search(r"\bsearch\s+bar\b", spoken_query, re.IGNORECASE):
                    spoken_query = re.split(
                        r"\bsearch\s+bar\b",
                        spoken_query,
                        flags=re.IGNORECASE,
                    )[-1]
                    spoken_query = re.sub(
                        r"^\s*(?:(?:hai|mein|me|par|pe|ke\s+andar)\b[\s,]*)+",
                        "",
                        spoken_query,
                        flags=re.IGNORECASE,
                    )
                spoken_query = re.sub(
                    r"^(?:(?:ja\s+kar|jakar|jaakar|jaake|ja\s+ke|jao|jaa\s+kar)\s+|"
                    r"(?:khud|zara|please|aur|and)\s+)+",
                    "",
                    spoken_query,
                    flags=re.IGNORECASE,
                )
            elif after_search:
                spoken_query = after_search.group("query")
            elif written_query:
                spoken_query = written_query.group("query")

            if spoken_query:
                spoken_query = re.sub(r"\s+", " ", spoken_query).strip(" \t\r\n.,!?;:\u0964\u0965")
                spoken_query = re.sub(
                    r"^(?:(?:par|pe|mein|me|wahan|udhar|there|na)\s+)+",
                    "",
                    spoken_query,
                    flags=re.IGNORECASE,
                ).strip(" \t\r\n.,!?;:\u0964\u0965")
                spoken_query = re.sub(r"\s+(?:na|please)$", "", spoken_query, flags=re.IGNORECASE).strip()
                filler_query = bool(re.fullmatch(
                    r"(?:kuch|kucch|something|anything|whatever|search|search karo)",
                    spoken_query,
                    flags=re.IGNORECASE,
                ))
                if spoken_query and not filler_query and len(spoken_query) <= 500:
                    if spoken_site == "google":
                        return result("start", "search_web", target=spoken_query)
                    if spoken_site == "wikipedia":
                        return result(
                            "start",
                            "open_url",
                            target="https://en.wikipedia.org/w/index.php?search=" + quote_plus(spoken_query, safe=""),
                        )
                    if spoken_site == "youtube":
                        return result(
                            "start",
                            "open_url",
                            target="https://www.youtube.com/results?search_query=" + quote_plus(spoken_query, safe=""),
                        )

        # Route explicit searches on known sites without relying on the LLM intent
        # classifier. A fixed host plus URL-encoded query avoids arbitrary URL execution.
        site_search_matches = (
            re.search(
                r"\bsearch\s+(?:for\s+)?(?P<query>.+?)\s+(?:on|in|using)\s+(?P<site>google|wikipedia|youtube)\b",
                original, flags=re.IGNORECASE,
            ),
            re.search(
                r"\bsearch\s+(?P<site>google|wikipedia|youtube)\s+(?:for\s+)?(?P<query>.+)$",
                original, flags=re.IGNORECASE,
            ),
            re.search(
                r"\bsearch\s+(?:on|in|using)\s+(?P<site>google|wikipedia|youtube)\s+(?:for\s+)?(?P<query>.+)$",
                original, flags=re.IGNORECASE,
            ),
            re.search(
                r"\b(?P<query>.+?)\s+(?:ko\s+)?(?P<site>google|wikipedia|youtube)\s+(?:par|pe)\s+search\s+(?:karo|karna|kar\s+(?:do|lo))$",
                original, flags=re.IGNORECASE,
            ),
            re.search(
                r"\b(?P<site>google|wikipedia|youtube)\s+search\s+(?:for\s+)?(?P<query>.+)$",
                original, flags=re.IGNORECASE,
            ),
            re.search(
                r"\b(?P<site>google|wikipedia|youtube)\s+(?:par|pe)\b.*\bsearch\b.*?\b(?:karo|karna(?:\s+hai)?|kar\s+(?:do|lo))\s+(?P<query>.+)$",
                original, flags=re.IGNORECASE,
            ),
            re.search(
                r"\b(?P<site>google|wikipedia|youtube)\s+(?:par|pe)\s+(?P<query>.+?)\s+search\s+(?:karo|karna|kar\s+(?:do|lo))$",
                original, flags=re.IGNORECASE,
            ),
        )
        site_search_match = next((match for match in site_search_matches if match), None)
        if site_search_match:
            site = site_search_match.group("site").casefold()
            query = site_search_match.group("query").strip(" \t\r\n.,!?;:")
            query = re.sub(r"\s+", " ", query).strip()
            placeholder_queries = {"kuch", "kucch", "something", "anything", "whatever", "anything else"}
            query_is_filler = bool(re.fullmatch(
                r"(?:mein\s+)?(?:kuch|kucch|something|anything|whatever)(?:\s+(?:search|search\s+(?:karo|karna|kar\s+(?:do|lo))))?",
                query, flags=re.IGNORECASE,
            ))
            if query and len(query) <= 500 and query.casefold() not in placeholder_queries and not query_is_filler:
                if site == "google":
                    return result("start", "search_web", target=query)
                if site == "wikipedia":
                    return result(
                        "start",
                        "open_url",
                        target="https://en.wikipedia.org/w/index.php?search=" + quote_plus(query, safe=""),
                    )
                if site == "youtube":
                    return result(
                        "start",
                        "open_url",
                        target="https://www.youtube.com/results?search_query=" + quote_plus(query, safe=""),
                    )
        # A request to open a Google tab and search, without a query yet,
        # still has one safe immediate action: open Google. The next voice
        # turn can supply the query instead of treating the whole request as chat.
        google_tab_search_match = re.fullmatch(
            r"(?:(?:ek|a|one)\s+)?(?:new\s+)?tab\s+open\s+"
            r"(?:karna|karo|kar\s+(?:do|lo))\s+google(?:\s+tab)?[,]?\s*"
            r"(?:wahan(?:\s+pe)?\s+)?search\s+(?:karo|karna|kar\s+(?:do|lo))",
            normalized,
            flags=re.IGNORECASE,
        )
        if google_tab_search_match:
            return result("start", "open_url", target="https://www.google.com")

        # "Microsoft Store" is an installed Windows app, not the Microsoft website.
        # Resolve it before the generic "microsoft" website alias below.
        microsoft_store_match = re.fullmatch(
            r"(?:please\s+)?(?:open|launch|start)\s+(?:the\s+)?"
            r"(?:microsoft\s+store|windows\s+store)(?:\s+(?:app|application))?",
            normalized,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"(?:microsoft\s+store|windows\s+store)\s+"
            r"(?:kholo|open\s+karo|open\s+karna|open\s+kar\s+(?:do|lo)|"
            r"\u0916\u094b\u0932\u094b|\u0913\u092a\u0928\s+\u0915\u0930\u094b)",
            normalized,
            flags=re.IGNORECASE,
        )
        if microsoft_store_match:
            return result("start", "open_app", target="microsoft store")

        app_match = re.fullmatch(
            r"(?:please\s+)?(?:open|launch|start)\s+(?:the\s+)?"
            r"(calculator|calc|notepad|text editor|file explorer|explorer|"
            r"chrome|google chrome|edge|microsoft edge|firefox|browser|web browser|"
            r"outlook|microsoft outlook|word|microsoft word|excel|microsoft excel|"
            r"powerpoint|microsoft powerpoint)"
            r"(?:\s+(?:app|application))?",
            normalized,
        )
        if app_match:
            app = app_match.group(1)
            if app in {"browser", "web browser"}:
                return result("start", "open_url", target="https://www.google.com")
            return result("start", "open_app", target=app)

        roman_urdu_app_match = re.fullmatch(
            r"(calculator|calc|notepad|file explorer|chrome|edge|firefox|browser|"
            r"outlook|word|excel|powerpoint)\s+"
            r"(?:kholo|open karo|open kar lo|open kar do|open karna|chalao|\u0913\u092a\u0928\s+\u0915\u0930\u094b|\u0913\u092a\u0928\s+\u0915\u0930\u0928\u093e|\u0916\u094b\u0932\u094b|\u0916\u094b\u0932\s+\u0926\u094b)",
            normalized,
        )
        if roman_urdu_app_match:
            app = roman_urdu_app_match.group(1)
            if app == "browser":
                return result("start", "open_url", target="https://www.google.com")
            return result("start", "open_app", target=app)

        drive_root_match = re.fullmatch(
            r"(?:please\s+)?(?:open|show|browse|go to|navigate to)\s+(?:the\s+)?(?:local\s+(?:disk|drive)\s+c|disk\s+c|c\s+drive|drive\s+c|c:)",
            normalized,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"(?:local\s+(?:disk|drive)\s+c|disk\s+c|c\s+drive|drive\s+c)\s+(?:kholo|open\s+karo|open\s+karna|open\s+kar\s+(?:do|lo))",
            normalized,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"\u0932\u094b\u0915\u0932\s+\u0921\u093f\u0938\u094d\u0915\s+\u0938\u0940\s+(?:\u0913\u092a\u0928\s+(?:\u0915\u0930\u0928\u093e|\u0915\u0930\u094b|\u0915\u0930\s+\u0926\u094b)|\u0916\u094b\u0932\u094b|\u0916\u094b\u0932\s+\u0926\u094b)",
            normalized,
            flags=re.IGNORECASE,
        )
        if drive_root_match:
            return result("start", "open_folder", target="local disk c")

        this_pc_match = re.fullmatch(
            r"(?:please\s+)?(?:open|show|browse|go\s+to|navigate\s+to)\s+(?:the\s+)?(?:this\s+pc|my\s+computer|computer)[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"(?:this\s+pc|my\s+computer|computer)\s+(?:kholo|khol\s+do|open\s+karo|open\s+karna|open\s+kar\s+(?:do|lo))[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        )
        if this_pc_match:
            return result("start", "open_folder", target="this pc")

        folder_match = re.fullmatch(
            r"(?:please\s+)?(?:open|show)\s+(?:my\s+)?"
            r"(desktop|documents|downloads|pictures|music|videos)(?:\s+folder)?",
            normalized,
        ) or re.fullmatch(
            r"(desktop|documents|downloads|pictures|music|videos)\s+kholo",
            normalized,
        )
        if folder_match:
            folder = folder_match.group(1)
            return result("start", "open_folder", target=folder)

        url_match = re.fullmatch(
            r"(?:please\s+)?(?:open|visit|go to|navigate to)\s+"
            r"(https?://[^\s<>\"']+)",
            original,
            flags=re.IGNORECASE,
        )
        if url_match:
            url = url_match.group(1).rstrip(".,!?;:)")
            return result("start", "open_url", target=url)

        # Resolve common spoken website names deterministically instead of
        # letting the chat model answer as though it cannot open a browser.
        # Keep this list explicit so arbitrary phrases never become URLs.
        named_site_match = re.fullmatch(
            r"(?:please\s+)?(?:open|visit|go to|navigate to)\s+(?:the\s+)?"
            r"(wikipedia|wikimedia(?:\s*[.,]?\s*wikipedia)?|google|youtube|gmail|"
            r"github|stackoverflow|reddit|bing|duckduckgo|microsoft|outlook|"
            r"facebook|x|twitter|linkedin|chatgpt)"
            r"(?:\s+(?:website|site|homepage))?",
            normalized,
            flags=re.IGNORECASE,
        )
        if named_site_match:
            site_name = re.sub(
                r"[\s.,]+", " ", named_site_match.group(1).lower()
            ).strip()
            site_urls = {
                "wikipedia": "https://www.wikipedia.org",
                "wikimedia wikipedia": "https://www.wikipedia.org",
                "wikimedia": "https://www.wikimedia.org",
                "google": "https://www.google.com",
                "youtube": "https://www.youtube.com",
                "gmail": "https://mail.google.com",
                "github": "https://github.com",
                "stackoverflow": "https://stackoverflow.com",
                "reddit": "https://www.reddit.com",
                "bing": "https://www.bing.com",
                "duckduckgo": "https://duckduckgo.com",
                "microsoft": "https://www.microsoft.com",
                "outlook": "https://outlook.live.com",
                "facebook": "https://www.facebook.com",
                "x": "https://x.com",
                "twitter": "https://x.com",
                "linkedin": "https://www.linkedin.com",
                "chatgpt": "https://chatgpt.com",
            }
            target_url = site_urls.get(site_name)
            if target_url:
                return result("start", "open_url", target=target_url)

        # Handle common Roman Urdu word order such as "Wikipedia open karo".
        # Resolve only known, allowlisted websites; never synthesize arbitrary URLs.
        reverse_site_match = re.fullmatch(
            r"(wikipedia|wikimedia(?:\s*[.,]?\s*wikipedia)?|google|youtube|gmail|"
            r"github|stackoverflow|reddit|bing|duckduckgo|microsoft|outlook|"
            r"facebook|x|twitter|linkedin|chatgpt)\s+(?:kholo|open\s+karo|open\s+kar\s+(?:lo|do|na)|open\s+karna|\u0913\u092a\u0928\s+(?:\u0915\u0930\u0928\u093e|\u0915\u0930\u094b|\u0915\u0930\s+(?:\u0932\u094b|\u0926\u094b))|\u0916\u094b\u0932\u094b|\u0916\u094b\u0932\s+\u0926\u094b|visit\s+karo|website\s+kholo|website\s+khol\s+do)",
            normalized,
            flags=re.IGNORECASE,
        )
        if reverse_site_match:
            site_name = re.sub(r"[\s.,]+", " ", reverse_site_match.group(1).lower()).strip()
            reverse_site_urls = {
                "wikipedia": "https://www.wikipedia.org",
                "wikimedia wikipedia": "https://www.wikipedia.org",
                "wikimedia": "https://www.wikimedia.org",
                "google": "https://www.google.com",
                "youtube": "https://www.youtube.com",
                "gmail": "https://mail.google.com",
                "github": "https://github.com",
                "stackoverflow": "https://stackoverflow.com",
                "reddit": "https://www.reddit.com",
                "bing": "https://www.bing.com",
                "duckduckgo": "https://duckduckgo.com",
                "microsoft": "https://www.microsoft.com",
                "outlook": "https://outlook.live.com",
                "facebook": "https://www.facebook.com",
                "x": "https://x.com",
                "twitter": "https://x.com",
                "linkedin": "https://www.linkedin.com",
                "chatgpt": "https://chatgpt.com",
            }
            target_url = reverse_site_urls.get(site_name)
            if target_url:
                return result("start", "open_url", target=target_url)

        web_search_match = re.fullmatch(
            r"(?:please\s+)?(?:google search for|search on google for)\s+(.+)",
            original,
            flags=re.IGNORECASE,
        )
        if web_search_match:
            query = web_search_match.group(1).strip(" .!?")
            if query:
                return result("start", "search_web", target=query)

        # File discovery requests about CVs/resumes should search local filenames,
        # not fall through to chat. The desktop service expands "cv" into common aliases.
        downloads_listing_match = re.fullmatch(
            r"(?:please\s+)?(?:show|list|display|check|view|get|fetch)\s+"
            r"(?:(?:me|my|all|the)\s+)*(?:my\s+)?(?:downloaded\s+files?|downloads)(?:\s+files?)?[.!?]*",
            original,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"(?:(?:meri|mere|my|the)\s+)?(?:downloaded\s+files?|downloads)\s+"
            r"(?:dikhao|dikh(?:a|ao|ana)?|list(?:\s+kar(?:o|na|do))?|show(?:\s+me)?|batao|check\s+karo)[.!?]*",
            original,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"(?:what\s+(?:have|did)\s+i\s+download(?:ed)?|show\s+what\s+i\s+downloaded)[.!?]*",
            original,
            flags=re.IGNORECASE,
        )
        if downloads_listing_match:
            return result("search", "list_files", query="downloads")

        cv_search_match = re.fullmatch(
            r"(?:please\s+)?(?:find(?:\s+and\s+list)?|list|show|search(?:\s+for)?|locate|check)\s+"
            r"(?:(?:me|my|all|the)\s+)*(?:cvs?|resumes?|curriculum\s+vitae)"
            r"(?:\s+files?)?(?:\s+(?:on|in)\s+(?:my\s+)?(?:device|computer|pc|laptop|folders?|documents?))?[.!?]*",
            original,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"(?:acha\s+|achha\s+)?(?:meri|my)\s+(?:cvs?|resumes?|curriculum\s+vitae)"
            r"(?:\s+files?)?.{0,80}\b(?:dekho|dikh(?:a|ao|ana)?|find|list|show|locate|search|check|batao)\b.*",
            original,
            flags=re.IGNORECASE,
        )
        if cv_search_match:
            return result("search", "find_files", query="cv")

        file_search_match = re.fullmatch(
            r"(?:please\s+)?(?:find|locate)\s+(?:the )?(?:file|document)\s+"
            r"(?:(?:named|called)\s+)?(.+)",
            original,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"(?:please\s+)?search\s+(?:my )?(?:files|documents)\s+for\s+(.+)",
            original,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"file\s+dhoondo\s+(.+)",
            original,
            flags=re.IGNORECASE,
        )
        if file_search_match:
            query = file_search_match.group(1).strip(" .!?")
            if query:
                return result("search", "find_files", query=query)

        # Support reverse-order voice phrasing such as "World open karna file".
        # Recycle Bin is a Windows shell namespace, not a normal disk folder.
        recycle_bin_match = re.fullmatch(
            r"(?:please\s+)?(?:open|show|browse|go\s+to|navigate\s+to)\s+(?:the\s+)?(?:recycle|cycle)\s+bin[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"(?:recycle|cycle)\s+bin\s+(?:kholo|khol\s+do|open\s+(?:karo|karna|kar\s+(?:do|lo)))[.!?]*",
            normalized,
            flags=re.IGNORECASE,
        )
        if recycle_bin_match:
            return result("start", "open_folder", target="recycle bin")

        reverse_order_open_file_match = re.fullmatch(
            r"(?P<target>[a-z0-9][a-z0-9 _().+-]{0,120}?)\s+"
            r"open\s+(?:karna|karo|kar\s+(?:do|lo))\s+(?:the\s+)?file",
            normalized,
            flags=re.IGNORECASE,
        )
        if reverse_order_open_file_match:
            target = reverse_order_open_file_match.group("target").strip(" .!?")
            if target:
                return result("start", "open_file", target=target)

        open_file_match = re.fullmatch(
            r"(?:please\s+)?open\s+(?:the )?(?:file|document)\s+"
            r"(?:(?:named|called)\s+)?(.+)",
            original,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"file\s+kholo\s+(.+)",
            original,
            flags=re.IGNORECASE,
        )
        if open_file_match:
            target = open_file_match.group(1).strip(" .!?")
            if target:
                return result("start", "open_file", target=target)

        # Common natural phrasing: "open proposal.pdf". Only a bare
        # filename is accepted by DesktopControlService, never an arbitrary path.
        bare_file_match = re.fullmatch(
            r"(?:please\s+)?open\s+(.+\.(?:pdf|docx?|rtf|txt|md|csv|xlsx?|pptx?|"
            r"png|jpe?g|gif|webp|bmp|mp3|wav|m4a|mp4|mov|avi|mkv))",
            original,
            flags=re.IGNORECASE,
        )
        if bare_file_match:
            target = bare_file_match.group(1).strip()
            if target:
                return result("start", "open_file", target=target)

        # Spoken order is often "Spotify kholo" or "VS Code open karna".
        reverse_generic_app_match = re.fullmatch(
            r"(?P<target>[a-z0-9][a-z0-9 ._()+#-]{0,79}?)\s+"
            r"(?:kholo|chalao|open\s+(?:karo|karna|kar\s+(?:do|lo)))",
            normalized,
            flags=re.IGNORECASE,
        )
        if reverse_generic_app_match:
            reverse_target = " ".join(reverse_generic_app_match.group("target").split()).strip(" .")
            if reverse_target.casefold() not in {
                "file", "folder", "document", "documents", "website", "site",
                "page", "tab", "window", "message", "messages", "email", "mail",
                "search", "movie", "song", "music", "video", "it", "this", "that",
                "local disk c", "disk c", "c drive", "drive c",
            }:
                return result("start", "open_app", target=reverse_target)

        # For other installed Windows applications, pass only a plain app name
        # to DesktopControlService, which resolves an exact Start Menu shortcut.
        # No arbitrary command line, path, or script is interpreted here.
        generic_app_match = re.fullmatch(
            r"(?:please\s+)?(?:open|launch|start)\s+(?:the\s+)?"
            r"(?P<target>[a-z0-9][a-z0-9 ._()+#-]{0,79}?)"
            r"(?:\s+(?:app|application|program))?",
            normalized,
            flags=re.IGNORECASE,
        )
        if generic_app_match:
            target = " ".join(generic_app_match.group("target").split()).strip(" .")
            target = re.sub(r"^(?:a|an|my)\s+", "", target, flags=re.IGNORECASE)
            if target.casefold() not in {
                "task", "tasks", "reminder", "reminders", "meeting", "meetings",
                "email", "mail", "message", "messages", "calendar", "event", "events",
                "timer", "alarm", "file", "folder", "document", "documents",
                "pdf", "website", "site", "url", "link", "tab", "window", "page",
                "web", "internet", "day", "my day",
            } and target:
                return result("start", "open_app", target=target)

        return None

    @staticmethod
    def _extract_explicit_task_title(message: str) -> str | None:
        """Extract a title only when the user explicitly labels it as a task title."""

        title_patterns = (
            r"(?:\btitle\b|\u091f\u093e\u0907\u091f\u0932)\s*(?:is|hai|\u0939\u0948|[:=])\s*[\"']([^\"']{1,300})[\"']",
            r"(?:\btitle\b|\u091f\u093e\u0907\u091f\u0932)\s*(?:is|hai|\u0939\u0948|[:=])\s*(.+?)(?=\s*[,;.!?]|$)",
        )
        for pattern in title_patterns:
            match = re.search(pattern, str(message or ""), flags=re.IGNORECASE)
            if not match:
                continue
            title = match.group(1).strip().strip(" \t\r\n\"'")
            title = re.sub(
                r"\s+(?:okay|ok|\u0913\u0915\u0947)$",
                "",
                title,
                flags=re.IGNORECASE,
            ).strip()
            title = title.rstrip(" .!?;:")
            if title and len(title) <= 300:
                return title
        return None

    def _deterministic_fallback(
        self,
        *,
        message: str,
        history: list[dict],
    ) -> dict:
        """
        Safely classify obvious requests when the LLM provider is unavailable.

        This path is deliberately narrow: clear task/reminder/calendar/web
        requests are recovered without guessing at arbitrary user intent.
        Unknown requests remain non-executable.
        """

        result = self._default_result()
        structured_message = str(message).strip()
        original_message = " ".join(
            str(message).strip().replace("’", "'").replace("‘", "'").replace("“", '"' ).replace("”", '"' ).split()
        )
        normalized = original_message.lower()

        # Calendar event creation is a state-changing action. Do not leave a
        # clear request to probabilistic intent classification, which previously
        # returned intent=chat and let realtime voice narrate a fake success.
        calendar_write_negated = re.search(
            r"\b(?:create|add|make|schedule|book|edit|update|delete)\b"
            r"(?:\s+(?:or|and|ya|aur)\s+(?:create|add|make|schedule|book|edit|update|delete)\b)?"
            r".{0,40}\b(?:mat|nahi|nahin)\s+(?:kar\w*|do|karo|karna)\b",
            normalized,
        )
        calendar_write_requested = (
            re.search(r"\b(?:calendar|event|meeting|appointment)\b", normalized)
            and not calendar_write_negated
            and re.search(
                r"\b(?:create|add|make|schedule|book)\b|"
                r"\b(?:create|add)\s+(?:kar|karo|karna|kar\s+do)\b",
                normalized,
            )
        )
        if calendar_write_requested:
            result["intent"] = "calendar"
            result["calendar_action"] = "create"
            result["calendar_id"] = "primary"
            result["requires_tool"] = False
            result["clarification_required"] = True

            title_match = re.search(
                r"\b(?:exact\s+title|called|named|titled)\s+(?P<title>.+)$",
                original_message,
                flags=re.IGNORECASE,
            )
            title = title_match.group("title").strip() if title_match else ""
            if title and title[0] in {"'", '"', "“", "‘"}:
                closing = {"'": "'", '"': '"', "“": "”", "‘": "’"}[title[0]]
                end_quote = title.find(closing, 1)
                if end_quote > 1:
                    title = title[1:end_quote]
            title = title.strip().rstrip(" .,!?:;")

            now = datetime.now(ZoneInfo(USER_TIMEZONE))
            event_date = None
            explicit_date = re.search(
                r"\b(?P<month>January|February|March|April|May|June|July|August|"
                r"September|October|November|December)\s+(?P<day>\d{1,2}),?\s*(?P<year>\d{4})?\b",
                original_message,
                flags=re.IGNORECASE,
            )
            if explicit_date:
                try:
                    month = datetime.strptime(explicit_date.group("month"), "%B").month
                    year = int(explicit_date.group("year") or now.year)
                    event_date = date(year, month, int(explicit_date.group("day")))
                except ValueError:
                    event_date = None
            if event_date is None:
                day_first_date = re.search(
                    r"\b(?P<day>\d{1,2})\s+(?P<month>January|February|March|April|May|June|July|August|"
                    r"September|October|November|December)\s+(?P<year>\d{4})\b",
                    original_message,
                    flags=re.IGNORECASE,
                )
                if day_first_date:
                    try:
                        month = datetime.strptime(day_first_date.group("month"), "%B").month
                        event_date = date(
                            int(day_first_date.group("year")),
                            month,
                            int(day_first_date.group("day")),
                        )
                    except ValueError:
                        event_date = None
            if event_date is None:
                weekday_match = re.search(
                    r"\b(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
                    original_message,
                    flags=re.IGNORECASE,
                )
                if weekday_match:
                    weekdays = {
                        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                        "friday": 4, "saturday": 5, "sunday": 6,
                    }
                    target_weekday = weekdays[weekday_match.group("weekday").lower()]
                    event_date = now.date() + timedelta(days=(target_weekday - now.weekday()) % 7)
            if event_date is None and re.search(r"\btomorrow\b|\bkal\b", normalized):
                event_date = now.date() + timedelta(days=1)
            if event_date is None and re.search(r"\btoday\b|\baaj\b", normalized):
                event_date = now.date()

            clock_pattern = (
                r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*"
                r"(?P<ampm>a\.?m\.?|p\.?m\.?)(?!\w)"
            )
            clocks = list(re.finditer(clock_pattern, original_message, flags=re.IGNORECASE))
            parsed_clocks = []
            for clock in clocks[:2]:
                hour = int(clock.group("hour"))
                minute = int(clock.group("minute") or 0)
                meridiem = clock.group("ampm").lower().replace(".", "")
                if not (1 <= hour <= 12 and 0 <= minute <= 59):
                    parsed_clocks = []
                    break
                hour = (0 if hour == 12 else hour) if meridiem == "am" else (12 if hour == 12 else hour + 12)
                parsed_clocks.append((hour, minute))

            if title and event_date is not None and parsed_clocks:
                start_hour, start_minute = parsed_clocks[0]
                start_at = datetime(
                    event_date.year, event_date.month, event_date.day,
                    start_hour, start_minute, tzinfo=ZoneInfo(USER_TIMEZONE),
                )
                if len(parsed_clocks) > 1:
                    end_hour, end_minute = parsed_clocks[1]
                    end_at = datetime(
                        event_date.year, event_date.month, event_date.day,
                        end_hour, end_minute, tzinfo=ZoneInfo(USER_TIMEZONE),
                    )
                    if end_at <= start_at:
                        end_at += timedelta(days=1)
                else:
                    end_at = start_at + timedelta(hours=1)
                if end_at > start_at:
                    result.update({
                        "intent": "calendar",
                        "calendar_action": "create",
                        "calendar_id": "primary",
                        "event": {
                            "summary": title,
                            "start": {"dateTime": start_at.isoformat()},
                            "end": {"dateTime": end_at.isoformat()},
                        },
                        "requires_tool": True,
                        "clarification_required": False,
                    })
            return result

        desktop_command = self._deterministic_desktop_fallback(
            original_message
        )
        if desktop_command is None and history:
            # Resolve common follow-ups such as "you go there and search
            # movies" against the most recent explicit website command.
            # This is intentionally limited to the allowlisted websites and
            # a clear search verb plus a non-empty search query.
            relative_message = original_message
            devanagari_aliases = (
                ("जाकर", "ja kar"),
                ("जा कर", "ja kar"),
                ("तुम", "tum"),
                ("खुद", "khud"),
                ("वहाँ", "wahan"),
                ("वहां", "wahan"),
                ("पर", "par"),
                ("सर्च", "search"),
                ("करना", "karna"),
                ("करो", "karo"),
                ("कर दो", "kar do"),
                ("ना", "na"),
                ("मूवीज", "movies"),
                ("मूवी", "movie"),
            )
            for source, replacement in devanagari_aliases:
                relative_message = relative_message.replace(source, replacement)

            relative_search = re.search(
                r"\b(?:wahan|udhar|there)\b.*?\bsearch\s+"
                r"(?:karo|karna|kar\s+(?:do|lo))(?:\s+na)?\s+"
                r"(?P<query>.+)$",
                relative_message,
                flags=re.IGNORECASE,
            )
            if relative_search:
                relative_query = relative_search.group("query").strip(" .,!?:;\u0964\u0965")
                site_context = None
                for history_item in reversed(history[-10:]):
                    if str(history_item.get("role", "")).casefold() != "user":
                        continue
                    previous_message = str(history_item.get("content") or "")
                    site_match = re.search(
                        r"\b(?P<site>google|wikipedia|youtube)\b",
                        previous_message,
                        flags=re.IGNORECASE,
                    )
                    if site_match and re.search(
                        r"\b(?:search|search bar|open|kholo|go to|ja kar|jakar)\b",
                        previous_message,
                        flags=re.IGNORECASE,
                    ):
                        site_context = site_match.group("site").casefold()
                        break

                if site_context and relative_query and len(relative_query) <= 500:
                    desktop_command = self._deterministic_desktop_fallback(
                        f"{site_context} par search karo {relative_query}"
                    )

        if desktop_command is not None:
            result.update(desktop_command)
            return result

        task_list_request = re.search(
            r"\b(?:show|list|check|view|get|fetch)\s+(?:(?:me|my|the)\s+)*(?:all\s+|current\s+|open\s+|pending\s+)?tasks?\b"
            r"|\b(?:what|which)\s+tasks?\b"
            r"|\b(?:tasks?|task)\b.{0,60}\b(?:nazar aa r(?:aha|ha)|dekho|dekh|dikha|show|list|check|visible)\b"
            r"|\b(?:ab|acha|achha)\s+(?:dekho|check karo|check kar)\b.{0,60}\btask\b"
            r"|\u091f\u093e\u0938\u094d\u0915.{0,60}(?:\u0926\u0947\u0916|\u0928\u091c\u0930|\u0926\u093f\u0916\u093e)",
            original_message,
            flags=re.IGNORECASE,
        )
        if task_list_request:
            result.update(
                {
                    "intent": "task",
                    "task": None,
                    "task_reference": None,
                    "task_action": "list",
                    "requires_tool": True,
                    "clarification_required": False,
                }
            )
            return result

        explicit_task_title = self._extract_explicit_task_title(original_message)
        explicit_task_create = re.search(
            r"\b(?:create|add|make)\s+(?:a\s+|the\s+)?(?:task|it|this|that)\b"
            r"|\b(?:isko|is\s+ko|ise|isey|yeh|ye)\s+(?:create|add|make)\b"
            r"|\u0907\u0938\u0915\u094b\s+\u0915\u094d\u0930\u093f\u090f\u091f"
            r"|\u0915\u094d\u0930\u093f\u090f\u091f\s+\u0915\u0930\s+\u0926\u094b",
            original_message,
            flags=re.IGNORECASE,
        ) is not None
        negated_task_create = re.search(
            r"\b(?:don't|do not|never|not)\b.{0,40}\b(?:create|add|make)\b"
            r"|\bhow\s+(?:do\s+i|to)\s+create\b",
            normalized,
            flags=re.IGNORECASE,
        ) is not None
        if explicit_task_title and explicit_task_create and not negated_task_create:
            result.update(
                {
                    "intent": "task",
                    "task": explicit_task_title,
                    "task_reference": None,
                    "task_action": "create",
                    "priority": None,
                    "requires_tool": True,
                    "clarification_required": False,
                }
            )
            return result

        if self._is_indirect_reference_message(message) and history:
            if any(
                phrase in normalized
                for phrase in (
                    "reminder",
                    "remind",
                )
            ):
                result["intent"] = "reminder"
            elif any(
                phrase in normalized
                for phrase in (
                    "task",
                    "it",
                    "that",
                    "this",
                )
            ):
                result["intent"] = "task"

        send_reference_message = normalized.rstrip(" .!?")
        if re.fullmatch(
            r"send\s+(?:that|this|it)\s+to\s+(?:him|her|them)",
            send_reference_message,
        ):
            result["intent"] = "action"
            result["action"] = "send"
            result["clarification_required"] = True
            result["requires_tool"] = False
            return result

        email_search_match = re.match(
            r"^(?:please\s+)?(?:search|find|look\s+for)\s+"
            r"(?:(?:my|the)\s+)?(?:emails?|e-mails?|mail|inbox)\s+"
            r"(?:for|about)\s+(.+)$",
            original_message,
            flags=re.IGNORECASE,
        )
        if email_search_match:
            search_query = email_search_match.group(1).strip(" .!?")
            if search_query:
                result["intent"] = "email"
                result["email_action"] = "search"
                result["query"] = search_query
                result["max_results"] = 5
                result["requires_tool"] = True
                return result

        # The recognizer may return Devanagari for an otherwise mixed-script
        # email request. Normalize only a small allowlist of email-query words;
        # never rewrite message contents, subjects, or outbound email bodies.
        email_routing_text = normalized
        if re.search(
            r"\b(?:email|e-mail|mail|inbox|message)\b|"
            r"\u0908\u092e\u0947\u0932|\u092e\u0947\u0932",
            email_routing_text,
            flags=re.IGNORECASE,
        ):
            for source, replacement in (
                ("\u0915\u094d\u092f\u093e", "kya"),
                ("\u0915\u094b\u0908", "koi"),
                ("\u091c\u0930\u0942\u0930\u0940", "zaroori"),
                ("\u091c\u093c\u0930\u0942\u0930\u0940", "zaroori"),
                ("\u092e\u0939\u0924\u094d\u0935\u092a\u0942\u0930\u094d\u0923", "important"),
                ("\u0905\u0939\u092e", "important"),
                ("\u0908\u092e\u0947\u0932", "email"),
                ("\u092e\u0947\u0932", "mail"),
                ("\u0906\u091c", "aaj"),
                ("\u0905\u092d\u0940", "abhi"),
                ("\u0906\u0908", "aayi"),
                ("\u0906\u092f\u0940", "aayi"),
                ("\u0906\u092f\u093e", "aaya"),
                ("\u092e\u093f\u0932\u0940", "mili"),
                ("\u092e\u093f\u0932\u093e", "mila"),
                ("\u0939\u0948", "hai"),
                ("\u0939\u0948\u0902", "hain"),
                ("\u0928\u0908", "new"),
                ("\u0928\u090f", "new"),
                ("\u0905\u092f\u093e", "aya"),
            ):
                email_routing_text = email_routing_text.replace(source, replacement)

        email_list_patterns = (
            # Natural Roman-Urdu often puts the verb last ("Meri emails dikhao").
            # Keep this alias limited to email/inbox words; generic "messages" may
            # refer to WhatsApp, SMS, or another provider and must not imply Gmail.
            r"^(?:(?:please|zara)\s+)?(?:(?:meri|mere|my|the)\s+)*(?:emails?|e-mails?|mail|inbox)\s+"
            r"(?:dikhao|dikhaiye|show|list|check(?:\s+karo)?|dekh(?:\s+lo|o)?|batao)[.!?]*$",
            r"^(?:please\s+)?(?:show|list|check|read|summari[sz]e|fetch|get|open)\s+"
            r"(?:(?:me|my|the)\s+)*(?:(?:latest|recent|new|unread|important|urgent|priority|"
            r"zaroori|zaruri|all|last(?:\s+\d+)?|top(?:\s+\d+)?)\s+)*"
            r"(?:emails?|e-mails?|inbox|messages?)\b.*$",
            r"^(?:what(?:'s|\s+is)\s+in\s+my\s+inbox|any\s+new\s+emails?|"
            r"do\s+i\s+have\s+(?:any\s+)?(?:new\s+)?emails?|"
            r"what\s+emails\s+did\s+i\s+get)\??$",
            r"^(?:(?:today|aaj|abhi)\s+)?"
            r"(?:(?:(?:please\s+)?(?:check|tell\s+me|let\s+me\s+know)\s+(?:if|whether)\s+)?"
            r"(?:(?:kya\s+)?(?:koi|any|did\s+i\s+(?:get|receive)|have\s+i\s+(?:got|received)|"
            r"do\s+i\s+have|is\s+there|are\s+there)\s+)?)"
            r"(?:(?:any|new|latest|recent|important|urgent|priority|zaroori|zaruri|unread)\s+)*"
            r"(?:emails?|e-mails?|mail|inbox)\b.*$",
        )
        if any(
            re.search(pattern, email_routing_text, flags=re.IGNORECASE)
            for pattern in email_list_patterns
        ):
            result["intent"] = "email"
            result["email_action"] = "list"
            result["include_body"] = bool(
                re.search(
                    r"\b(?:read|summar(?:y|ies|ize|ise))\b",
                    email_routing_text,
                    flags=re.IGNORECASE,
                )
            )
            unread_requested = bool(re.search(r"\bunread\b", email_routing_text))
            important_requested = bool(
                re.search(r"\b(?:important|urgent|priority|zaroori|zaruri)\b", email_routing_text)
            )
            recent_requested = bool(
                re.search(
                    r"\b(?:today|aaj|abhi|just\s+now|arriv\w*|received|came\s+in|come\s+in|"
                    r"aayi|aaya|ayi|aya|mili|mila|did\s+i\s+get|did\s+i\s+receive|have\s+i\s+received)\b",
                    email_routing_text,
                    flags=re.IGNORECASE,
                )
            )
            if re.search(r"\bsent\s+(?:emails?|mail)\b", email_routing_text):
                result["query"] = "in:sent"
            else:
                query_parts = ["in:inbox"]
                if unread_requested:
                    query_parts.append("is:unread")
                if recent_requested:
                    # Query recent mail, not only Gmail's own importance label:
                    # NOVA can inspect bounded sender/subject/snippet metadata to
                    # spot urgent-looking mail that Gmail did not mark important.
                    query_parts.append("newer_than:1d")
                elif important_requested:
                    query_parts.append("is:important")
                if unread_requested or recent_requested or important_requested:
                    result["query"] = " ".join(query_parts)
            result["max_results"] = 10 if (important_requested and recent_requested) else 5
            result["requires_tool"] = True
            return result

        # Realtime voice models commonly compose a complete email request from
        # several spoken turns into one sentence. Route that explicit structure
        # deterministically so the LLM cannot downgrade the send action to chat.
        composed_email_match = re.match(
            r"^(?:please\s+)?send\s+(?:(?:a|an|the)\s+)?"
            r"(?:[\w-]+\s+){0,2}emails?\s+to\s+"
            r"(?P<recipient>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
            r"\s+(?:with\s+)?(?:the\s+)?subject\s*[:=]?\s*"
            r"(?P<subject>.+?)\s+(?:and\s+)?(?:with\s+)?(?:the\s+)?(?:body|message)\s*[:=]?\s*"
            r"(?P<body>.+?)\s*[.!?]*$",
            original_message,
            flags=re.IGNORECASE,
        )

        if composed_email_match:
            recipient = composed_email_match.group("recipient").strip()

            # Prefer a recipient the user explicitly corrected in recent turns
            # over a different address hallucinated by realtime speech synthesis.
            email_address_pattern = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
            correction_pattern = re.compile(
                r"\b(?:wrong|incorrect|galat|sahi|correct|actually|exact|"
                r"nahi|nahin|not|no)\b"
                r"|\u0917\u0932\u0924|\u0918\u0932\u0924|\u0938\u0939\u0940"
                r"|\u0928\u0939\u0940\u0902|\u0928\u0939\u0940",
                flags=re.IGNORECASE,
            )
            for history_item in reversed((history or [])[-12:]):
                if str(history_item.get("role", "")).casefold() != "user":
                    continue
                prior_user_text = str(history_item.get("content") or "")
                prior_addresses = re.findall(
                    email_address_pattern,
                    prior_user_text,
                    flags=re.IGNORECASE,
                )
                if prior_addresses and correction_pattern.search(prior_user_text):
                    recipient = prior_addresses[-1].strip()
                    break

            def _unquote_email_field(value: str) -> str:
                value = str(value or "").strip()
                if (
                    len(value) >= 2
                    and value[0] in {"'", '"'}
                    and value[-1] == value[0]
                ):
                    value = value[1:-1].strip()
                return value

            subject = _unquote_email_field(
                composed_email_match.group("subject")
            ).strip()
            body = _unquote_email_field(
                composed_email_match.group("body")
            ).strip()
            # Instructions about repeating/confirming the address are controls for
            # NOVA, not part of the outbound email body.
            body = re.split(
                r"\s+please\s+repeat\s+(?:the\s+)?recipient(?:\s+address)?\b.*$",
                body,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip()

            if recipient and subject and body:
                result["intent"] = "email"
                result["email_action"] = "send"
                result["action"] = "send"
                result["recipient_reference"] = None
                result["to"] = recipient
                result["subject"] = subject
                result["body"] = body
                result["requires_tool"] = True
                return result

        structured_email_match = re.match(
            r"^(?:please\s+)?send\s+(?:(?:a|an|the)\s+)?"
            r"(?:[\w-]+\s+){0,2}emails?\s+to\s+"
            r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
            r"\s*[.!]?\s*\r?\n\s*subject\s*:\s*(.*?)\s*"
            r"\r?\n\s*body\s*:\s*(.+?)\s*$",
            structured_message,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if structured_email_match:
            recipient = structured_email_match.group(1).strip()
            subject = structured_email_match.group(2).strip(" \t\r\n.!?\"“”")
            body = structured_email_match.group(3).strip(" \t\r\n\"“”")

            if recipient and subject and body:
                result["intent"] = "email"
                result["email_action"] = "send"
                result["action"] = "send"
                result["recipient_reference"] = None
                result["to"] = recipient
                result["subject"] = subject
                result["body"] = body
                result["requires_tool"] = True
                return result

        email_match = re.match(
            r"^send\s+an?\s+email\s+to\s+"
            r"(myself|me|\[[^\]\s]+@[^\]\s]+\]|<[^>\s]+@[^>\s]+>|[^\s@<>\[\]]+@[^\s@<>\[\]]+)\s+"
            r"(?:saying|that\s+says)\s+(.+)$",
            original_message,
            flags=re.IGNORECASE,
        )

        if email_match:
            recipient = email_match.group(1).strip()
            body = email_match.group(2).strip()

            body = body.strip(" \t\r\n\"“”")

            if body:
                result["intent"] = "email"
                result["email_action"] = "send"
                result["action"] = "send"
                result["subject"] = "NOVA message"
                result["body"] = body
                result["requires_tool"] = True

                if recipient.lower() in {"myself", "me"}:
                    result["recipient_reference"] = "self"
                    result["to"] = None
                else:
                    if (
                        recipient.startswith("[")
                        and recipient.endswith("]")
                    ) or (
                        recipient.startswith("<")
                        and recipient.endswith(">")
                    ):
                        recipient = recipient[1:-1].strip()

                    result["to"] = recipient

                return result

        if normalized.startswith((
            "remind me ",
            "remind me to ",
            "set a reminder",
            "set reminder",
        )):
            result["intent"] = "reminder"
            result["reminder_action"] = "create"
            result["requires_tool"] = True

            time_match = re.search(
                r"\b(today|tomorrow)\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
                original_message,
                flags=re.IGNORECASE,
            )

            if time_match:
                result["time"] = time_match.group(0)
                result["scheduled_at"] = self._deterministic_scheduled_at(
                    day_expression=time_match.group(1).lower(),
                    hour_text=time_match.group(2),
                    minute_text=time_match.group(3),
                    meridiem=time_match.group(4).lower(),
                )

                remainder = original_message[:time_match.start()] + " " + original_message[time_match.end():]
            else:
                remainder = original_message

            content_match = re.search(
                r"\bto\s+(.+)$",
                remainder,
                flags=re.IGNORECASE,
            )

            if content_match:
                result["task"] = content_match.group(1).strip(" .")

            if result["task"] is None:
                cleaned = re.sub(
                    r"^(remind me|set a reminder|set reminder)\s*",
                    "",
                    remainder,
                    flags=re.IGNORECASE,
                ).strip(" .")
                result["task"] = cleaned or None

            return result

        # Route personal reminder-list requests before the web freshness
        # fallback. Here "current" refers to saved user data, not current web facts.
        reminder_list_patterns = (
            r"^(?:please\s+)?(?:show|list|display|view|get|fetch)\s+"
            r"(?:(?:me|us)\s+)?"
            r"(?:(?:all\s+of\s+)?(?:my|the|all|current|saved|existing|pending|upcoming|scheduled|active|completed|cancelled|canceled|only)\s+)*"
            r"(?:reminders?|reminder\s+lists?)(?:\b|$)",
            r"^(?:what|which)\s+(?:(?:are|is)\s+)?"
            r"(?:(?:all|my|current|available|saved|existing|pending|upcoming|scheduled|active|completed|cancelled|canceled)\s+)*"
            r"reminders?\b",
        )
        if any(
            re.search(pattern, normalized, flags=re.IGNORECASE)
            for pattern in reminder_list_patterns
        ):
            result["intent"] = "reminder"
            result["reminder_action"] = "list"
            result["reminder_reference"] = None
            result["reminder_id"] = None
            result["task"] = None
            result["requires_tool"] = True
            return result

        # Route explicit bulk task deletion into the permission/confirmation
        # graph. Resolve and snapshot the exact matching task IDs before asking
        # for approval; never reinterpret a bulk delete as ordinary chat.
        bulk_task_delete_patterns = (
            r"^(?:please\s+)?(?:delete|remove|clear|erase)\s+"
            r"(?:(?:all|every|each)\s+)?(?:(?:of\s+)?(?:my|the)\s+)?"
            r"(?:(?:pending|outstanding|incomplete|unfinished|active|completed|"
            r"cancelled|canceled)\s+)*(?:tasks?|task\s+lists?)"
            r"(?:[\s,]+(?:please|now|for me))?[.!?,]*$",
            r"^(?:saare|saray|tamam|sab|sabhi)\s+"
            r"(?:(?:pending|outstanding|incomplete|unfinished)\s+)?tasks?\s+"
            r"(?:delete|remove|hata)\s+(?:kar\s+do|kardo|do)[.!?]*$",
            r"^(?:delete|remove|hata)\s+kar\s+do\s+"
            r"(?:saare|saray|tamam|sab|sabhi)\s+"
            r"(?:(?:pending|outstanding|incomplete|unfinished)\s+)?tasks?[.!?]*$",
        )
        if any(
            re.search(pattern, normalized, flags=re.IGNORECASE)
            for pattern in bulk_task_delete_patterns
        ):
            explicit_pending_scope = bool(
                re.search(
                    r"\b(?:pending|outstanding|incomplete|unfinished)\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
            )
            result["intent"] = "task"
            result["task_action"] = "delete"
            result["task"] = None
            result["task_reference"] = None
            result["task_id"] = None
            result["bulk_task_delete"] = True
            result["task_status_filter"] = (
                "pending" if explicit_pending_scope else None
            )
            result["requires_tool"] = True
            return result

        # Route task-list requests deterministically as well. If the intent
        # provider is unavailable, a read-only task query must still reach the
        # task tool instead of falling back to ordinary chat.
        task_list_patterns = (
            r"^(?:please\s+)?(?:show|list|display|view|get|fetch)\s+"
            r"(?:(?:me|us)\s+)?"
            r"(?:(?:my|all|current|available|saved|existing|pending|completed|cancelled|canceled|"
            r"in[- ]progress|only)\s+)*"
            r"(?:tasks?|task\s+lists?)(?:\b|$)",
            r"^(?:what|which)\s+(?:(?:are|is)\s+)?"
            r"(?:(?:all|my|the|current|available|saved|pending|outstanding|incomplete|unfinished|active|overdue|due|completed|cancelled|canceled)\s+)*tasks?\b",
            r"^(?:mujhe\s+)?(?:(?:batao|bata|dikhao|dikha|list)\s+)?"
            r"(?:mere|meri|meray|merey|mery)\s+(?:(?:paas|liye)\s+)?"
            r"(?:kaun(?:-kaun)?\s+se\s+)"
            r"(?:(?:saare|saray|tamam|sab|sabhi|current|saved|pending|available|"
            r"completed|cancelled|canceled|sirf|only|in[- ]progress)\s+)*"
            r"(?:tasks?|task\s+lists?)\b.*",
            r"^(?:mere|meri|meray|merey|mery)\s+"
            r"(?:(?:saare|saray|tamam|sab|sabhi|current|saved|pending|completed|"
            r"cancelled|canceled|sirf|only|in[- ]progress)\s+)*"
            r"(?:tasks?|task\s+lists?)\b.*"
            r"\b(?:list|dikha|bata|dekh|check)\w*\b",
            r"^(?:saare|saray|tamam|sab|sabhi)\s+tasks?\b.*"
            r"\b(?:list|dikha|bata|dekh|check)\w*\b",
            r"^(?:tasks?|task\s+lists?)\b.*"
            r"\b(?:list|dikha|bata|dekh|check)\w*\b",
            r"^(?:please\s+)?(?:show|list|display|view|get|fetch)\s+"
            r"all\s+of\s+(?:my|the)\s+(?:tasks?|task\s+lists?)\b",
            # Hindi/Devanagari variants must query persisted tasks, not enter
            # the ordinary voice-chat path and guess that no tasks exist.
            r"^(?:\u0915\u094d\u092f\u093e\s+)?"
            r"(?:\u092e\u0947\u0930\u0947|\u092e\u0947\u0930\u0940)\s+"
            r"(?:(?:\u092a\u093e\u0938|\u0932\u093f\u090f)\s+)?"
            r"(?:(?:\u0915\u094b\u0908|\u0938\u093e\u0930\u0947|\u0938\u092d\u0940|\u0924\u092e\u093e\u092e|\u0938\u092c|\u0915\u094c\u0928(?:-\u0915\u094c\u0928)?\s+\u0938\u0947)\s+)?"
            r"(?:\u091f\u093e\u0938\u094d\u0915(?:\u094d\u0938)?|\u0915\u093e\u0930\u094d\u092f)\b.*"
            r"(?:\u0939\u0948|\u0939\u0948\u0902|\u0932\u093f\u0938\u094d\u091f|\u0938\u0942\u091a\u0940|\u0926\u093f\u0916\u093e|\u092c\u0924\u093e\u0913|\u092c\u0924\u093e|\u0926\u0947\u0916|\u091a\u0947\u0915|\u0928\u091c\u0930|\u0930\u093f\u0915\u0949\u0930\u094d\u0921)",
        )
        if any(
            re.search(pattern, normalized, flags=re.IGNORECASE)
            for pattern in task_list_patterns
        ):
            result["intent"] = "task"
            result["task_action"] = "list"
            result["task"] = None
            result["task_reference"] = None
            result["task_id"] = None
            result["requires_tool"] = True
            return result

        # Route explicit task-priority updates by numeric task ID. This form
        # is often produced by voice confirmation/normalization and must not
        # fall through as casual chat.
        priority_update_match = re.match(
            r"^(?:update|change|set)\s+(?:the\s+)?priority\s+of\s+task\s+#?(?P<task_id>\d+)\s+to\s+(?P<priority>low|medium|high)[.!?]*$",
            original_message,
            flags=re.IGNORECASE,
        )
        if priority_update_match:
            result["intent"] = "task"
            result["task_action"] = "update"
            result["task_id"] = int(priority_update_match.group("task_id"))
            result["task"] = None
            result["task_reference"] = None
            result["priority"] = priority_update_match.group("priority").lower()
            result["requires_tool"] = True
            return result

        # Route explicit existing-task commands deterministically. Destructive
        # commands still flow through NOVA's permission and confirmation graph.
        existing_task_match = re.match(
            r"^(?P<verb>start|complete|finish|cancel|delete|remove|update)\s+"
            r"(?:(?:my|the|this|that)\s+)?task\s+"
            r"(?P<reference>.+)$",
            original_message,
            flags=re.IGNORECASE,
        )
        if existing_task_match:
            action = existing_task_match.group("verb").lower()
            reference = existing_task_match.group("reference").strip()
            reference = reference.strip(" .!?").strip().strip('"').strip("'").strip()
            if 2 <= len(reference) <= 200:
                result["intent"] = "task"
                result["task_action"] = "complete" if action == "finish" else action
                result["task_reference"] = reference
                result["requires_tool"] = True
                return result

        task_match = re.match(
            r"^(?:"
            r"(?:please\s+)?(?:create|add|make)\s+"
            r"(?:(?:a(?:\s+new)?|another|new)\s+)?task\s+(?P<details>.+)"
            r"|"
            r"(?:hey\s+)?(?:nova[\s,:-]+)?(?:ek\s+)?task\s+"
            r"(?:create|add|make|bana(?:o)?|bana\s+do)\s+"
            r"(?:karo|kar\s+do|kardo)?\s*(?P<roman_details>.+)"
            r")$",
            original_message,
            flags=re.IGNORECASE,
        )

        if task_match:
            task_title = (
                task_match.group("details")
                or task_match.group("roman_details")
                or ""
            ).strip(" .\\\"")

            # Explicit title phrases are common in voice-normalized
            # requests. Extract the quoted title rather than persisting
            # wrapper words such as "with the title" as part of the title.
            title_introducer_match = re.search(
                r"\b(?:with\s+)?(?:the\s+)?(?:exact\s+)?title\s+(?:is\s+)?",
                original_message,
                flags=re.IGNORECASE,
            )
            explicit_title = None
            if title_introducer_match:
                title_remainder = original_message[title_introducer_match.end():].lstrip()
                quote_pairs = {
                    chr(34): chr(34),
                    chr(39): chr(39),
                    chr(0x201C): chr(0x201D),
                    chr(0x2018): chr(0x2019),
                }
                if title_remainder and title_remainder[0] in quote_pairs:
                    closing_quote = quote_pairs[title_remainder[0]]
                    closing_at = title_remainder.find(closing_quote, 1)
                    if closing_at > 1:
                        explicit_title = title_remainder[1:closing_at].strip()
                else:
                    # Speech recognition often omits spoken quotation marks.
                    # Support an unquoted Roman Urdu phrase like:
                    # "exact title NOVA Test 42 ho, due date mat rakhna".
                    unquoted_title = title_remainder
                    end_of_title = re.search(
                        r"\s+\b(?:ho|hai|hain)\b",
                        unquoted_title,
                        flags=re.IGNORECASE,
                    )
                    if end_of_title is None:
                        end_of_title = re.search(
                            r"\s+(?:no\s+due\s+date|without\s+(?:a\s+)?due\s+date|"
                            r"due\s+date\b|default\s+priority\b|"
                            r"(?:low|medium|high)\s+priority\b)",
                            unquoted_title,
                            flags=re.IGNORECASE,
                        )
                    if end_of_title is not None:
                        unquoted_title = unquoted_title[:end_of_title.start()]
                    candidate_title = unquoted_title.strip(" ,.!?:;")
                    if candidate_title:
                        explicit_title = candidate_title
            titled_match = re.search(
                r'\btask\s+titled\s+["“](.+?)["”](?=\s|[.!?]*$)',
                original_message,
                flags=re.IGNORECASE,
            )
            if explicit_title:
                task_title = explicit_title
            elif titled_match:
                task_title = titled_match.group(1).strip()
            else:
                called_match = re.search(
                    r'\bcalled\s+"([^"]+)"',
                    original_message,
                    flags=re.IGNORECASE,
                )
                if called_match:
                    task_title = called_match.group(1).strip()
                else:
                    task_to_match = re.search(
                        r'\btask\s+to\s+(.+?)(?:\s+with\s+(?:high|medium|low)\s+priority)?(?:\s+and\s+due\s+tomorrow)?$',
                        original_message,
                        flags=re.IGNORECASE,
                    )
                    if task_to_match:
                        task_title = task_to_match.group(1).strip(" .\\\"")

            # The command can include a title introducer and task metadata.
            # Keep only the title before persisting; priority and due date are
            # extracted independently below.
            task_title = re.sub(
                r"^(?:named|called|titled)\s+",
                "",
                task_title,
                flags=re.IGNORECASE,
            )
            metadata_suffix = re.search(
                r"\s+(?:(?:with|and|using|use)\s+)?"
                r"(?:no\s+due\s+date|without\s+(?:a\s+)?due\s+date|"
                r"default\s+priority|(?:low|medium|high)\s+priority)\b",
                task_title,
                flags=re.IGNORECASE,
            )
            if metadata_suffix:
                task_title = task_title[:metadata_suffix.start()]
            task_title = task_title.strip(" .\\\"????")

            result["intent"] = "task"
            result["task"] = task_title or None
            result["task_action"] = "create"
            result["requires_tool"] = True

            if "high priority" in normalized:
                result["priority"] = "high"
            elif "medium priority" in normalized:
                result["priority"] = "medium"
            elif "low priority" in normalized:
                result["priority"] = "low"

            # Parse an explicit calendar date/time before creating the task.
            # The LLM must not be allowed to claim a due date that never made
            # it into the executable task payload.
            has_due_context = bool(
                re.search(
                    r"\b(?:due|deadline|scheduled|set\s+the\s+due\s+date)\b",
                    normalized,
                )
            )
            explicit_due_date = re.search(
                r"\b(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
                r"(?P<day>\d{1,2}),?\s+(?P<year>\d{4})"
                r"(?:,?\s+(?:at\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>a\.?m\.?|p\.?m\.?))?",
                original_message,
                flags=re.IGNORECASE,
            )
            if has_due_context and explicit_due_date:
                try:
                    month = datetime.strptime(
                        explicit_due_date.group("month"), "%B"
                    ).month
                    day = int(explicit_due_date.group("day"))
                    year = int(explicit_due_date.group("year"))
                    hour_text = explicit_due_date.group("hour")
                    if hour_text is None:
                        hour, minute = 23, 59
                    else:
                        hour = int(hour_text)
                        minute = int(explicit_due_date.group("minute") or 0)
                        meridiem = explicit_due_date.group("ampm").lower().replace(".", "")
                        if not 1 <= hour <= 12 or not 0 <= minute <= 59:
                            raise ValueError("Invalid 12-hour time")
                        if meridiem == "am":
                            hour = 0 if hour == 12 else hour
                        else:
                            hour = 12 if hour == 12 else hour + 12
                    due_datetime = datetime(
                        year, month, day, hour, minute,
                        tzinfo=ZoneInfo(USER_TIMEZONE),
                    )
                except ValueError:
                    result["task"] = None
                    result["task_action"] = None
                    result["requires_tool"] = False
                    result["clarification_required"] = True
                    return result
                result["time"] = explicit_due_date.group(0).strip()
                result["scheduled_at"] = due_datetime.isoformat(timespec="minutes")
            elif "tomorrow" in normalized:
                result["time"] = "tomorrow"
                result["scheduled_at"] = self._deterministic_end_of_day(
                    days_ahead=1
                )

                clock_match = re.search(
                    r"\bat\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>a\.?m\.?|p\.?m\.?)\b",
                    original_message,
                    flags=re.IGNORECASE,
                )
                if clock_match:
                    hour = int(clock_match.group("hour"))
                    minute = int(clock_match.group("minute") or 0)
                    meridiem = clock_match.group("ampm").lower().replace(".", "")
                    if 1 <= hour <= 12 and 0 <= minute <= 59:
                        if meridiem == "am":
                            hour = 0 if hour == 12 else hour
                        else:
                            hour = 12 if hour == 12 else hour + 12
                        tomorrow = datetime.now(ZoneInfo(USER_TIMEZONE)).date() + timedelta(days=1)
                        due_datetime = datetime(
                            tomorrow.year, tomorrow.month, tomorrow.day, hour, minute,
                            tzinfo=ZoneInfo(USER_TIMEZONE),
                        )
                        result["time"] = clock_match.group(0).strip()
                        result["scheduled_at"] = due_datetime.isoformat(timespec="minutes")

            return result

        calendar_reference = bool(
            re.search(
                r"\bcalendar\b|"
                r"\b(?:calendar\s+)?events?\b|"
                r"\bappointments?\b|"
                r"\bschedule\b|"
                r"\u0915\u0948\u0932\u0947\u0902\u0921\u0930|"
                r"\u0907\u0935\u0947\u0902\u091f(?:\u094d\u0938)?",
                normalized,
                flags=re.IGNORECASE,
            )
        )
        calendar_list_verb = bool(
            re.search(
                r"\b(?:what's\s+on|whats\s+on|show(?:\s+me)?|list|view|get|fetch|display|check|"
                r"dikhao|dikhaye|dikhaiye|dekh(?:o|na)?|batao|bataiye)\b|"
                r"\u0926\u093f\u0916\u093e\u0913|"
                r"\u0926\u093f\u0916\u093e\u090f|"
                r"\u0926\u0947\u0916\u094b|"
                r"\u092c\u0924\u093e\u0913",
                normalized,
                flags=re.IGNORECASE,
            )
        )
        if calendar_reference and calendar_list_verb:
            result["intent"] = "calendar"
            result["calendar_action"] = "list"
            result["requires_tool"] = True

            # Resolve an explicit day range locally so the Calendar provider
            # can return the user's events rather than a generic all-day list.
            # In this phrasing, "kal/कल" is treated as tomorrow, as in NOVA's
            # existing task/reminder command language.
            karachi_now = datetime.now(ZoneInfo(USER_TIMEZONE))
            if re.search(r"\b(?:tomorrow|kal)\b|\u0915\u0932", normalized):
                day_start = (karachi_now + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                result["time_min"] = day_start.isoformat()
                result["time_max"] = (day_start + timedelta(days=1)).isoformat()
            elif re.search(r"\b(?:today|aaj)\b|\u0906\u091c", normalized):
                day_start = karachi_now.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                result["time_min"] = day_start.isoformat()
                result["time_max"] = (day_start + timedelta(days=1)).isoformat()
            return result

        weather_signals = (
            "weather",
            "temperature",
            "forecast",
            "conditions",
        )
        has_weather = any(
            signal in normalized
            for signal in weather_signals
        )
        has_weather_location = bool(
            re.search(
                r"\b(?:weather|temperature|forecast|conditions?)\s+(?:in|for|at)\s+[^?!.,;]+",
                normalized,
            )
        )

        if has_weather and has_weather_location:
            result["intent"] = "web"
            result["web_action"] = "search"
            result["web_topic"] = "weather"
            result["web_time_range"] = None
            result["query"] = str(message).strip()
            result["action"] = "search"
            result["requires_tool"] = True
            return result

        fresh_time_signals = (
            "latest",
            "current",
            "currently",
            "today",
            "today's",
            "recent",
            "recently",
            "newest",
            "right now",
            "now",
            "live",
            "real time",
            "realtime",
        )
        fresh_news_signals = (
            "news",
            "headline",
            "headlines",
            "developments",
            "development",
            "announcement",
            "announcements",
            "updates",
            "update",
        )
        explicit_web_signals = (
            "search the web",
            "search online",
            "browse the web",
            "look up",
            "research ",
        )

        has_fresh_time = any(
            signal in normalized
            for signal in fresh_time_signals
        )
        has_fresh_news = any(
            signal in normalized
            for signal in fresh_news_signals
        )
        has_explicit_web_request = any(
            signal in normalized
            for signal in explicit_web_signals
        )

        explicit_source_request = any(
            marker in normalized
            for marker in (
                "web source",
                "reliable source",
                "source link",
                "publication date",
                "cite sources",
                "citation",
            )
        )
        comparison_markers = (
            "compare",
            "comparison",
            "strongest",
            "strengths",
            "limitations",
            "clear winner",
            "which companies",
        )
        source_grounded_comparison = (
            explicit_source_request
            and any(
                marker in normalized
                for marker in comparison_markers
            )
        )

        if source_grounded_comparison:
            # Use an unbounded search window for comparative research.
            # The news topic also allows Google News RSS to act as a
            # recoverable provider when Tavily and local SearXNG are down.
            result["intent"] = "web"
            result["web_action"] = "search"
            result["web_topic"] = "news"
            result["web_time_range"] = None
            result["query"] = (
                "consumer AI voice assistants 2026 Gemini Live "
                "Amazon Alexa+ Apple Siri ChatGPT Voice capabilities "
                "limitations official sources reviews"
            )
            result["action"] = "search"
            result["requires_tool"] = True
            return result

        if (
            has_explicit_web_request
            or (
                has_fresh_time
                and (
                    has_fresh_news
                    or "ai" in normalized
                    and any(
                        signal in normalized
                        for signal in (
                            "latest",
                            "current",
                            "recent",
                            "today",
                        )
                    )
                )
            )
        ):
            result["intent"] = "web"
            result["web_action"] = "search"
            result["web_topic"] = (
                "news"
                if has_fresh_news or "ai" in normalized
                else "general"
            )
            result["web_time_range"] = (
                "day"
                if any(
                    signal in normalized
                    for signal in (
                        "today",
                        "today's",
                        "latest",
                        "current",
                        "recent",
                        "right now",
                        "now",
                    )
                )
                else None
            )
            if re.search(
                r"\bai\s+(?:news|headlines?)\b|\b(?:news|headlines?)\s+(?:in|about|on)\s+ai\b",
                normalized,
            ):
                result["query"] = "latest AI news"
            else:
                result["query"] = str(message).strip()
            result["action"] = "search"
            result["requires_tool"] = True
            return result

        if any(
            marker in normalized
            for marker in (
                "help me plan",
                "plan tomorrow",
                "make a plan",
                "plan my day",
            )
        ):
            result["intent"] = "planning"
            result["requires_tool"] = False
            return result

        planning_context = any(
            any(
                marker in str(item.get("content") or "").lower()
                for marker in (
                    "help me plan",
                    "plan tomorrow",
                    "make a plan",
                    "plan my day",
                )
            )
            for item in history
            if item.get("role") == "user"
        )

        planning_follow_up = (
            planning_context
            and (
                re.search(
                    r"\b(?:only\s+)?have\s+"
                    r"(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)"
                    r"\s+(?:hours?|hrs?|minutes?|mins?)\b",
                    normalized,
                )
                is not None
                or any(
                    phrase in normalized
                    for phrase in (
                        "what should i do first",
                        "what do i do first",
                        "what can wait",
                        "what can wait until tomorrow",
                        "what should wait until tomorrow",
                    )
                )
            )
        )

        if planning_follow_up:
            result["intent"] = "planning"
            result["requires_tool"] = False
            return result

        return result

    @staticmethod
    def _deterministic_scheduled_at(
        *,
        day_expression: str,
        hour_text: str,
        minute_text: str | None,
        meridiem: str,
    ) -> str:
        now = datetime.now(ZoneInfo(USER_TIMEZONE))
        days_ahead = 1 if day_expression == "tomorrow" else 0
        target_date = (now + timedelta(days=days_ahead)).date()
        hour = int(hour_text)
        minute = int(minute_text or "00")

        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0

        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            tzinfo=ZoneInfo(USER_TIMEZONE),
        ).isoformat(timespec="seconds")

    @staticmethod
    def _deterministic_end_of_day(
        *,
        days_ahead: int,
    ) -> str:
        now = datetime.now(ZoneInfo(USER_TIMEZONE))
        target = (now + timedelta(days=days_ahead)).date()
        return datetime(
            target.year,
            target.month,
            target.day,
            23,
            59,
            59,
            tzinfo=ZoneInfo(USER_TIMEZONE),
        ).isoformat(timespec="seconds")

    def _default_result(self) -> dict:
        return {
            "intent": "chat",
            "task": None,
            "task_reference": None,
            "task_action": None,
            "task_id": None,
            "priority": None,
            "reminder_action": None,
            "reminder_reference": None,
            "reminder_id": None,
            "time": None,
            "scheduled_at": None,
            "emotion": "neutral",
            "tone": "friendly",
            "visual": "none",
            "action": None,
            "email_action": None,
            "message_id": None,
            "include_body": False,
            "to": None,
            "recipient_reference": None,
            "cc": None,
            "bcc": None,
            "subject": None,
            "body": None,
            "calendar_action": None,
            "calendar_id": None,
            "event_id": None,
            "event": None,
            "time_min": None,
            "time_max": None,
            "query": None,
            "max_results": None,
            "page_token": None,
            "single_events": None,
            "order_by": None,
            "show_deleted": None,
            "send_updates": None,
            "web_action": None,
            "web_topic": None,
            "web_time_range": None,
            "desktop_operation": None,
            "desktop_target": None,
            "desktop_query": None,
            "clarification_required": False,
            "requires_tool": False,
        }

    def _normalize_reminder_task(
        self,
        task: str | None,
        action: str | None,
    ) -> str | None:
        """
        Normalize reminder content into the canonical `task`
        field so downstream tools always receive a title.
        """

        if task:
            normalized = task.strip()

            if normalized:
                return normalized

        if not action:
            return None

        normalized = action.strip()

        prefixes = (
            "reminder to ",
            "remind me to ",
            "reminder: ",
            "remind me ",
        )

        lowered = normalized.lower()

        for prefix in prefixes:
            if lowered.startswith(prefix):
                normalized = (
                    normalized[len(prefix):]
                    .strip()
                )
                break

        return normalized or None

    def _validate_result(
        self,
        result: dict,
    ) -> dict:

        valid_intents = {
            "chat",
            "question",
            "advice",
            "planning",
            "reminder",
            "task",
            "action",
            "email",
            "calendar",
            "web",
            "desktop",
        }

        valid_emotions = {
            "happy",
            "sad",
            "angry",
            "stressed",
            "excited",
            "romantic",
            "playful",
            "neutral",
        }

        valid_tones = {
            "friendly",
            "supportive",
            "playful",
            "romantic",
            "professional",
            "neutral",
        }

        valid_visuals = {
            "none",
            "smile",
            "laugh",
            "hearts",
            "sad",
            "concerned",
            "celebration",
            "thinking",
            "listening",
            "reminder",
        }

        valid_task_actions = {
            "create",
            "list",
            "start",
            "complete",
            "cancel",
            "delete",
            "update",
        }

        valid_reminder_actions = {
            "create",
            "list",
            "complete",
            "cancel",
            "delete",
            "update",
        }

        valid_priorities = {
            "low",
            "medium",
            "high",
        }

        intent = result.get("intent")
        emotion = result.get("emotion")
        tone = result.get("tone")
        visual = result.get("visual")

        if intent not in valid_intents:
            intent = "chat"

        if emotion not in valid_emotions:
            emotion = "neutral"

        if tone not in valid_tones:
            tone = "friendly"

        if visual not in valid_visuals:
            visual = "none"

        task = result.get("task")
        task_reference = result.get(
            "task_reference"
        )
        task_action = result.get(
            "task_action"
        )
        task_id = result.get("task_id")
        priority = result.get("priority")

        reminder_action = result.get(
            "reminder_action"
        )
        reminder_reference = result.get(
            "reminder_reference"
        )
        reminder_id = result.get(
            "reminder_id"
        )

        time = result.get("time")
        scheduled_at = result.get(
            "scheduled_at"
        )
        action = result.get("action")
        email_action = result.get("email_action")
        message_id = result.get("message_id")
        include_body = result.get("include_body", False)
        if not isinstance(include_body, bool):
            include_body = False
        to = result.get("to")
        recipient_reference = result.get(
            "recipient_reference"
        )
        cc = result.get("cc")
        bcc = result.get("bcc")
        subject = result.get("subject")
        body = result.get("body")

        if task is not None:
            task = str(task).strip() or None

        if task_reference is not None:
            task_reference = (
                str(task_reference).strip()
                or None
            )

        if task_action not in valid_task_actions:
            task_action = None

        if task_id is not None:
            try:
                task_id = int(task_id)
            except (TypeError, ValueError):
                task_id = None

        if task_id is not None and task_id < 1:
            task_id = None

        if priority not in valid_priorities:
            priority = None

        if reminder_action not in valid_reminder_actions:
            reminder_action = None

        if reminder_reference is not None:
            reminder_reference = (
                str(
                    reminder_reference
                ).strip()
                or None
            )

        if reminder_id is not None:
            try:
                reminder_id = int(
                    reminder_id
                )
            except (TypeError, ValueError):
                reminder_id = None

        if reminder_id is not None and reminder_id < 1:
            reminder_id = None

        if time is not None:
            time = str(time).strip() or None

        calendar_action = result.get("calendar_action")
        calendar_id = result.get("calendar_id")
        event_id = result.get("event_id")
        event = result.get("event")
        time_min = result.get("time_min")
        time_max = result.get("time_max")
        query = result.get("query")
        desktop_operation = result.get("desktop_operation")
        desktop_target = result.get("desktop_target")
        desktop_query = result.get("desktop_query")
        max_results = result.get("max_results")
        page_token = result.get("page_token")
        single_events = result.get("single_events")
        order_by = result.get("order_by")
        show_deleted = result.get("show_deleted")
        send_updates = result.get("send_updates")
        web_action = result.get("web_action")
        web_topic = result.get("web_topic")
        web_time_range = result.get("web_time_range")

        if scheduled_at is not None:
            scheduled_at = (
                str(scheduled_at).strip()
                or None
            )

        valid_calendar_actions = {
            "list",
            "get",
            "create",
            "update",
            "delete",
        }

        if calendar_action not in valid_calendar_actions:
            calendar_action = None

        for field_name in (
            "calendar_id",
            "event_id",
            "time_min",
            "time_max",
            "query",
            "page_token",
        ):
            value = locals()[field_name]

            if value is not None:
                value = str(value).strip() or None
                if field_name == "calendar_id":
                    calendar_id = value
                elif field_name == "event_id":
                    event_id = value
                elif field_name == "time_min":
                    time_min = value
                elif field_name == "time_max":
                    time_max = value
                elif field_name == "query":
                    query = value
                elif field_name == "page_token":
                    page_token = value

        if isinstance(max_results, bool):
            max_results = None
        elif max_results is not None:
            try:
                max_results = int(max_results)
            except (TypeError, ValueError):
                max_results = None

            if (
                max_results is not None
                and not 1 <= max_results <= 2500
            ):
                max_results = None

        if single_events is not None and not isinstance(
            single_events,
            bool,
        ):
            single_events = None

        if show_deleted is not None and not isinstance(
            show_deleted,
            bool,
        ):
            show_deleted = None

        if order_by not in {
            "startTime",
            "updated",
        }:
            order_by = None

        if send_updates not in {
            "all",
            "externalOnly",
            "none",
        }:
            send_updates = None

        if event is not None and not isinstance(
            event,
            dict,
        ):
            event = None

        if action is not None:
            action = str(action).strip() or None

        valid_email_actions = {"send", "list", "search", "get"}
        if email_action not in valid_email_actions:
            email_action = None

        if message_id is not None:
            message_id = str(message_id).strip() or None
            if message_id is not None and (
                len(message_id) > 200
                or not re.fullmatch(r"[A-Za-z0-9_-]+", message_id)
            ):
                message_id = None

        if recipient_reference not in {
            "self",
        }:
            recipient_reference = None

        def _normalize_recipients(value):
            if value is None:
                return None
            if isinstance(value, str):
                values = [item.strip() for item in value.split(",") if item.strip()]
            elif isinstance(value, list):
                values = [str(item).strip() for item in value if str(item).strip()]
            else:
                values = []
            return values or None

        to = _normalize_recipients(to)
        cc = _normalize_recipients(cc)
        bcc = _normalize_recipients(bcc)
        subject = str(subject).strip() or None if subject is not None else None
        body = str(body).strip() or None if body is not None else None

        # -------------------------------------------------
        # Normalize reminder content into `task`.
        # -------------------------------------------------

        if intent == "reminder":
            task = self._normalize_reminder_task(
                task=task,
                action=action,
            )

        # -------------------------------------------------
        # Task-specific fields only belong to task intent.
        # -------------------------------------------------

        if intent != "task":
            task_reference = None
            task_action = None
            task_id = None
            priority = None

        # -------------------------------------------------
        # Reminder-specific fields only belong to reminder
        # intent.
        # -------------------------------------------------

        if intent != "reminder":
            reminder_action = None
            reminder_reference = None
            reminder_id = None

        if intent != "email":
            email_action = None
            message_id = None
            include_body = False
            to = None
            recipient_reference = None
            cc = None
            bcc = None
            subject = None
            body = None

        if intent != "calendar":
            calendar_action = None
            calendar_id = None
            event_id = None
            event = None
            time_min = None
            time_max = None
            page_token = None
            single_events = None
            order_by = None
            show_deleted = None
            send_updates = None

        if intent != "web":
            web_action = None
            web_topic = None
            web_time_range = None

        if intent != "desktop":
            desktop_operation = None
            desktop_target = None
            desktop_query = None
        else:
            valid_desktop_operations = {
                "open_app",
                "open_url",
                "search_web",
                "open_folder",
                "open_file",
                "find_files",
                "list_files",
                "inspect_screen",
                "click_ui",
                "type_ui",
                "press_key",
                "play_youtube",
                "play_spotify",
            }
            if desktop_operation not in valid_desktop_operations:
                intent = "chat"
                action = None
                desktop_operation = None
                desktop_target = None
                desktop_query = None
            else:
                desktop_target = str(desktop_target).strip() if desktop_target is not None else None
                desktop_query = str(desktop_query).strip() if desktop_query is not None else None
                expected_action = "search" if desktop_operation in {"find_files", "list_files"} else "start"
                if action != expected_action:
                    intent = "chat"
                    action = None
                    desktop_operation = None
                    desktop_target = None
                    desktop_query = None
                elif desktop_operation in {"find_files", "list_files"}:
                    valid_file_queries = {"desktop", "documents", "downloads", "pictures", "music", "videos"}
                    if (
                        not desktop_query
                        or len(desktop_query) > 120
                        or "/" in desktop_query
                        or "\\" in desktop_query
                        or desktop_operation == "list_files" and desktop_query.casefold() not in valid_file_queries
                    ):
                        intent = "chat"
                        action = None
                        desktop_operation = None
                        desktop_query = None
                elif desktop_operation in {"play_youtube", "play_spotify"} and (
                    not desktop_target
                    or len(desktop_target) < 2
                    or len(desktop_target) > 180
                    or any(ord(char) < 32 for char in desktop_target)
                    or desktop_target.casefold() in {
                        "song", "songs", "music", "a song", "any song", "something",
                        "anything", "whatever", "that song", "this song", "my favorite song",
                        "my favourite song", "kuch", "koi song", "koi gana", "gaana", "gana",
                        "video", "videos", "latest video", "latest videos",
                        "recent video", "newest video", "koi latest video",
                    }
                ):
                    intent = "chat"
                    action = None
                    desktop_operation = None
                    desktop_target = None
                    desktop_query = None
                elif desktop_operation in {"click_ui", "type_ui", "press_key"} and (
                    not desktop_target
                    or len(desktop_target) > 160
                    or desktop_operation == "type_ui" and (
                        not desktop_query or len(desktop_query) > 2000
                    )
                    or desktop_operation == "click_ui" and desktop_query is not None and len(desktop_query) > 160
                    or desktop_operation == "press_key" and desktop_query is not None and len(desktop_query) > 160
                ):
                    intent = "chat"
                    action = None
                    desktop_operation = None
                    desktop_target = None
                    desktop_query = None
                elif desktop_operation != "inspect_screen" and (not desktop_target or len(desktop_target) > (2048 if desktop_operation == "open_url" else 500)):
                    intent = "chat"
                    action = None
                    desktop_operation = None
                    desktop_target = None

        if intent == "web":
            if web_action != "search":
                web_action = "search"

            if web_topic not in {
                "general",
                "news",
                "finance",
                "weather",
            }:
                web_topic = "general"

            if web_time_range not in {
                "day",
                "week",
                "month",
                "year",
            }:
                web_time_range = None

        # -------------------------------------------------
        # For reminder creation, default action is create.
        # -------------------------------------------------

        if (
            intent == "reminder"
            and reminder_action is None
        ):
            reminder_action = "create"

        requires_tool = intent in {
            "reminder",
            "task",
            "action",
            "email",
            "calendar",
            "web",
            "desktop",
        }

        return {
            "intent": intent,
            "task": task,
            "task_reference": task_reference,
            "task_action": task_action,
            "task_id": task_id,
            "priority": priority,
            "reminder_action": reminder_action,
            "reminder_reference": reminder_reference,
            "reminder_id": reminder_id,
            "time": time,
            "scheduled_at": scheduled_at,
            "emotion": emotion,
            "tone": tone,
            "visual": visual,
            "action": action,
            "email_action": email_action,
            "message_id": message_id,
            "include_body": include_body,
            "to": to,
            "recipient_reference": recipient_reference,
            "cc": cc,
            "bcc": bcc,
            "subject": subject,
            "body": body,
            "calendar_action": calendar_action,
            "calendar_id": calendar_id,
            "event_id": event_id,
            "event": event,
            "time_min": time_min,
            "time_max": time_max,
            "query": query,
            "max_results": max_results,
            "page_token": page_token,
            "single_events": single_events,
            "order_by": order_by,
            "show_deleted": show_deleted,
            "send_updates": send_updates,
            "web_action": web_action,
            "web_topic": web_topic,
            "web_time_range": web_time_range,
            "desktop_operation": desktop_operation,
            "desktop_target": desktop_target,
            "desktop_query": desktop_query,
            "requires_tool": requires_tool,
        }