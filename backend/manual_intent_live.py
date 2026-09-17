from pprint import pprint

from services.intent_service import IntentService


service = IntentService()

test_messages = [
    "Remind me tomorrow at 10 AM to submit my CV.",
    "Show me my reminders.",
    "Cancel the reminder about my CV.",
    "Move my CV reminder to tomorrow at 3 PM.",
    "Create a high priority task to practice LangGraph for my interview.",
    "Complete my LangGraph task.",
    "Make my LangGraph task high priority.",
    "What is LangGraph?",
    "I'm feeling stressed about my AI Engineer interview.",
]


for message in test_messages:
    print("\n" + "=" * 70)
    print("USER:", message)
    print("=" * 70)

    result = service.analyze(message)

    pprint(result)