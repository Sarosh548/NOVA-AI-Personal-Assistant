import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI


MODEL_NAME = "openai/gpt-oss-20b"
USER_TIMEZONE = "Asia/Karachi"


class IntentService:
    def __init__(self):
        groq_api_key = os.getenv("GROQ_API_KEY")

        if not groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set."
            )

        self.client = OpenAI(
            api_key=groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )

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

        now = datetime.now(
            ZoneInfo(USER_TIMEZONE)
        )

        current_datetime = now.isoformat(
            timespec="minutes"
        )

        recent_history = history[-10:]

        history_context = "\n".join(
            f"{item.get('role', 'unknown')}: "
            f"{item.get('content', '')}"
            for item in recent_history
        )

        if not history_context:
            history_context = (
                "No previous conversation available."
            )

        instructions = f"""
You are NOVA's understanding system.

Analyze the user's CURRENT message while using the recent
conversation only when needed to resolve context or references.

Current date and time:
{current_datetime}

User timezone:
{USER_TIMEZONE}

Recent conversation:
{history_context}

Choose exactly one intent:

- "chat"       = casual conversation
- "question"   = asking for information
- "advice"     = asking what they should do
- "planning"   = creating or organizing a plan
- "reminder"   = asking NOVA to create, view, complete,
                 cancel, delete, or update a reminder
- "task"       = asking NOVA to create, view, start, complete,
                 cancel, delete, or update a task
- "action"     = asking NOVA to perform an external action
- "email"      = asking NOVA to send an email
- "calendar"   = asking NOVA to view, create, update, or delete a Google Calendar event
- "web"        = asking NOVA to search the live public web for current or external information

Choose exactly one emotion:

- "happy"
- "sad"
- "angry"
- "stressed"
- "excited"
- "romantic"
- "playful"
- "neutral"

Choose exactly one tone:

- "friendly"
- "supportive"
- "playful"
- "romantic"
- "professional"
- "neutral"

Choose exactly one visual:

- "none"
- "smile"
- "laugh"
- "hearts"
- "sad"
- "concerned"
- "celebration"
- "thinking"
- "listening"
- "reminder"

Extract:

- task:
    For task creation, the short title/description of the new task.

    For reminders:
    put ONLY the reminder content/title here.

    For existing-task actions, this may be null.

    For existing-reminder update, this may contain a new
    reminder title only when the user explicitly wants to
    change the reminder text.

- task_reference:
    A short natural-language reference to an EXISTING task when
    the user wants to start, complete, cancel, delete, or update
    a task without giving a numeric task ID.

    Use recent conversation history when the current message
    contains an indirect reference such as:
    "it"
    "that task"
    "the previous task"
    "the LangGraph task"
    "that one"

    Extract the identifying part of the existing task title.

- task_action:
    "create"
    "list"
    "start"
    "complete"
    "cancel"
    "delete"
    "update"
    or null when not a task request.

- task_id:
    numeric task ID if explicitly given,
    otherwise null

- priority:
    "low"
    "medium"
    "high"
    or null when not provided

- reminder_action:
    "create"
    "list"
    "complete"
    "cancel"
    "delete"
    "update"
    or null when not a reminder request

- reminder_reference:
    A short natural-language reference to an EXISTING reminder
    when the user wants to complete, cancel, delete, or update
    a reminder without giving a numeric reminder ID.

    Use recent conversation history when the current message
    contains an indirect reference such as:
    "it"
    "that reminder"
    "the previous reminder"
    "that one"

    Extract the identifying part of the existing reminder title.

- reminder_id:
    numeric reminder ID if explicitly given,
    otherwise null

- time:
    user's original time expression, or null

- scheduled_at:
    exact ISO 8601 datetime in the user's timezone,
    or null when no schedule exists

- action:
    short external action description, or null

- email_action:
    "send" or null when not an email request

- to:
    explicit recipient email address or list, or null

- cc:
    explicit CC recipient email address or list, or null

- bcc:
    explicit BCC recipient email address or list, or null

- subject:
    email subject, or null

- body:
    email body, or null

Calendar rules:

- calendar_action:
    "list", "get", "create", "update", "delete", or null

- calendar_id:
    explicit Google Calendar ID, or null

- event_id:
    explicit Google Calendar event ID, or null

- event:
    for create, an object containing the requested event fields.
    Create events must include start and end objects using either
    dateTime or date.
    Include summary, description, or location only when explicitly
    provided by the user.
    Include attendees only when the user explicitly asks to invite
    participants.
    For update, include only fields the user explicitly wants changed.
    When changing event time, include both start and end.
    For list/get/delete, normally null.

- time_min:
    ISO 8601 filter for listing events, or null

- time_max:
    ISO 8601 filter for listing events, or null

- query:
    Calendar search query, or null

- max_results:
    integer from 1 to 2500 when requested, otherwise null

- page_token:
    Calendar pagination token, or null

- single_events:
    true or false when explicitly requested, otherwise null

- order_by:
    "startTime" or "updated" when explicitly requested, otherwise null

- show_deleted:
    true or false when explicitly requested, otherwise null

- send_updates:
    "all", "externalOnly", or "none" when explicitly requested,
    otherwise null

Web search rules:

- web_action:
    "search" or null when not a web request

- web_topic:
    "general", "news", or "finance", or null when not a web request

- web_time_range:
    "day", "week", "month", "year", or null when not requested

- query:
    the concise search question to send to the live web

- max_results:
    an integer from 1 to 10 for web search when explicitly
    requested, otherwise null

Use intent = "web" whenever answering requires fresh external
information such as current events, latest software/library
changes, current prices, live schedules, recent announcements,
or explicit web research.

Web examples:

User:
"Search the web for the latest FastAPI release."

Return:
intent = "web"
web_action = "search"
web_topic = "general"
query = "latest FastAPI release"
requires_tool = true

User:
"What are today's AI news headlines?"

Return:
intent = "web"
web_action = "search"
web_topic = "news"
web_time_range = "day"
query = "AI news headlines"
requires_tool = true

Calendar examples:

User:
"What's on my calendar tomorrow?"

Return:
intent = "calendar"
calendar_action = "list"
time_min/time_max = tomorrow start/end in Asia/Karachi
event = null
requires_tool = true

User:
"Schedule a team meeting tomorrow at 3 PM for one hour."

Return:
intent = "calendar"
calendar_action = "create"
event = {
  "summary": "Team meeting",
  "start": {"dateTime": "calculated ISO datetime with timezone"},
  "end": {"dateTime": "calculated ISO datetime with timezone"}
}
requires_tool = true

User:
"Create a client meeting tomorrow at 4 PM and invite client@example.com."

Return a create event with summary, start, end, and:
attendees = [{"email": "client@example.com"}]

User:
"Move event abc123 to tomorrow at 6 PM."

Return:
intent = "calendar"
calendar_action = "update"
event_id = "abc123"
event = {
  "start": {"dateTime": "calculated ISO datetime with timezone"},
  "end": {"dateTime": "calculated ISO datetime with timezone"}
}

User:
"Delete calendar event abc123."

Return:
intent = "calendar"
calendar_action = "delete"
event_id = "abc123"
event = null

Calendar safety rules:
- Never invent an event ID or attendee email address.
- Never invent a location or description.
- For timed event creation without a duration, use one hour.
- Use the user's timezone Asia/Karachi.
- For today/tomorrow/date-range listing, populate time_min/time_max.
- Do not populate attendees unless explicitly supplied.
- Keep Calendar action in calendar_action.

- requires_tool:
    true for reminders, tasks, or external actions,
    otherwise false

Task reference rules:

- For CREATE:
    put the NEW task title in "task".
    "task_reference" should be null.

- For LIST:
    "task_reference" should normally be null.

- For START / COMPLETE / CANCEL / DELETE:
    if the user gives a numeric ID, put it in task_id.

    If the user names the task directly, put the identifying
    task name in task_reference.

    If the user uses an indirect reference such as "it" or
    "that task", use recent conversation history to identify
    the existing task and put its identifying name in
    task_reference.

- For UPDATE:
    if the user gives a numeric ID, put it in task_id.

    If the user names the task directly, put the identifying
    task name in task_reference.

    If the user uses an indirect reference such as "it",
    "that task", or "the previous one", use recent conversation
    history to identify the existing task and put its identifying
    name in task_reference.

    Put the new priority in "priority" when provided.

    Put the new due date/time in "scheduled_at" when provided.

Reminder rules:

- For CREATE:
    "reminder_action" = "create"

    Put ONLY the reminder content/title in "task".

- For LIST:
    "reminder_action" = "list"

    "reminder_reference" should normally be null.

- For COMPLETE / CANCEL / DELETE:
    "reminder_action" must contain the requested action.

    If the user gives a numeric reminder ID, put it in
    "reminder_id".

    If the user names the reminder directly, put the identifying
    reminder text in "reminder_reference".

    If the user uses an indirect reference such as "it",
    "that reminder", or "the previous one", use recent
    conversation history to identify the existing reminder
    and put its identifying text in "reminder_reference".

- For UPDATE:
    "reminder_action" = "update"

    If the user gives a numeric reminder ID, put it in
    "reminder_id".

    If the user names the reminder directly, put the identifying
    reminder text in "reminder_reference".

    If the user uses an indirect reference such as "it",
    "that reminder", or "the previous one", use recent
    conversation history to identify the existing reminder
    and put its identifying text in "reminder_reference".

    Put the new reminder time in "scheduled_at" when provided.

    Put a new reminder title/content in "task" only when the
    user explicitly asks to change the reminder text.

Examples:

User:
"Remind me tomorrow at 10 AM to submit my CV."

Return:

task = "submit my CV"
reminder_action = "create"
reminder_reference = null
reminder_id = null
time = "tomorrow at 10 AM"
scheduled_at = the correct ISO datetime

User:
"Show me my reminders."

Return:

task = null
reminder_action = "list"
reminder_reference = null
reminder_id = null

User:
"Cancel the reminder about my CV."

Return:

task = null
reminder_action = "cancel"
reminder_reference = "my CV"
reminder_id = null

User:
"Complete reminder 8."

Return:

task = null
reminder_action = "complete"
reminder_reference = null
reminder_id = 8

Conversation:

user:
"Remind me tomorrow at 3 PM to review my LangGraph notes."

assistant:
"Done. Your reminder is scheduled."

User:
"Cancel it."

Return:

task = null
reminder_action = "cancel"
reminder_reference = "review my LangGraph notes"
reminder_id = null

Conversation:

user:
"Remind me tomorrow at 3 PM to review my LangGraph notes."

assistant:
"Done. Your reminder is scheduled."

User:
"Move it to 7 PM."

Return:

task = null
reminder_action = "update"
reminder_reference = "review my LangGraph notes"
reminder_id = null
scheduled_at = the correct ISO datetime

Email examples:

User:
"Send an email to hr@example.com with subject Interview Update and tell them I completed the assignment."

Return:

intent = "email"
email_action = "send"
to = ["hr@example.com"]
cc = null
bcc = null
subject = "Interview Update"
body = "I completed the assignment."
requires_tool = true

Task examples:

User:
"Add a high priority task to finish my AI Engineer CV."

Return:

task = "finish my AI Engineer CV"
task_reference = null
task_action = "create"
task_id = null
priority = "high"

Conversation:

user:
"Create a task to practice LangGraph for my interview."

assistant:
"Done. I created the task."

User:
"Complete it."

Return:

task = null
task_reference = "practice LangGraph for my interview"
task_action = "complete"
task_id = null

User:
"Make my LangGraph task high priority."

Return:

task = null
task_reference = "LangGraph"
task_action = "update"
task_id = null
priority = "high"

User:
"Set it for tomorrow at 5 PM."

Return:

task = null
task_reference = "LangGraph"
task_action = "update"
task_id = null
priority = null
scheduled_at = the correct ISO datetime

Important:

- Analyze the CURRENT user message.
- Use history only for conversational context and reference
  resolution.
- Do not confuse old user requests with the current request.
- Do not invent information.
- For existing-task operations, extract a reference whenever
  the user clearly identifies the task directly or indirectly.
- For existing-reminder operations, extract a reference whenever
  the user clearly identifies the reminder directly or indirectly.
- Do not require the user to know numeric IDs.
- Use null when information is genuinely absent.
- Return ONLY valid JSON.
- Do not use markdown.
- Do not add explanations.

For scheduled_at:

- Resolve clear dates and times such as:
  "today at 5 PM"
  "tomorrow at 9 AM"
  "next Monday at 6 PM"
  "in 2 hours"

- Use the current date/time above to calculate relative dates.
- Use the user's timezone: Asia/Karachi.
- Include the timezone offset.
- If a clear datetime is given, return it even if it is
  already in the past.
- The backend separately validates whether the time is allowed.
- Do not invent a time when none was provided.
- If genuinely ambiguous, use null.

Return exactly:

{{
  "intent": "chat|question|advice|planning|reminder|task|action|email|calendar|web",
  "task": "task title, reminder content, or null",
  "task_reference": "existing task reference or null",
  "task_action": "create|list|start|complete|cancel|delete|update or null",
  "task_id": 123,
  "priority": "low|medium|high or null",
  "reminder_action": "create|list|complete|cancel|delete|update or null",
  "reminder_reference": "existing reminder reference or null",
  "reminder_id": 123,
  "time": "original time expression or null",
  "scheduled_at": "ISO datetime with timezone or null",
  "emotion": "happy|sad|angry|stressed|excited|romantic|playful|neutral",
  "tone": "friendly|supportive|playful|romantic|professional|neutral",
  "visual": "none|smile|laugh|hearts|sad|concerned|celebration|thinking|listening|reminder",
  "action": "action description or null",
  "email_action": "send or null",
  "to": "recipient or null",
  "cc": "CC recipient or null",
  "bcc": "BCC recipient or null",
  "subject": "email subject or null",
  "body": "email body or null",
  "requires_tool": true
}}
"""

        response = self.client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": instructions,
                },
                {
                    "role": "user",
                    "content": message,
                },
            ],
        )

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

        if intent not in {
            "chat",
            "question",
            "advice",
        }:
            return result

        normalized = " ".join(
            message.strip().lower().split()
        )

        if not normalized:
            return result

        protected_patterns = (
            r"\bremind me\b",
            r"\b(?:create|add|make)\\s+(?:a\\s+)?(?:high\\s+|medium\\s+|low\\s+)?priority\\s+task\b",
            r"\b(?:create|add|make)\\s+(?:a\\s+)?task\b",
            r"\b(?:show|list|view)\\s+(?:my\\s+)?(?:tasks?|reminders?|calendar|schedule)\b",
            r"\b(?:complete|start|cancel|delete|update|move|reschedule)\\s+(?:my\\s+)?(?:task|reminder|event)\b",
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
            "now",
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
        )

        has_information_marker = any(
            marker in normalized
            for marker in information_markers
        )

        if not has_information_marker:
            return result

        topic = result.get("web_topic")

        if "news" in normalized or "headline" in normalized:
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

        if any(
            marker in normalized
            for marker in (
                "today",
                "today's",
                "right now",
                "now",
                "live",
                "realtime",
                "real time",
            )
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

        result["intent"] = "web"
        result["web_action"] = "search"
        result["web_topic"] = topic or "general"
        result["web_time_range"] = time_range
        result["query"] = query or None
        result["action"] = "search"
        result["requires_tool"] = True

        return result

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
            "to": None,
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
        to = result.get("to")
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

        if email_action != "send":
            email_action = None

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
            to = None
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

        if intent == "web":
            if web_action != "search":
                web_action = "search"

            if web_topic not in {
                "general",
                "news",
                "finance",
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
            "to": to,
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
            "requires_tool": requires_tool,
        }