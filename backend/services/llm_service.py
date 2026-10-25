import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from collections.abc import Iterator

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from config import (
    LLMSettings,
    get_llm_settings,
)
from services.personality_service import NOVA_PERSONALITY


MODEL_NAME = "openai/gpt-oss-20b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

logger = logging.getLogger(__name__)

# Shared across graph, intent, and companion LLMService instances in this process.
_PROVIDER_COOLDOWN_LOCK = threading.Lock()
_PROVIDER_REQUEST_LOCK = threading.Lock()
_provider_cooldown_until = 0.0


class LLMProviderCoolingDownError(RuntimeError):
    """Raised locally while the provider's rate-limit cooldown is active."""


class LLMEmptyResponseError(RuntimeError):
    """Raised when the provider returns no usable text completion."""


def check_llm_provider_available() -> None:
    with _PROVIDER_COOLDOWN_LOCK:
        remaining = _provider_cooldown_until - time.monotonic()
    if remaining > 0:
        raise LLMProviderCoolingDownError(
            f"AI service is rate-limited; retry in about {max(1, int(remaining))} seconds."
        )


def acquire_llm_provider_slot() -> None:
    """Acquire the single local provider slot without queueing or waiting."""
    check_llm_provider_available()
    if not _PROVIDER_REQUEST_LOCK.acquire(blocking=False):
        raise LLMProviderCoolingDownError(
            "The AI service is busy with another request. Please retry shortly; "
            "no action has been taken."
        )
    try:
        check_llm_provider_available()
    except Exception:
        _PROVIDER_REQUEST_LOCK.release()
        raise


def release_llm_provider_slot() -> None:
    _PROVIDER_REQUEST_LOCK.release()


def _release_provider_slot_when_stream_finishes(stream):
    try:
        yield from stream
    finally:
        release_llm_provider_slot()


MAX_PROVIDER_COOLDOWN_SECONDS = 24 * 60 * 60


def _parse_retry_delay(value) -> float | None:
    """Parse numeric seconds, provider duration strings, or HTTP-date headers."""
    if value is None:
        return None
    text = str(value).strip()
    try:
        return max(0.0, float(text))
    except (TypeError, ValueError):
        pass

    duration = re.fullmatch(
        r"(?:(\d+(?:\.\d+)?)m)?\s*(\d+(?:\.\d+)?)s",
        text,
        flags=re.IGNORECASE,
    )
    if duration:
        return float(duration.group(1) or 0) * 60 + float(duration.group(2))

    try:
        reset_at = parsedate_to_datetime(text)
        if reset_at.tzinfo is None:
            reset_at = reset_at.replace(tzinfo=timezone.utc)
        return max(0.0, (reset_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def record_llm_rate_limit(exc: Exception) -> None:
    """Honor provider cooldown hints so quota-exhausted calls do not resume too early."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    delay_hints: list[float] = []

    if headers is not None:
        # Different limits may reset at different times (e.g. TPM in seconds
        # and TPD in minutes). Honor the longest valid provider hint.
        for header in (
            "retry-after",
            "x-ratelimit-reset-tokens",
            "x-ratelimit-reset-requests",
        ):
            candidate = _parse_retry_delay(headers.get(header))
            if candidate is not None:
                delay_hints.append(candidate)

    # Some providers put the longer quota reset only in the error body.
    match = re.search(
        r"(?:try again|retry) in\s+((?:\d+(?:\.\d+)?m)?\s*\d+(?:\.\d+)?s)",
        str(exc),
        flags=re.IGNORECASE,
    )
    if match:
        candidate = _parse_retry_delay(match.group(1))
        if candidate is not None:
            delay_hints.append(candidate)

    delay = max(delay_hints) if delay_hints else 10.0

    # Do not clamp a real multi-minute/hour reset down to one minute; doing so
    # causes repeated 429s and burns more daily quota. Cap only pathological hints.
    delay = min(max(delay, 1.0), MAX_PROVIDER_COOLDOWN_SECONDS)
    with _PROVIDER_COOLDOWN_LOCK:
        global _provider_cooldown_until
        _provider_cooldown_until = max(
            _provider_cooldown_until,
            time.monotonic() + delay,
        )
    logger.warning(
        "LLM provider rate limit received; suppressing new calls for %.1f seconds.",
        delay,
    )


# Conservative bounds for the current 8K TPM tier. Character counts are a
# heuristic, so leave meaningful headroom for tokenization and completion budget.
MAX_LLM_PROMPT_CHARACTERS = 8_000
MAX_PINNED_USER_MESSAGE_CHARACTERS = 2_000
MAX_PINNED_WEB_SOURCE_CHARACTERS = 3_200
DEFAULT_MAX_COMPLETION_TOKENS = 512
LLM_PROVIDER_UNAVAILABLE_RESPONSE = (
    "I'm having a temporary connection issue with my AI service right now. "
    "I haven't taken any action. Please try again in a moment."
)


def _truncate_middle(text: str, max_characters: int) -> str:
    """Bound large input while retaining its opening and most recent details."""

    if len(text) <= max_characters:
        return text

    marker = (
        "\n\n[Middle context omitted to stay within the model's safe input budget.]"
        "\n\n"
    )
    if max_characters <= len(marker):
        return text[:max_characters]

    remaining = max_characters - len(marker)
    head_length = remaining // 2
    tail_length = remaining - head_length
    return (
        text[:head_length]
        + marker
        + (text[-tail_length:] if tail_length else "")
    )


def _bound_prompt(
    instructions: str,
    user_input: str,
) -> tuple[str, str]:
    """
    Bound prompt size while protecting the current request and retrieved web
    evidence from middle truncation. Older conversational/tool context is the
    first material trimmed when the provider budget is tight.
    """

    if len(instructions) >= MAX_LLM_PROMPT_CHARACTERS:
        instructions = _truncate_middle(
            instructions,
            MAX_LLM_PROMPT_CHARACTERS // 2,
        )

    pinned_user_section = ""
    pinned_web_section = ""

    # Keep the explicit current request even if the surrounding context is
    # too large. The rest of the graph prompt can be shortened independently.
    user_start_marker = "Current user message:\n"
    user_end_marker = "\n\nSingle-step tool result:"
    user_start = user_input.find(user_start_marker)
    if user_start >= 0:
        user_end = user_input.find(
            user_end_marker,
            user_start + len(user_start_marker),
        )
        if user_end >= 0:
            pinned_user_section = user_input[
                user_start:user_end
            ].strip()
            user_input = (
                user_input[:user_start]
                + user_input[user_end:]
            )

    # The web grounding section is bounded upstream to a few sources and
    # short snippets. Pin it after other context so truncation cannot silently
    # remove the very evidence NOVA must use to answer a current-information
    # request.
    web_start_marker = "Live web search sources:\n"
    web_end_marker = "\n\nLive web source metadata:"
    web_start = user_input.find(web_start_marker)
    if web_start >= 0:
        web_end = user_input.find(
            web_end_marker,
            web_start + len(web_start_marker),
        )
        if web_end >= 0:
            candidate = user_input[web_start:web_end].strip()
            if "[Web Source " in candidate:
                pinned_web_section = candidate
                user_input = (
                    user_input[:web_start]
                    + user_input[web_end:]
                )

                # Structured source metadata is returned separately by NOVA;
                # the prompt only needs the source labels and bounded evidence.
                metadata_start = user_input.find(
                    "\n\nLive web source metadata:"
                )
                if metadata_start >= 0:
                    metadata_end = user_input.find(
                        "\n\nWorkflow result:",
                        metadata_start,
                    )
                    if metadata_end >= 0:
                        user_input = (
                            user_input[:metadata_start]
                            + user_input[metadata_end:]
                        )

    # Preserve the response rules at the end of the graph prompt. Source
    # content stays before those rules so retrieved text cannot override them.
    pinned_rules_section = ""
    rules_marker = "\n\nResponse rules:"
    rules_start = user_input.find(rules_marker)
    if rules_start >= 0:
        pinned_rules_section = user_input[rules_start:].strip()
        user_input = user_input[:rules_start]

    if pinned_user_section:
        pinned_user_section = _truncate_middle(
            pinned_user_section,
            MAX_PINNED_USER_MESSAGE_CHARACTERS,
        )
    if pinned_web_section:
        pinned_web_section = _truncate_middle(
            pinned_web_section,
            MAX_PINNED_WEB_SOURCE_CHARACTERS,
        )

    pinned_sections = [
        section
        for section in (
            pinned_user_section,
            pinned_web_section,
            pinned_rules_section,
        )
        if section
    ]
    pinned_context = "\n\n".join(pinned_sections)

    user_budget = max(
        0,
        MAX_LLM_PROMPT_CHARACTERS - len(instructions),
    )
    separator_size = 2 if pinned_context else 0
    body_budget = max(
        0,
        user_budget - len(pinned_context) - separator_size,
    )
    bounded_body = _truncate_middle(
        user_input,
        body_budget,
    )
    bounded_input = (
        bounded_body.rstrip()
        + ("\n\n" if bounded_body.strip() and pinned_context else "")
        + pinned_context
    )

    # A defensive final check keeps this invariant true even if later prompt
    # sections or model instructions grow.
    if len(instructions) + len(bounded_input) > MAX_LLM_PROMPT_CHARACTERS:
        overflow = (
            len(instructions)
            + len(bounded_input)
            - MAX_LLM_PROMPT_CHARACTERS
        )
        if pinned_web_section and len(pinned_web_section) > overflow:
            pinned_web_section = _truncate_middle(
                pinned_web_section,
                len(pinned_web_section) - overflow,
            )
            pinned_context = "\n\n".join(
                section
                for section in (
                    pinned_user_section,
                    pinned_web_section,
                    pinned_rules_section,
                )
                if section
            )
            bounded_input = (
                bounded_body.rstrip()
                + ("\n\n" if bounded_body.strip() and pinned_context else "")
                + pinned_context
            )
        if len(instructions) + len(bounded_input) > MAX_LLM_PROMPT_CHARACTERS:
            remaining = max(
                0,
                MAX_LLM_PROMPT_CHARACTERS - len(instructions),
            )
            bounded_input = _truncate_middle(
                bounded_input,
                remaining,
            )

    return instructions, bounded_input


def is_llm_provider_error(exc: Exception) -> bool:
    """
    Return True only for provider/network failures that NOVA can safely
    surface as a temporary capability outage.

    Programming and validation errors intentionally remain uncaught so real
    application defects are not hidden behind a generic fallback response.
    """

    if isinstance(
        exc,
        (
            APIConnectionError,
            APITimeoutError,
            RateLimitError,
            LLMProviderCoolingDownError,
            LLMEmptyResponseError,
        ),
    ):
        return True

    # Groq can report the TPM/context budget rejection as HTTP 413 with
    # an APIStatusError (rather than RateLimitError). Treat this as a
    # recoverable provider failure so grounded web results can still be used.
    return (
        isinstance(exc, APIStatusError)
        and (
            exc.status_code == 413
            or exc.status_code >= 500
        )
    )


class LLMService:
    def __init__(
        self,
        *,
        client=None,
        settings: LLMSettings | None = None,
    ):
        active_settings = (
            settings
            if settings is not None
            else get_llm_settings()
        )

        if client is not None:
            self.client = client
            self.voice_client = client
            self.settings = active_settings
            return

        groq_api_key = os.getenv("GROQ_API_KEY")

        if not groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set.")

        self.client = OpenAI(
            api_key=groq_api_key,
            base_url=GROQ_BASE_URL,
            timeout=min(
                active_settings.llm_request_timeout_seconds,
                10.0,
            ),
            # No SDK retries: NOVA records 429 cooldowns and fails fast.
            max_retries=0,
        )
        self.voice_client = OpenAI(
            api_key=groq_api_key,
            base_url=GROQ_BASE_URL,
            timeout=min(
                active_settings.llm_request_timeout_seconds,
                10.0,
            ),
            # Realtime voice uses the same explicit retry boundary,
            # with the stream path controlling its smaller attempt budget.
            max_retries=0,
        )

        self.settings = active_settings

    # =========================================================
    # Internal helper
    # =========================================================

    def _chat_messages(
        self,
        instructions: str,
        user_input: str,
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": instructions,
            },
            {
                "role": "user",
                "content": user_input,
            },
        ]

    @staticmethod
    def _retry_after_seconds(
        exc: Exception,
        *,
        default_seconds: float = 2.0,
    ) -> float:
        """Read a provider Retry-After hint without exposing provider details."""

        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)

        hints: list[float] = []
        if headers is not None:
            for header in (
                "retry-after",
                "x-ratelimit-reset-tokens",
                "x-ratelimit-reset-requests",
            ):
                parsed = _parse_retry_delay(headers.get(header))
                if parsed is not None:
                    hints.append(parsed)

        match = re.search(
            r"(?:try again|retry) in\s+((?:\d+(?:\.\d+)?m)?\s*\d+(?:\.\d+)?s)",
            str(exc),
            flags=re.IGNORECASE,
        )
        if match:
            parsed = _parse_retry_delay(match.group(1))
            if parsed is not None:
                hints.append(parsed)

        if hints:
            return min(max(max(hints), 0.25), MAX_PROVIDER_COOLDOWN_SECONDS)
        return min(max(default_seconds, 0.25), MAX_PROVIDER_COOLDOWN_SECONDS)

    def _provider_completion(
        self,
        completion_kwargs: dict,
        *,
        client=None,
        max_attempts: int | None = None,
    ):
        """Make one bounded provider request; never amplify 429s with nested retries."""

        active_client = client if client is not None else self.client
        acquire_llm_provider_slot()

        try:
            response = active_client.chat.completions.create(**completion_kwargs)
        except RateLimitError as exc:
            record_llm_rate_limit(exc)
            release_llm_provider_slot()
            raise
        except Exception:
            release_llm_provider_slot()
            raise

        if completion_kwargs.get("stream") is True:
            # Keep the slot through the entire stream, not just response setup.
            return _release_provider_slot_when_stream_finishes(response)

        release_llm_provider_slot()
        return response

    def _chat_completion(
        self,
        instructions: str,
        user_input: str,
        *,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
        include_reasoning: bool | None = None,
    ) -> str:
        """
        Safely generate plain text from explicit system
        instructions and user input.

        This is the provider-level boundary used by NOVA's
        different LLM capabilities.
        """

        instructions, user_input = _bound_prompt(
            instructions,
            user_input,
        )
        completion_kwargs = {
            "model": MODEL_NAME,
            "messages": self._chat_messages(
                instructions,
                user_input,
            ),
            "max_completion_tokens": min(
                max(
                    1,
                    int(
                        max_completion_tokens
                        if max_completion_tokens is not None
                        else DEFAULT_MAX_COMPLETION_TOKENS
                    ),
                ),
                DEFAULT_MAX_COMPLETION_TOKENS,
            ),
        }

        if reasoning_effort is not None:
            completion_kwargs["reasoning_effort"] = reasoning_effort

        if include_reasoning is not None:
            completion_kwargs["include_reasoning"] = include_reasoning

        response = self._provider_completion(
            completion_kwargs,
        )

        content = str(response.choices[0].message.content or "").strip()

        if not content:
            raise LLMEmptyResponseError(
                "The AI provider returned an empty completion."
            )

        return content

    def _chat_completion_stream(
        self,
        instructions: str,
        user_input: str,
        *,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
        include_reasoning: bool | None = None,
        client=None,
    ) -> Iterator[str]:
        """
        Stream non-empty text deltas from an LLM chat completion.

        The underlying SDK call remains synchronous so existing NOVA
        callers can continue using the current client boundary. Async
        transports can consume this iterator from a worker thread.
        """

        instructions, user_input = _bound_prompt(
            instructions,
            user_input,
        )
        completion_kwargs = {
            "model": MODEL_NAME,
            "messages": self._chat_messages(
                instructions,
                user_input,
            ),
            "stream": True,
            "max_completion_tokens": min(
                max(
                    1,
                    int(
                        max_completion_tokens
                        if max_completion_tokens is not None
                        else DEFAULT_MAX_COMPLETION_TOKENS
                    ),
                ),
                DEFAULT_MAX_COMPLETION_TOKENS,
            ),
        }

        if reasoning_effort is not None:
            completion_kwargs["reasoning_effort"] = reasoning_effort

        if include_reasoning is not None:
            completion_kwargs["include_reasoning"] = include_reasoning

        stream_attempts = (
            2
            if client is not None and client is self.voice_client
            else self.settings.llm_max_retries + 1
        )

        stream = self._provider_completion(
            completion_kwargs,
            client=client,
            max_attempts=stream_attempts,
        )

        for chunk in stream:
            choices = getattr(
                chunk,
                "choices",
                None,
            )

            if not choices:
                continue

            delta = getattr(
                choices[0],
                "delta",
                None,
            )

            if delta is None:
                continue

            content = getattr(
                delta,
                "content",
                None,
            )

            if content:
                yield str(content)

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

    def generate_with_instructions_stream(
        self,
        *,
        instructions: str,
        user_input: str,
    ) -> Iterator[str]:
        """
        Stream a response using caller-provided instructions.
        """

        return self._chat_completion_stream(
            instructions=instructions,
            user_input=user_input,
        )

    # =========================================================
    # Normal NOVA response
    # =========================================================

    @staticmethod
    def _response_instructions() -> str:
        return f"""
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

    def generate_response(self, message: str) -> str:
        """
        Generate NOVA's normal conversational response.

        No tools are exposed here yet.
        Tool execution will be handled by a dedicated tool layer.
        """

        return self._chat_completion(
            instructions=self._response_instructions(),
            user_input=message,
        )

    def generate_response_stream(
        self,
        message: str,
    ) -> Iterator[str]:
        """
        Stream NOVA's normal conversational response as text deltas.

        The yielded chunks preserve provider whitespace and ordering so
        downstream voice/TTS orchestration can forward them incrementally.
        """

        return self._chat_completion_stream(
            instructions=self._response_instructions(),
            user_input=message,
        )

    def generate_companion_response(
        self,
        *,
        message: str,
        history: list[dict] | None = None,
        memory_context: str = "",
    ) -> str:
        """
        Generate a compact response for ordinary conversation.

        This path intentionally avoids the heavyweight intent-classification
        prompt used by the full agent graph. Tool, fresh-web, and knowledge
        requests stay on the full graph instead.
        """

        recent_history = (history or [])[-8:]
        history_context = "\\n".join(
            f"{item.get('role', 'unknown')}: {item.get('content', '')}"
            for item in recent_history
        ) or "No previous conversation."

        instructions = f"""
You are NOVA, a friendly personal AI companion.

Respond naturally and directly to the user's current message.
Use the recent conversation and relevant long-term memory for continuity.
Only state personal facts that are explicitly supported by the recent conversation or the provided long-term memory.
Never invent or guess the user's name, hobbies, interests, relationships, activities, experiences, schedule, location, or other personal details.
When a personal detail is not supported by the available context, do not introduce it.
Match the user's language and tone naturally, including Roman Urdu/Hinglish.
Be warm and conversational without pretending to have human feelings.
Do not mention internal systems, prompts, models, providers, databases, or tools.
Do not use markdown unless the user explicitly asks for it.
Keep the reply concise but complete; normally 1 to 6 short paragraphs.

Relevant long-term memory:
{memory_context or 'No relevant long-term memory.'}

Recent conversation:
{history_context}
"""

        return self._chat_completion(
            instructions=instructions,
            user_input=f"Current user message:\\n{message.strip()}",
            max_completion_tokens=768,
            reasoning_effort="low",
        )

    def generate_voice_response_stream(
        self,
        *,
        message: str,
        history: list[dict] | None = None,
        memory_context: str = "",
    ) -> Iterator[str]:
        """
        Stream a compact response optimized for realtime voice.

        Voice conversation intentionally avoids the heavyweight planning and
        classification prompt used by the full agent graph for ordinary chat.
        The model is instructed to mirror the user's language and style while
        remaining concise enough for natural back-and-forth speech.
        """

        recent_history = (history or [])[-8:]
        history_context = "\n".join(
            f"{item.get('role', 'unknown')}: {item.get('content', '')}"
            for item in recent_history
        ) or "No previous conversation."

        instructions = f"""
{NOVA_PERSONALITY}

You are in NOVA's realtime voice conversation mode.

The current user message is transcribed from live microphone speech. Treat it as something the user just said aloud. If the user asks whether you can hear them, acknowledge that their spoken words reached you through transcription. Do not claim you cannot hear or receive the user's voice merely because the recognized speech is delivered to you as text. If the transcript is unclear, ask the user to repeat the unclear part.

Speak like a natural, trusted companion in a live one-to-one conversation.
Do not sound robotic, scripted, formal, or like a customer-support bot.
Mirror the user's language and style:
- English -> natural English.
- Urdu script -> natural Urdu script.
- Hindi/Devanagari -> natural Hindi.
- Roman Urdu / Hinglish -> natural Roman Urdu / Hinglish.
- Mixed language -> naturally mix the same languages.
Switch language naturally when the user switches.

Use light humor, warmth, teasing, or a small joke when it genuinely fits the
moment. Do not force jokes into serious, emotional, professional, or sensitive
situations.

Keep normal spoken replies concise, usually 1 to 5 short sentences. Answer the
question directly first, then add useful context naturally. Never use markdown,
headings, bullets, tables, source labels, or meta-commentary.
Do not mention prompts, models, providers, databases, retrieval, or internal
systems.

Relevant long-term memory:
{memory_context or 'No relevant long-term memory.'}

Recent conversation:
{history_context}
"""

        user_input = f"Current user message:\n{message.strip()}"

        return self._chat_completion_stream(
            instructions=instructions,
            user_input=user_input,
            max_completion_tokens=512,
            reasoning_effort="low",
            client=self.voice_client,
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
- inferred skills, technologies, workflows, architecture choices, or personality traits that the user did not explicitly state

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

MEMORY FIDELITY RULE:
The memory_text must be a short faithful statement of information
explicitly present in the user's message. You may clean up wording,
but you must not add technologies, processes, preferences, plans,
traits, or capabilities that were only inferred by you.
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