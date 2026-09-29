import asyncio
import signal
import uuid
from collections.abc import AsyncIterator

import pytest
import websockets
from httpx import ASGITransport, AsyncClient, Response

from tests.conftest import PLIVO_TOKEN, plivo_signed
from truman.caller.plivo_server import (
    HANGUP_XML,
    NO_CALL,
    PlivoServer,
    StreamRegistry,
    create_app,
)

PUBLIC_URL = "https://truman.example.com"
STREAM_SIGNED_URL = "http://truman.example.com"
RETRIES = "rc=5&amp;ct=2000&amp;rd=1000&amp;rp=5xx,ct"


@pytest.fixture
async def served() -> AsyncIterator[tuple[StreamRegistry, PlivoServer]]:
    registry = StreamRegistry()
    server = PlivoServer(create_app(registry, PUBLIC_URL, PLIVO_TOKEN), port=0)
    await server.start()
    yield registry, server
    await server.stop(2.0)


async def post(client: AsyncClient, path: str, fields: dict[str, str]) -> Response:
    return await client.post(path, data=fields, headers=plivo_signed(PUBLIC_URL + path, fields))


def stream(server: PlivoServer, conversation_id: uuid.UUID) -> websockets.connect:
    path = f"/stream/{conversation_id}"
    return websockets.connect(
        f"ws://127.0.0.1:{server.port}{path}",
        additional_headers=plivo_signed(STREAM_SIGNED_URL + path, method="GET"),
    )


async def test_the_answer_xml_streams_a_waiting_conversation_and_hangs_up_others() -> None:
    registry = StreamRegistry()
    conversation_id = uuid.uuid4()
    entry = registry.expect(conversation_id)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(registry, PUBLIC_URL, PLIVO_TOKEN)),
        base_url="http://worker",
    ) as client:
        answer = await post(
            client, f"/answer/{conversation_id}", {"CallUUID": "abc", "CallStatus": "in-progress"}
        )
        unknown = await post(client, f"/answer/{uuid.uuid4()}", {})
        garbled = await post(client, "/answer/not-a-conversation", {})

    assert answer.status_code == 200 and answer.headers["content-type"].startswith(
        "application/xml"
    )
    assert f"wss://truman.example.com/stream/{conversation_id}" in answer.text
    assert (
        f'statusCallbackUrl="https://truman.example.com/callbacks/{conversation_id}#{RETRIES}"'
        in answer.text
    )
    assert 'bidirectional="true"' in answer.text and 'keepCallAlive="true"' in answer.text
    assert 'contentType="audio/x-l16;rate=8000"' in answer.text
    assert f'extraHeaders="conversation_id={conversation_id}"' in answer.text
    assert unknown.status_code == 200 and unknown.text == HANGUP_XML
    assert garbled.status_code == 200 and garbled.text == HANGUP_XML
    assert entry.callbacks.get_nowait() == {"CallUUID": "abc", "CallStatus": "in-progress"}


async def test_callbacks_reach_the_waiting_conversation_and_are_always_acknowledged() -> None:
    registry = StreamRegistry()
    conversation_id = uuid.uuid4()
    entry = registry.expect(conversation_id)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(registry, PUBLIC_URL, PLIVO_TOKEN)),
        base_url="http://worker",
    ) as client:
        known = await post(
            client, f"/callbacks/{conversation_id}", {"CallStatus": "ringing", "CallUUID": "abc"}
        )
        unknown = await post(client, f"/callbacks/{uuid.uuid4()}", {"CallStatus": "completed"})

    assert known.status_code == 200 and unknown.status_code == 200
    assert entry.callbacks.get_nowait() == {"CallStatus": "ringing", "CallUUID": "abc"}


async def test_the_stream_socket_is_handed_to_the_waiting_entry_and_held_until_forgotten(
    served: tuple[StreamRegistry, PlivoServer],
) -> None:
    registry, server = served
    conversation_id = uuid.uuid4()
    entry = registry.expect(conversation_id)

    async with stream(server, conversation_id) as plivo:
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

    async with stream(server, uuid.uuid4()) as stranger:
        with pytest.raises(websockets.ConnectionClosed) as refused:
            await asyncio.wait_for(stranger.recv(), 2)
    assert refused.value.rcvd is not None
    assert refused.value.rcvd.code == 1008 and refused.value.rcvd.reason == NO_CALL

    async with stream(server, conversation_id) as first:
        await asyncio.wait_for(entry.socket, 2)
        async with stream(server, conversation_id) as second:
            with pytest.raises(websockets.ConnectionClosed) as duplicate:
                await asyncio.wait_for(second.recv(), 2)
        assert duplicate.value.rcvd is not None and duplicate.value.rcvd.code == 1008
        registry.forget(conversation_id)
        with pytest.raises(websockets.ConnectionClosed):
            await asyncio.wait_for(first.recv(), 2)


async def test_the_server_does_not_replace_the_process_signal_handlers() -> None:
    before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    server = PlivoServer(create_app(StreamRegistry(), PUBLIC_URL, PLIVO_TOKEN), port=0)
    await server.start()
    try:
        assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before
    finally:
        await server.stop(2.0)


async def test_requests_plivo_did_not_sign_are_refused_and_never_reach_a_call(
    served: tuple[StreamRegistry, PlivoServer],
) -> None:
    registry, server = served
    conversation_id = uuid.uuid4()
    entry = registry.expect(conversation_id)
    path = f"/callbacks/{conversation_id}"
    fields = {"CallStatus": "ringing"}
    forged = plivo_signed(PUBLIC_URL + path, {"CallStatus": "completed"})

    async with AsyncClient(
        transport=ASGITransport(app=create_app(registry, PUBLIC_URL, PLIVO_TOKEN)),
        base_url="http://worker",
    ) as client:
        unsigned = await client.post(path, data=fields)
        tampered = await client.post(path, data=fields, headers=forged)
        answer = await client.post(f"/answer/{conversation_id}", data=fields)
    with pytest.raises(websockets.InvalidStatus):
        async with websockets.connect(f"ws://127.0.0.1:{server.port}/stream/{conversation_id}"):
            pass

    assert unsigned.status_code == tampered.status_code == answer.status_code == 403
    assert entry.callbacks.empty() and not entry.socket.done()
