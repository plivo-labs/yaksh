import asyncio
import uuid
from pathlib import Path

from tests.caller.test_plivo import Observer
from tests.conftest import make_settings
from truman.caller.persona import CallState, hang_up
from truman.caller.pipecat import PipecatCaller, outcome
from truman.caller.plivo import STALLED, Clock, Wire
from truman.domain.agents import AgentConfig
from truman.domain.conversations import CallRequest, EndReason, WireEventKind


async def test_a_refused_connection_ends_the_call_as_an_error(tmp_path: Path) -> None:
    providers = ("deepgram_api_key", "elevenlabs_api_key", "openai_api_key")
    settings = make_settings(tmp_path, **dict.fromkeys(providers, "test"))
    request = CallRequest(
        conversation_id=uuid.uuid4(),
        agent=AgentConfig.model_validate({"websocket_url": "ws://127.0.0.1:9/stream"}),
        persona_prompt="Book a table.",
        caller_number="+15550100000",
        max_duration_s=10,
        output_dir=tmp_path / "out",
    )
    observer = Observer()

    outcome = await asyncio.wait_for(
        PipecatCaller(settings).run(request, observer, asyncio.Event()), timeout=30
    )

    assert outcome.connected is False and outcome.end_reason is EndReason.ERROR
    assert outcome.caller_error and outcome.recording_path is None
    assert observer.kinds()[0] is WireEventKind.CONNECT_STARTED


class StuckPipeline:
    def has_finished(self) -> bool:
        return False

    async def stop_when_done(self) -> None:
        pass

    async def cancel(self) -> None:
        pass


async def test_hanging_up_never_returns_while_the_pipeline_is_alive() -> None:
    running = asyncio.create_task(asyncio.sleep(3600))
    state = CallState(end_reason=EndReason.USER_REQUEST)
    task = asyncio.create_task(hang_up(state, StuckPipeline(), running))
    await asyncio.sleep(0.05)

    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()

    running.cancel()
    await asyncio.wait({task}, timeout=1)
    assert task.done() and not task.cancelled()


def test_a_wire_that_failed_while_draining_turns_a_finished_call_into_an_error(
    tmp_path: Path,
) -> None:
    wire = Wire("stream", Clock(), Observer())
    wire.failed = STALLED
    state = CallState(connected=True, end_reason=EndReason.GOAL_REACHED)

    result = outcome(state, wire, tmp_path / "recording.wav")

    assert result.end_reason is EndReason.ERROR and result.caller_error == STALLED
