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
        task, time, and possible action.
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
- "task"       = asking NOVA to manage or track a task
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

- task: short description of what the user wants, or null
- time: user's original time expression, or null
- scheduled_at: exact ISO 8601 datetime in the user's timezone,
  or null when no schedule exists
- action: short external action description, or null
- requires_tool: true for reminders or external actions,
  otherwise false

For scheduled_at:

- Resolve unambiguous dates and times such as:
  "today at 5 PM"
  "tomorrow at 9 AM"
  "next Monday at 6 PM"
  "in 2 hours"

- Use the current date/time above to calculate relative dates.
- Use the user's timezone: Asia/Karachi.
- Include the timezone offset.

IMPORTANT:

- If the user gives a clear date/time, return the exact datetime
  even if that datetime is already in the past.
- Do NOT change a clear past datetime to null.
- The backend will separately validate whether the reminder time
  is in the future.
- Do not invent a time when none was provided.
- If the date/time is genuinely ambiguous, use null.

Examples:

User message:
"Remind me today at 5 PM to test NOVA."

Return scheduled_at as the exact 5 PM datetime for today,
even if the current time is already after 5 PM.

User message:
"Remind me tomorrow at 5 PM to test NOVA."

Return tomorrow's 5 PM datetime.

Important:

- Do not invent information.
- Use null when information is not present.
- Return ONLY valid JSON.
- Do not use markdown.
- Do not add explanations.

Return exactly:

{{
  "intent": "chat|question|advice|planning|reminder|task|action",
  "task": "short description or null",
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
            "time": None,
            "scheduled_at": None,
            "emotion": "neutral",
            "tone": "friendly",
            "visual": "none",
            "action": None,
            "requires_tool": False,
        }

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
        time = result.get("time")
        scheduled_at = result.get("scheduled_at")
        action = result.get("action")

        if task is not None:
            task = str(task).strip() or None

        if time is not None:
            time = str(time).strip() or None

        if scheduled_at is not None:
            scheduled_at = str(
                scheduled_at
            ).strip() or None

        if action is not None:
            action = str(action).strip() or None

        # Backend-level safety rule:
        # reminders and actions always require a tool.
        requires_tool = intent in {
            "reminder",
            "action",
        }

        return {
            "intent": intent,
            "task": task,
            "time": time,
            "scheduled_at": scheduled_at,
            "emotion": emotion,
            "tone": tone,
            "visual": visual,
            "action": action,
            "requires_tool": requires_tool,
        }