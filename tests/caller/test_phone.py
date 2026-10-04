import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
import websockets
from fastapi import FastAPI, Request, Response, WebSocket
from httpx import AsyncClient

from tests.conftest import (
    CALLER,
    OUTBOUND_AGENT,
    PLIVO_TOKEN,
    Observer,
    make_settings,
    plivo_signed,
    refuse_calls,
)
from truman.caller import phone
from truman.caller.audio import Clock
from truman.caller.phone import Connected, Dialer, PhoneCaller, Receiver
from truman.caller.pipeline import CallState
from truman.caller.plivo_server import PendingStream, PlivoServer, StreamRegistry, create_app
from truman.domain.agents import AgentConfig
from truman.domain.conversations import (
    CallOutcome,
    CallRequest,
    EndReason,
    LineFacts,
    WireEventKind,
)
from truman.integrations.plivo import PlivoApi
from truman.integrations.trigger import TriggerOutcome, TriggerResult

PROVIDERS = ("deepgram_api_key", "elevenlabs_api_key", "openai_api_key")

AGENT_NUMBER = "+14155550100"
POOL_NUMBER = "+17862242321"
SIGNED_URL = "http://placeholder"
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
        path = f"/callbacks/{conversation_id}"
        async with AsyncClient(base_url=self.public_url) as client:
            response = await client.post(
                path, data=fields, headers=plivo_signed(SIGNED_URL + path, fields)
            )
        assert response.status_code == 200

    async def answer(self, conversation_id: uuid.UUID, call_uuid: str) -> str:
        path = f"/answer/{conversation_id}"
        fields = {"CallStatus": "in-progress", "CallUUID": call_uuid}
        async with AsyncClient(base_url=self.public_url) as client:
            response = await client.post(
                path, data=fields, headers=plivo_signed(SIGNED_URL + path, fields)
            )
        assert response.status_code == 200
        return response.text

    def stream(self, conversation_id: uuid.UUID) -> websockets.connect:
        path = f"/stream/{conversation_id}"
        return websockets.connect(
            f"ws://127.0.0.1:{self.worker.port}{path}",
            additional_headers=plivo_signed(f"http://placeholder{path}", method="GET"),
        )


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    monkeypatch.setattr(phone, "CALLBACK_GRACE_S", 0.5)
    monkeypatch.setattr(phone, "STREAM_GRACE_S", 0.5)
    fake = FastAPI()
    registry = StreamRegistry()
    worker = PlivoServer(create_app(registry, SIGNED_URL, PLIVO_TOKEN, refuse_calls), port=0)
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
    async with rig.stream(call.conversation_id) as plivo:
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


async def test_a_call_that_only_rang_is_not_reported_as_answered(rig: Rig, tmp_path: Path) -> None:
    call = request(tmp_path)
    dialing = dial(rig, call, Observer(), asyncio.Event())
    await rig.report(call.conversation_id, CallStatus="ringing", CallUUID="call-4")

    outcome = await asyncio.wait_for(dialing, 5)

    assert outcome.end_reason is EndReason.ERROR and outcome.caller_error
    assert "rang" in outcome.caller_error and "answered" not in outcome.caller_error


async def test_a_hangup_before_the_stream_names_the_side_plivo_reports(
    rig: Rig, tmp_path: Path
) -> None:
    async def hung_up(**report: str) -> CallOutcome:
        call = request(tmp_path)
        dialing = dial(rig, call, Observer(), asyncio.Event())
        await rig.report(call.conversation_id, CallStatus="completed", Event="Hangup", **report)
        return await asyncio.wait_for(dialing, 2)

    agent = await hung_up(HangupSource="Callee", HangupCause="NORMAL_CLEARING")
    carrier = await hung_up(HangupSource="Plivo", HangupCauseName="Network Error")
    unknown = await hung_up(HangupCause="NORMAL_CLEARING")

    assert agent.end_reason is EndReason.AGENT_HANGUP
    assert carrier.end_reason is EndReason.ERROR
    assert carrier.caller_error == "Plivo reports hangup source Plivo: Network Error"
    assert unknown.end_reason is EndReason.ERROR
    assert unknown.caller_error == (
        "the call ended before its stream started: completed (NORMAL_CLEARING)"
    )


def test_the_end_of_a_stream_is_named_by_the_hangup_report_that_follows() -> None:
    agent, outbound, unknown, observed = CallState(), CallState(), CallState(), CallState()
    for state in (agent, outbound, unknown):
        state.end(EndReason.STREAM_ENDED)
    observed.end(EndReason.CALLER_HANGUP)
    callee = {"CallStatus": "completed", "Event": "Hangup", "HangupSource": "Callee"}
    caller = {"CallStatus": "completed", "Event": "Hangup", "HangupSource": "Caller"}

    phone.resolve_stream_end(agent, callee, phone.CALLED_SIDE)
    phone.resolve_stream_end(outbound, caller, phone.CALLING_SIDE)
    phone.resolve_stream_end(unknown, None, phone.CALLED_SIDE)
    phone.resolve_stream_end(observed, callee, phone.CALLED_SIDE)

    assert (agent.end_reason, agent.error) == (EndReason.AGENT_HANGUP, None)
    assert (outbound.end_reason, outbound.error) == (EndReason.AGENT_HANGUP, None), (
        "an outbound agent called Truman, so its side is the caller"
    )
    assert unknown.end_reason is EndReason.STREAM_ENDED
    assert unknown.error == "the stream ended and Plivo did not say which side ended the call"
    assert (observed.end_reason, observed.error) == (EndReason.CALLER_HANGUP, None)


async def test_the_line_hangs_up_once_and_reads_the_report_that_follows() -> None:
    reports: asyncio.Queue[dict[str, str]] = asyncio.Queue()
    hung_up: list[str] = []
    report = {
        "Event": "Hangup",
        "HangupSource": "Caller",
        "HangupCauseName": "Normal Hangup",
        "Duration": "47",
        "BillDuration": "60",
        "AnswerTime": "2026-10-05 10:02:18",
        "EndTime": "2026-10-05 10:03:05",
    }

    async def hang_up(call_uuid: str) -> None:
        hung_up.append(call_uuid)
        reports.put_nowait({"Event": "StartStream"})
        reports.put_nowait(report)

    line = phone.Line("call-7", reports, hang_up)
    got = await line.end()
    await line.hang_up()

    assert hung_up == ["call-7"]
    assert got == report
    assert phone.line_facts(report) == LineFacts(
        hangup_source="Caller",
        hangup_cause="Normal Hangup",
        duration_s=47,
        bill_duration_s=60,
        answer_time="2026-10-05 10:02:18",
        end_time="2026-10-05 10:03:05",
    )


async def test_a_line_whose_report_does_not_come_ends_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(phone, "HANGUP_REPORT_WAIT_S", 0.05)

    async def hang_up(_call_uuid: str) -> None:
        return None

    assert await phone.Line("call-8", asyncio.Queue(), hang_up).end() is None


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
    async with rig.stream(call.conversation_id) as stranger:
        await stranger.send('{"event": "connected", "protocol": "Call"}')
        await stranger.send('{"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1"}}')
        outcome = await asyncio.wait_for(running, 2)

    assert outcome.connected is False and outcome.end_reason is EndReason.ERROR
    assert outcome.caller_error and "start event: connected" in outcome.caller_error
    assert outcome.call_uuid == "call-9"
    assert observer.kinds() == [WireEventKind.CONNECT_STARTED, WireEventKind.ANSWERED]
    assert rig.registry.get(call.conversation_id) is None
    assert rig.seen[-1] == {"hang_up": "call-9"}


def outbound_request(tmp_path: Path, window_s: float = 5) -> CallRequest:
    agent = AgentConfig.model_validate(
        {key: value for key, value in OUTBOUND_AGENT.items() if key != "name"}
    )
    return CallRequest(
        conversation_id=uuid.uuid4(),
        agent=agent,
        **CALLER,
        caller_number=POOL_NUMBER,
        max_duration_s=120,
        accept_calls_until=datetime.now(UTC) + timedelta(seconds=window_s),
        output_dir=tmp_path,
    )


def receive(
    rig: Rig, call: CallRequest, observer: Observer, trigger: asyncio.Future[TriggerOutcome]
) -> tuple[PendingStream, asyncio.Task[Any]]:
    entry = rig.registry.expect(call.conversation_id)
    task = asyncio.create_task(
        Receiver().receive(call, entry, observer, lambda: 0, asyncio.Event(), trigger)
    )
    return entry, task


def settled_trigger(result: TriggerResult, detail: str) -> asyncio.Future[TriggerOutcome]:
    future: asyncio.Future[TriggerOutcome] = asyncio.get_running_loop().create_future()
    future.set_result(TriggerOutcome(result, detail))
    return future


async def test_a_refused_trigger_ends_the_wait_at_once(rig: Rig, tmp_path: Path) -> None:
    _, receiving = receive(
        rig,
        outbound_request(tmp_path),
        Observer(),
        settled_trigger(TriggerResult.REJECTED, 'HTTP 422: {"error": "phone is required"}'),
    )

    outcome = await asyncio.wait_for(receiving, 2)

    assert outcome.end_reason is EndReason.TRIGGER_FAILED
    assert outcome.caller_error == 'HTTP 422: {"error": "phone is required"}'


async def test_a_call_that_arrives_before_the_trigger_answers_is_taken(
    rig: Rig, tmp_path: Path
) -> None:
    call = outbound_request(tmp_path)
    observer = Observer()
    pending: asyncio.Future[TriggerOutcome] = asyncio.get_running_loop().create_future()
    entry, receiving = receive(rig, call, observer, pending)

    entry.callbacks.put_nowait({"CallUUID": "call-1", "From": AGENT_NUMBER})
    async with rig.stream(call.conversation_id) as plivo:
        await plivo.send(json.dumps({"event": "start", "start": START}))
        connected = await asyncio.wait_for(receiving, 2)
        rig.registry.forget(call.conversation_id)

    assert isinstance(connected, Connected) and connected.call_uuid == "call-1"
    assert observer.kinds() == [WireEventKind.WAITING_FOR_CALL, WireEventKind.ANSWERED]
    assert not pending.done(), "the trigger keeps running after the call connected"


async def test_no_call_within_the_window_names_the_trigger_result(rig: Rig, tmp_path: Path) -> None:
    _, receiving = receive(
        rig,
        outbound_request(tmp_path, window_s=0.2),
        Observer(),
        settled_trigger(TriggerResult.UNKNOWN, "HTTP 503: upstream down"),
    )

    outcome = await asyncio.wait_for(receiving, 5)

    assert outcome.end_reason is EndReason.NO_CALL
    assert outcome.caller_error == (
        f"no call reached {POOL_NUMBER} within the dial window; "
        "trigger result: HTTP 503: upstream down"
    )


async def test_a_stream_for_another_call_is_refused(rig: Rig, tmp_path: Path) -> None:
    call = outbound_request(tmp_path)
    entry, receiving = receive(
        rig, call, Observer(), settled_trigger(TriggerResult.DELIVERED, "HTTP 200: {}")
    )

    entry.callbacks.put_nowait({"CallUUID": "call-2"})
    async with rig.stream(call.conversation_id) as plivo:
        await plivo.send(json.dumps({"event": "start", "start": START}))
        outcome = await asyncio.wait_for(receiving, 2)
        rig.registry.forget(call.conversation_id)

    assert outcome.end_reason is EndReason.ERROR
    assert outcome.caller_error == "the stream belongs to call call-1, not the accepted call"


async def test_an_agent_that_hangs_up_before_the_stream_opens_is_named(
    rig: Rig, tmp_path: Path
) -> None:
    call = outbound_request(tmp_path)
    entry, receiving = receive(
        rig, call, Observer(), settled_trigger(TriggerResult.DELIVERED, "HTTP 200: {}")
    )

    entry.callbacks.put_nowait({"CallUUID": "call-1"})
    entry.callbacks.put_nowait({"CallUUID": "call-1", "Event": "Hangup", "HangupSource": "Caller"})
    outcome = await asyncio.wait_for(receiving, 2)
    rig.registry.forget(call.conversation_id)

    assert (outcome.end_reason, outcome.call_uuid) == (EndReason.AGENT_HANGUP, "call-1")


async def test_a_trigger_that_cannot_be_rendered_is_recorded_as_not_sent(
    rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRUMAN_TRIGGER_KEY", "sk_test")
    observer = Observer()
    call = outbound_request(tmp_path)

    outcome = await rig.caller(tmp_path)._send_trigger(call, observer, Clock())

    assert outcome.result is TriggerResult.NOT_SENT
    assert outcome.detail == "the scenario has no agent data named 'Customer name'"
    assert [(e.kind, e.detail) for e in observer.events] == [
        (WireEventKind.TRIGGER_SENT, outcome.detail)
    ]


class StartedSocket:
    """A stream socket whose Plivo start event is already waiting."""

    async def receive_text(self) -> str:
        return json.dumps({"event": "start", "start": START})


@pytest.mark.parametrize(
    "trigger_result", [TriggerResult.REJECTED, TriggerResult.DELIVERED], ids=["refused", "sent"]
)
async def test_an_accepted_call_wins_over_events_that_arrive_with_it(
    rig: Rig, tmp_path: Path, trigger_result: TriggerResult
) -> None:
    call = outbound_request(tmp_path)
    entry = rig.registry.expect(call.conversation_id)
    entry.callbacks.put_nowait({"CallUUID": "call-1"})
    entry.socket.set_result(cast(WebSocket, StartedSocket()))

    connected = await Receiver().receive(
        call, entry, Observer(), lambda: 0, asyncio.Event(), settled_trigger(trigger_result, "x")
    )
    rig.registry.forget(call.conversation_id)

    assert isinstance(connected, Connected) and connected.call_uuid == "call-1"
