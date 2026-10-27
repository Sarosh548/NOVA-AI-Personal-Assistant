from __future__ import annotations

import ast
import logging
import math
import re
from difflib import SequenceMatcher
from collections.abc import Callable
from typing import Any

from services.conversation_service import ConversationService
from services.confirmation_service import ConfirmationService
from services.execution_context import ExecutionContext
from services.llm_service import (
    LLMService,
    LLM_PROVIDER_UNAVAILABLE_RESPONSE,
    is_llm_provider_error,
)
from services.execution_service import NOVAExecutionService
from services.memory_service import MemoryService
from services.knowledge_service import (
    DEFAULT_RERANK_CANDIDATE_LIMIT,
    KnowledgeService,
)


logger = logging.getLogger(__name__)


PRIVATE_KNOWLEDGE_SAVE_PREFIXES = (
    "add this to my private knowledge:",
    "add this to private knowledge:",
    "save this to my private knowledge:",
    "save this to private knowledge:",
)

PRIVATE_KNOWLEDGE_SEARCH_PREFIXES = (
    "search my private knowledge for ",
    "search my knowledge for ",
    "search the private knowledge for ",
    "search the knowledge for ",
    "what does my private knowledge say about ",
    "what does my knowledge say about ",
)

PRIVATE_KNOWLEDGE_SEARCH_FALLBACK_THRESHOLD = 0.45

_ARITHMETIC_REQUEST_PREFIX = re.compile(
    r"^(?:please\s+)?(?:calculate|compute|evaluate|solve|what\s+is|what's|whats|how\s+much\s+is)\s+",
    re.IGNORECASE,
)
_ARITHMETIC_RESPONSE_SUFFIX = re.compile(
    r"^(?:(?:[.!?,;:]\s*)?(?:(?:and\s+)?(?:please\s+)?"
    r"(?:reply|answer|respond|write|return|show|give|output|just|only|exactly|"
    r"no\s+explanation|without\s+explanation)\b.{0,160})?)?$",
    re.IGNORECASE,
)


def _evaluate_simple_arithmetic(node: ast.AST) -> int | float | None:
    """Evaluate only small, explicit arithmetic ASTs; never execute Python code."""
    if isinstance(node, ast.Expression):
        return _evaluate_simple_arithmetic(node.body)

    if isinstance(node, ast.Constant):
        value = node.value
        if type(value) not in (int, float) or abs(value) > 1_000_000_000:
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _evaluate_simple_arithmetic(node.operand)
        if operand is None:
            return None
        result = operand if isinstance(node.op, ast.UAdd) else -operand
        return result if abs(result) <= 1_000_000_000_000 else None

    if not isinstance(node, ast.BinOp):
        return None

    left = _evaluate_simple_arithmetic(node.left)
    right = _evaluate_simple_arithmetic(node.right)
    if left is None or right is None:
        return None

    try:
        if isinstance(node.op, ast.Add):
            result = left + right
        elif isinstance(node.op, ast.Sub):
            result = left - right
        elif isinstance(node.op, ast.Mult):
            result = left * right
        elif isinstance(node.op, ast.Div):
            result = left / right
        elif isinstance(node.op, ast.FloorDiv):
            result = left // right
        elif isinstance(node.op, ast.Mod):
            result = left % right
        elif isinstance(node.op, ast.Pow):
            if abs(right) > 10 or abs(left) > 1_000_000:
                return None
            result = left ** right
        else:
            return None
    except (ArithmeticError, ValueError):
        return None

    if isinstance(result, complex) or abs(result) > 1_000_000_000_000:
        return None
    if isinstance(result, float) and not math.isfinite(result):
        return None
    return result


def _simple_arithmetic_response(message: str) -> str | None:
    """Resolve a narrowly phrased calculator question without relying on an LLM guess."""
    text = " ".join(str(message).strip().split())
    if not text or len(text) > 320:
        return None

    prefix = _ARITHMETIC_REQUEST_PREFIX.match(text)
    if prefix is None:
        return None

    expression_and_suffix = text[prefix.end():]
    expression_and_suffix = re.sub(
        r"\b(?:multiplied\s+by|multiply\s+by|times)\b",
        "*",
        expression_and_suffix,
        flags=re.IGNORECASE,
    )
    expression_and_suffix = re.sub(
        r"\b(?:divided\s+by|divide\s+by|over)\b",
        "/",
        expression_and_suffix,
        flags=re.IGNORECASE,
    )
    expression_and_suffix = re.sub(r"\bplus\b", "+", expression_and_suffix, flags=re.IGNORECASE)
    expression_and_suffix = re.sub(r"\bminus\b", "-", expression_and_suffix, flags=re.IGNORECASE)
    expression_and_suffix = re.sub(
        r"(?<=\d)\s*[xX]\s*(?=\d)",
        "*",
        expression_and_suffix,
    )
    expression_and_suffix = expression_and_suffix.replace("×", "*").replace("÷", "/")
    expression_and_suffix = expression_and_suffix.replace("^", "**")

    match = re.match(r"\s*([0-9(][0-9\s().+\-*/%]*)", expression_and_suffix)
    if match is None:
        return None

    expression = match.group(1).strip()
    suffix = expression_and_suffix[match.end():].strip()
    if suffix and _ARITHMETIC_RESPONSE_SUFFIX.fullmatch(suffix) is None:
        return None
    if len(expression) > 120 or not re.search(r"[+\-*/%]", expression):
        return None

    try:
        syntax = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError):
        return None

    if sum(1 for _ in ast.walk(syntax)) > 31:
        return None

    result = _evaluate_simple_arithmetic(syntax)
    if result is None:
        return None
    if isinstance(result, float):
        if result.is_integer():
            return str(int(result))
        return format(result, ".12g")
    return str(result)


_MEMORY_CANDIDATE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bremember that\b",
        r"\bremember this\b",
        r"\bkeep in mind\b",
        r"\bfrom now on\b",
        r"\bmy name is\b",
        r"\bmera naam\s+(?!kya\b)\w+",
        r"\b\w+\s+naam\s+hai\b",
        r"\u092e\u0947\u0930\u093e\s+\u0928\u093e\u092e\s+(?!\u0915\u094d\u092f\u093e\b)\S+",
        r"\u0645\u06cc\u0631\u0627\s+\u0646\u0627\u0645\s+(?!\u06a9\u06cc\u0627\b)\S+",
        r"\b(?:pyar se\s+mujhe|mujhe\s+pyar se)\s+\w+\s+bulate(?:\s+hain)?\b",
        r"\u067e\u06cc\u0627\u0631\s+\u0633\u06d2\s+\u0645\u062c\u06be\u06d2\s+\S+\s+\u0628\u0644\u0627\u062a\u06d2\s+\u06c1\u06cc\u06ba",
        r"\u0645\u062c\u06be\u06d2\s+\u067e\u06cc\u0627\u0631\s+\u0633\u06d2\s+\S+\s+\u0628\u0644\u0627\u062a\u06d2\s+\u06c1\u06cc\u06ba",
        r"\bmy (?:long[- ]term )?goal\b",
        r"\bmy career goal\b",
        r"\bmy preference\b",
        r"\bI want to become\b",
        r"\bI want to be (?:a|an)\b",
        r"\bI prefer\b",
        r"\bI like\b",
        r"\bI love\b",
        r"\bI dislike\b",
        r"\bI hate\b",
        r"\bI live in\b",
        r"\bI work as\b",
        r"\bI(?: am|'m) working on\b",
        r"\bI(?: am|'m) studying\b",
        r"\bI graduated\b",
        r"\bI completed my degree\b",
        r"\bmera goal\b",
        r"\bmera maqsad\b",
        r"\bmeri pasand\b",
        r"\bmeri preference\b",
        r"\bmujhe .{1,50} pasand hai\b",
        r"\bmain .{1,50} banna chahta(?: hoon| hun)?\b",
        r"\bNOVA should\b",
    )
)


def _format_persisted_task_list_response(tool_result, user_message=None):
    """Build task-list answers and title verification from persisted rows only."""
    if not isinstance(tool_result, dict):
        return None
    if tool_result.get("tool") != "task" or tool_result.get("action") != "list":
        return None
    if tool_result.get("success") is not True or tool_result.get("error"):
        return None

    payload = tool_result.get("result")
    if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
        return None
    tasks = payload["tasks"]
    message = str(user_message or "").lower()
    asks_active_count = bool(
        re.search(
            r"\b(?:how many|count|number of|total)\b.{0,100}\bactive tasks?\b"
            r"|\bactive tasks?\b.{0,100}\b(?:count|how many|number)\b",
            message,
        )
    )
    if not tasks:
        if asks_active_count:
            return "Aapki saved task list mein 0 active tasks hain."
        response = "Aapki saved task list mein abhi koi task nahi mila."
        if re.search(r"\b(?:verify|check|confirm)(?:\s+karo)?\b|वेरीफाई|वेरिफाई|चेक|जांच|जाँच|जांचो|जाँचो", message):
            response += " Is liye requested task saved list mein verify nahi hua."
        return response

    if asks_active_count:
        active_statuses = {"pending", "in_progress", "in-progress", "active"}
        active_count = sum(
            1
            for task in tasks
            if isinstance(task, dict)
            and str(task.get("status") or "").strip().lower() in active_statuses
        )
        return f"Aapki saved task list mein {active_count} active tasks hain."

    lines = [f"Aapki saved task list mein total {len(tasks)} tasks hain:"]
    for task in tasks[:12]:
        if not isinstance(task, dict):
            continue
        title = str(task.get("title") or "Untitled task").strip()
        status = str(task.get("status") or "unknown").strip()
        priority = str(task.get("priority") or "unknown").strip()
        due_at = task.get("due_at")
        details = f"status: {status}, priority: {priority}"
        if due_at:
            details += f", due: {due_at}"
        lines.append(f"- {title} ({details})")
    if len(tasks) > 12:
        lines.append(f"Filhal pehle 12 tasks dikhaye gaye hain; total {len(tasks)} saved tasks hain.")

    def append_saved_task_summary(title):
        matched_task = next(
            (
                item
                for item in tasks
                if isinstance(item, dict)
                and str(item.get("title") or "").strip() == title
            ),
            None,
        )
        if matched_task is None:
            lines.append(f"Saved title: '{title}'.")
            return
        status = str(matched_task.get("status") or "unknown").strip()
        priority = str(matched_task.get("priority") or "unknown").strip()
        due_at = matched_task.get("due_at")
        due_detail = f", due: {due_at}" if due_at else ", no due date"
        lines.append(
            f"Saved task: '{title}' (status: {status}, priority: {priority}{due_detail})."
        )

    # Explicit verification compares persisted titles; it should return the
    # relevant task, not read the whole task list aloud unnecessarily.
    message = str(user_message or "").strip().lower()
    if re.search(r"\b(?:verify|check|confirm)(?:\s+karo)?\b|वेरीफाई|वेरिफाई|चेक|जांच|जाँच|जांचो|जाँचो", message):
        target_match = re.search(
            r"\b(?:verify|check|confirm)(?:\s+karo)?\s+"
            r"(?:(?:that|if|whether|ke|ki)\s+)?(?:us\s+mein\s+)?"
            r"(.+?)(?=\s+(?:task\s+list|list\s+mein|"
            r"is\s+(?:in\s+(?:my\s+)?(?:task\s+)?list|saved|present|available|there)|"
            r"(?:has\s+been|was)\s+(?:saved|created|added)|"
            r"shamil\s+hai|included|exists|hai\s+ya\s+nahi)\b|[?.!]|$)",
            message,
            flags=re.IGNORECASE,
        )
        if target_match is None:
            target_match = re.search(
                r"(?:वेरीफाई|वेरिफाई|चेक|जांचो|जाँचो|जांच|जाँच)[^?.!।]{0,40}?(?:कि|की|के)\s+"
                r"(.+?)(?=\s+(?:task\s+list|टास्क\s+लिस्ट|list\s+mein|लिस्ट\s+में|"
                r"hai\s+ya\s+nahi|है\s+या\s+नहीं|included|exists)\b|[?.!।]|$)",
                message,
                flags=re.IGNORECASE,
            )
        if target_match:
            target = " ".join(target_match.group(1).split()).strip(" \t\r\n\"'")
            target = re.sub(r"^(?:us\s+mein|the|this|that)\s+", "", target, flags=re.IGNORECASE)
            target_key = re.sub(r"[^a-z0-9]+", " ", target).strip()
            exact_match_title = None
            partial_matches = []
            close_matches = []
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                stored_title = str(task.get("title") or "").strip()
                stored_key = re.sub(r"[^a-z0-9]+", " ", stored_title.lower()).strip()
                if not target_key or not stored_key:
                    continue
                if target_key == stored_key:
                    exact_match_title = stored_title
                    break
                if stored_key.startswith(target_key + " ") or f" {target_key} " in f" {stored_key} ":
                    partial_matches.append(stored_title)
                    continue
                similarity = SequenceMatcher(
                    None,
                    target_key.replace(" ", ""),
                    stored_key.replace(" ", ""),
                ).ratio()
                if similarity >= 0.92:
                    close_matches.append((similarity, stored_title))
            if target_key:
                lines = []
                if exact_match_title:
                    lines.append(f"Verification: exact '{target}' saved task list mein mila.")
                    append_saved_task_summary(exact_match_title)
                elif partial_matches:
                    if len(partial_matches) == 1:
                        lines.append(f"Verification: '{target}' saved task list mein mila.")
                        append_saved_task_summary(partial_matches[0])
                    else:
                        lines.append(
                            f"Verification: '{target}' multiple saved titles mein mila: "
                            + ", ".join(f"'{title}'" for title in partial_matches[:3])
                            + "."
                        )
                elif close_matches:
                    close_matches.sort(key=lambda item: item[0], reverse=True)
                    best_score, best_title = close_matches[0]
                    unique_best = (
                        len(close_matches) == 1
                        or best_score - close_matches[1][0] >= 0.05
                    )
                    if unique_best:
                        lines.append(
                            f"Verification: exact title '{target}' nahi mila, "
                            f"lekin closest saved title '{best_title}' hai."
                        )
                        append_saved_task_summary(best_title)
                        lines.append("Voice transcript mein title ka chhota hissa miss hua ho sakta hai.")
                    else:
                        lines.append(f"Verification: exact '{target}' task saved list mein nahi mila.")
                        suggestions = ", ".join(
                            f"'{title}'" for _, title in close_matches[:3]
                        )
                        lines.append(f"Similar saved titles: {suggestions}.")
                else:
                    lines.append(f"Verification: exact '{target}' task saved list mein nahi mila.")
                    if len(tasks) == 1 and isinstance(tasks[0], dict):
                        actual_title = str(tasks[0].get("title") or "Untitled task").strip()
                        lines.append(f"Saved record ka actual title: '{actual_title}'.")
    return "\n".join(lines)


def _format_persisted_reminder_list_response(tool_result, user_message=None):
    """Build reminder-list answers from the user's persisted reminder rows."""
    if not isinstance(tool_result, dict):
        return None
    if (
        tool_result.get("tool") != "reminder"
        or tool_result.get("action") != "list"
        or tool_result.get("success") is not True
        or tool_result.get("error")
    ):
        return None

    payload = tool_result.get("result")
    if not isinstance(payload, dict) or not isinstance(payload.get("reminders"), list):
        return None
    reminders = [item for item in payload["reminders"] if isinstance(item, dict)]
    if not reminders:
        return "Aapki saved reminder list mein abhi koi pending reminder nahi mila."

    lines = [f"Aapki saved reminder list mein total {len(reminders)} pending reminders hain:"]
    for reminder in reminders[:12]:
        title = str(reminder.get("title") or "Untitled reminder").strip()
        status = str(reminder.get("status") or "unknown").strip()
        scheduled_at = reminder.get("reminder_time")
        details = f"status: {status}"
        if scheduled_at:
            details += f", scheduled: {scheduled_at}"
        lines.append(f"- {title} ({details})")
    if len(reminders) > 12:
        lines.append(f"Filhal pehle 12 reminders dikhaye gaye hain; total {len(reminders)} pending reminders hain.")
    return "\n".join(lines)


def _format_failed_read_action_response(tool_result):
    """Surface real read-action failures instead of model-generated success claims."""
    if not isinstance(tool_result, dict) or tool_result.get("success") is not False:
        return None

    tool = str(tool_result.get("tool") or "").strip().lower()
    action = str(tool_result.get("action") or "").strip().lower()
    error = str(tool_result.get("error") or "").strip()
    if not error:
        return None

    if tool == "email" and action in {"list", "search", "get"}:
        lowered_error = error.casefold()
        if "inbox access has not been granted" in lowered_error or "read-only email permission" in lowered_error:
            return (
                "Gmail inbox reading is not authorized yet. Reconnect Google/Gmail in "
                "Control Center → Notifications and approve the requested read-only Gmail permission. "
                "No email was sent, replied to, archived, or deleted."
            )
        if "connect your google/gmail account" in lowered_error:
            return (
                "Gmail is not connected to NOVA for inbox reading. Connect Google/Gmail in "
                "Control Center → Notifications, then retry. No email was sent, replied to, "
                "archived, or deleted."
            )
        return (
            f"NOVA could not read your Gmail inbox: {error} "
            "No email was sent, replied to, archived, or deleted."
        )

    if tool == "calendar" and action in {"list", "get"}:
        lowered_error = error.casefold()
        if "not connected" in lowered_error or "not configured" in lowered_error or "not authorized" in lowered_error:
            return (
                "Google Calendar is not connected or authorized for this NOVA account. "
                "Open the Calendar workspace, connect Google Calendar, and complete Google's authorization. "
                "No Calendar changes were made."
            )
        return f"NOVA could not load Calendar events: {error} No Calendar changes were made."

    if tool == "reminder" and action == "list":
        return f"NOVA could not load your saved reminders: {error} No reminders were changed."

    return None


def _append_requested_web_sources(response, user_message, tool_result):
    """Attach real retrieved URLs when the user explicitly asks for source links."""
    message = str(user_message or "").lower()
    if not re.search(
        r"\b(?:source|sources|link|links|citation|citations|cite|reference|references)\b|"
        r"\u0938\u094d\u0930\u094b\u0924|\u0932\u093f\u0902\u0915",
        message,
        flags=re.IGNORECASE,
    ):
        return response
    if not isinstance(tool_result, dict):
        return response
    if (
        tool_result.get("tool") != "web"
        or tool_result.get("action") != "search"
        or tool_result.get("success") is not True
    ):
        return response

    payload = tool_result.get("result")
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return response

    seen_urls = set(re.findall(r"https?://[^\s<>]+", str(response or "")))
    source_lines = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title") or "Source").split()).strip()
        url = str(item.get("url") or item.get("link") or "").strip()
        if not title or not (url.startswith("https://") or url.startswith("http://")):
            continue
        if url in seen_urls:
            continue
        published = str(item.get("published_date") or item.get("publishedDate") or "").strip()
        line = f"- {title[:180]} — {url}"
        if published:
            line += f" (published: {published[:40]})"
        source_lines.append(line)
        seen_urls.add(url)
        if len(source_lines) >= 5:
            break

    if not source_lines:
        requests_fresh_sources = bool(
            re.search(
                r"\b(?:latest|recent|current|today|right now|at the moment|live|now|aaj|abhi|filhal)\b",
                message,
            )
        )
        if requests_fresh_sources:
            return (
                "I couldn't verify a fresh, dated source for this request just now. "
                "The search returned no source within the requested freshness window, "
                "so I won't present older articles as the latest update."
            )
        return response
    return str(response or "").rstrip() + "\n\nSources (open links):\n" + "\n".join(source_lines)


def _clarify_chat_only_email_draft(response, user_message, tool_result):
    """Prevent a conversational email draft from being mistaken for a Gmail-saved draft."""
    message = str(user_message or "").lower()
    has_email = bool(
        re.search(r"\b(?:email|e-mails?|mail)\b|\u0908\u092e\u0947\u0932|\u092e\u0947\u0932", message)
    )
    has_draft = bool(
        re.search(r"\bdraft\b|\u0921\u094d\u0930\u093e\u092b\u094d\u091f", message)
    )
    says_do_not_send = bool(
        re.search(r"\b(?:don't|do not|never)\b.{0,50}\bsend\b|\bsend\s+mat\s+(?:kar\w*|bhej\w*)\b|\bmat\s+bhej\w*\b", message)
        or (
            "मत" in message
            and any(
                marker in message
                for marker in ("send", "सेंड", "भेज")
            )
        )
    )
    if not (has_email and has_draft and says_do_not_send):
        return response
    if (
        isinstance(tool_result, dict)
        and tool_result.get("tool") == "email"
        and tool_result.get("action") in {"draft", "create_draft"}
        and tool_result.get("success") is True
    ):
        return response

    note = (
        "Note: Yeh draft sirf is chat mein tayyar hua hai; Gmail ke Drafts mein save nahi hua "
        "aur send bhi nahi hua."
    )
    if note.casefold() in str(response or "").casefold():
        return response
    return str(response or "").rstrip() + "\n\n" + note


class ConversationExecutionService:
    """
    Shared conversational execution boundary for NOVA.

    This service owns the orchestration around the existing NOVA graph:
    conversation lookup, bounded history, execution, persistence, and
    memory extraction. Transport layers such as HTTP and realtime voice
    remain responsible only for protocol concerns.
    """

    def __init__(
        self,
        *,
        conversation_service: ConversationService,
        execution_service: NOVAExecutionService,
        llm_service: LLMService,
        memory_service: MemoryService,
        knowledge_service: KnowledgeService | None = None,
        confirmation_service: ConfirmationService | None = None,
        context_max_messages: int = 12,
        context_max_characters: int = 12_000,
    ):
        if context_max_messages < 1:
            raise ValueError(
                "context_max_messages must be greater than 0."
            )

        if context_max_characters < 1:
            raise ValueError(
                "context_max_characters must be greater than 0."
            )

        self.conversation_service = conversation_service
        self.execution_service = execution_service
        self.llm_service = llm_service
        self.memory_service = memory_service
        self.knowledge_service = knowledge_service
        self.confirmation_service = confirmation_service
        self.context_max_messages = context_max_messages
        self.context_max_characters = context_max_characters

    def bind_dependencies(
        self,
        *,
        conversation_service: ConversationService | None = None,
        execution_service: NOVAExecutionService | None = None,
        llm_service: LLMService | None = None,
        memory_service: MemoryService | None = None,
        knowledge_service: KnowledgeService | None = None,
        confirmation_service: ConfirmationService | None = None,
    ) -> None:
        if conversation_service is not None:
            self.conversation_service = conversation_service

        if execution_service is not None:
            self.execution_service = execution_service

        if llm_service is not None:
            self.llm_service = llm_service

        if memory_service is not None:
            self.memory_service = memory_service

        if knowledge_service is not None:
            self.knowledge_service = knowledge_service

        if confirmation_service is not None:
            self.confirmation_service = confirmation_service

    def prepare_conversation(
        self,
        *,
        user_id: str,
        conversation_id: int | None = None,
    ) -> int:
        """
        Prepare the conversation identity before realtime execution begins.

        Realtime voice can accept a new turn while a previous execution
        worker is still unwinding after interruption. Establishing the
        conversation id before launching that worker keeps subsequent turns
        anchored to the same conversation.
        """

        return self.conversation_service.get_or_create_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
        )

    _FULL_PIPELINE_PATTERNS = (
        re.compile(
            r"\\b(?:wikipedia|google|youtube|gmail|github|reddit|bing|duckduckgo|"
            r"microsoft|outlook|facebook|twitter|linkedin|chatgpt)\\s+"
            r"(?:\\u0913\\u092a\\u0928\\s+(?:\\u0915\\u0930\\u0928\\u093e|"
            r"\\u0915\\u0930\\u094b|\\u0915\\u0930\\s+(?:\\u0932\\u094b|\\u0926\\u094b))|"
            r"\\u0916\\u094b\\u0932\\u094b|\\u0916\\u094b\\u0932\\s+\\u0926\\u094b)"
            r"(?=\\s|[\\u0964\\u0965.!?]|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:open|launch|start)\s+(?:the\s+)?(?:calculator|calc|notepad|text editor|file explorer|explorer|chrome|google chrome|edge|microsoft edge|firefox|browser|web browser|desktop|documents|downloads|pictures|music|videos|file|document|outlook|microsoft outlook|word|microsoft word|excel|microsoft excel|powerpoint|microsoft powerpoint)\b"
            r"|\bopen\s+[^\s/\\]+\.(?:pdf|docx?|rtf|txt|md|csv|xlsx?|pptx?|png|jpe?g|gif|webp|bmp|mp3|wav|m4a|mp4|mov|avi|mkv)\b"
            r"|\b(?:open|visit|navigate to|go to)\s+https?://"
            r"|\b(?:open|visit|navigate to|go to)\s+(?:the\s+)?(?:wikipedia|wikimedia(?:\s*[.,]?\s*wikipedia)?|google|youtube|gmail|github|stackoverflow|reddit|bing|duckduckgo|microsoft|outlook|facebook|twitter|linkedin|chatgpt)(?:\s+(?:website|site|homepage))?\b"
            r"|\b(?:wikipedia|wikimedia(?:\s*[.,]?\s*wikipedia)?|google|youtube|gmail|github|stackoverflow|reddit|bing|duckduckgo|microsoft|outlook|facebook|twitter|linkedin|chatgpt)\s+(?:kholo|open\s+karo|open\s+kar\s+(?:lo|do|na)|open\s+karna|visit\s+karo|website\s+kholo|website\s+khol\s+do|\u0913\u092a\u0928\s+(?:\u0915\u0930\u0928\u093e|\u0915\u0930\u094b)|\u0916\u094b\u0932\u094b|\u0916\u094b\u0932\s+\u0926\u094b)\b"
            r"|\b(?:search (?:the )?(?:web|internet|browser) for|web search for|google search for|search on google for|search (?:my )?(?:files|documents) for|find (?:the )?(?:file|document)|locate (?:the )?(?:file|document)|open (?:the )?(?:file|document))\b"
            r"|\b(?:file dhoondo|file kholo|calculator kholo|notepad kholo|browser kholo)\b"
            r"|\b(?:calculator|calc|notepad|file explorer|browser|documents|downloads|desktop)\s+(?:kholo|open\s+karo|open\s+kar\s+(?:lo|do)|chalao)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(remind\w*|task\w*|calendar|meeting|email|mail|send|schedule|book|delete|cancel|complete|update|create|add|plan|planning|workflow|routine|start (?:my|the) (?:task|reminder|workflow)|remember that|remember this|memorize this|save this|note this|don't forget)\b"
            r"|\b(yaad dila|yaad rakh|yaad rakho|yaad rakhna|reminder bana|task bana|calendar me|meeting rakh|email bhej|mail bhej|bhej do|schedule kar|book kar|delete kar|cancel kar|complete kar|update kar|bana do|add kar)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(search|look up|lookup|browse|latest|current(?:ly)?|recent(?:ly)?|newest|news|weather|price|prices|exchange rate|stock|who won|source links?|publication dates?|citations?|cite sources|reliable web sources)\b"
            r"|\b(latest kya|aaj ki khabar|aaj ke khab|aaj ka mausam|mausam batao|rate kya|qeemat kya|abhi ka rate)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:play|start|put on)\s+.+?\s+(?:on|in)\s+(?:youtube|you tube)\b"
            r"|\b(?:youtube|you tube)\s+(?:par|pe|mein|me|पर|पे)\s+.+?\s+(?:chalao|chala do|laga do|bajao|चलाओ|चला दो|लगाओ|बजाओ)\b"
            r"|\b(?:youtube|you tube)\s+(?:kholo|open karo|open kar do|open kar lo)\s+(?:aur|and)\s+.+?\s+(?:chalao|chala do|laga do|bajao|चलाओ|चला दो|लगाओ|बजाओ)\b",
            re.IGNORECASE,
        ),
        # Keep local file discovery, reverse-order desktop commands, and drive roots
        # on the tool graph even when realtime ASR changes their word order.
        re.compile(
            r"\b(?:find|list|show|locate|search(?:\s+for)?|check)\b.{0,100}\b(?:cv|cvs|resume|resumes|curriculum\s+vitae)\b"
            r"|\b(?:cv|cvs|resume|resumes|curriculum\s+vitae)\b.{0,80}\b(?:find|list|show|search|check|dekho|dhoondo)\b"
            r"|\b(?:open|show|browse|go to|navigate to)\s+(?:the\s+)?(?:local\s+disk\s+c|disk\s+c|c\s+drive|drive\s+c|c:)\b"
            r"|\b(?:local\s+disk\s+c|disk\s+c|c\s+drive|drive\s+c)\s+(?:kholo|open\s+karo|open\s+karna|open\s+kar\s+(?:do|lo))\b"
            r"|\b(?:power\s+)?(?:powerpoint|microsoft\s+powerpoint|word|excel)\s+(?:kholo|open\s+(?:karo|karna|kar\s+(?:do|lo)))\b"
            r"|\u0932\u094b\u0915\u0932\s+\u0921\u093f\u0938\u094d\u0915\s+\u0938\u0940\s+\u0913\u092a\u0928\s+(?:\u0915\u0930\u0928\u093e|\u0915\u0930\u094b)"
            r"|\b[a-z0-9][a-z0-9 _().+-]{0,120}?\s+open\s+(?:karna|karo|kar\s+(?:do|lo))\s+(?:the\s+)?file\b",
            re.IGNORECASE,
        ),
        # Downloads listing and Spotify playback must use the execution graph.
        re.compile(
            r"^(?:please\s+)?(?:list|show|display)\s+(?:my\s+)?(?:files?\s+(?:in|from)\s+downloads|downloaded\s+files|downloads(?:\s+folder)?)[.!?]*$"
            r"|^(?:meri|mere|my)\s+(?:downloaded\s+files|files\s+in\s+downloads|downloads\s+files)\s+(?:dikhao|dikhaiye|show|list|display)[.!?]*$"
            r"|^spotify\s+(?:kholo|open\s+karo|open\s+kar\s+(?:lo|do)|(?:par|pe)\s+jao)\s+(?:aur|and)\s+.+\s+(?:chalao|chala\s+do|laga\s+do|bajao|play\s+(?:karo|kar\s+(?:do|lo)))[.!?]*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(?:(?:please|zara)\s+)?(?:(?:meri|mere|my|the)\s+)*(?:emails?|e-mails?|mail|inbox)\s+"
            r"(?:dikhao|dikhaiye|show|list|check(?:\s+karo)?|dekh(?:\s+lo|o)?|batao)[.!?]*$",
            re.IGNORECASE,
        ),
        # Hindi-script realtime transcription may contain no Latin "search"
        # token; keep those explicit search commands off the generic chat path.
        re.compile(
            r"(?:\u0938\u0930\u094d\u091a|\u0916\u094b\u091c).{0,60}"
            r"(?:\u0915\u0930\u094b|\u0915\u0930\s+\u0926\u094b|\u0915\u0930\u0928\u093e)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(knowledge base|my notes|uploaded|document|pdf|guide|handbook)\b"
            r"|\bmeri notes|meri file|uploaded file|document me|pdf me\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(activity|activities|updates?|progress update)\b"
            r"|\b(aaj ki activity|aaj ke updates|aaj kya updates)\b",
            re.IGNORECASE,
        ),
        # Realtime voice can yield Hindi-script task transcripts and action
        # verbs without the English word "task"; route these to execution.
        re.compile(
            r"(?:\u091f\u093e\u0938\u094d\u0915(?:\u094d\u0938)?|\u0915\u093e\u0930\u094d\u092f)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:\u0915\u094d\u0930\u093f\u090f\u091f|\u092c\u0928\u093e\s+\u0926\u094b|"
            r"\u091c\u094b\u0921\u093c\s+\u0926\u094b|\u090f\u0921\s+\u0915\u0930\s+\u0926\u094b)",
            re.IGNORECASE,
        ),
    )

    @classmethod
    def _has_unfinished_email_draft_context(
        cls,
        message: str,
        history: list[dict] | None = None,
    ) -> bool:
        """
        Keep short replies to an active email draft on the full execution graph.

        Recipient addresses, subject preferences, and approval acknowledgements
        often contain none of the action keywords used by the fast-path router.
        Sending them through the compact chat path can lose the draft context
        and falsely imply that an email was sent without executing the tool.
        """
        messages = (history or [])[-12:]
        if not messages:
            return False

        normalized_message = " ".join(
            str(message).strip().lower().split()
        )
        if not normalized_message:
            return False

        email_follow_up = bool(
            re.fullmatch(
                r"(?:my\s+)?(?:email\s*(?:is|:)?\s*)?"
                r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}",
                normalized_message,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"\b(email|e-mail|recipient|subject|body|message|"
                r"confirm|confirmation|send|sent|bhej|bhej\s+di)\b",
                normalized_message,
                flags=re.IGNORECASE,
            )
            or normalized_message in {
                "yes",
                "yes please",
                "yep",
                "yeah",
                "ok",
                "okay",
                "sure",
                "no",
                "cancel",
                "cancel it",
            }
        )
        request_index = None
        for index in range(len(messages) - 1, -1, -1):
            item = messages[index]
            if item.get("role") != "user":
                continue
            prior_message = " ".join(
                str(item.get("content") or "").strip().lower().split()
            )
            if (
                re.search(r"\b(email|e-mail)\b", prior_message)
                and re.search(
                    r"\b(send|sending|bhej|bhejna|bhej\s+do)\b",
                    prior_message,
                )
            ):
                request_index = index
                break

        if request_index is None:
            return False

        completed_markers = (
            "email sent successfully",
            "email was sent",
            "email has been sent",
            "successfully sent the email",
            "successfully sent",
            "i sent the email",
            "i've sent the email",
            "couldn't send the email",
            "could not send the email",
            "failed to send the email",
            "email delivery failed",
            "email request was cancelled",
            "email request was canceled",
        )
        cancelled_markers = {
            "cancel",
            "cancel it",
            "cancel this email",
            "forget the email",
            "discard the email",
        }

        for item in messages[request_index + 1:]:
            role = item.get("role")
            content = " ".join(
                str(item.get("content") or "").strip().lower().split()
            )
            if role == "user" and content in cancelled_markers:
                return False
            if role == "assistant" and any(
                marker in content for marker in completed_markers
            ):
                return False

        # Keep any active email draft on the full graph, including plain-text subjects.
        active_email_prompt = any(
            re.search(
                r"\b(email|recipient|subject|body|message|confirm|send|sending|correct)\b",
                " ".join(str(item.get("content") or "").strip().lower().split()),
            )
            for item in messages[request_index + 1:]
            if item.get("role") == "assistant"
        )
        if not active_email_prompt:
            return False
        if email_follow_up:
            return True

        recipient_pattern = r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}"
        recipient_seen = False
        subject_prompt_after_recipient = False
        for item in messages[request_index + 1:]:
            content = " ".join(
                str(item.get("content") or "").strip().lower().split()
            )
            if item.get("role") == "user" and re.fullmatch(
                rf"(?:my\s+)?(?:email\s*(?:is|:)?\s*)?{recipient_pattern}",
                content,
            ):
                recipient_seen = True
            elif item.get("role") == "assistant" and recipient_seen and (
                re.search(r"\bwhat\s+subject\b", content)
                or re.search(
                    r"\bwhat would you like me to do with that email address\b",
                    content,
                )
            ):
                subject_prompt_after_recipient = True

        if not (recipient_seen and subject_prompt_after_recipient):
            return False

        if (
            len(normalized_message) > 120
            or "?" in normalized_message
            or normalized_message in {
                "hi", "hello", "hey", "tell me a joke",
                "what's up", "whats up", "never mind",
            }
            or re.match(
                r"^(?:tell me|what|why|when|where|who|how)\b",
                normalized_message,
            )
        ):
            return False

        return True

    @classmethod
    def _is_planning_context_follow_up(
        cls,
        message: str,
        history: list[dict] | None = None,
    ) -> bool:
        """Keep follow-ups to an earlier planning request on the full graph."""

        normalized = " ".join(
            message.strip().lower().split()
        )

        if not normalized:
            return False

        follow_up_patterns = (
            "what should i do first",
            "what do i do first",
            "what do i start with",
            "what can wait",
            "what can wait until tomorrow",
            "what should wait until tomorrow",
        )

        has_duration = re.search(
            r"\b(?:only\s+)?have\s+"
            r"(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)"
            r"\s+(?:hours?|hrs?|minutes?|mins?)\b",
            normalized,
        ) is not None

        if not (
            has_duration
            or any(
                phrase in normalized
                for phrase in follow_up_patterns
            )
        ):
            return False

        if has_duration and "focused work" in normalized:
            return True

        planning_markers = (
            "help me plan",
            "plan tomorrow",
            "make a plan",
            "plan my day",
            "help me organize my day",
        )

        follow_up_markers = (
            "what should i do first",
            "what do i do first",
            "what do i start with",
            "what can wait",
            "what can wait until tomorrow",
            "what should wait until tomorrow",
        )

        recent_messages = (
            (history or [])[-8:]
        )

        return any(
            item.get("role") == "user"
            and (
                any(
                    marker in str(item.get("content") or "").lower()
                    for marker in planning_markers
                )
                or any(
                    marker in str(item.get("content") or "").lower()
                    for marker in follow_up_markers
                )
                or "focused work" in str(item.get("content") or "").lower()
            )
            for item in recent_messages
        )

    @classmethod
    def _has_task_creation_confirmation_context(
        cls,
        message: str,
        history: list[dict] | None = None,
    ) -> bool:
        """Keep explicit approval of a proposed task creation on the execution graph."""

        normalized = re.sub(r"[,.!?;:]+", " ", str(message or "").lower())
        normalized = " ".join(normalized.split())
        if not normalized or len(normalized) > 120:
            return False

        affirmative = re.fullmatch(
            r"(?:(?:okay|ok|yes|yeah|yep|sure|right|go ahead|do it|please do|"
            r"this is what i want|that's what i want|that is what i want|"
            r"haan|han|ji|bilkul|theek hai|haan yehi chahiye|"
            r"\u0939\u093e\u0901|\u0939\u093e\u0902|\u091c\u0940 \u0939\u093e\u0901|"
            r"\u0920\u0940\u0915 \u0939\u0948|\u0915\u0930 \u0926\u094b)\s*)+",
            normalized,
            flags=re.IGNORECASE,
        )
        if not affirmative:
            return False

        recent = (history or [])[-8:]
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
            return False

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
            return False

        return any(
            item.get("role") == "user"
            and re.search(
                r"\b(?:create|add|make)\b|\btask\b|"
                r"\u091f\u093e\u0938\u094d\u0915|\u0915\u094d\u0930\u093f\u090f\u091f|\u092c\u0928\u093e\s+\u0926\u094b",
                str(item.get("content") or ""),
                flags=re.IGNORECASE,
            )
            for item in recent
        )

    @classmethod
    def _has_unfinished_calendar_confirmation_context(
        cls,
        message: str,
        history: list[dict] | None = None,
    ) -> bool:
        """Route approval replies for a proposed Calendar write through NOVA's execution graph."""
        normalized = re.sub(r"[,.!?;:।]+", " ", str(message or "").lower())
        normalized = " ".join(normalized.split())
        if not normalized or len(normalized) > 120:
            return False

        affirmative = re.fullmatch(
            r"(?:(?:yes|yeah|yep|yup|okay|ok|sure|confirm(?:ed)?|approve(?:d)?|"
            r"go ahead|do it|please do|haan|han|jee|ji|kar do|add kar do|"
            r"yes add kar do|\u092f\u0938|\u0939\u093e\u0901|\u0939\u093e\u0902|"
            r"\u091c\u0940|\u0915\u0930 \u0926\u094b|\u091c\u094b\u0921\u093c \u0926\u094b|"
            r"\u092f\u0938 \u0915\u0930 \u0926\u094b|\u0939\u093e\u0901 \u0915\u0930 \u0926\u094b|"
            r"\u0939\u093e\u0902 \u0915\u0930 \u0926\u094b|\u091c\u0940 \u0915\u0930 \u0926\u094b)\s*)+",
            normalized,
            flags=re.IGNORECASE,
        )
        if not affirmative:
            return False

        recent = (history or [])[-12:]
        latest_assistant = next(
            (
                str(item.get("content") or "").strip().lower()
                for item in reversed(recent)
                if item.get("role") == "assistant" and str(item.get("content") or "").strip()
            ),
            "",
        )
        if not latest_assistant:
            return False

        asks_for_confirmation = re.search(
            r"\b(?:confirm|confirmation|is that correct|should i create|shall i create|"
            r"would you like me to create|do you want me to create|add it|shall i add|"
            r"may i go ahead and create|go ahead and create|may i add)\b",
            latest_assistant,
            flags=re.IGNORECASE,
        ) is not None
        mentions_calendar_event = re.search(
            r"\b(?:calendar|event|meeting|schedule)\b",
            latest_assistant,
            flags=re.IGNORECASE,
        ) is not None
        prior_create_request = any(
            item.get("role") == "user"
            and re.search(
                r"\b(?:calendar|event|meeting|schedule)\b",
                str(item.get("content") or ""),
                flags=re.IGNORECASE,
            )
            and re.search(
                r"\b(?:create|add|schedule|book|put)\b|\badd kar do\b",
                str(item.get("content") or ""),
                flags=re.IGNORECASE,
            )
            for item in recent
        )
        return asks_for_confirmation and mentions_calendar_event and prior_create_request

    @classmethod
    def _is_fast_conversation(
        cls,
        message: str,
        history: list[dict] | None = None,
    ) -> bool:
        """
        Detect ordinary conversation that is safe to answer without the full
        tool-planning graph.

        This is intentionally conservative: ambiguous requests stay on the
        existing full execution path rather than risking a missed action.
        """

        normalized = " ".join(message.strip().split())
        if not normalized or len(normalized) > 800:
            return False

        # Saved-document questions need the full graph's user-scoped knowledge
        # retrieval; the fast companion path injects memory only.
        saved_knowledge_query = re.search(
            r"\b(?:private knowledge|knowledge base|saved knowledge|saved notes?|"
            r"saved documents?|document contents?|source title|document title)\b"
            r"|\b(?:stored|saved|recorded|contained)\s+in\s+"
            r"[a-z0-9][a-z0-9 _-]{2,100}\b",
            normalized,
            flags=re.IGNORECASE,
        )
        if saved_knowledge_query:
            return False

        # Explicit requests to play media must always reach the full action
        # graph. The compact chat path previously missed polite Roman Urdu
        # verbs ("chalayen") and mixed-script Gemini transcripts ("चलाना").
        has_media_site = re.search(
            r"\b(?:youtube|you\s+tube|spotify)\b",
            normalized,
            flags=re.IGNORECASE,
        ) is not None
        has_roman_play_verb = re.search(
            r"\b(?:chala\w*|bajao\w*|play\w*|laga\s+(?:do|lo))\b",
            normalized,
            flags=re.IGNORECASE,
        ) is not None
        has_devanagari_play_verb = any(
            verb in normalized
            for verb in (
                "\u091a\u0932\u093e\u0928\u093e",  # चलाना
                "\u091a\u0932\u093e\u0913",  # चलाओ
                "\u092c\u091c\u093e\u0913",  # बजाओ
                "\u0932\u0917\u093e \u0926\u094b",  # लगा दो
            )
        )
        if has_media_site and (has_roman_play_verb or has_devanagari_play_verb):
            return False

        # Never let an explicit open/launch/start command go through the
        # generic chat model. Known and unknown app names both need the
        # deterministic execution path, where installed shortcuts are checked.
        if re.match(r"^(?:please\s+)?(?:open|launch|start)\s+", normalized, re.IGNORECASE):
            return False

        # Gemini ASR may mix English site names with Devanagari action verbs.
        # Unicode combining marks make a trailing regex word-boundary brittle,
        # so use exact normalized phrases here before considering the fast path.
        deva = lambda *codepoints: "".join(chr(value) for value in codepoints)
        deva_open = deva(0x0913, 0x092A, 0x0928)
        deva_karo = deva(0x0915, 0x0930, 0x094B)
        deva_karna = deva(0x0915, 0x0930, 0x0928, 0x093E)
        deva_kar_lo = deva(0x0915, 0x0930) + " " + deva(0x0932, 0x094B)
        deva_kar_do = deva(0x0915, 0x0930) + " " + deva(0x0926, 0x094B)
        deva_kholo = deva(0x0916, 0x094B, 0x0932, 0x094B)
        deva_khol_do = deva(0x0916, 0x094B, 0x0932) + " " + deva(0x0926, 0x094B)
        dev_notepad = deva(0x0928, 0x094B, 0x091F, 0x092A, 0x0948, 0x0921)
        dev_calculator = deva(0x0915, 0x0948, 0x0932, 0x0915, 0x0941, 0x0932, 0x0947, 0x091F, 0x0930)
        dev_text_editor = deva(0x091F, 0x0947, 0x0915, 0x094D, 0x0938, 0x094D, 0x091F) + " " + deva(0x090F, 0x0921, 0x093F, 0x091F, 0x0930)
        dev_browser = deva(0x092C, 0x094D, 0x0930, 0x093E, 0x0909, 0x091C, 0x093C, 0x0930)
        target_terms = (
            "wikipedia", "wikimedia", "google", "youtube", "gmail", "github",
            "reddit", "bing", "duckduckgo", "microsoft", "outlook", "facebook",
            "twitter", "linkedin", "chatgpt", "notepad", "calculator", "calc",
            "file explorer", "browser", "documents", "downloads", "desktop",
            dev_notepad, dev_calculator, dev_text_editor, dev_browser,
        )
        has_allowlisted_target = (
            re.search(
                r"\b(?:wikipedia|wikimedia|google|youtube|gmail|github|reddit|bing|"
                r"duckduckgo|microsoft|outlook|facebook|twitter|linkedin|chatgpt|"
                r"notepad|calculator|calc|file explorer|browser|documents|downloads|desktop)\b",
                normalized,
                flags=re.IGNORECASE,
            )
            is not None
            or any(term in normalized.casefold() for term in target_terms if term)
        )
        action_terms = (
            deva_open, deva_karna, deva_karo, deva_kar_lo, deva_kar_do,
            deva_kholo, deva_khol_do,
        )
        # Test action tokens independently rather than requiring an exact
        # adjacent phrase; ASR frequently adds fillers like "hai" or punctuation.
        has_devanagari_action = any(term in normalized for term in action_terms)
        if has_allowlisted_target and has_devanagari_action:
            return False

        # Explicit fixed drive-root requests are deterministic desktop actions.
        # Keep both "Local Disk C" and spoken "Local Drive C" off fast chat.
        if re.search(
            r"\b(?:open|show|browse|go to|navigate to)\s+(?:the\s+)?(?:local\s+(?:disk|drive)\s+c|disk\s+c|c\s+drive|drive\s+c|c:)\b"
            r"|\b(?:local\s+(?:disk|drive)\s+c|disk\s+c|c\s+drive|drive\s+c)\s+(?:kholo|open\s+karo|open\s+karna|open\s+kar\s+(?:do|lo))\b",
            normalized,
            flags=re.IGNORECASE,
        ):
            return False

        # Explicit app/site actions in Roman Urdu must also bypass fast chat,
        # including "nikaal do mere liye text editor" phrasing.
        if re.search(
            r"\b(?:open|launch|start|visit|go to|navigate to)\s+"
            r"(?:the\s+)?(?:wikipedia|wikimedia|google|youtube|gmail|github|"
            r"reddit|bing|duckduckgo|microsoft|outlook|facebook|twitter|linkedin|"
            r"chatgpt|notepad|calculator|calc|text editor|file explorer|chrome|"
            r"edge|firefox|browser|documents|downloads|desktop)\b"
            r"|\b(?:wikipedia|wikimedia|google|youtube|gmail|github|reddit|bing|"
            r"duckduckgo|microsoft|outlook|facebook|twitter|linkedin|chatgpt|"
            r"notepad|calculator|calc|text editor|file explorer|chrome|edge|"
            r"firefox|browser)\s+(?:kholo|open\s+karo|open\s+kar\s+(?:lo|do)|"
            r"open\s+karna|chalao|website\s+kholo)\b"
            r"|\b(?:abhi\s+)?(?:to\s+)?(?:nikaal|nikal)\s+do\s+"
            r"(?:mere\s+liye\s+)?(?:text editor|notepad|calculator|calc|"
            r"file explorer|chrome|edge|firefox|browser)\b",
            normalized,
            flags=re.IGNORECASE,
        ):
            return False

        # Reverse-order local-app requests must never be answered as ordinary chat.
        if re.search(
            r"(?:^|\s)(?:[a-z0-9][a-z0-9 ._()+#-]{0,79})\s+(?:kholo|chalao|open karo|open karna|open kar do|open kar lo)[.!?]*$",
            normalized,
            flags=re.IGNORECASE,
        ):
            return False

        # A user request to list downloaded files, play media, or inspect the
        # current desktop must run through deterministic tools, never chat fallback.
        if re.search(
            r"^(?:show|list|display|check|view|get|fetch)\s+(?:(?:me|my|all|the)\s+)*(?:my\s+)?(?:downloaded\s+files?|downloads)(?:\s+files?)?[.!?]*$"
            r"|^(?:(?:meri|mere|my|the)\s+)?(?:downloaded\s+files?|downloads)\s+(?:dikhao|dikh(?:a|ao|ana)?|list(?:\s+kar(?:o|na|do))?|show(?:\s+me)?|batao|check\s+karo)[.!?]*$"
            r"|^(?:what\s+(?:have|did)\s+i\s+download(?:ed)?|show\s+what\s+i\s+downloaded)[.!?]*$"
            r"|^(?:spotify\s+(?:par|pe|on|in|पर|पे)\s+(?:jao\s+(?:aur|and)\s+|जाओ\s+और\s+)?).+?\s+(?:chalao|chala\s+do|laga\s+do|bajao|play\s+(?:karo|kar\s+(?:do|lo))|चलाओ|चला\s+दो|लगाओ|लगा\s+दो|बजाओ)[.!?।]*$"
            r"|^(?:youtube|you\s+tube)\s+(?:par|pe|mein|me|में|पर|पे)\s+.+?\s+(?:chalao|chala\s+do|chalana|chalaana|laga\s+do|bajao|चलाओ|चला\s+दो|चलाना|लगाओ|लगा\s+दो|बजाओ)(?:\s+mere\s+liye|\s+मेरे\s+लिए)?[.!?।]*$"
            r"|^(?:मेरे|मेरी)\s+(?:स्क्रीन|डेस्कटॉप)\s+पर\s+(?:अभी\s+)?क्या\s+(?:ओपन|खुला)\s+है[।.!?]*$"
            r"|^(?:play|start|chalao|chala\s+do|laga\s+do|bajao|चलाओ|चला\s+दो|लगाओ|लगा\s+दो|बजाओ)\s+.+?\s+(?:on|in|par|pe|पर|पे)\s+spotify[.!?।]*$"
            r"|^(?:please\s+)?(?:youtube|you\s+tube)\s+(?:(?:par|pe)\s+)?(?:jao\s+(?:aur|and)\s+)?(?:ki\s+)?(?:.+?)\s+(?:latest|newest|most\s+recent|recent)\s+(?:video|videos)[^.!?]*\s+(?:chalao|chala\s+do|laga\s+do|play(?:\s+karo)?)[.!?]*$"
            r"|^(?:please\s+)?(?:what(?:'s| is)|whats)\s+(?:currently\s+)?(?:open\s+on|on|open\s+in)\s+(?:my\s+)?(?:screen|desktop|computer)[.!?]*$"
            r"|^(?:(?:please|zara|mujhe|mujhy)\s+)?(?:(?:meri|mera|my|current)\s+)?(?:screen|desktop|window)\s+(?:dikhao|dikha\s+do|check\s+karo|inspect\s+karo|dekh\s+lo|dekho)[.!?]*$"
            r"|^(?:screen|desktop)\s+(?:par|pe)\s+(?:kya\s+)?(?:hai|dikh\s+raha\s+hai|nazar\s+aa\s+raha\s+hai)[.!?]*$",
            normalized,
            flags=re.IGNORECASE,
        ):
            return False

        # Screen inspection and explicit UI interactions require the full execution
        # graph; answering from the chat fast path would falsely imply a click/type ran.
        if re.search(
            r"^(?:what(?:'s| is)|whats|what)\s+(?:(?:currently|right now)\s+)?(?:open\s+on|on|open in|open)\s+(?:my\s+)?(?:screen|desktop|computer)(?:\s+(?:right now|currently|at the moment|please))?[.!?]*$"
            r"|^(?:please\s+)?(?:inspect|check|show|look at|read)\s+(?:the\s+)?(?:current\s+)?(?:screen|desktop|window)(?:\s+(?:in|for|named|titled)\s+.+)?[.!?]*$"
            r"|^(?:(?:please|zara|mujhe|mujhy)\s+)?(?:(?:meri|mera|my|current)\s+)?(?:screen|desktop|window)\s+(?:dikhao|dikha\s+do|check\s+karo|inspect\s+karo|dekh\s+lo|dekho)[.!?]*$"
            r"|^(?:screen|desktop)\s+(?:par|pe)\s+(?:kya\s+)?(?:hai|dikh\s+raha\s+hai|nazar\s+aa\s+raha\s+hai)[.!?]*$"
            r"|^(?:स्क्रीन|डेस्कटॉप|विंडो)\s+(?:दिखाओ|दिखा\s+दो|चेक\s+करो|जाँचो|इंस्पेक्ट\s+करो)[।.!?]*$"
            r"|^(?:स्क्रीन|डेस्कटॉप)\s+पर\s+क्या\s+(?:है|दिख\s+रहा\s+है|नज़र\s+आ\s+रहा\s+है)[।.!?]*$"
            r"|^(?:please\s+)?(?:click|tap|select)\s+(?:on\s+)?(?:the\s+)?[^.!?]{1,120}(?:\s+(?:button|link|tab))?(?:\s+(?:in|on|inside)\s+(?:the\s+)?[^.!?]{1,120})?[.!?]*$"
            r"|^(?:please\s+)?(?:type|enter|write)\s+.+?\s+(?:into|in)\s+(?:the\s+)?[^.!?]{1,120}[.!?]*$"
            r"|^(?:please\s+)?(?:press|hit)\s+(?:ctrl\+[lfacv]|tab|shift\+tab|escape|esc|space|backspace|up|down|left|right|home|end|f5|enter)(?:\s+(?:in|on)\s+(?:the\s+)?[^.!?]{1,120})?[.!?]*$",
            normalized,
            flags=re.IGNORECASE,
        ):
            return False

        if re.search(
            r"^(?:(?:please|zara)\s+)?(?:(?:.+?)\s+(?:mein|me|ke\s+andar)\s+)?[^.!?]{1,120}?\s+(?:(?:button|link|tab)\s+)?(?:par|pe)\s+(?:click|tap)\s+(?:karo|karna|kar\s+(?:do|lo))[.!?]*$"
            r"|^[^.!?]{1,120}?\s+(?:mein|me)\s+.+?\s+(?:likho|likh\s+(?:do|dijiye)|type\s+karo|enter\s+karo)[.!?]*$"
            r"|^(?:ctrl\+[lfacv]|tab|shift\+tab|escape|esc|space|backspace|up|down|left|right|home|end|f5|enter)\s+(?:dabao|daba\s+do|press\s+karo|press\s+kar\s+do|kar\s+do)[.!?]*$",
            normalized,
            flags=re.IGNORECASE,
        ):
            return False

        if cls._is_planning_context_follow_up(
            message=message,
            history=history,
        ):
            return False

        if cls._has_unfinished_email_draft_context(
            message=message,
            history=history,
        ):
            return False

        if cls._has_task_creation_confirmation_context(
            message=message,
            history=history,
        ):
            return False

        # A short approval after NOVA proposed a Calendar event is not ordinary
        # chat, even if a pending database confirmation was not persisted.
        # Route it through the graph, which must resolve or safely reject it.
        if cls._has_unfinished_calendar_confirmation_context(
            message=message,
            history=history,
        ):
            return False

        # Persisted task/reminder agenda questions belong to the full NOVA
        # graph because their answer must come from current application data,
        # not from a fresh LLM-generated response.
        if normalized.lower() in {
            "what do i need to work on tomorrow?",
            "what should i work on tomorrow?",
            "what do i have to work on tomorrow?",
            "what do i need to do tomorrow?",
            "what should i do tomorrow?",
            "what work do i have tomorrow?",
            "what tasks do i have tomorrow?",
        }:
            return False

        # Spoken current-information questions often arrive with fillers or
        # non-native word order ("tell me like today in cricket which man is
        # live right now"). They must bypass the generic companion fast path
        # so the intent classifier and fresh-web-research guard can run.
        has_freshness_cue = re.search(
            r"\b(?:latest|current(?:ly)?|recent(?:ly)?|today(?:'s)?|"
            r"right now|live|as of now|this week|this month|this year)\b",
            normalized,
            flags=re.IGNORECASE,
        ) is not None
        has_live_information_subject = re.search(
            r"\b(?:news|headlines?|weather|forecast|prices?|rates?|stocks?|"
            r"score|scores|match|matches|cricket|football|sports?|playing|"
            r"happening|updates?|status|version|versions)\b",
            normalized,
            flags=re.IGNORECASE,
        ) is not None
        has_information_request = re.search(
            r"\b(?:what|who|which|when|where|why|how|tell me|show me|"
            r"give me|find|search|look up|check|browse|is there|are there)\b",
            normalized,
            flags=re.IGNORECASE,
        ) is not None
        if (
            has_freshness_cue
            and has_live_information_subject
            and has_information_request
        ):
            return False

        return not any(
            pattern.search(normalized)
            for pattern in cls._FULL_PIPELINE_PATTERNS
        )

    def _has_pending_confirmation(
        self,
        *,
        user_id: str,
        conversation_id: int,
    ) -> bool:
        """Keep every message on the confirmation graph while approval is pending."""
        if self.confirmation_service is None:
            return False

        try:
            return (
                self.confirmation_service.get_latest_pending_confirmation(
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
                is not None
            )
        except Exception as exc:
            # Fail closed: a lookup failure must not send an unverified
            # message through the fast path that bypasses confirmation state.
            logger.warning(
                "Pending confirmation lookup failed; using full graph: %s",
                type(exc).__name__,
            )
            return True

    @staticmethod
    def _fallback_conversation_title(message: str) -> str:
        normalized = " ".join(message.strip().split())
        if not normalized:
            return "New Conversation"

        first_line = normalized.split("\n", 1)[0].strip()
        words = first_line.split()
        title = " ".join(words[:6]).strip(" .,!?:;")
        if not title:
            return "New Conversation"

        return title[:200]

    @staticmethod
    def _profile_memory_query_type(message: str) -> str | None:
        """Identify questions that must consult durable profile memories."""
        normalized = " ".join(str(message).strip().lower().split())
        name_patterns = (
            r"\bwhat(?:\s+is|'s)\s+my\s+name\b",
            r"\bwho am i\b",
            r"\bwhat\s+name\s+do\s+you\s+have\s+(?:saved|stored|remembered)(?:\s+for me)?\b",
            r"\bwhat\s+name\s+(?:have you|did you)\s+(?:saved|stored|remembered)\b",
            r"\bwhat\s+(?:name|first name)\s+(?:have you|did you)\s+(?:saved|stored|remembered)\b",
            r"\bwhat did you (?:save|store|remember) as my name\b",
            r"\b(?:saved|stored|remembered) name for me\b",
            r"\bmera naam kya(?: hai)?\b",
            r"\u0645\u06cc\u0631\u0627\s+\u0646\u0627\u0645\s+\u06a9\u06cc\u0627",
            r"\u092e\u0947\u0930\u093e\s+\u0928\u093e\u092e\s+\u0915\u094d\u092f\u0627",
        )
        if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in name_patterns):
            return "name"

        profile_patterns = (
            r"\bwhat do you know about me\b",
            r"\bwhat are my (?:goals|preferences|projects|interests)\b",
            r"\bwhat do you remember about (?:me|my\b)",
            r"\bwhat have i told you about\b",
            r"\bwhat (?:have you|did you) (?:saved?|stored?|remembered?) about\b",
            r"\bwhat (?:have you|did you) (?:saved?|stored?) (?:for|about) me\b",
            r"\bwhat (?:is|does) (?:saved|stored) in my (?:memory|memories|profile)\b",
            r"\bapko mere bare mein kya pata\b",
            r"\u0622\u067e\s+\u06a9\u0648\s+\u0645\u06cc\u0631\u06d2\s+\u0628\u0627\u0631\u06d2\s+\u0645\u06cc\u06ba\s+\u06a9\u06cc\u0627\s+\u067e\u062a\u06c1",
            r"\u0906\u092a\u0915\u094b\s+\u092e\u0947\u0930\u0947\s+\u092c\u093e\u0930\u0947\s+\u092e\u0947\u0902\s+\u0915\u094d\u092f\u093e\s+\u092a\u0924\u093e",
        )
        if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in profile_patterns):
            return "profile"
        return None

    def _conversation_memory_context(
        self,
        *,
        user_id: str,
        message: str,
    ) -> str:
        """Return semantic memories plus durable profile facts for identity questions."""
        try:
            memories = self.memory_service.find_similar_memories(
                user_id=user_id,
                new_memory=message,
                threshold=0.65,
                limit=4,
            )
        except Exception:
            memories = []

        profile_query_type = self._profile_memory_query_type(message)
        if profile_query_type:
            try:
                profile_memories = self.memory_service.get_profile_memories(
                    user_id=user_id,
                    limit=20,
                )
            except Exception:
                profile_memories = []

            name_marker = re.compile(
                r"\bname\b|\bcalled\b|\bnickname\b|\bnaam\b|"
                r"\u0646\u0627\u0645|\u0928\u093e\u092e",
                re.IGNORECASE,
            )
            name_memories = [
                item for item in profile_memories
                if name_marker.search(str(item.get("memory", "")))
            ]
            canonical_name_marker = re.compile(
                r"\buser(?:'s)?\s+name\s+is\b|\bname\s+is\b|"
                r"\bmera\s+naam\b|"
                r"\u0645\u06cc\u0631\u0627\s+\u0646\u0627\u0645|"
                r"\u092e\u0947\u0930\u093e\s+\u0928\u093e\u092e",
                re.IGNORECASE,
            )
            canonical_name_memories = [
                item for item in name_memories
                if canonical_name_marker.search(str(item.get("memory", "")))
            ]
            if name_memories:
                # Profile reads are newest-updated-first. A newer nickname-only
                # memory must not supersede the canonical name record.
                latest_name_memory = (canonical_name_memories or name_memories)[0]
                if profile_query_type == "name":
                    profile_memories = [latest_name_memory]
                else:
                    profile_memories = [
                        latest_name_memory,
                        *[
                            item for item in profile_memories
                            if not name_marker.search(str(item.get("memory", "")))
                        ],
                    ]
            elif profile_query_type == "name":
                # A generic identity fact (e.g. a family member's name) is
                # not enough evidence to answer the user's own-name question.
                profile_memories = []

            if profile_query_type == "name":
                canonical_name_memory = (
                    str(profile_memories[0].get("memory", "")).strip().casefold()
                    if profile_memories
                    else ""
                )
                memories = [
                    item for item in memories
                    if (
                        not name_marker.search(str(item.get("memory", "")))
                        or (
                            canonical_name_memory
                            and str(item.get("memory", "")).strip().casefold()
                            == canonical_name_memory
                        )
                    )
                ]

            merged: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in [*profile_memories, *memories]:
                memory_text = str(item.get("memory", "")).strip()
                key = memory_text.casefold()
                if memory_text and key not in seen:
                    merged.append(item)
                    seen.add(key)
            if merged:
                memories = merged[:8]

        return "\n".join(
            f"- {item.get('memory', '')}"
            for item in memories
            if str(item.get("memory", "")).strip()
        )

    @staticmethod
    def _is_memory_candidate(message: str) -> bool:
        """Skip costly memory extraction for greetings, commands, and transient chatter."""
        return any(pattern.search(message) for pattern in _MEMORY_CANDIDATE_PATTERNS)

    def extract_and_save_memory(
        self,
        *,
        user_id: str,
        user_message: str,
    ) -> str | None:
        """
        Extract and persist likely long-term personal facts.

        Provider/database failures are contained because memory is an
        enhancement, never the authoritative conversational response.
        """
        if not self._is_memory_candidate(user_message):
            return None

        try:
            new_memory = self.llm_service.extract_memory(
                user_message
            )
        except Exception as exc:
            logger.warning(
                "Conversation memory extraction failed: %s",
                type(exc).__name__,
            )
            return None

        if not new_memory:
            return None

        try:
            return self.memory_service.add_memory(
                user_id=user_id,
                memory_text=new_memory["memory_text"],
                category=new_memory["category"],
                importance=new_memory["importance"],
                user_message=user_message,
            )
        except Exception as exc:
            logger.warning(
                "Conversation memory persistence failed: %s",
                type(exc).__name__,
            )
            return None

    @staticmethod
    def _private_knowledge_command(
        message: str,
    ) -> tuple[str, str] | None:
        normalized = " ".join(
            str(message).strip().lower().split()
        )

        for prefix in PRIVATE_KNOWLEDGE_SAVE_PREFIXES:
            if normalized.startswith(prefix):
                content = str(message).strip()[len(prefix):].strip()
                if content:
                    return ("save", content)
                return None

        for prefix in PRIVATE_KNOWLEDGE_SEARCH_PREFIXES:
            if normalized.startswith(prefix):
                query = str(message).strip()[len(prefix):].strip()
                if query:
                    return ("search", query)
                return None

        return None

    def _execute_private_knowledge_command(
        self,
        *,
        user_id: str,
        conversation_id: int,
        user_message: str,
    ) -> dict[str, Any] | None:
        command = self._private_knowledge_command(
            user_message
        )

        if command is None:
            return None

        if self.knowledge_service is None:
            return {
                "response": (
                    "Private knowledge is temporarily unavailable. "
                    "Please try again in a moment."
                ),
                "conversation_id": conversation_id,
                "knowledge_sources": [],
                "skip_memory_extraction": True,
            }

        action, payload = command

        if action == "save":
            try:
                document = self.knowledge_service.create_document(
                    user_id=user_id,
                    title="Private Knowledge",
                    content=payload,
                    source="NOVA conversation",
                )
            except ValueError as exc:
                if "identical content" in str(exc).lower():
                    response = (
                        "That information is already in your private knowledge."
                    )
                else:
                    raise
            else:
                response = (
                    "Got it. I saved that to your private knowledge."
                )

                return {
                    "response": response,
                    "conversation_id": conversation_id,
                    "knowledge_sources": [
                        {
                            "document_id": document["id"],
                            "title": document["title"],
                            "source": document["source"],
                            "chunk_index": 0,
                            "similarity": 1.0,
                        }
                    ],
                    "skip_memory_extraction": True,
                }

            return {
                "response": response,
                "conversation_id": conversation_id,
                "knowledge_sources": [],
                "skip_memory_extraction": True,
            }

        matches = self.knowledge_service.search(
            user_id=user_id,
            query=payload,
            threshold=0.60,
            limit=8,
            rerank=True,
            candidate_limit=DEFAULT_RERANK_CANDIDATE_LIMIT,
        )

        if not matches:
            focused_query = re.sub(
                r"^(?:how|what|why|when|where|who)\s+",
                "",
                payload,
                count=1,
                flags=re.IGNORECASE,
            ).strip(" ?!.,;:")

            if focused_query and focused_query != payload:
                matches = self.knowledge_service.search(
                    user_id=user_id,
                    query=focused_query,
                    threshold=PRIVATE_KNOWLEDGE_SEARCH_FALLBACK_THRESHOLD,
                    limit=8,
                    rerank=True,
                    candidate_limit=DEFAULT_RERANK_CANDIDATE_LIMIT,
                )

        if not matches:
            return {
                "response": (
                    "I couldn't find anything relevant in your private knowledge."
                ),
                "conversation_id": conversation_id,
                "knowledge_sources": [],
                "skip_memory_extraction": True,
            }

        sections: list[str] = []
        sources: list[dict[str, Any]] = []

        for index, match in enumerate(matches, start=1):
            content = str(
                match.get("content", "")
            ).strip()

            if not content:
                continue

            title = str(
                match.get("title")
                or "Private Knowledge"
            ).strip()

            source = str(
                match.get("source")
                or "NOVA conversation"
            ).strip()

            sections.append(
                f"[Source {index}] {title}\n{content}"
            )

            sources.append(
                {
                    "document_id": match.get("document_id"),
                    "title": title,
                    "source": source,
                    "chunk_index": match.get("chunk_index"),
                    "similarity": match.get("similarity"),
                }
            )

        if not sections:
            return {
                "response": (
                    "I couldn't find anything relevant in your private knowledge."
                ),
                "conversation_id": conversation_id,
                "knowledge_sources": [],
                "skip_memory_extraction": True,
            }

        response = (
            "Here’s what I found in your private knowledge:\n\n"
            + "\n\n".join(sections)
        )

        return {
            "response": response,
            "conversation_id": conversation_id,
            "knowledge_sources": sources,
            "skip_memory_extraction": True,
        }

    def execute_voice_message(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: int | None = None,
        on_response_delta: Callable[[str], None] | None = None,
        is_execution_current: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a realtime voice turn with a fast conversational path.

        Ordinary conversation uses one compact streaming LLM call. Requests
        that may require tools, fresh web information, or knowledge retrieval
        remain on the full NOVA graph so existing safety and execution rules
        continue to apply.
        """

        user_message = str(message).strip()

        if not user_message:
            return {
                "error": "message cannot be empty"
            }

        conversation_id = self.prepare_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
        )

        history = self.conversation_service.get_context_history(
            user_id=user_id,
            conversation_id=conversation_id,
            max_messages=self.context_max_messages,
            max_characters=self.context_max_characters,
        )

        if (
            is_execution_current is not None
            and not is_execution_current()
        ):
            return {
                "cancelled": True,
                "conversation_id": conversation_id,
            }

        arithmetic_response = _simple_arithmetic_response(user_message)
        is_fast_candidate = arithmetic_response is not None or self._is_fast_conversation(
            user_message,
            history=history,
        )
        if (
            not is_fast_candidate
            or (
                arithmetic_response is None
                and self._has_pending_confirmation(
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
            )
        ):
            return self.execute_message(
                user_id=user_id,
                message=user_message,
                conversation_id=conversation_id,
                execution_context=ExecutionContext.interactive(voice=True),
                on_response_delta=on_response_delta,
                is_execution_current=is_execution_current,
                defer_memory_extraction=True,
            )

        if arithmetic_response is not None:
            response = arithmetic_response
            if on_response_delta is not None:
                on_response_delta(response)
        else:
            memory_context = self._conversation_memory_context(
                user_id=user_id,
                message=user_message,
            )

            response_parts: list[str] = []

            try:
                stream = self.llm_service.generate_voice_response_stream(
                    message=user_message,
                    history=history,
                    memory_context=memory_context,
                )

                for delta in stream:
                    if (
                        is_execution_current is not None
                        and not is_execution_current()
                    ):
                        return {
                            "cancelled": True,
                            "conversation_id": conversation_id,
                        }

                    response_parts.append(delta)
                    if on_response_delta is not None:
                        on_response_delta(delta)

                response = "".join(response_parts).strip()

            except Exception as exc:
                if not is_llm_provider_error(exc):
                    raise

                response = LLM_PROVIDER_UNAVAILABLE_RESPONSE
                if on_response_delta is not None:
                    on_response_delta(response)

        if (
            is_execution_current is not None
            and not is_execution_current()
        ):
            return {
                "cancelled": True,
                "conversation_id": conversation_id,
            }

        self.conversation_service.save_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="user",
            content=user_message,
        )

        self.conversation_service.save_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="assistant",
            content=response,
        )

        return {
            "response": response,
            "conversation_id": conversation_id,
            "understanding": {
                "intent": "chat",
                "requires_tool": False,
            },
            "plan": {"requires_tool": False},
            "permission": {
                "allowed": False,
                "requires_confirmation": False,
            },
            "confirmation": {
                "id": None,
                "status": None,
                "tool": None,
                "action": None,
                "reason": None,
            },
            "tool_result": {
                "success": False,
                "tool": None,
                "action": None,
                "result": None,
                "error": None,
            },
            "workflow_result": {},
            "memory_action": None,
            "knowledge_sources": [],
            "web_sources": [],
        }

    def execute_message(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: int | None = None,
        execution_context: ExecutionContext | None = None,
        on_response_delta: Callable[[str], None] | None = None,
        is_execution_current: Callable[[], bool] | None = None,
        defer_memory_extraction: bool = False,
    ) -> dict[str, Any]:
        user_message = str(message).strip()

        if not user_message:
            return {
                "error": "message cannot be empty"
            }

        resolved_context = (
            execution_context
            if execution_context is not None
            else ExecutionContext.interactive()
        )

        conversation_id = (
            self.conversation_service
            .get_or_create_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
            )
        )

        history = (
            self.conversation_service
            .get_context_history(
                user_id=user_id,
                conversation_id=conversation_id,
                max_messages=self.context_max_messages,
                max_characters=self.context_max_characters,
            )
        )

        if is_execution_current is not None and not is_execution_current():
            return {
                "cancelled": True,
                "conversation_id": conversation_id,
            }

        pending_calendar_approval = self._has_unfinished_calendar_confirmation_context(
            user_message,
            history=history,
        )
        if pending_calendar_approval and not self._has_pending_confirmation(
            user_id=user_id,
            conversation_id=conversation_id,
        ):
            response = (
                "I couldn't verify a pending Calendar confirmation, so I have NOT "
                "created the event. Please ask me to create it again and I'll verify "
                "the details before reporting success."
            )
            self.conversation_service.save_message(
                user_id=user_id,
                conversation_id=conversation_id,
                role="user",
                content=user_message,
            )
            self.conversation_service.save_message(
                user_id=user_id,
                conversation_id=conversation_id,
                role="assistant",
                content=response,
            )
            return {
                "response": response,
                "conversation_id": conversation_id,
                "understanding": {"intent": "calendar", "requires_tool": False},
                "plan": {"requires_tool": False},
                "permission": {"allowed": False, "requires_confirmation": False},
                "confirmation": {"id": None, "status": None, "tool": None, "action": None, "reason": None},
                "tool_result": {"success": False, "tool": None, "action": None, "result": None, "error": "No pending Calendar confirmation exists."},
                "workflow_result": {},
                "memory_action": None,
                "knowledge_sources": [],
                "web_sources": [],
            }

        arithmetic_response = _simple_arithmetic_response(user_message)
        is_fast_candidate = resolved_context.is_interactive and (
            arithmetic_response is not None
            or (
                not resolved_context.is_voice
                and self._is_fast_conversation(
                    user_message,
                    history=history,
                )
            )
        )
        is_private_knowledge_candidate = (
            not resolved_context.is_voice
            and self._private_knowledge_command(user_message) is not None
        )
        has_pending_confirmation = (
            self._has_pending_confirmation(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            if (
                arithmetic_response is None
                and (is_fast_candidate or is_private_knowledge_candidate)
            )
            else False
        )

        private_knowledge_result = (
            None
            if resolved_context.is_voice or has_pending_confirmation
            else self._execute_private_knowledge_command(
                user_id=user_id,
                conversation_id=conversation_id,
                user_message=user_message,
            )
        )

        if private_knowledge_result is not None:
            response = private_knowledge_result["response"]

            self.conversation_service.save_message(
                user_id=user_id,
                conversation_id=conversation_id,
                role="user",
                content=user_message,
            )

            self.conversation_service.save_message(
                user_id=user_id,
                conversation_id=conversation_id,
                role="assistant",
                content=response,
            )

            if not history:
                try:
                    self.conversation_service.update_conversation_title(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        title=self._fallback_conversation_title(
                            user_message
                        ),
                    )
                except Exception as exc:
                    logger.warning(
                        "Conversation title persistence failed: %s",
                        type(exc).__name__,
                    )

            return {
                "response": response,
                "conversation_id": conversation_id,
                "understanding": {
                    "intent": "knowledge",
                    "requires_tool": False,
                },
                "plan": {
                    "requires_tool": False,
                },
                "permission": {
                    "allowed": False,
                    "requires_confirmation": False,
                },
                "confirmation": {
                    "id": None,
                    "status": None,
                    "tool": None,
                    "action": None,
                    "reason": None,
                },
                "tool_result": {
                    "success": False,
                    "tool": None,
                    "action": None,
                    "result": None,
                    "error": None,
                },
                "workflow_result": {},
                "memory_action": None,
                "knowledge_sources": private_knowledge_result[
                    "knowledge_sources"
                ],
                "web_sources": [],
            }

        if not has_pending_confirmation and is_fast_candidate:
            if arithmetic_response is not None:
                response = arithmetic_response
                if on_response_delta is not None:
                    on_response_delta(response)
            else:
                memory_context = self._conversation_memory_context(
                    user_id=user_id,
                    message=user_message,
                )

                try:
                    response = self.llm_service.generate_companion_response(
                        message=user_message,
                        history=history,
                        memory_context=memory_context,
                    )
                except Exception as exc:
                    if not is_llm_provider_error(exc):
                        logger.exception(
                            "Fast conversation response generation failed."
                        )
                        raise

                    logger.warning(
                        "Fast conversation provider unavailable: %s",
                        type(exc).__name__,
                    )
                    response = LLM_PROVIDER_UNAVAILABLE_RESPONSE

            if (
                is_execution_current is not None
                and not is_execution_current()
            ):
                return {
                    "cancelled": True,
                    "conversation_id": conversation_id,
                }

            self.conversation_service.save_message(
                user_id=user_id,
                conversation_id=conversation_id,
                role="user",
                content=user_message,
            )

            self.conversation_service.save_message(
                user_id=user_id,
                conversation_id=conversation_id,
                role="assistant",
                content=response,
            )

            if not history:
                title = self._fallback_conversation_title(
                    user_message
                )

                try:
                    self.conversation_service.update_conversation_title(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        title=title,
                    )
                except Exception as exc:
                    logger.warning(
                        "Conversation title persistence failed: %s",
                        type(exc).__name__,
                    )

            memory_action = None
            if not defer_memory_extraction:
                memory_action = self.extract_and_save_memory(
                    user_id=user_id,
                    user_message=user_message,
                )

            return {
                "response": response,
                "conversation_id": conversation_id,
                "understanding": {
                    "intent": "chat",
                    "requires_tool": False,
                },
                "plan": {
                    "requires_tool": False,
                },
                "permission": {
                    "allowed": False,
                    "requires_confirmation": False,
                },
                "confirmation": {
                    "id": None,
                    "status": None,
                    "tool": None,
                    "action": None,
                    "reason": None,
                },
                "tool_result": {
                    "success": False,
                    "tool": None,
                    "action": None,
                    "result": None,
                    "error": None,
                },
                "workflow_result": {},
                "memory_action": memory_action,
                "knowledge_sources": [],
                "web_sources": [],
            }

        execution_kwargs = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "user_message": user_message,
            "history": history,
            "execution_context": resolved_context,
        }

        if on_response_delta is not None:
            execution_kwargs["on_response_delta"] = (
                on_response_delta
            )

        result = self.execution_service.execute(
            **execution_kwargs
        )

        if is_execution_current is not None and not is_execution_current():
            return {
                "cancelled": True,
                "conversation_id": conversation_id,
            }

        response = str(result.get("response") or "").strip()
        if not response:
            logger.error(
                "Execution graph returned an empty response; using safe fallback."
            )
            response = (
                "I couldn't produce a complete answer just now. "
                "No external action was taken. Please try again in a moment."
            )

        understanding = result["understanding"]
        plan = result.get("plan", {})
        permission = result.get("permission", {})
        confirmation = result.get("confirmation", {})
        tool_result = result["tool_result"]
        workflow_result = result.get("workflow_result", {})
        knowledge_sources = result.get("knowledge_sources", [])
        web_sources = result.get("web_sources", [])

        # The task-list tool result is the source of truth. In live voice the
        # generator once claimed it needed system access even though the tool
        # had returned a successful, user-scoped database list.
        persisted_task_response = _format_persisted_task_list_response(
            tool_result,
            user_message,
        )
        if persisted_task_response is not None:
            response = persisted_task_response

        # Reminder-list answers must also reflect the actual user-scoped rows;
        # the model must not claim it lacks access after a successful tool call.
        persisted_reminder_response = _format_persisted_reminder_list_response(
            tool_result,
            user_message,
        )
        if persisted_reminder_response is not None:
            response = persisted_reminder_response

        read_action_error_response = _format_failed_read_action_response(tool_result)
        if read_action_error_response is not None:
            response = read_action_error_response
        response = _append_requested_web_sources(
            response,
            user_message,
            tool_result,
        )
        response = _clarify_chat_only_email_draft(
            response,
            user_message,
            tool_result,
        )

        self.conversation_service.save_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="user",
            content=user_message,
        )

        self.conversation_service.save_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="assistant",
            content=response,
        )

        if not history and not resolved_context.is_voice:
            # Deterministic local titles avoid an extra provider call after
            # the user-facing response has already been generated.
            title = self._fallback_conversation_title(user_message)

            try:
                self.conversation_service.update_conversation_title(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    title=title,
                )
            except Exception as exc:
                logger.warning(
                    "Conversation title persistence failed: %s",
                    type(exc).__name__,
                )

        memory_action = None

        if not defer_memory_extraction:
            memory_action = self.extract_and_save_memory(
                user_id=user_id,
                user_message=user_message,
            )

        return {
            "response": response,
            "conversation_id": conversation_id,
            "understanding": understanding,
            "plan": plan,
            "permission": permission,
            "confirmation": confirmation,
            "tool_result": tool_result,
            "workflow_result": workflow_result,
            "memory_action": memory_action,
            "knowledge_sources": knowledge_sources,
            "web_sources": web_sources,
        }
