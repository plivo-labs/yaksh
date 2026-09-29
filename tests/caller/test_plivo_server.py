import asyncio
import signal
import uuid
from collections.abc import AsyncIterator

import pytest
import websockets
from httpx import ASGITransport, AsyncClient, Response

from tests.conftest import PLIVO_TOKEN, plivo_signed, refuse_calls
from truman.caller.plivo_server import (
    HANGUP_XML,
    NO_CALL,
    REJECT_XML,
    Accept,
    PlivoServer,
    StreamRegistry,
    create_app,
)
from truman.domain.conversations import Admission, IncomingCall

PUBLIC_URL = "https://truman.example.com"
STREAM_SIGNED_URL = "http://truman.example.com"
RETRIES = "rc=5&amp;ct=2000&amp;rd=1000&amp;rp=5xx,ct"


@pytest.fixture
async def served() -> AsyncIterator[tuple[StreamRegistry, PlivoServer]]:
    registry = StreamRegistry()
    server = PlivoServer(create_app(registry, PUBLIC_URL, PLIVO_TOKEN, refuse_calls), port=0)
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
        transport=ASGITransport(app=create_app(registry, PUBLIC_URL, PLIVO_TOKEN, refuse_calls)),
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
        f'statusCallbackUrl="https://truman.example.com/stream-status/{conversation_id}#{RETRIES}"'
        in answer.text
    )
    assert 'bidirectional="true"' in answer.text and 'keepCallAlive="true"' in answer.text
    assert 'contentType="audio/x-l16;rate=8000"' in answer.text
    assert f'extraHeaders="conversation_id={conversation_id}"' in answer.text
    assert unknown.status_code == 200 and unknown.text == HANGUP_XML
    assert garbled.status_code == 200 and garbled.text == HANGUP_XML
    assert entry.callbacks.get_nowait() == {"CallUUID": "abc", "CallStatus": "in-progress"}


async def test_call_reports_reach_the_waiting_conversation_and_stream_events_do_not() -> None:
    registry = StreamRegistry()
    conversation_id = uuid.uuid4()
    entry = registry.expect(conversation_id)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(registry, PUBLIC_URL, PLIVO_TOKEN, refuse_calls)),
        base_url="http://worker",
    ) as client:
        known = await post(
            client, f"/callbacks/{conversation_id}", {"CallStatus": "ringing", "CallUUID": "abc"}
        )
        unknown = await post(client, f"/callbacks/{uuid.uuid4()}", {"CallStatus": "completed"})
        stream = await post(client, f"/stream-status/{conversation_id}", {"Event": "StartStream"})

    assert known.status_code == unknown.status_code == stream.status_code == 200
    assert entry.callbacks.get_nowait() == {"CallStatus": "ringing", "CallUUID": "abc"}
    assert entry.callbacks.empty()


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
    server = PlivoServer(
        create_app(StreamRegistry(), PUBLIC_URL, PLIVO_TOKEN, refuse_calls), port=0
    )
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
        transport=ASGITransport(app=create_app(registry, PUBLIC_URL, PLIVO_TOKEN, refuse_calls)),
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


CALL = {"To": "15716535187", "From": "+19153188577", "CallUUID": "call-7"}


def admitting(conversation_id: uuid.UUID, seen: list[IncomingCall] | None = None) -> Accept:
    async def accept(call: IncomingCall) -> Admission | str:
        if seen is not None:
            seen.append(call)
        return Admission(conversation_id=conversation_id, max_duration_s=120)

    return accept


async def test_an_admitted_incoming_call_streams_with_a_plivo_side_time_limit() -> None:
    registry = StreamRegistry()
    waiting = uuid.uuid4()
    entry = registry.expect(waiting)
    seen: list[IncomingCall] = []
    app = create_app(registry, PUBLIC_URL, PLIVO_TOKEN, admitting(waiting, seen))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://worker") as client:
        answered = await post(client, "/incoming", CALL)
        retried = await post(client, "/incoming", CALL)

    assert seen[0] == IncomingCall(
        to_number="+15716535187", from_number="+19153188577", call_uuid="call-7"
    )
    assert answered.text == retried.text
    assert answered.text.index('<Hangup schedule="150"/>') < answered.text.index("<Stream")
    assert f"wss://truman.example.com/stream/{waiting}" in answered.text
    assert entry.callbacks.get_nowait() == CALL


async def test_the_hangup_report_of_an_admitted_call_reaches_it() -> None:
    registry = StreamRegistry()
    waiting = uuid.uuid4()
    entry = registry.expect(waiting)
    app = create_app(registry, PUBLIC_URL, PLIVO_TOKEN, admitting(waiting))
    hangup = {"CallUUID": "call-7", "Event": "Hangup", "HangupSource": "Caller"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://worker") as client:
        await post(client, "/incoming", CALL)
        reported = await post(client, "/incoming/hangup", hangup)
        stray = await post(client, "/incoming/hangup", {**hangup, "CallUUID": "other"})

    assert reported.status_code == stray.status_code == 200
    assert [entry.callbacks.get_nowait() for _ in range(2)] == [CALL, hangup]
    assert entry.callbacks.empty()


@pytest.mark.parametrize(
    ("accept", "expecting"),
    [(refuse_calls, True), (admitting(uuid.uuid4()), False)],
    ids=["not admitted", "no waiting stream"],
)
async def test_incoming_calls_that_cannot_stream_are_rejected(
    accept: Accept, expecting: bool
) -> None:
    registry = StreamRegistry()
    if expecting:
        registry.expect(uuid.uuid4())
    app = create_app(registry, PUBLIC_URL, PLIVO_TOKEN, accept)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://worker") as client:
        rejected = await post(client, "/incoming", CALL)
        unsigned = await client.post("/incoming", data=CALL)

    assert rejected.text == REJECT_XML
    assert unsigned.status_code == 403
