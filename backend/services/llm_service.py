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

    def extract_memory(self, message: str) -> str | None:
        memory_instructions = """
You are NOVA's memory extraction system.

Read the user's message and decide whether it contains a useful
long-term personal fact that could improve future conversations.

Save facts such as:
- name
- long-term goals
- stable preferences
- important recurring interests
- ongoing projects
- useful personal context

Do NOT save:
- ordinary questions
- greetings
- temporary thoughts
- requests
- one-time statements that are not useful later
- information that is not about the user

If there is a useful long-term fact, return ONLY the fact as one short sentence.

If there is nothing worth remembering, return exactly:
NONE
"""

        response = self.client.responses.create(
            model="openai/gpt-oss-20b",
            instructions=memory_instructions,
            input=message,
        )

        memory = response.output_text.strip()

        if memory.upper() == "NONE":
            return None

        return memory