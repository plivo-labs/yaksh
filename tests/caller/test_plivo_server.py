import asyncio
import signal
import uuid
from collections.abc import AsyncIterator

import pytest
import websockets
from httpx import ASGITransport, AsyncClient

from truman.caller.plivo_server import (
    HANGUP_XML,
    NO_CALL,
    PlivoServer,
    StreamRegistry,
    create_app,
)

PUBLIC_URL = "https://truman.example.com"


@pytest.fixture
async def served() -> AsyncIterator[tuple[StreamRegistry, PlivoServer]]:
    registry = StreamRegistry()
    server = PlivoServer(create_app(registry, PUBLIC_URL), port=0)
    await server.start()
    yield registry, server
    await server.stop(2.0)


async def test_the_answer_xml_streams_a_waiting_conversation_and_hangs_up_others() -> None:
    registry = StreamRegistry()
    conversation_id = uuid.uuid4()
    entry = registry.expect(conversation_id)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(registry, PUBLIC_URL)), base_url="http://worker"
    ) as client:
        answer = await client.post(
            f"/answer/{conversation_id}", data={"CallUUID": "abc", "CallStatus": "in-progress"}
        )
        unknown = await client.get(f"/answer/{uuid.uuid4()}")
        garbled = await client.get("/answer/not-a-conversation")

    assert answer.status_code == 200 and answer.headers["content-type"].startswith(
        "application/xml"
    )
    assert f"wss://truman.example.com/stream/{conversation_id}" in answer.text
    assert 'bidirectional="true"' in answer.text and 'keepCallAlive="false"' in answer.text
    assert 'contentType="audio/x-mulaw;rate=8000"' in answer.text
    assert unknown.status_code == 200 and unknown.text == HANGUP_XML
    assert garbled.status_code == 200 and garbled.text == HANGUP_XML
    assert entry.callbacks.get_nowait() == {"CallUUID": "abc", "CallStatus": "in-progress"}


async def test_callbacks_reach_the_waiting_conversation_and_are_always_acknowledged() -> None:
    registry = StreamRegistry()
    conversation_id = uuid.uuid4()
    entry = registry.expect(conversation_id)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(registry, PUBLIC_URL)), base_url="http://worker"
    ) as client:
        known = await client.post(
            f"/callbacks/{conversation_id}", data={"CallStatus": "ringing", "CallUUID": "abc"}
        )
        unknown = await client.post(f"/callbacks/{uuid.uuid4()}", data={"CallStatus": "completed"})

    assert known.status_code == 200 and unknown.status_code == 200
    assert entry.callbacks.get_nowait() == {"CallStatus": "ringing", "CallUUID": "abc"}


async def test_the_stream_socket_is_handed_to_the_waiting_entry_and_held_until_forgotten(
    served: tuple[StreamRegistry, PlivoServer],
) -> None:
    registry, server = served
    conversation_id = uuid.uuid4()
    entry = registry.expect(conversation_id)

    async with websockets.connect(
        f"ws://127.0.0.1:{server.port}/stream/{conversation_id}"
    ) as plivo:
        socket = await asyncio.wait_for(entry.socket, 2)
        await plivo.send('{"event": "start"}')
        assert await socket.receive_text() == '{"event": "start"}'
        await socket.send_text('{"event": "playAudio"}')
        assert await plivo.recv() == '{"event": "playAudio"}'

        registry.forget(conversation_id)
        with pytest.raises(websockets.ConnectionClosed):
            await asyncio.wait_for(plivo.recv(), 2)


async def test_sockets_for_unknown_or_already_streaming_conversations_are_refused(
    served: tuple[StreamRegistry, PlivoServer],
) -> None:
    registry, server = served
    conversation_id = uuid.uuid4()
    entry = registry.expect(conversation_id)

    async with websockets.connect(
        f"ws://127.0.0.1:{server.port}/stream/{uuid.uuid4()}"
    ) as stranger:
        with pytest.raises(websockets.ConnectionClosed) as refused:
            await asyncio.wait_for(stranger.recv(), 2)
    assert refused.value.rcvd is not None
    assert refused.value.rcvd.code == 1008 and refused.value.rcvd.reason == NO_CALL

    async with websockets.connect(
        f"ws://127.0.0.1:{server.port}/stream/{conversation_id}"
    ) as first:
        await asyncio.wait_for(entry.socket, 2)
        async with websockets.connect(
            f"ws://127.0.0.1:{server.port}/stream/{conversation_id}"
        ) as second:
            with pytest.raises(websockets.ConnectionClosed) as duplicate:
                await asyncio.wait_for(second.recv(), 2)
        assert duplicate.value.rcvd is not None and duplicate.value.rcvd.code == 1008
        registry.forget(conversation_id)
        with pytest.raises(websockets.ConnectionClosed):
            await asyncio.wait_for(first.recv(), 2)


async def test_the_server_does_not_replace_the_process_signal_handlers() -> None:
    before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    server = PlivoServer(create_app(StreamRegistry(), PUBLIC_URL), port=0)
    await server.start()
    try:
        assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before
    finally:
        await server.stop(2.0)
