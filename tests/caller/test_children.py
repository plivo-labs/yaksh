import asyncio
import multiprocessing
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

import pytest
from fastapi import WebSocket, WebSocketDisconnect

from tests.caller import call_process_targets as targets
from tests.conftest import AGENT, APP_SETTINGS, CALLER, Observer, wait_until
from yaksh.caller import children, phone
from yaksh.caller.audio import Clock
from yaksh.caller.children import ChildConversations, ChildFailed
from yaksh.caller.conversation import Connected, ConversationStart
from yaksh.caller.pipeline import CallerKeys
from yaksh.domain.agents import AgentConfig, Transport
from yaksh.domain.conversations import CallObserver, CallOutcome, CallRequest, EndReason
from yaksh.simulation.calls import LiveCall, run_call


class Stream:
    """The stream's WebSocket in the worker: it gives nothing until it is told to, and takes
    each message with `take`."""

    def __init__(self, take: Callable[[dict[str, Any]], Any] | None = None) -> None:
        self.incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self._take = take

    async def receive(self) -> dict[str, Any]:
        return await self.incoming.get()

    async def send(self, message: dict[str, Any]) -> None:
        if self._take is not None:
            await self._take(message)
        self.sent.append(message)


def request() -> CallRequest:
    return CallRequest(
        conversation_id=uuid.uuid4(),
        agent=AgentConfig.model_validate({"agent_number": "+14155550100", "brief": AGENT["brief"]}),
        transport=Transport.PHONE,
        **CALLER,
        caller_number="+17862242321",
        max_duration_s=120,
        app_settings=APP_SETTINGS,
        caller=APP_SETTINGS.caller,
    )


def started(
    stream: Stream, observer: CallObserver | None = None, stop: asyncio.Event | None = None
) -> ConversationStart:
    return ConversationStart(
        request(),
        cast(CallerKeys, None),
        observer or Observer(),
        stop or asyncio.Event(),
        Clock(),
        Connected(cast(WebSocket, stream), "stream-1", "call-1", "audio/x-l16"),
        None,
        connected_ms=0,
    )


def call_pids() -> set[int]:
    return {
        process.pid
        for process in multiprocessing.active_children()
        if process.name == "yaksh-call" and process.pid is not None
    }


def running(pid: int) -> bool:
    """A zombie does not count: it holds nothing, and its parent reaps it later."""
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/stat") as stat:
                return stat.read().rsplit(")", 1)[1].split()[0] != "Z"
        except FileNotFoundError:
            return False
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return state.stdout.strip() not in ("", "Z")


@pytest.fixture
async def pools() -> AsyncIterator[Callable[[Callable[..., None]], ChildConversations]]:
    """Pools of call processes running a test target; closing them must leave no process."""
    made: list[ChildConversations] = []
    seen: set[int] = set()

    def make(target: Callable[..., None]) -> ChildConversations:
        pool = ChildConversations("postgresql://unused", target)
        made.append(pool)
        return pool

    yield make
    seen |= call_pids()
    for pool in made:
        assert await pool.close()
    await wait_until(lambda: not any(running(pid) for pid in seen))


async def test_a_call_process_holds_the_conversation_and_leaves(pools: Any) -> None:
    pool = pools(targets.holds)

    conversation = await pool.reserve().start(started(Stream()))
    ended, heard = await conversation.ended(), await conversation.heard()
    await conversation.close()

    assert ended == targets.ENDED and heard.recording == b"wav"


async def test_a_process_that_never_gets_ready_is_replaced_and_then_the_call_fails(
    pools: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(children, "READY_TIMEOUT_S", 0.5)
    pool = pools(targets.never_ready)

    with pytest.raises(ChildFailed, match="no call process got ready in 3 tries"):
        await pool.reserve().start(started(Stream()))


async def test_a_process_that_dies_during_the_call_fails_only_that_call(pools: Any) -> None:
    pool = pools(targets.dies_at_start)

    conversation = await pool.reserve().start(started(Stream()))
    with pytest.raises(ChildFailed, match="stopped before the call ended"):
        await conversation.ended()
    await conversation.close()


def live_pids() -> set[int]:
    return {pid for pid in call_pids() if running(pid)}


async def test_a_seat_given_back_before_its_call_starts_kills_only_its_process(pools: Any) -> None:
    pool = pools(targets.holds)
    seat = pool.reserve()
    await wait_until(lambda: len(live_pids()) == 1 + children.SPARES)

    await seat.release()

    await wait_until(lambda: len(live_pids()) == children.SPARES)


async def test_a_call_cancelled_while_it_takes_its_process_kills_only_that_process(
    pools: Any,
) -> None:
    pool = pools(targets.never_ready)
    seat = pool.reserve()
    starting = asyncio.create_task(seat.start(started(Stream())))
    await wait_until(lambda: len(live_pids()) == 1 + children.SPARES)

    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting
    await seat.release()

    await wait_until(lambda: len(live_pids()) == children.SPARES)


async def test_the_pool_keeps_its_spares_and_no_more(pools: Any) -> None:
    pool = pools(targets.holds)
    pool.warm()
    seats = [pool.reserve() for _ in range(3)]
    for seat in seats:
        await seat.release()

    await wait_until(lambda: len(call_pids()) == children.SPARES)


async def test_a_stream_too_slow_for_the_call_fails_it(
    pools: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(children, "STREAM_SEND_LIMIT_S", 0.2)

    async def stuck(_message: dict[str, Any]) -> None:
        await asyncio.sleep(3600)

    pool = pools(targets.sends_audio)
    conversation = await pool.reserve().start(started(Stream(stuck)))

    with pytest.raises(ChildFailed, match="did not take audio"):
        await conversation.ended()
    await conversation.close()


async def test_a_close_that_plivo_does_not_answer_does_not_fail_the_call(pools: Any) -> None:
    async def unanswered(message: dict[str, Any]) -> None:
        if message["type"] == "websocket.close":
            await asyncio.sleep(3600)

    stream = Stream(unanswered)
    pool = pools(targets.closes_the_stream)
    conversation = await pool.reserve().start(started(stream))

    heard = await conversation.heard()
    await conversation.close()

    assert heard.recording == b"wav" and [m["type"] for m in stream.sent] == ["websocket.send"]


async def test_a_stream_that_disconnected_stops_taking_messages_without_failing_the_call(
    pools: Any,
) -> None:
    async def hung_up(_message: dict[str, Any]) -> None:
        raise WebSocketDisconnect(1000)

    pool = pools(targets.sends_audio)
    conversation = await pool.reserve().start(started(Stream(hung_up)))
    await asyncio.sleep(0.2)

    conversation.cancel()
    heard = await conversation.heard()
    await conversation.close()

    assert heard.recording == b"wav"


class SeatedCaller:
    """A phone caller whose line is already connected: it holds the conversation in a call
    process, and its hang-up takes `hang_up_s`."""

    def __init__(self, pool: ChildConversations, hang_up_s: float) -> None:
        self._pool = pool
        self._hang_up_s = hang_up_s

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        async def hang_up(_call_uuid: str) -> None:
            await asyncio.sleep(self._hang_up_s)

        start = started(Stream(), observer, stop)
        line = phone.Line("call-1", asyncio.Queue(), hang_up)
        seat = self._pool.reserve()
        try:
            return await phone.talk(start, seat, line)
        finally:
            await seat.release()


@pytest.mark.parametrize(
    "target",
    [targets.ignores_cancel, targets.ends_but_never_hears, targets.hears_but_stays],
    ids=["ignores the cancel", "ends but never hears", "hears but stays"],
)
async def test_a_stopped_call_settles_within_the_stop_deadline_whatever_its_process_does(
    pools: Any, monkeypatch: pytest.MonkeyPatch, target: Callable[..., None]
) -> None:
    monkeypatch.setattr(children, "CANCEL_KILL_S", 0.5)
    monkeypatch.setattr(children, "EXIT_TIMEOUT_S", 0.5)
    end_timeout_s = 2.0
    live = LiveCall()
    running = asyncio.create_task(
        run_call(
            SeatedCaller(pools(target), hang_up_s=0.5),
            request(),
            live,
            end_timeout_s=end_timeout_s,
            dial_timeout_s=30,
        )
    )
    await wait_until(lambda: targets.HOLDING in live.wire_events, timeout=30)
    stopped = time.monotonic()

    live.request_stop(EndReason.USER_REQUEST)
    outcome = await running

    assert time.monotonic() - stopped < 2 * end_timeout_s
    assert outcome.end_reason is EndReason.USER_REQUEST
