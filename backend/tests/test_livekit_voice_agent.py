from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

from livekit_voice_agent import (
    AGENT_NAME,
    NovaLiveKitAgent,
    NovaGeminiRealtimeModel,
    _clear_stale_gemini_resumption_handle,
    _build_voice_http_options,
    _execute_voice_message_in_worker,
    _extract_voice_memory,
    _instructions,
    _prewarm_voice_execution_graph,
    _realtime_input_config,
    _realtime_context_window_compression,
    server,
)


def test_livekit_agent_name_matches_room_dispatch():
    assert AGENT_NAME == "nova-voice"


def test_android_phone_action_router_matches_device_commands_not_cloud_actions():
    assert NovaLiveKitAgent.looks_like_mobile_device_action("Open Tapmad")
    assert NovaLiveKitAgent.looks_like_mobile_device_action("YouTube open karo mere liye")
    assert NovaLiveKitAgent.looks_like_mobile_device_action("Open YouTube and play Pal Pal")
    assert NovaLiveKitAgent.looks_like_mobile_device_action("YouTube kholo aur Pal Pal song chalao")
    assert NovaLiveKitAgent.looks_like_mobile_device_action("YouTube \u0916\u094b\u0932\u094b\u0964")
    assert NovaLiveKitAgent.looks_like_mobile_device_action("YouTube \u0916\u094b\u0932\u094b")
    assert NovaLiveKitAgent.looks_like_mobile_device_action("YouTube \u0916\u094b\u0932\u094b \u0914\u0930 Pal Pal \u0917\u093e\u0928\u093e \u091a\u0932\u093e\u0913")
    assert not NovaLiveKitAgent.looks_like_mobile_device_action("Tell me about YouTube")
    assert NovaLiveKitAgent.looks_like_mobile_device_action("awaz barha do")
    assert NovaLiveKitAgent.looks_like_mobile_device_action("go to Settings")
    assert NovaLiveKitAgent.looks_like_mobile_device_action("scroll down on the phone")
    assert NovaLiveKitAgent.looks_like_mobile_device_action("हाँ, YouTube ओपन करके कोई सॉन्ग चलाओ पल-पल।")
    assert NovaLiveKitAgent.looks_like_mobile_device_action("YouTube ओपन करो मेरा।")
    assert NovaLiveKitAgent.looks_like_mobile_device_action("YouTube खोलो और Pal Pal चलाओ")
    assert NovaLiveKitAgent.looks_like_mobile_device_action("یوٹیوب کھول دو")
    assert not NovaLiveKitAgent.looks_like_mobile_device_action(
        "Send an email to sarosh@example.com"
    )
    assert not NovaLiveKitAgent.looks_like_mobile_device_action(
        "Search the web for recent AI news"
    )


def test_gemini_resumption_conflict_clears_only_the_stale_handle():
    live_session = SimpleNamespace(
        _session_resumption_handle="opaque-resumption-handle",
        _resumption_chat_ctx=object(),
    )
    event = SimpleNamespace(error=RuntimeError("1008 None. Requested entity already exists"))

    assert _clear_stale_gemini_resumption_handle(live_session, event) is True
    assert live_session._session_resumption_handle is None
    assert live_session._resumption_chat_ctx is None

    healthy_session = SimpleNamespace(
        _session_resumption_handle="still-valid-handle",
        _resumption_chat_ctx=object(),
    )
    unrelated_event = SimpleNamespace(error=RuntimeError("temporary network reset"))
    original_context = healthy_session._resumption_chat_ctx

    assert _clear_stale_gemini_resumption_handle(healthy_session, unrelated_event) is False
    assert healthy_session._session_resumption_handle == "still-valid-handle"
    assert healthy_session._resumption_chat_ctx is original_context

    expired_session = SimpleNamespace(
        _session_resumption_handle="expired-handle",
        _resumption_chat_ctx=object(),
    )
    expired_event = SimpleNamespace(
        error=RuntimeError("1008 - session not found or expired"),
    )
    assert _clear_stale_gemini_resumption_handle(expired_session, expired_event) is True
    assert expired_session._session_resumption_handle is None
    assert expired_session._resumption_chat_ctx is None


def test_gemini_resumption_recovery_is_attached_to_the_returned_session(monkeypatch):
    registered_handlers = {}
    realtime_session = SimpleNamespace(
        marker="returned-session-wrapper",
        _session_resumption_handle="rejected-handle",
        _resumption_chat_ctx=object(),
    )
    realtime_session.on = (
        lambda event_name, callback: registered_handlers.__setitem__(event_name, callback)
    )

    def fake_parent_session(self, *, turn_detection_disabled=False):
        return realtime_session

    parent_model = NovaGeminiRealtimeModel.__mro__[1]
    monkeypatch.setattr(parent_model, "session", fake_parent_session)
    model = object.__new__(NovaGeminiRealtimeModel)

    assert model.session() is realtime_session
    assert "error" in registered_handlers
    assert registered_handlers["error"](
        SimpleNamespace(error=RuntimeError("1008 Requested entity already exists"))
    ) is True
    assert realtime_session._session_resumption_handle is None
    assert realtime_session._resumption_chat_ctx is None
    assert realtime_session.marker == "returned-session-wrapper"


def test_livekit_worker_preloads_execution_graph_and_keeps_one_worker_warm():
    assert server._preload_modules == ["main"]
    assert server._num_idle_processes == 1
    assert server._setup_fnc is _prewarm_voice_execution_graph
    assert server._initialize_process_timeout >= 60.0


def test_livekit_worker_prewarms_execution_graph_in_worker_process(monkeypatch, caplog):
    fake_execution_service = object()
    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=fake_execution_service),
    )

    with caplog.at_level("INFO", logger="nova.livekit_voice"):
        _prewarm_voice_execution_graph(None)

    assert "execution graph prewarmed" in caplog.text


def test_voice_worker_configures_runtime_notification_provider_before_action(monkeypatch):
    calls = []

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            calls.append(("execute", kwargs))
            return {"response": "sent", "tool_result": {"success": True}}

    def configure_delivery():
        calls.append(("configure", None))

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(
            conversation_execution_service=FakeExecutionService(),
            configure_runtime_notification_service=configure_delivery,
        ),
    )

    result = _execute_voice_message_in_worker(
        user_id="user-123",
        message="Confirm",
        conversation_id=42,
    )

    assert result["tool_result"]["success"] is True
    assert calls == [
        ("configure", None),
        (
            "execute",
            {
                "user_id": "user-123",
                "message": "Confirm",
                "conversation_id": 42,
            },
        ),
    ]


def test_multilingual_voice_instructions_mirror_language_and_script():
    instructions = _instructions("multi")
    assert "English -> English" in instructions
    assert "Urdu script -> Urdu script" in instructions
    assert "Roman Urdu or Hinglish" in instructions
    assert "Devanagari -> Hindi in Devanagari" in instructions
    assert "not an English-speaker accent" in instructions
    assert "smooth, continuous flow" in instructions
    assert "Avoid multi-second pauses mid-sentence" in instructions


def test_urdu_mode_does_not_switch_to_hindi():
    instructions = _instructions("ur")
    assert "Pakistani Urdu in Urdu script" in instructions
    assert "Do not switch to Hindi" in instructions


def test_voice_agent_defers_sensitive_actions_to_nova_execution_policy():
    instructions = _instructions("multi")
    assert "nova_execute_request" in instructions
    assert "permissions and confirmation requirements" in instructions
    assert "Never claim an action completed unless the" in instructions


def test_voice_agent_must_route_explicit_desktop_actions_to_executor():
    instructions = _instructions("multi")
    assert "every explicit device action" in instructions
    assert "opening or navigating to a website/URL" in instructions
    assert "launching an application" in instructions
    assert "searching local files" in instructions
    assert "MUST" in instructions
    assert "Never say that you cannot open websites or" in instructions
    assert "full original user request" in instructions


def test_voice_tool_bridge_uses_authenticated_execution_context(monkeypatch):
    calls = []

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            calls.append(kwargs)
            return {
                "response": "Reminder created.",
                "conversation_id": 42,
                "understanding": {"intent": "reminder", "requires_tool": True},
                "confirmation": {"id": 12, "status": "pending", "tool": "reminder"},
                "tool_result": {"success": True, "tool": "reminder"},
            }

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(
            conversation_execution_service=FakeExecutionService(),
        ),
    )

    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=42,
        language="multi",
    )
    result = asyncio.run(
        agent.nova_execute_request(
            context=object(),
            request="Remind me tomorrow at 9 AM to review my tasks.",
        )
    )
    payload = json.loads(result)

    assert payload["ok"] is False
    assert payload["action_succeeded"] is False
    assert payload["confirmation_pending"] is True
    assert payload["result"]["confirmation"]["status"] == "pending"
    assert calls == [
        {
            "user_id": "user-123",
            "message": "Remind me tomorrow at 9 AM to review my tasks.",
            "conversation_id": 42,
        }
    ]


def test_voice_execution_guard_resets_only_for_a_new_finalized_turn():
    agent = NovaLiveKitAgent(user_id="user-123", conversation_id=42, language="multi")

    agent.begin_user_turn("Open Notepad", turn_id="provider-item-1")
    assert agent._voice_tool_used is False
    assert agent._current_user_turn_id == "provider-item-1"

    # Re-delivering the same finalized provider item must not unlock execution.
    agent._voice_tool_used = True
    agent.begin_user_turn("Open Notepad", turn_id="provider-item-1")
    assert agent._voice_tool_used is True

    # A genuinely new provider item starts a new turn and permits one execution.
    agent.begin_user_turn("Open Calculator", turn_id="provider-item-2")
    assert agent._voice_tool_used is False
    assert agent._current_user_turn_id == "provider-item-2"


def test_voice_tool_bridge_rejects_duplicate_call_until_a_new_user_turn(monkeypatch):
    calls = []

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            calls.append(kwargs)
            return {
                "response": "Opened Notepad.",
                "conversation_id": 42,
                "understanding": {"intent": "desktop", "requires_tool": True},
                "confirmation": None,
                "tool_result": {
                    "success": True,
                    "tool": "desktop",
                    "action": "start",
                    "error": None,
                },
            }

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(user_id="user-123", conversation_id=42, language="multi")

    agent.begin_user_turn("Open Notepad", turn_id="provider-item-1")
    first = json.loads(asyncio.run(
        agent.nova_execute_request(context=object(), request="Open Notepad")
    ))
    duplicate = json.loads(asyncio.run(
        agent.nova_execute_request(context=object(), request="Open Notepad")
    ))

    assert first["action_succeeded"] is True
    assert duplicate["ok"] is False
    assert "already submitted" in duplicate["message"].lower()
    assert len(calls) == 1

    agent.begin_user_turn("Open Calculator", turn_id="provider-item-2")
    next_turn = json.loads(asyncio.run(
        agent.nova_execute_request(context=object(), request="Open Calculator")
    ))
    assert next_turn["action_succeeded"] is True
    assert len(calls) == 2
    assert calls[-1]["message"] == "Open Calculator"


def test_voice_tool_bridge_never_claims_success_after_executor_error(monkeypatch):
    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            raise RuntimeError("internal-test-secret")

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(
            conversation_execution_service=FakeExecutionService(),
        ),
    )

    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=42,
        language="multi",
    )
    result = asyncio.run(
        agent.nova_execute_request(
            context=object(),
            request="Send the email we discussed.",
        )
    )
    payload = json.loads(result)

    assert payload["ok"] is False
    assert "Do not claim the requested action was completed." in payload["message"]
    assert "internal-test-secret" not in result


def test_voice_agent_action_detector_claims_mixed_devanagari_website_command():
    agent = NovaLiveKitAgent(user_id="user-123", conversation_id=42, language="multi")
    request = "\u0905\u091a\u094d\u091b\u093e, Wikipedia \u0913\u092a\u0928 \u0915\u0930\u0928\u093e\u0964"
    assert agent._request_looks_actionable(request) is True
    assert agent.queue_direct_action(request) is True


def test_voice_agent_claims_mixed_devanagari_website_command_with_hai():
    agent = NovaLiveKitAgent(user_id="user-123", conversation_id=42, language="multi")
    request = "Acha, Wikipedia \u0913\u092a\u0928 \u0915\u0930\u0928\u093e \u0939\u0948\u0964"
    assert agent._request_looks_actionable(request) is True


def test_voice_agent_claims_cv_discovery_and_hindi_local_disk_actions():
    agent = NovaLiveKitAgent(user_id="user-123", conversation_id=42, language="multi")

    cv_request = "Achha meri CV dekho wo mujhe batao kaun kaun si hai?"
    drive_request = "\u0905\u091a\u094d\u091b\u093e \u0932\u094b\u0915\u0932 \u0921\u093f\u0938\u094d\u0915 \u0938\u0940 \u0913\u092a\u0928 \u0915\u0930\u0928\u093e\u0964"

    assert agent._request_looks_actionable(cv_request) is True
    assert agent._request_looks_actionable(drive_request) is True
    assert agent._request_looks_actionable("Meri downloaded files dikhao") is True
    assert agent._request_looks_actionable("Meri emails dikhao") is True
    assert agent._request_looks_actionable("Meri inbox check karo") is True
    assert agent._request_looks_actionable("List files in Downloads") is True
    assert agent._request_looks_actionable("Spotify kholo aur Pal Pal chalao") is True
    assert agent._request_looks_actionable("Spotify par jao aur Pal Pal song chalao") is True


def test_voice_agent_does_not_execute_vague_email_capability_question():
    agent = NovaLiveKitAgent(user_id="user-123", conversation_id=42, language="multi")
    assert not agent._request_looks_actionable("Email mein koi email send kar sakti ho?")
    assert agent._request_looks_actionable("simple email test draft now")
    assert not agent._request_looks_actionable("How do I draft a simple test email?")
    assert not agent._request_looks_actionable("Simple test email draft, do not send")


def test_direct_action_reply_suppression_survives_duplicate_final_transcript():
    agent = NovaLiveKitAgent(user_id="user-123", conversation_id=42, language="multi")
    agent.begin_user_turn("Open Wikipedia", turn_id="provider-item-1")
    assert agent.queue_direct_action("Open Wikipedia") is True

    # The direct action may finish before the provider emits a duplicate final
    # transcript for the same item. That duplicate must not release suppression.
    agent._direct_action_in_progress = False
    agent.release_action_reply_suppression_for_new_turn(turn_id="provider-item-1")
    assert agent._suppress_realtime_reply_for_action is True

    # A distinct provider item is a new user turn and can release the old latch.
    agent.release_action_reply_suppression_for_new_turn(turn_id="provider-item-2")
    assert agent._suppress_realtime_reply_for_action is False


def test_voice_agent_claims_supported_explicit_actions_before_model_tool_selection():
    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=42,
        language="multi",
    )

    assert agent._request_looks_actionable("Open Wikipedia")
    assert agent._request_looks_actionable("Open Local Drive C")
    assert agent._request_looks_actionable("Local Drive C open karna")
    assert agent._request_looks_actionable("Wikipedia open karo")
    assert agent._request_looks_actionable("What's open on my screen?")
    assert agent._request_looks_actionable("What's on my screen right now?")
    assert agent._request_looks_actionable("What open on my screen right now?")
    assert agent._request_looks_actionable("What is on my screen?")
    assert agent._request_looks_actionable("Meri downloaded files dikhao")
    assert agent._request_looks_actionable("Spotify par jao aur Pal Pal song chalao")
    assert agent._request_looks_actionable("Spotify पर जाओ और पल पल सॉन्ग चलाओ।")
    assert agent._request_looks_actionable("MrBeast ki latest video chalao")
    assert agent._request_looks_actionable("MrBeast ne jo like latest video upload ki hai na usko chalao")
    assert agent._request_looks_actionable("YouTube par jao aur MrBeast ki latest video chalao")
    assert agent._request_looks_actionable("Inspect the desktop")
    assert agent._request_looks_actionable("Screen pe kya hai")
    assert agent._request_looks_actionable("Meri screen dikhao")
    assert agent._request_looks_actionable("स्क्रीन दिखाओ")
    assert agent._request_looks_actionable("डेस्कटॉप पर क्या दिख रहा है")
    assert agent._request_looks_actionable("Click Search in YouTube")
    assert agent._request_looks_actionable("Type Interstellar into Search")
    assert agent._request_looks_actionable("Press CTRL+L in Opera")
    assert agent._request_looks_actionable("YouTube mein pal-pal song chalana mere liye")
    assert agent._request_looks_actionable("YouTube में पल-पल सॉन्ग चलाना मेरे लिए।")
    assert agent._request_looks_actionable("मेरे स्क्रीन पर अभी क्या ओपन है?")
    assert agent._request_looks_actionable("Search button pe click kar do")
    assert agent._request_looks_actionable("YouTube mein Search button pe click kar do")
    assert agent._request_looks_actionable("Search bar mein Interstellar likh do")
    assert agent._request_looks_actionable("CTRL+L dabao")
    assert agent._request_looks_actionable("YouTube खोलो और इंटरस्टेलर साउंडट्रैक चलाओ।")
    assert agent._request_looks_actionable("YouTube kholo aur Interstellar soundtrack chalao.")
    assert agent._request_looks_actionable("YouTube par MrBeast ki koi latest video chalao.")
    assert agent._request_looks_actionable("Ab dekho kya task mein nazar aa raha hai?")
    assert not agent._request_looks_actionable("Don't open Wikipedia")
    assert not agent._request_looks_actionable("Don't click Send in Gmail")
    assert not agent._request_looks_actionable("How do I open Wikipedia?")
    assert not agent._request_looks_actionable("How do I click Search in YouTube?")
    assert agent.queue_direct_action("Open Wikipedia") is True
    assert agent._direct_action_in_progress is True

    # A second tool call in the same realtime turn cannot execute the action twice.
    assert agent.queue_direct_action("Open Wikipedia") is False


def test_direct_voice_action_runs_shared_executor_and_speaks_verified_result(monkeypatch):
    calls = []
    events = []
    spoken = []

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            calls.append(kwargs)
            return {
                "response": "Opened https://www.wikipedia.org in your default browser.",
                "conversation_id": 42,
                "understanding": {"intent": "desktop", "requires_tool": True},
                "confirmation": None,
                "tool_result": {
                    "success": True,
                    "tool": "desktop",
                    "action": "open_url",
                    "error": None,
                },
            }

    class FakeSpeechHandle:
        async def wait_for_playout(self):
            return None

    class FakeSession:
        async def interrupt(self, *, force=False):
            return None

        def generate_reply(self, *, user_input, input_modality):
            marker = "Repeat exactly this action result aloud and add nothing else: "
            spoken.append(user_input.split(marker, 1)[1])
            assert input_modality == "text"
            return FakeSpeechHandle()

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=42,
        language="multi",
        voice_event_publisher=events.append,
    )
    fake_session = FakeSession()
    monkeypatch.setattr(
        agent,
        "_get_activity_or_raise",
        lambda: SimpleNamespace(session=fake_session),
    )

    request = "Open Wikipedia"
    assert agent.queue_direct_action(request) is True
    asyncio.run(agent.execute_direct_action(request))

    assert calls == [{
        "user_id": "user-123",
        "message": "Open Wikipedia",
        "conversation_id": 42,
    }]
    assert spoken == ["Opened https://www.wikipedia.org in your default browser."]
    assert len(events) == 1
    assert events[0]["type"] == "nova.transcript"
    assert events[0]["speaker"] == "assistant"
    assert events[0]["text"] == spoken[0]
    assert agent._direct_action_in_progress is False


def test_direct_voice_email_draft_speaks_recipient_clarification(monkeypatch):
    spoken = []

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            assert kwargs["message"] == "simple email test draft now"
            return {
                "response": (
                    "I can prepare a simple test email with the subject "
                    "'Test Email - Quick Check'. Who should receive it? "
                    "I’ll show you the full preview and ask for your approval "
                    "before anything is sent."
                ),
                "conversation_id": 42,
                "understanding": {
                    "intent": "email",
                    "requires_tool": False,
                    "email_draft_status": "collecting",
                    "email_draft_missing": "recipient",
                },
                "confirmation": {"status": None, "tool": None, "action": None},
                "tool_result": {
                    "success": False,
                    "tool": None,
                    "action": None,
                    "error": None,
                },
            }

    class FakeSpeechHandle:
        async def wait_for_playout(self):
            return None

    class FakeSession:
        async def interrupt(self, *, force=False):
            return None

        def generate_reply(self, *, user_input, input_modality):
            marker = "Repeat exactly this action result aloud and add nothing else: "
            spoken.append(user_input.split(marker, 1)[1])
            assert input_modality == "text"
            return FakeSpeechHandle()

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(user_id="user-123", conversation_id=42, language="multi")
    monkeypatch.setattr(
        agent,
        "_get_activity_or_raise",
        lambda: SimpleNamespace(session=FakeSession()),
    )

    request = "simple email test draft now"
    assert agent.queue_direct_action(request) is True
    asyncio.run(agent.execute_direct_action(request))

    assert len(spoken) == 1
    assert "who should receive it" in spoken[0].lower()
    assert "approval" in spoken[0].lower()
    assert "couldn't complete" not in spoken[0].lower()
    assert agent._direct_action_in_progress is False


def test_direct_voice_action_does_not_hold_action_lock_until_speech_finishes(monkeypatch):
    playback_started = asyncio.Event()
    playback_release = asyncio.Event()

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            return {
                "response": "Opened Notepad.",
                "conversation_id": 42,
                "understanding": {"intent": "desktop", "requires_tool": True},
                "confirmation": None,
                "tool_result": {
                    "success": True,
                    "tool": "desktop",
                    "action": "start",
                    "error": None,
                },
            }

    class FakeSpeechHandle:
        async def wait_for_playout(self):
            playback_started.set()
            await playback_release.wait()

    class FakeSession:
        async def interrupt(self, *, force=False):
            return None

        def generate_reply(self, *, user_input, input_modality):
            assert "Opened Notepad." in user_input
            assert input_modality == "text"
            return FakeSpeechHandle()

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(user_id="user-123", conversation_id=42, language="multi")
    fake_session = FakeSession()
    monkeypatch.setattr(
        agent,
        "_get_activity_or_raise",
        lambda: SimpleNamespace(session=fake_session),
    )
    assert agent.queue_direct_action("Open Notepad") is True

    async def exercise():
        await agent.execute_direct_action("Open Notepad")
        assert agent._direct_action_in_progress is False
        await asyncio.wait_for(playback_started.wait(), timeout=0.5)
        playback_release.set()
        await asyncio.sleep(0)

    asyncio.run(exercise())


def test_direct_voice_action_does_not_speak_success_when_executor_failed(monkeypatch):
    spoken = []

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            return {
                "response": "Opened Wikipedia successfully.",
                "conversation_id": 42,
                "understanding": {"intent": "chat", "requires_tool": False},
                "confirmation": None,
                "tool_result": {"success": False, "tool": None, "action": None},
            }

    class FakeSpeechHandle:
        async def wait_for_playout(self):
            return None

    class FakeSession:
        async def interrupt(self, *, force=False):
            return None

        def generate_reply(self, *, user_input, input_modality):
            marker = "Repeat exactly this action result aloud and add nothing else: "
            spoken.append(user_input.split(marker, 1)[1])
            assert input_modality == "text"
            return FakeSpeechHandle()

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=42,
        language="multi",
    )
    monkeypatch.setattr(
        agent,
        "_get_activity_or_raise",
        lambda: SimpleNamespace(session=FakeSession()),
    )

    request = "Open Wikipedia"
    assert agent.queue_direct_action(request) is True
    asyncio.run(agent.execute_direct_action(request))

    assert len(spoken) == 1
    assert "couldn't complete" in spoken[0].lower()
    assert "opened" not in spoken[0].lower()
    assert agent._direct_action_in_progress is False


def test_direct_voice_action_speaks_verified_desktop_failure_reason(monkeypatch):
    spoken = []

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            return {
                "response": "I couldn't complete that desktop action: No unique visible, enabled UI control named 'Recycle Bin' was found.",
                "conversation_id": 42,
                "understanding": {"intent": "desktop", "requires_tool": True},
                "confirmation": None,
                "tool_result": {
                    "success": False,
                    "tool": "desktop",
                    "action": "start",
                    "error": "No unique visible, enabled UI control named 'Recycle Bin' was found.",
                },
            }

    class FakeSpeechHandle:
        async def wait_for_playout(self):
            return None

    class FakeSession:
        async def interrupt(self, *, force=False):
            return None

        def generate_reply(self, *, user_input, input_modality):
            marker = "Repeat exactly this action result aloud and add nothing else: "
            spoken.append(user_input.split(marker, 1)[1])
            assert input_modality == "text"
            return FakeSpeechHandle()

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(user_id="user-123", conversation_id=42, language="multi")
    monkeypatch.setattr(
        agent,
        "_get_activity_or_raise",
        lambda: SimpleNamespace(session=FakeSession()),
    )

    request = "Recycle Bin open karo"
    assert agent.queue_direct_action(request) is True
    asyncio.run(agent.execute_direct_action(request))

    assert len(spoken) == 1
    assert "No unique visible, enabled UI control named 'Recycle Bin' was found" in spoken[0]
    assert "couldn't complete that action successfully. NOVA did not confirm" not in spoken[0]
    assert agent._direct_action_in_progress is False


def test_voice_tool_bridge_fails_closed_when_action_request_is_misclassified_as_chat(monkeypatch):
    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            return {
                "response": "Task created successfully.",
                "conversation_id": 42,
                "understanding": {"intent": "chat", "requires_tool": False},
                "confirmation": None,
                "tool_result": {"success": False, "tool": None, "action": None},
            }

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=42,
        language="multi",
    )
    request = (
        "\u0939\u093e\u0902, \u0907\u0938\u0915\u094b "
        "\u0915\u094d\u0930\u093f\u090f\u091f \u0915\u0930 \u0926\u094b\u0964 "
        "\u091f\u093e\u0907\u091f\u0932 \u0939\u0948 Nova Live Title Check 2338"
    )

    result = asyncio.run(
        agent.nova_execute_request(context=object(), request=request)
    )
    payload = json.loads(result)

    assert payload["ok"] is False
    assert payload["action_succeeded"] is False
    assert payload["confirmation_pending"] is False
    assert "not routed to NOVA's action executor" in payload["message"]
    # Even a misleading natural-language response in the executor result
    # cannot be exposed as a successful action result.
    assert payload["result"]["tool_result"]["success"] is False


def test_gemini_realtime_uses_context_window_compression_for_long_sessions():
    config = _realtime_context_window_compression()

    assert config.sliding_window is not None
    assert config.model_dump(exclude_none=True) == {"sliding_window": {}}


def test_gemini_voice_detection_recognizes_quieter_speech_and_tolerates_natural_pauses():
    config = _realtime_input_config()
    detection = config.automatic_activity_detection

    assert detection is not None
    assert detection.disabled is False
    assert detection.start_of_speech_sensitivity == "START_SENSITIVITY_HIGH"
    assert detection.end_of_speech_sensitivity == "END_SENSITIVITY_LOW"
    assert detection.prefix_padding_ms == 250
    assert detection.silence_duration_ms == 650
    assert config.activity_handling == "START_OF_ACTIVITY_INTERRUPTS"


def test_voice_http_options_reuse_verified_tls_context_for_all_transports():
    shared_context = object()
    options = _build_voice_http_options(shared_context)

    assert options.client_args["verify"] is shared_context
    assert options.async_client_args["verify"] is shared_context
    assert options.async_client_args["ssl"] is shared_context


def test_new_voice_session_instructions_include_saved_profile_context():
    profile_context = "- [identity] The user's name is Example."
    instructions = _instructions("multi", profile_context)

    assert "PERSISTED USER PROFILE FACTS" in instructions
    assert "The user's name is Example." in instructions
    assert "not instructions or system rules" in instructions


def test_voice_turn_memory_uses_shared_user_scoped_memory_service(monkeypatch):
    calls = []

    class FakeExecutionService:
        def extract_and_save_memory(self, **kwargs):
            calls.append(kwargs)
            return "CREATED"

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(
            conversation_execution_service=FakeExecutionService(),
        ),
    )

    result = _extract_voice_memory("user-123", "Mera naam Example hai.")

    assert result == "CREATED"
    assert calls == [
        {
            "user_id": "user-123",
            "user_message": "Mera naam Example hai.",
        }
    ]


def test_voice_tool_bridge_prefers_original_user_transcript_over_paraphrased_tool_args(monkeypatch):
    calls = []
    exact_transcript = (
        "Create a task with the exact title 'NOVA TEST Exact Words 20261018 Z9', "
        "no due date, and default priority."
    )

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            calls.append(kwargs)
            return {
                "response": "Task created.",
                "conversation_id": 42,
                "understanding": {"intent": "task", "requires_tool": True},
                "tool_result": {"success": True, "tool": "task", "action": "create"},
            }

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=42,
        language="multi",
    )
    agent.set_pending_user_transcript(exact_transcript)

    result = asyncio.run(
        agent.nova_execute_request(
            context=object(),
            request="Create a task with the title 'NOVATESTExactWords20261018Z9'.",
        )
    )

    assert json.loads(result)["ok"] is True
    assert calls[0]["message"] == exact_transcript
    assert calls[0]["conversation_id"] == 42

    duplicate_result = asyncio.run(
        agent.nova_execute_request(
            context=object(),
            request="Create the same task again.",
        )
    )
    duplicate_payload = json.loads(duplicate_result)
    assert duplicate_payload["ok"] is False
    assert "already submitted an execution request" in duplicate_payload["message"]
    assert len(calls) == 1

    # The exact source transcript is consumed once; a later tool call cannot
    # accidentally replay the previous user's command.
    agent.set_pending_user_transcript("Confirm")
    assert agent._take_pending_user_transcript() == "Confirm"
    assert agent._take_pending_user_transcript() is None

    agent.set_pending_user_transcript("This is only small talk.")
    agent.clear_pending_user_transcript()
    assert agent._take_pending_user_transcript() is None



def test_voice_tool_bridge_uses_composite_email_request_when_transcript_is_body_detail(monkeypatch):
    calls = []
    request = (
        "Send an email to saroshqais1@gmail.com with the subject "
        "'NOVA Voice Email Text Fix Verification' and the body "
        "'Testing voice initiated email delivery after the Nova fix'."
    )
    preview = {
        "kind": "email",
        "to": "saroshqais1@gmail.com",
        "cc": None,
        "bcc": None,
        "subject": "NOVA Voice Email Text Fix Verification",
        "body": "Testing voice initiated email delivery after the Nova fix",
    }

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            calls.append(kwargs)
            return {
                "response": "Please confirm this email before I send it.",
                "conversation_id": 42,
                "understanding": {"intent": "email", "requires_tool": True},
                "confirmation": {
                    "id": 78,
                    "status": "pending",
                    "tool": "email",
                    "action": "send",
                    "reason": "External email requires explicit confirmation.",
                    "preview": preview,
                },
                "tool_result": {"success": False, "tool": None, "action": None},
            }

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(user_id="user-123", conversation_id=42, language="multi")
    agent.set_pending_user_transcript("testikois initiated email delivery after the Nova fix")

    result = asyncio.run(
        agent.nova_execute_request(context=object(), request=request)
    )
    payload = json.loads(result)

    assert calls[0]["message"] == request
    assert payload["confirmation_pending"] is True
    assert payload["action_succeeded"] is False


def test_voice_tool_bridge_converts_grounded_composed_email_draft_to_approval_preview(monkeypatch):
    calls = []
    events = []
    request = (
        "Draft an email to sarooshqais1@gmail.com with the subject "
        "'Project Update' and the body "
        "'Hey, main tumhara project update kar diya hai. Thanks.'"
    )
    preview = {
        "kind": "email",
        "to": "saroshqais1@gmail.com",
        "cc": None,
        "bcc": None,
        "subject": "Project Update",
        "body": "Hey, main tumhara project update kar diya hai. Thanks.",
    }

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            calls.append(kwargs)
            return {
                "response": "Please review this email before I send it.",
                "conversation_id": 42,
                "understanding": {"intent": "email", "requires_tool": True},
                "confirmation": {
                    "id": 79,
                    "status": "pending",
                    "tool": "email",
                    "action": "send",
                    "reason": "External email requires explicit confirmation.",
                    "preview": preview,
                },
                "tool_result": {"success": False, "tool": None, "action": None},
            }

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=42,
        language="multi",
        voice_event_publisher=events.append,
    )
    agent.set_pending_user_transcript(
        "Email saroshqais1@gmail.com. Subject Project Update. "
        "Body: Hey, main tumhara project update kar diya hai. Thanks."
    )

    result = asyncio.run(
        agent.nova_execute_request(context=object(), request=request)
    )
    payload = json.loads(result)

    assert calls[0]["message"].startswith(
        "Send an email to saroshqais1@gmail.com"
    )
    assert payload["confirmation_pending"] is True
    assert payload["action_succeeded"] is False
    assert events[0]["type"] == "nova.action_preview"
    assert events[0]["preview"]["to"] == "saroshqais1@gmail.com"


def test_voice_tool_bridge_rejects_stale_email_request_when_latest_transcript_is_unrelated(monkeypatch):
    calls = []
    request = (
        "Send an email to saroshqais1@gmail.com with the subject "
        "'NOVA Voice Email Text Fix Verification' and the body "
        "'Testing voice initiated email delivery after the Nova fix'."
    )

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            calls.append(kwargs)
            raise AssertionError("Unrelated voice input must not reach the executor")

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(user_id="user-123", conversation_id=42, language="multi")
    agent.set_pending_user_transcript("aurat se video na yaar")

    result = asyncio.run(
        agent.nova_execute_request(context=object(), request=request)
    )
    payload = json.loads(result)

    assert calls == []
    assert payload["ok"] is False
    assert payload["action_succeeded"] is False
    assert payload["confirmation_pending"] is False
    assert "no action was executed" in payload["message"].lower()
    assert agent._voice_tool_used is True


def test_voice_agent_publishes_pending_email_preview_to_voice_ui(monkeypatch):
    events = []
    preview = {
        "kind": "email",
        "to": "recipient@example.com",
        "cc": None,
        "bcc": None,
        "subject": "Project update",
        "body": "The project is on track.",
    }

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            return {
                "response": "Please review this email before I send it.",
                "conversation_id": 42,
                "understanding": {"intent": "email", "requires_tool": True},
                "confirmation": {
                    "id": 77,
                    "status": "pending",
                    "tool": "email",
                    "action": "send",
                    "reason": "External email requires explicit confirmation.",
                    "preview": preview,
                },
                "tool_result": {"success": False, "tool": None, "action": None},
            }

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=42,
        language="multi",
        voice_event_publisher=events.append,
    )

    result = asyncio.run(
        agent.nova_execute_request(
            context=object(),
            request="Send an email to recipient@example.com.",
        )
    )

    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["action_succeeded"] is False
    assert payload["confirmation_pending"] is True
    assert events == [{
        "type": "nova.action_preview",
        "confirmation_id": 77,
        "status": "pending",
        "tool": "email",
        "action": "send",
        "reason": "External email requires explicit confirmation.",
        "preview": preview,
    }]


def test_calendar_event_create_is_always_claimed_as_an_action():
    request = (
        "Create a calendar event Friday at 4:00 p.m. called "
        "Nova calendar confirmation retest 1021."
    )
    assert NovaLiveKitAgent._request_looks_actionable(request)
    assert NovaLiveKitAgent._request_looks_actionable(
        "Confirm: Create a calendar event Friday at 4 PM called NOVA test."
    )
    assert not NovaLiveKitAgent._request_looks_actionable(
        "How do I create a calendar event?"
    )

def test_voice_email_body_grounding_accepts_devanagari_transcription():
    request = (
        "Send an email to saroshqais1@gmail.com with the subject "
        "'Nova Voice Email' and the message "
        "'mera test successful complete ho gaya hai'."
    )
    transcript = "\u092e\u0947\u0930\u093e \u091f\u0947\u0938\u094d\u091f \u0938\u0915\u094d\u0938\u0947\u0938\u092b\u0941\u0932 \u0915\u0902\u092a\u094d\u0932\u0940\u091f \u0939\u094b \u0917\u092f\u093e \u0939\u0948\u0964"

    assert NovaLiveKitAgent._transcript_matches_email_body(transcript, request) is True


def test_transcribed_email_recipient_normalizes_spaced_letters():
    transcript = (
        "email s a r o s h q a i s 1@gmail.com with the subject "
        "Nova voice email retest 2 and the message This is a fresh voice test."
    )

    normalized, recipient = NovaLiveKitAgent._normalize_transcribed_email_recipient(
        transcript
    )

    assert recipient == "saroshqais1@gmail.com"
    assert (
        "email saroshqais1@gmail.com with the subject" in normalized
    )


def test_voice_email_body_grounding_allows_additional_approval_instruction():
    request = (
        "Send an email to sarooshqais1@gmail.com with the subject "
        "Nova voice email retest 2 and the message "
        "This is a fresh voice test after the fix."
    )
    transcript = (
        "email s a r o s h q a i s 1@gmail.com with the subject "
        "Nova voice email retest 2 and the message "
        "This is a fresh voice test after the fix. "
        "Please repeat the recipient address before asking for my approval."
    )

    assert NovaLiveKitAgent._transcript_matches_email_body(transcript, request) is True


def test_voice_tool_bridge_uses_spoken_recipient_and_keeps_email_pending(monkeypatch):
    calls = []
    preview = {
        "kind": "email",
        "to": "saroshqais1@gmail.com",
        "cc": None,
        "bcc": None,
        "subject": "NOVA Voice Email Retest 2",
        "body": "This is a fresh voice test after the fix.",
    }
    request = (
        "Send an email to sarooshqais1@gmail.com with the subject "
        "Nova voice email retest 2 and the message "
        "This is a fresh voice test after the fix."
    )
    transcript = (
        "email s a r o s h q a i s 1@gmail.com with the subject "
        "Nova voice email retest 2 and the message "
        "This is a fresh voice test after the fix. "
        "Please repeat the recipient address before asking for my approval."
    )

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            calls.append(kwargs)
            return {
                "response": "Please review this email before I send it.",
                "conversation_id": 42,
                "understanding": {"intent": "email", "requires_tool": True},
                "confirmation": {
                    "id": 77,
                    "status": "pending",
                    "tool": "email",
                    "action": "send",
                    "reason": "External email requires explicit confirmation.",
                    "preview": preview,
                },
                "tool_result": {
                    "success": False,
                    "tool": None,
                    "action": None,
                },
            }

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(user_id="user-123", conversation_id=42, language="multi")
    agent.set_pending_user_transcript(transcript)

    result = asyncio.run(
        agent.nova_execute_request(context=object(), request=request)
    )
    payload = json.loads(result)

    assert len(calls) == 1
    assert "to saroshqais1@gmail.com" in calls[0]["message"]
    assert "to sarooshqais1@gmail.com" not in calls[0]["message"]
    assert payload["confirmation_pending"] is True
    assert payload["action_succeeded"] is False

def test_voice_tool_bridge_accepts_recipient_only_turn_for_email_composition(monkeypatch):
    calls = []
    events = []
    request = (
        "Draft an email to sroshqais1@gmail.com with the subject "
        "'NOVA Voice Test' and the body 'Yeh NOVA ka voice test email hai'. "
        "Show the preview first and do not send without approval."
    )
    preview = {
        "kind": "email",
        "to": "saroshqais1@gmail.com",
        "cc": None,
        "bcc": None,
        "subject": "NOVA Voice Test",
        "body": "Yeh NOVA ka voice test email hai",
    }

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            calls.append(kwargs)
            return {
                "response": "Please review this email before I send it.",
                "conversation_id": 42,
                "understanding": {"intent": "email", "requires_tool": True},
                "confirmation": {
                    "id": 81,
                    "status": "pending",
                    "tool": "email",
                    "action": "send",
                    "reason": "External email requires explicit confirmation.",
                    "preview": preview,
                },
                "tool_result": {
                    "success": False,
                    "tool": None,
                    "action": None,
                },
            }

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(conversation_execution_service=FakeExecutionService()),
    )
    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=42,
        language="multi",
        voice_event_publisher=events.append,
    )
    # Reproduce the live case: NOVA asked for the recipient, so the user's
    # latest finalized turn contains only the spoken address. The realtime
    # model's composed recipient is missing an "a" and must not win.
    agent.set_pending_user_transcript("email s a r o s h q a i s 1@gmail.com")

    result = asyncio.run(
        agent.nova_execute_request(context=object(), request=request)
    )
    payload = json.loads(result)

    assert len(calls) == 1
    assert calls[0]["message"].startswith(
        "Send an email to saroshqais1@gmail.com"
    )
    assert "to sroshqais1@gmail.com" not in calls[0]["message"]
    assert payload["confirmation_pending"] is True
    assert payload["action_succeeded"] is False
    assert events[0]["type"] == "nova.action_preview"
    assert events[0]["preview"]["to"] == "saroshqais1@gmail.com"



def test_subject_body_email_followup_reaches_contextual_email_composition():
    transcript = "Subject update test aur body mein likhna hai test successful."
    composed_request = (
        "Create a draft email to saroshqais1@gmail.com with the subject "
        "'Update Test' and body 'Test Successful'"
    )
    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=470,
        language="multi",
    )

    # "update" is a global direct-action keyword, but here it is part of the
    # email subject. Let Gemini use the ongoing context to compose the request;
    # the existing bridge will ground the model's body against this transcript.
    assert NovaLiveKitAgent._request_looks_actionable(transcript) is True
    assert NovaLiveKitAgent._looks_like_email_field_followup(transcript) is True
    assert NovaLiveKitAgent._transcript_matches_email_body(
        transcript, composed_request
    ) is True
    assert agent.queue_direct_action(transcript) is False
    assert agent._direct_action_in_progress is False
    assert agent._voice_tool_used is False


def test_complete_explicit_email_command_is_not_treated_as_a_field_followup():
    transcript = (
        "Create an email to saroshqais1@gmail.com with subject Update Test "
        "and body Test Successful"
    )
    assert NovaLiveKitAgent._looks_like_email_field_followup(transcript) is False


def test_voice_tool_bridge_never_reports_email_sent_when_executor_returns_email_list(monkeypatch):
    request = (
        "Send an email to saroshqais1@gmail.com with the subject "
        "'Update test' and body 'Test successful'."
    )

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            return {
                "response": "Email sent successfully.",
                "conversation_id": 42,
                "understanding": {"intent": "email", "requires_tool": True},
                "confirmation": {
                    "id": 94,
                    "status": "consumed",
                    "tool": "email",
                    "action": "list",
                    "reason": "Incorrectly classified action.",
                },
                "tool_result": {
                    "success": True,
                    "tool": "email",
                    "action": "list",
                    "result": {"count": 0, "messages": []},
                    "error": None,
                },
            }

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(
            conversation_execution_service=FakeExecutionService(),
        ),
    )
    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=42,
        language="multi",
    )
    agent.set_pending_user_transcript(request)

    result = asyncio.run(
        agent.nova_execute_request(context=object(), request=request)
    )
    payload = json.loads(result)

    assert payload["ok"] is False
    assert payload["action_succeeded"] is False
    assert "no email was sent" in payload["message"].lower()


def test_voice_tool_bridge_keeps_incomplete_email_send_on_draft_collection_path(monkeypatch):
    request = "Email mujhe send karni hai."

    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            assert kwargs["message"] == request
            return {
                "response": "Who should receive the email?",
                "conversation_id": 43,
                "understanding": {
                    "intent": "email",
                    "requires_tool": False,
                    "email_draft_status": "collecting",
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
            }

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(
            conversation_execution_service=FakeExecutionService(),
        ),
    )
    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=43,
        language="multi",
    )
    agent.set_pending_user_transcript(request)

    result = asyncio.run(
        agent.nova_execute_request(context=object(), request=request)
    )
    payload = json.loads(result)

    assert payload["ok"] is True
    assert payload["action_succeeded"] is None
    assert "who should receive" in payload["result"]["response"].lower()


def test_voice_tool_bridge_does_not_mistake_legacy_email_list_approval_for_send(monkeypatch):
    class FakeExecutionService:
        def execute_voice_message(self, **kwargs):
            return {
                "response": "Your email has been sent.",
                "conversation_id": 44,
                "understanding": {"intent": "email", "requires_tool": True},
                "confirmation": {
                    "id": 95,
                    "status": "consumed",
                    "tool": "email",
                    "action": "list",
                    "reason": "Legacy confirmation created by the old routing bug.",
                },
                "tool_result": {
                    "success": True,
                    "tool": "email",
                    "action": "list",
                    "result": {"count": 0, "messages": []},
                    "error": None,
                },
            }

    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(
            conversation_execution_service=FakeExecutionService(),
        ),
    )
    agent = NovaLiveKitAgent(
        user_id="user-123",
        conversation_id=44,
        language="multi",
    )
    agent.set_pending_user_transcript("Confirm")

    result = asyncio.run(
        agent.nova_execute_request(context=object(), request="Confirm")
    )
    payload = json.loads(result)

    assert payload["ok"] is False
    assert payload["action_succeeded"] is False
    assert "no email was sent" in payload["message"].lower()
