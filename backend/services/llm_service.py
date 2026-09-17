import json
import os

from openai import OpenAI

from services.personality_service import NOVA_PERSONALITY


MODEL_NAME = "openai/gpt-oss-20b"


class LLMService:
    def __init__(self):
        groq_api_key = os.getenv("GROQ_API_KEY")

        if not groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set.")

        self.client = OpenAI(
            api_key=groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )

    # =========================================================
    # Internal helper
    # =========================================================

    def _chat_completion(
        self,
        instructions: str,
        user_input: str,
    ) -> str:
        """
        Safely generate plain text from explicit system
        instructions and user input.

        This is the provider-level boundary used by NOVA's
        different LLM capabilities.
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
                    "content": user_input,
                },
            ],
        )

        content = response.choices[0].message.content

        if not content:
            return ""

        return content.strip()

    # =========================================================
    # Generic instruction-driven generation
    # =========================================================

    def generate_with_instructions(
        self,
        *,
        instructions: str,
        user_input: str,
    ) -> str:
        """
        Generate a response using caller-provided instructions.

        This is intended for specialized NOVA LLM capabilities
        such as:
        - planning
        - structured reasoning
        - classification
        - extraction
        - future agent workflows

        Unlike generate_response(), this method does not inject
        NOVA's conversational response rules.
        """

        return self._chat_completion(
            instructions=instructions,
            user_input=user_input,
        )

    # =========================================================
    # Normal NOVA response
    # =========================================================

    def generate_response(self, message: str) -> str:
        """
        Generate NOVA's normal conversational response.

        No tools are exposed here yet.
        Tool execution will be handled by a dedicated tool layer.
        """

        instructions = f"""
{NOVA_PERSONALITY}

You are generating NOVA's conversational response.

IMPORTANT:
- Respond only with normal text.
- Do not call tools.
- Do not output tool calls.
- Do not output JSON unless the user explicitly asks for JSON.
- Do not pretend that an action was executed when no tool is available.
- If the user asks for an action that is not currently available,
  respond naturally and honestly.
"""

        return self._chat_completion(
            instructions=instructions,
            user_input=message,
        )

    # =========================================================
    # Memory extraction
    # =========================================================

    def extract_memory(
        self,
        message: str,
    ) -> dict | None:
        """
        Extract a useful long-term personal memory.
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

        raw_output = self._chat_completion(
            instructions=memory_instructions,
            user_input=message,
        )

        try:
            result = json.loads(raw_output)
        except json.JSONDecodeError:
            return None

        if not isinstance(result, dict):
            return None

        memory_text = result.get("memory_text")
        category = result.get("category")
        importance = result.get("importance")

        if not memory_text:
            return None

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

        valid_importance = {
            "high",
            "medium",
            "low",
        }

        if importance not in valid_importance:
            importance = "medium"

        return {
            "memory_text": str(memory_text).strip(),
            "category": category,
            "importance": importance,
        }

    # =========================================================
    # Memory conflict resolver
    # =========================================================

    def resolve_memory_conflict(
        self,
        new_memory: str,
        new_category: str,
        existing_memory: str,
    ) -> str:
        """
        Decide how a new memory relates to existing memories.

        Returns:
            DUPLICATE
            UPDATE
            KEEP
        """

        conflict_instructions = f"""
You are NOVA's long-term memory decision system.

Your task is to compare a NEW personal memory with
one or more EXISTING personal memories.

Existing memories:
{existing_memory}

New memory:
{new_memory}

Category:
{new_category}

You MUST choose exactly ONE action:

DUPLICATE
Use DUPLICATE when the new memory expresses the same
underlying fact as an existing memory, even when the
wording is different.

Example:
Existing:
User wants to become a machine learning engineer.

New:
My goal is to become a machine learning engineer.

Decision:
DUPLICATE

UPDATE
Use UPDATE only when the new memory clearly changes,
corrects, or replaces an existing fact.

The new memory must provide evidence of a change,
correction, or replacement.

Example:
Existing:
User wants to become a machine learning engineer.

New:
I changed my goal and now want to become a Data Scientist.

Decision:
UPDATE

KEEP
Use KEEP when the new memory is a separate fact that
can remain true together with the existing memory.

Example:
Existing:
User wants to become a machine learning engineer.

New:
My goal is to become a Data Scientist.

Decision:
KEEP

IMPORTANT RULES:

- Semantic similarity alone does NOT mean DUPLICATE.
- Related topics do NOT automatically mean DUPLICATE.
- Similar goals, careers, technologies, projects, or interests
  can be separate facts.
- Do NOT use UPDATE unless the new memory clearly indicates
  that the old fact has changed, been corrected, or replaced.
- When uncertain between UPDATE and KEEP, prefer KEEP.
- When the facts clearly describe the same underlying fact,
  use DUPLICATE.
- Consider the meaning of the facts, not just the wording.

Return ONLY one word:

DUPLICATE
UPDATE
KEEP
"""

        decision = self._chat_completion(
            instructions=conflict_instructions,
            user_input="Resolve the memory relationship.",
        )

        decision = decision.strip().upper()

        if decision == "DUPLICATE":
            return "DUPLICATE"

        if decision == "UPDATE":
            return "UPDATE"

        return "KEEP"

    # =========================================================
    # Conversation title
    # =========================================================

    def generate_conversation_title(
        self,
        message: str,
    ) -> str:
        """
        Generate a short human-friendly conversation title.
        """

        title_instructions = """
You create short titles for NOVA conversations.

Read the user's first message and create ONE concise title
that describes the main topic.

Rules:
- Maximum 6 words.
- Use normal title-style wording.
- Do not use quotation marks.
- Do not use emojis.
- Do not mention NOVA unless NOVA itself is the main topic.
- Do not add explanations.
- Return ONLY the title.

Examples:

User:
I want to make a study plan for Germany.

Title:
Germany Study Plan

User:
Help me fix my FastAPI memory system.

Title:
Fixing FastAPI Memory

User:
I want to talk about my AI career.

Title:
AI Career Planning
"""

        title = self._chat_completion(
            instructions=title_instructions,
            user_input=message,
        )

        if not title:
            return "New Conversation"

        return title[:200]