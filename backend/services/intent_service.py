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
  "intent": "chat|question|advice|planning|reminder|task|action",
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

        if scheduled_at is not None:
            scheduled_at = (
                str(scheduled_at).strip()
                or None
            )

        if action is not None:
            action = str(action).strip() or None

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
            "requires_tool": requires_tool,
        }