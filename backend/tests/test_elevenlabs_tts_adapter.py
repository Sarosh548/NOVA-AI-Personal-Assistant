    monkeypatch.setattr(
        provider_module,
        "connect",
        fake_connect,
    )

    stream = await ElevenLabsTTSAdapter(
        make_settings()
    ).start_stream(
        make_request()
    )

    await stream.send_text(
        "Hello NOVA"
    )

    assert len(websocket.sent) == 1

    await stream.finish()

    assert json.loads(
        websocket.sent[-2]
    ) == {
        "text": "Hello NOVA ",
        "flush": True,
    }
    assert json.loads(
        websocket.sent[-1]
    ) == {
        "text": "",
    }

    events = [
        event
        async for event in stream.events()
    ]

    assert [event.type for event in events] == [
        "audio",
        "final",
    ]
    assert events[0].audio == b"Hello"
    assert events[0].sequence == 1
    assert events[1].audio == b""
    assert events[1].sequence == 2

    await stream.close()


@pytest.mark.asyncio
async def test_stream_maps_provider_error_to_adapter_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = FakeWebSocket(
        [
            json.dumps(
                {