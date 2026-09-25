import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import websockets
from fastapi import FastAPI, Request, Response
from httpx import AsyncClient

from tests.conftest import CALLER, Observer, make_settings
from truman.caller import phone
from truman.caller.phone import Connected, Dialer, PhoneCaller
from truman.caller.plivo_server import PlivoServer, StreamRegistry, create_app
from truman.domain.agents import AgentConfig
from truman.domain.conversations import CallOutcome, CallRequest, EndReason, WireEventKind
from truman.integrations.plivo import PlivoApi

PROVIDERS = ("deepgram_api_key", "elevenlabs_api_key", "openai_api_key")

AGENT_NUMBER = "+14155550100"
POOL_NUMBER = "+17862242321"
RETRIES = "rc=5&ct=2000&rd=1000&rp=5xx,ct"
START = {"streamId": "stream-1", "callId": "call-1", "mediaFormat": {"encoding": "audio/x-l16"}}


class Rig:
    """The worker's stream server, a fake Plivo API that records what it was asked, and a dialer."""

    def __init__(self, worker: PlivoServer, plivo: PlivoServer, registry: StreamRegistry) -> None:
        self.worker = worker
        self.registry = registry
        self.seen: list[dict[str, Any]] = []
        self.public_url = f"http://127.0.0.1:{worker.port}"
        self.api = PlivoApi("MAXXXX", "token", base_url=f"http://127.0.0.1:{plivo.port}")
        self.dialer = Dialer(self.api, self.public_url, ring_timeout_s=1)

    def caller(self, tmp_path: Path) -> PhoneCaller:
        settings = make_settings(
            tmp_path,
            **dict.fromkeys(PROVIDERS, "test"),
            plivo_auth_id="MAXXXX",
            plivo_auth_token="token",
            public_url=self.public_url,
            ring_timeout_s=1,
        )
        return PhoneCaller(settings, self.registry, self.api)

    async def report(self, conversation_id: uuid.UUID, **fields: str) -> None:
        async with AsyncClient(base_url=self.public_url) as client:
            response = await client.post(f"/callbacks/{conversation_id}", data=fields)
        assert response.status_code == 200

    async def answer(self, conversation_id: uuid.UUID, call_uuid: str) -> str:
        async with AsyncClient(base_url=self.public_url) as client:
            response = await client.post(
                f"/answer/{conversation_id}",
                data={"CallStatus": "in-progress", "CallUUID": call_uuid},
            )
        assert response.status_code == 200
        return response.text


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    monkeypatch.setattr(phone, "CALLBACK_GRACE_S", 0.5)
    monkeypatch.setattr(phone, "STREAM_GRACE_S", 0.5)
    fake = FastAPI()
    registry = StreamRegistry()
    worker = PlivoServer(create_app(registry, "http://placeholder"), port=0)
    plivo = PlivoServer(fake, port=0)
    await worker.start()
    await plivo.start()
    rig = Rig(worker, plivo, registry)

    @fake.post("/v1/Account/{auth_id}/Call/")
    async def create(request: Request) -> Response:
        rig.seen.append({"create": await request.json()})
        return Response('{"request_uuid": "req-1"}', status_code=201)

    @fake.delete("/v1/Account/{auth_id}/Request/{request_uuid}/")
    async def cancel(request_uuid: str) -> Response:
        rig.seen.append({"cancel": request_uuid})
        return Response(status_code=204)

    @fake.delete("/v1/Account/{auth_id}/Call/{call_uuid}/")
    async def hang_up(call_uuid: str) -> Response:
        rig.seen.append({"hang_up": call_uuid})
        return Response(status_code=204)

    yield rig
    await worker.stop(2.0)
    await plivo.stop(2.0)


def request(tmp_path: Path) -> CallRequest:
    return CallRequest(
        conversation_id=uuid.uuid4(),
        agent=AgentConfig.model_validate({"agent_number": AGENT_NUMBER}),
        **CALLER,
        caller_number=POOL_NUMBER,
        max_duration_s=120,
        output_dir=tmp_path,
    )


async def seen(observer: Observer, kind: WireEventKind) -> None:
    while kind not in observer.kinds():
        await asyncio.sleep(0.01)


def dial(rig: Rig, call: CallRequest, observer: Observer, stop: asyncio.Event) -> asyncio.Task[Any]:
    entry = rig.registry.expect(call.conversation_id)
    return asyncio.create_task(rig.dialer.dial(call, entry, observer, lambda: 0, stop))


async def test_the_stream_arrives_after_the_agent_rings_and_answers(
    rig: Rig, tmp_path: Path
) -> None:
    call = request(tmp_path)
    observer = Observer()
    dialing = dial(rig, call, observer, asyncio.Event())

    await rig.report(call.conversation_id, CallStatus="ringing", CallUUID="call-1")
    await rig.report(call.conversation_id, CallStatus="ringing", CallUUID="call-1")
    xml = await rig.answer(call.conversation_id, "call-1")
    async with websockets.connect(
        f"ws://127.0.0.1:{rig.worker.port}/stream/{call.conversation_id}"
    ) as plivo:
        await plivo.send(json.dumps({"event": "start", "start": START}))
        connected = await asyncio.wait_for(dialing, 2)
        assert isinstance(connected, Connected)
        assert (connected.stream_id, connected.call_uuid) == ("stream-1", "call-1")
        assert connected.encoding == "audio/x-l16"
        assert f"/stream/{call.conversation_id}" in xml
        rig.registry.forget(call.conversation_id)

    assert observer.kinds() == [WireEventKind.RINGING, WireEventKind.ANSWERED]
    assert rig.seen == [
        {
            "create": {
                "from": POOL_NUMBER,
                "to": AGENT_NUMBER,
                "answer_url": f"{rig.public_url}/answer/{call.conversation_id}",
                "answer_method": "POST",
                "hangup_url": f"{rig.public_url}/callbacks/{call.conversation_id}#{RETRIES}",
                "hangup_method": "POST",
                "ring_url": f"{rig.public_url}/callbacks/{call.conversation_id}#{RETRIES}",
                "ring_method": "POST",
                "ring_timeout": 1,
                "time_limit": 120 + phone.TIME_LIMIT_MARGIN_S,
            }
        }
    ]


async def test_an_unanswered_call_and_a_stop_while_ringing_end_without_a_stream(
    rig: Rig, tmp_path: Path
) -> None:
    unanswered = request(tmp_path)
    dialing = dial(rig, unanswered, Observer(), asyncio.Event())
    await rig.report(unanswered.conversation_id, CallStatus="ringing")
    await rig.report(unanswered.conversation_id, CallStatus="no-answer", HangupCause="NO_ANSWER")
    no_answer = await asyncio.wait_for(dialing, 2)

    stop = asyncio.Event()
    cancelled = request(tmp_path)
    dialing = dial(rig, cancelled, Observer(), stop)
    await rig.report(cancelled.conversation_id, CallStatus="ringing")
    stop.set()
    stopped = await asyncio.wait_for(dialing, 2)

    stop = asyncio.Event()
    answered = request(tmp_path)
    observer = Observer()
    dialing = dial(rig, answered, observer, stop)
    await rig.answer(answered.conversation_id, "call-3")
    await asyncio.wait_for(seen(observer, WireEventKind.ANSWERED), 2)
    stop.set()
    hung_up = await asyncio.wait_for(dialing, 2)

    assert no_answer == CallOutcome(
        connected=False,
        end_reason=EndReason.NO_ANSWER,
        caller_error="the agent did not answer: no-answer (NO_ANSWER)",
    )
    assert stopped == CallOutcome(connected=False, end_reason=EndReason.USER_REQUEST)
    assert hung_up == CallOutcome(
        connected=False, end_reason=EndReason.USER_REQUEST, call_uuid="call-3"
    )
    assert [action for action in rig.seen if "create" not in action] == [
        {"cancel": "req-1"},
        {"hang_up": "call-3"},
    ]


async def test_silence_from_plivo_and_a_missing_stream_time_out(rig: Rig, tmp_path: Path) -> None:
    silent = request(tmp_path)
    nothing = await asyncio.wait_for(dial(rig, silent, Observer(), asyncio.Event()), 5)

    answered = request(tmp_path)
    dialing = dial(rig, answered, Observer(), asyncio.Event())
    await rig.answer(answered.conversation_id, "call-2")
    no_stream = await asyncio.wait_for(dialing, 5)

    assert nothing.end_reason is EndReason.ERROR and nothing.caller_error
    assert "TRUMAN_PUBLIC_URL" in nothing.caller_error
    assert no_stream.end_reason is EndReason.ERROR and no_stream.caller_error
    assert "never reached the worker" in no_stream.caller_error
    assert [action for action in rig.seen if "create" not in action] == [
        {"cancel": "req-1"},
        {"hang_up": "call-2"},
    ]


async def test_the_phone_caller_reports_an_unanswered_call_and_frees_its_stream_entry(
    rig: Rig, tmp_path: Path
) -> None:
    call = request(tmp_path)
    observer = Observer()
    running = asyncio.create_task(rig.caller(tmp_path).run(call, observer, asyncio.Event()))
    await asyncio.wait_for(seen(observer, WireEventKind.CONNECT_STARTED), 2)
    await rig.report(call.conversation_id, CallStatus="ringing")
    await rig.report(call.conversation_id, CallStatus="no-answer")

    outcome = await asyncio.wait_for(running, 2)

    assert outcome.connected is False and outcome.end_reason is EndReason.NO_ANSWER
    assert observer.kinds() == [WireEventKind.CONNECT_STARTED, WireEventKind.RINGING]
    assert rig.registry.get(call.conversation_id) is None


async def test_a_stream_that_is_not_plivo_ends_the_call_before_any_provider_is_touched(
    rig: Rig, tmp_path: Path
) -> None:
    call = request(tmp_path)
    observer = Observer()
    running = asyncio.create_task(rig.caller(tmp_path).run(call, observer, asyncio.Event()))
    await asyncio.wait_for(seen(observer, WireEventKind.CONNECT_STARTED), 2)
    await rig.answer(call.conversation_id, "call-9")
    async with websockets.connect(
        f"ws://127.0.0.1:{rig.worker.port}/stream/{call.conversation_id}"
    ) as stranger:
        await stranger.send('{"event": "connected", "protocol": "Call"}')
        await stranger.send('{"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1"}}')
        outcome = await asyncio.wait_for(running, 2)

    assert outcome.connected is False and outcome.end_reason is EndReason.ERROR
    assert outcome.caller_error and "start event: connected" in outcome.caller_error
    assert outcome.call_uuid == "call-9"
    assert observer.kinds() == [WireEventKind.CONNECT_STARTED, WireEventKind.ANSWERED]
    assert rig.registry.get(call.conversation_id) is None
    assert rig.seen[-1] == {"hang_up": "call-9"}
