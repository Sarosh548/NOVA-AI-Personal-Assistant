import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI


MODEL_NAME = "openai/gpt-oss-20b"
USER_TIMEZONE = "Asia/Karachi"


class IntentService:
    def __init__(self):
        groq_api_key = os.getenv("GROQ_API_KEY")

        if not groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set.")

        self.client = OpenAI(
            api_key=groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )

    def analyze(self, message: str) -> dict:
        """
        Understand the user's intent, emotion, tone, visual,
        task information, reminder timing, and possible action.
        """

        if not message.strip():
            return self._default_result()

        now = datetime.now(
            ZoneInfo(USER_TIMEZONE)
        )

        current_datetime = now.isoformat(
            timespec="minutes"
        )

        instructions = f"""
You are NOVA's understanding system.

Analyze ONLY the user's message.

Current date and time:
{current_datetime}

User timezone:
{USER_TIMEZONE}

Choose exactly one intent:

- "chat"       = casual conversation
- "question"   = asking for information
- "advice"     = asking what they should do
- "planning"   = creating or organizing a plan
- "reminder"   = asking NOVA to remind them
- "task"       = asking NOVA to create, view, start, complete,
                 cancel, or delete a task
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
    Example:
    User: "Remind me tomorrow at 10 AM to submit my CV."
    task = "submit my CV"

    For existing-task actions, this may be null.

- task_reference:
    A short natural-language reference to an EXISTING task when
    the user wants to start, complete, cancel, or delete a task
    without giving a numeric task ID.
    Extract the identifying part of the task title.

- task_action:
    "create"
    "list"
    "start"
    "complete"
    "cancel"
    "delete"
    or null when not a task request

- task_id:
    numeric task ID if explicitly given,
    otherwise null

- priority:
    "low"
    "medium"
    "high"
    or null when not provided

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
    put the new task title in "task".
    "task_reference" should be null.

- For LIST:
    "task_reference" should normally be null.

- For START / COMPLETE / CANCEL / DELETE:
    if the user gives a numeric ID, put it in task_id.
    If the user names the task instead, put the identifying
    task name in task_reference.

Reminder rules:

- The reminder message/content MUST be stored in "task".
- Do not leave "task" null when the user clearly tells you
  what they want to be reminded about.
- "action" may contain a short description too, but "task"
  is the canonical reminder title.

Examples:

User:
"Add a high priority task to finish my AI Engineer CV."

Return:

task = "finish my AI Engineer CV"
task_reference = null
task_action = "create"
task_id = null
priority = "high"

User:
"I finished my AI Engineer CV task. Mark it as completed."

Return:

task = null
task_reference = "AI Engineer CV"
task_action = "complete"
task_id = null

User:
"Complete task 3."

Return:

task = null
task_reference = null
task_action = "complete"
task_id = 3

User:
"Cancel my gym task."

Return:

task = null
task_reference = "gym"
task_action = "cancel"
task_id = null

User:
"Show me my pending tasks."

Return:

task = null
task_reference = null
task_action = "list"
task_id = null

User:
"Remind me tomorrow at 10 AM to submit my CV."

Return:

task = "submit my CV"
task_reference = null
task_action = null
task_id = null
priority = null
time = "tomorrow at 10 AM"
scheduled_at = the correct ISO datetime
action = "reminder to submit my CV"

Important:

- Do not invent information.
- For existing-task operations, extract a reference whenever
  the user clearly identifies the task by name.
- Do not require the user to know the numeric task ID.
- Use null when the information is genuinely absent.
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
  "task_action": "create|list|start|complete|cancel|delete or null",
  "task_id": 123,
  "priority": "low|medium|high or null",
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

        return self._validate_result(result)

    def _default_result(self) -> dict:
        return {
            "intent": "chat",
            "task": None,
            "task_reference": None,
            "task_action": None,
            "task_id": None,
            "priority": None,
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
                normalized = normalized[len(prefix):].strip()
                break

        return normalized or None

    def _validate_result(self, result: dict) -> dict:
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
        task_reference = result.get("task_reference")
        task_action = result.get("task_action")
        task_id = result.get("task_id")
        priority = result.get("priority")
        time = result.get("time")
        scheduled_at = result.get("scheduled_at")
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

        if time is not None:
            time = str(time).strip() or None

        if scheduled_at is not None:
            scheduled_at = str(
                scheduled_at
            ).strip() or None

        if action is not None:
            action = str(action).strip() or None

        # -------------------------------------------------
        # Normalize reminder content.
        #
        # Reminder text is stored in `task` because the
        # reminder tool uses that field as its title.
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
            "time": time,
            "scheduled_at": scheduled_at,
            "emotion": emotion,
            "tone": tone,
            "visual": visual,
            "action": action,
            "requires_tool": requires_tool,
        }