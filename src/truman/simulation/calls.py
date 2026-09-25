import asyncio
import contextlib

from truman.domain.conversations import (
    Caller,
    CallOutcome,
    CallRequest,
    EndReason,
    Transcript,
    Turn,
    WireEvent,
    WireEventKind,
)

STOP_IGNORED = "caller did not stop within the end timeout"


class CallerUnresponsiveError(Exception):
    """The caller survived cancellation; its task is leaked and only a process restart clears it."""


class LiveCall:
    def __init__(self) -> None:
        self.turns: list[Turn] = []
        self.wire_events: list[WireEvent] = []
        self.stop = asyncio.Event()
        self.connected = False
        self.end_reason = EndReason.USER_REQUEST
        self.outcome: CallOutcome | None = None
        self.dirty = False

    def turn(self, turn: Turn) -> None:
        self.turns.append(turn)
        self.dirty = True

    def wire_event(self, event: WireEvent) -> None:
        self.wire_events.append(event)
        if event.kind is WireEventKind.CONNECTED:
            self.connected = True
        self.dirty = True

    def request_stop(self, reason: EndReason) -> None:
        if not self.stop.is_set():
            self.end_reason = reason
            self.stop.set()

    def stop_ignored(self) -> CallOutcome:
        return CallOutcome(
            connected=self.connected, end_reason=self.end_reason, caller_error=STOP_IGNORED
        )

    def snapshot(self) -> Transcript:
        self.dirty = False
        return Transcript(turns=list(self.turns), wire_events=list(self.wire_events))


async def run_call(
    caller: Caller, request: CallRequest, live: LiveCall, *, end_timeout_s: float
) -> CallOutcome:
    """Run the caller under the max duration and the stop deadline.

    A stop request gives the caller `end_timeout_s` to hang up on its own, then it is cancelled
    and given the same again to unwind. Cancelling this coroutine stops the caller the same
    bounded way before re-raising, so no caller task outlives the call unnoticed.
    """
    run = asyncio.ensure_future(caller.run(request, live, live.stop))
    stopped = asyncio.ensure_future(live.stop.wait())
    try:
        await asyncio.wait(
            {run, stopped}, timeout=request.max_duration_s, return_when=asyncio.FIRST_COMPLETED
        )
        if run.done():
            return settle(run.result(), live)
        live.request_stop(EndReason.DURATION_LIMIT)
        return await outcome_after_stop(run, live, end_timeout_s)
    except asyncio.CancelledError:
        live.request_stop(EndReason.WORKER_STOPPED)
        live.outcome = await outcome_after_stop(run, live, end_timeout_s)
        raise
    finally:
        stopped.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stopped


def settle(outcome: CallOutcome, live: LiveCall) -> CallOutcome:
    """A requested stop owns the end reason when the stop is what ended the call; a call that
    ended on its own keeps the reason the caller observed."""
    if not live.stop.is_set() or outcome.end_reason is not EndReason.USER_REQUEST:
        return outcome
    return outcome.model_copy(update={"end_reason": live.end_reason})


async def outcome_after_stop(
    run: asyncio.Future[CallOutcome], live: LiveCall, end_timeout_s: float
) -> CallOutcome:
    await asyncio.wait({run}, timeout=end_timeout_s)
    if run.done():
        return settle(run.result(), live)
    run.cancel()
    await asyncio.wait({run}, timeout=end_timeout_s)
    if not run.done():
        raise CallerUnresponsiveError(STOP_IGNORED)
    if run.cancelled() or run.exception() is not None:
        return live.stop_ignored()
    return run.result().model_copy(
        update={"end_reason": live.end_reason, "caller_error": STOP_IGNORED}
    )
