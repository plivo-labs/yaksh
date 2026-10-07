import asyncio
import uuid
from pathlib import Path

from tests.conftest import AGENT, APP_SETTINGS, CALLER
from yaksha.domain.agents import AgentConfig
from yaksha.domain.conversations import (
    CallObserver,
    CallOutcome,
    CallRequest,
    EndReason,
    WireEvent,
    WireEventKind,
)
from yaksha.simulation.calls import STOP_IGNORED, LiveCall, run_call

REQUEST = CallRequest(
    conversation_id=uuid.uuid4(),
    agent=AgentConfig.model_validate({"agent_number": "+14155550100", "brief": AGENT["brief"]}),
    **CALLER,
    caller_number="+15550100000",
    max_duration_s=10,
    output_dir=Path("/tmp/unused"),
    app_settings=APP_SETTINGS,
)


class ReturnsOnStop:
    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        await stop.wait()
        return CallOutcome(connected=True, end_reason=EndReason.USER_REQUEST)


async def test_a_requested_stop_reason_wins_even_when_the_caller_returns_at_once() -> None:
    live = LiveCall()
    live.request_stop(EndReason.WORKER_STOPPED)

    outcome = await run_call(ReturnsOnStop(), REQUEST, live, end_timeout_s=0.2, dial_timeout_s=5)

    assert outcome.end_reason is EndReason.WORKER_STOPPED and outcome.connected is True


class ReturnsOnlyWhenCancelled:
    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            return CallOutcome(
                connected=True,
                end_reason=EndReason.AGENT_HANGUP,
                recording_path=Path("/data/saved.wav"),
            )
        raise AssertionError("unreachable")


async def test_a_caller_that_needed_cancelling_keeps_its_recording_but_is_marked() -> None:
    live = LiveCall()
    live.request_stop(EndReason.USER_REQUEST)

    outcome = await run_call(
        ReturnsOnlyWhenCancelled(), REQUEST, live, end_timeout_s=0.1, dial_timeout_s=5
    )

    assert outcome.recording_path == Path("/data/saved.wav")
    assert outcome.end_reason is EndReason.USER_REQUEST
    assert outcome.caller_error == STOP_IGNORED


class EndsOnItsOwnDuringStop:
    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        await stop.wait()
        return CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP)


async def test_a_stop_that_comes_after_the_call_ended_does_not_rename_its_end() -> None:
    live = LiveCall()
    live.request_stop(EndReason.USER_REQUEST)

    outcome = await run_call(
        EndsOnItsOwnDuringStop(), REQUEST, live, end_timeout_s=0.2, dial_timeout_s=5
    )

    assert outcome.end_reason is EndReason.AGENT_HANGUP


class AnswersLate:
    """Rings for a while, connects, then talks until it is stopped."""

    def __init__(self, ring_s: float) -> None:
        self.ring_s = ring_s

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        await asyncio.sleep(self.ring_s)
        observer.wire_event(WireEvent(kind=WireEventKind.CONNECTED, at_ms=0))
        await stop.wait()
        return CallOutcome(connected=True, end_reason=EndReason.USER_REQUEST)


async def test_the_time_limit_counts_from_connect_not_from_dialing() -> None:
    live = LiveCall()
    request = REQUEST.model_copy(update={"max_duration_s": 0.3})
    loop = asyncio.get_running_loop()
    started = loop.time()

    outcome = await run_call(
        AnswersLate(ring_s=0.5), request, live, end_timeout_s=0.2, dial_timeout_s=5
    )

    assert outcome.end_reason is EndReason.DURATION_LIMIT
    assert loop.time() - started >= 0.8


def test_a_second_connected_event_moves_the_first() -> None:
    live = LiveCall()
    live.wire_event(WireEvent(kind=WireEventKind.CONNECTED, at_ms=3_000))
    live.wire_event(WireEvent(kind=WireEventKind.AGENT_AUDIO, at_ms=4_500))
    live.wire_event(WireEvent(kind=WireEventKind.CONNECTED, at_ms=2_200))

    assert [(e.kind, e.at_ms) for e in live.snapshot().wire_events] == [
        (WireEventKind.CONNECTED, 2_200),
        (WireEventKind.AGENT_AUDIO, 4_500),
    ]


async def test_a_caller_that_never_connects_is_stopped_at_the_dial_deadline_with_a_reason() -> None:
    live = LiveCall()

    outcome = await run_call(ReturnsOnStop(), REQUEST, live, end_timeout_s=0.2, dial_timeout_s=0.1)

    assert outcome.end_reason is EndReason.ERROR
    assert outcome.caller_error == "the call did not connect within 0.1s"


class RaisesWhenCancelled:
    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise RuntimeError("boom") from None
        raise AssertionError("unreachable")


async def test_a_caller_that_fails_while_it_is_cancelled_keeps_its_error() -> None:
    live = LiveCall()
    live.request_stop(EndReason.USER_REQUEST)

    outcome = await run_call(
        RaisesWhenCancelled(), REQUEST, live, end_timeout_s=0.1, dial_timeout_s=5
    )

    assert outcome.caller_error == f"{STOP_IGNORED}; then it failed: RuntimeError: boom"


async def test_a_deadline_stop_names_its_reason_before_the_caller_failure() -> None:
    live = LiveCall()

    outcome = await run_call(
        RaisesWhenCancelled(), REQUEST, live, end_timeout_s=0.1, dial_timeout_s=0.1
    )

    assert outcome.caller_error == (
        f"the call did not connect within 0.1s; {STOP_IGNORED}; then it failed: RuntimeError: boom"
    )
