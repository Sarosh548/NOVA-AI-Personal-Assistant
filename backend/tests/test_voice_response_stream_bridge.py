from __future__ import annotations

import asyncio

import pytest

from services.voice_response_stream_bridge import (
    VoiceResponseStreamBridge,
    VoiceResponseStreamBridgeError,
)


@pytest.mark.asyncio
async def test_bridge_delivers_worker_thread_deltas_in_order() -> None:
    bridge = VoiceResponseStreamBridge(
        loop=asyncio.get_running_loop(),
        max_queue_items=4,
        enqueue_timeout_seconds=1.0,
    )

    received: list[str] = []

    async def consume() -> None:
        async for delta in bridge.text_deltas():
            received.append(delta)

    consumer = asyncio.create_task(
        consume()
    )

    await asyncio.to_thread(
        bridge.on_delta,
        "Hello ",
    )
    await asyncio.to_thread(
        bridge.on_delta,
        "world.",
    )

    await bridge.finish()
    await consumer

    assert received == [
        "Hello ",
        "world.",
    ]


@pytest.mark.asyncio
async def test_bridge_ignores_whitespace_only_deltas() -> None:
    bridge = VoiceResponseStreamBridge(
        loop=asyncio.get_running_loop(),
        max_queue_items=4,
        enqueue_timeout_seconds=1.0,
    )

    received: list[str] = []

    async def consume() -> None:
        async for delta in bridge.text_deltas():
            received.append(delta)

    consumer = asyncio.create_task(
        consume()
    )

    await asyncio.to_thread(
        bridge.on_delta,
        "   ",
    )
    await asyncio.to_thread(
        bridge.on_delta,
        "Hello",
    )

    await bridge.finish()
    await consumer

    assert received == [
        "Hello"
    ]


@pytest.mark.asyncio
async def test_bridge_applies_bounded_backpressure_without_dropping_normal_queue_items() -> None:
    bridge = VoiceResponseStreamBridge(
        loop=asyncio.get_running_loop(),
        max_queue_items=1,
        enqueue_timeout_seconds=0.05,
    )

    await asyncio.to_thread(
        bridge.on_delta,
        "first",
    )

    with pytest.raises(
        VoiceResponseStreamBridgeError,
        match="backpressure deadline",
    ):
        await asyncio.to_thread(
            bridge.on_delta,
            "second",
        )

    received: list[str] = []

    async def consume() -> None:
        with pytest.raises(
            VoiceResponseStreamBridgeError,
            match="backpressure deadline",
        ):
            async for delta in bridge.text_deltas():
                received.append(delta)

    await consume()

    assert received == []


@pytest.mark.asyncio
async def test_bridge_finish_preserves_buffered_deltas() -> None:
    bridge = VoiceResponseStreamBridge(
        loop=asyncio.get_running_loop(),
        max_queue_items=4,
        enqueue_timeout_seconds=1.0,
    )

    await asyncio.to_thread(
        bridge.on_delta,
        "one",
    )
    await asyncio.to_thread(
        bridge.on_delta,
        "two",
    )

    await bridge.finish()

    received = [
        delta
        async for delta in bridge.text_deltas()
    ]

    assert received == [
        "one",
        "two",
    ]


@pytest.mark.asyncio
async def test_bridge_abort_terminates_consumer() -> None:
    bridge = VoiceResponseStreamBridge(
        loop=asyncio.get_running_loop(),
        max_queue_items=4,
        enqueue_timeout_seconds=1.0,
    )

    async def consume() -> list[str]:
        values: list[str] = []

        with pytest.raises(
            VoiceResponseStreamBridgeError,
            match="tts failed",
        ):
            async for delta in bridge.text_deltas():
                values.append(delta)

        return values

    consumer = asyncio.create_task(
        consume()
    )

    await bridge.abort(
        "tts failed"
    )

    assert await consumer == []


@pytest.mark.asyncio
async def test_bridge_rejects_delta_after_abort() -> None:
    bridge = VoiceResponseStreamBridge(
        loop=asyncio.get_running_loop(),
        max_queue_items=4,
        enqueue_timeout_seconds=1.0,
    )

    await bridge.abort(
        "bridge stopped"
    )

    with pytest.raises(
        VoiceResponseStreamBridgeError,
        match="bridge stopped",
    ):
        await asyncio.to_thread(
            bridge.on_delta,
            "late",
        )
