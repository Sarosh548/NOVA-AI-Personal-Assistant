
        core_service = websocket.app.state.conversation_execution_service
        assert len(core_service.calls) == 1


def test_voice_websocket_auto_commits_on_end_of_speech(
    monkeypatch,
):
    _patch_auth(monkeypatch)
    _patch_fake_stt(monkeypatch)
    _patch_fake_tts(monkeypatch)

    client = TestClient(
        _build_app()
    )

    with client.websocket_connect(
        "/voice/ws",
        headers={
            "Authorization": "Bearer test-token",
        },
    ) as websocket:
        websocket.receive_json()

        websocket.send_json(
            {
                "type": "turn.start",
                "turn_id": "turn-auto-1",
            }
        )

        started = websocket.receive_json()

        assert started["type"] == "turn.started"
        assert started["turn_id"] == "turn-auto-1"

        FakeVoiceSTTOrchestrator.instances[0].emit_end_of_speech = True

        websocket.send_bytes(
            b"input-audio"
        )

        seen_types = []
        assistant = None

        while assistant is None:
            message = websocket.receive()

            if message.get("bytes") is not None:
                continue

            payload = json.loads(
                message["text"]
            )
            seen_types.append(payload["type"])

            if payload["type"] == "assistant.response":