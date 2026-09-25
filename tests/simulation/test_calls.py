import asyncio
import uuid
from pathlib import Path

from tests.conftest import CALLER
from truman.domain.agents import AgentConfig
from truman.domain.conversations import (
    CallObserver,
    CallOutcome,
    CallRequest,
    EndReason,
)
from truman.simulation.calls import STOP_IGNORED, LiveCall, run_call

REQUEST = CallRequest(
    conversation_id=uuid.uuid4(),
    agent=AgentConfig.model_validate({"agent_number": "+14155550100"}),
    **CALLER,
    caller_number="+15550100000",
    max_duration_s=10,
    output_dir=Path("/tmp/unused"),
)


class ReturnsOnStop:
    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        await stop.wait()
        return CallOutcome(connected=True, end_reason=EndReason.USER_REQUEST)


async def test_a_requested_stop_reason_wins_even_when_the_caller_returns_at_once() -> None:
    live = LiveCall()
    live.request_stop(EndReason.PROCESS_RESTART)

    outcome = await run_call(ReturnsOnStop(), REQUEST, live, end_timeout_s=0.2)

    assert outcome.end_reason is EndReason.PROCESS_RESTART and outcome.connected is True


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

    outcome = await run_call(ReturnsOnlyWhenCancelled(), REQUEST, live, end_timeout_s=0.1)

    assert outcome.recording_path == Path("/data/saved.wav")
    assert outcome.end_reason is EndReason.USER_REQUEST
    assert outcome.caller_error == STOP_IGNORED
