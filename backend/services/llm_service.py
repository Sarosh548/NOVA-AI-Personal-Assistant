import json
import os

from openai import OpenAI

from services.personality_service import NOVA_PERSONALITY


class LLMService:
    def __init__(self):
        groq_api_key = os.getenv("GROQ_API_KEY")

        if not groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set.")

        self.client = OpenAI(
            api_key=groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )

    def generate_response(self, message: str) -> str:
        response = self.client.responses.create(
            model="openai/gpt-oss-20b",
            instructions=NOVA_PERSONALITY,
            input=message,
        )

        return response.output_text

    def extract_memory(self, message: str) -> dict | None:
        """
        Extract a useful long-term personal memory from the user's message.

        Returns:
            {
                "memory_text": str,
                "category": str,
                "importance": str
            }

        Or None when there is nothing worth remembering.
        """

        memory_instructions = """
You are NOVA's long-term memory extraction system.

Analyze ONLY the user's message.

Your job is to determine whether the message contains
a useful long-term personal fact that could improve
future conversations.

SAVE useful long-term facts such as:
- user's name
- long-term goals
- stable preferences
- ongoing projects
- important recurring interests
- useful personal context

DO NOT SAVE:
- greetings
- ordinary questions
- temporary feelings or thoughts
- requests
- commands
- one-time information with no future value
- information that is not about the user

Choose exactly one category:

- "identity"       for name or personal identity facts
- "goal"           for long-term goals or ambitions
- "preference"     for stable likes, dislikes, or preferences
- "project"        for ongoing projects or work
- "interest"       for recurring interests
- "context"        for other useful long-term personal context

Choose exactly one importance:

- "high"   = very useful for future conversations
- "medium" = useful but not critical
- "low"    = mildly useful

Return ONLY valid JSON.

When there is a useful memory, return:

{
  "memory_text": "one short clear sentence",
  "category": "identity|goal|preference|project|interest|context",
  "importance": "high|medium|low"
}

When there is nothing worth remembering, return exactly:

{
  "memory_text": null,
  "category": null,
  "importance": null
}

Do not add markdown.
Do not add explanations.
"""

        response = self.client.responses.create(
            model="openai/gpt-oss-20b",
            instructions=memory_instructions,
            input=message,
        )

        raw_output = response.output_text.strip()

        try:
            result = json.loads(raw_output)
        except json.JSONDecodeError:
            return None

        if not isinstance(result, dict):
            return None

        memory_text = result.get("memory_text")
        category = result.get("category")
        importance = result.get("importance")

        # No useful memory
        if not memory_text:
            return None

        # Validate category
        valid_categories = {
            "identity",
            "goal",
            "preference",
            "project",
            "interest",
            "context",
        }

        if category not in valid_categories:
            category = "context"

        # Validate importance
        valid_importance = {
            "high",
            "medium",
            "low",
        }

        if importance not in valid_importance:
            importance = "medium"

        return {
            "memory_text": memory_text.strip(),
            "category": category,
            "importance": importance,
        }

    def resolve_memory_conflict(
        self,
        new_memory: str,
        new_category: str,
        existing_memory: str,
    ) -> str:
        """
        Decide whether a new memory conflicts with an existing memory.

        Returns:
            "UPDATE" when the new fact replaces or changes the old fact.
            "KEEP" when both facts can remain true.
        """

        conflict_instructions = f"""
You are NOVA's memory conflict resolver.

Compare these two personal memory facts.

Existing memory:
{existing_memory}

New memory:
{new_memory}

Category:
{new_category}

Return ONLY one word:

UPDATE
Use UPDATE when the new fact clearly replaces, changes,
or corrects the existing fact.

KEEP
Use KEEP when both facts can remain true together,
or when there is no clear conflict.

Examples:

Existing:
I prefer Python.

New:
I now prefer Java for my projects.

Answer:
UPDATE

Existing:
I use Python for AI projects.

New:
I use Java for Android development.

Answer:
KEEP

Do not add explanations.
"""

        response = self.client.responses.create(
            model="openai/gpt-oss-20b",
            instructions=conflict_instructions,
            input="Resolve the memory conflict.",
        )

        decision = response.output_text.strip().upper()

        if decision == "UPDATE":
            return "UPDATE"

        return "KEEP"