import asyncio
import contextlib
import logging

from truman.diagnostics import describe_exception
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

log = logging.getLogger(__name__)

STOP_IGNORED = "caller did not stop within the end timeout"


class CallerUnresponsiveError(Exception):
    """The caller survived cancellation; its task is leaked and only a process restart clears it."""


class LiveCall:
    def __init__(self) -> None:
        self.turns: list[Turn] = []
        self.wire_events: list[WireEvent] = []
        self.stop = asyncio.Event()
        self.connected_event = asyncio.Event()
        self.end_reason = EndReason.USER_REQUEST
        self.stop_detail: str | None = None
        self.outcome: CallOutcome | None = None
        self.dirty = False

    def turn(self, turn: Turn) -> None:
        self.turns.append(turn)
        self.dirty = True

    def wire_event(self, event: WireEvent) -> None:
        self.wire_events.append(event)
        if event.kind is WireEventKind.CONNECTED:
            self.connected_event.set()
        self.dirty = True

    @property
    def connected(self) -> bool:
        return self.connected_event.is_set()

    def request_stop(self, reason: EndReason, detail: str | None = None) -> None:
        """Stop the call for `reason`; `detail` says why when the reason alone does not."""
        if not self.stop.is_set():
            self.end_reason = reason
            self.stop_detail = detail
            self.stop.set()

    def stop_ignored(self, failure: str | None = None) -> CallOutcome:
        """The outcome of a caller that had to be cancelled; `failure` is what it raised."""
        parts = [self.stop_detail, STOP_IGNORED, failure and f"then it failed: {failure}"]
        error = "; ".join(part for part in parts if part)
        return CallOutcome(connected=self.connected, end_reason=self.end_reason, caller_error=error)

    def snapshot(self) -> Transcript:
        self.dirty = False
        return Transcript(turns=list(self.turns), wire_events=list(self.wire_events))


async def run_call(
    caller: Caller,
    request: CallRequest,
    live: LiveCall,
    *,
    end_timeout_s: float,
    dial_timeout_s: float,
) -> CallOutcome:
    """Run the caller: up to `dial_timeout_s` to connect its stream, then the max duration
    counted from the moment the stream connected, under the stop deadline.

    The caller gives up dialing on its own well before `dial_timeout_s`; that deadline only
    keeps a caller that never connects from holding the conversation. A stop request gives
    the caller `end_timeout_s` to hang up on its own, then it is cancelled and given the same
    again to unwind. Cancelling this coroutine stops the caller the same bounded way before
    re-raising, so no caller task outlives the call unnoticed.
    """
    run = asyncio.ensure_future(caller.run(request, live, live.stop))
    stopped = asyncio.ensure_future(live.stop.wait())
    connected = asyncio.ensure_future(live.connected_event.wait())
    try:
        await asyncio.wait(
            {run, stopped, connected}, timeout=dial_timeout_s, return_when=asyncio.FIRST_COMPLETED
        )
        deadline, detail = EndReason.ERROR, f"the call did not connect within {dial_timeout_s:g}s"
        if live.connected:
            deadline, detail = EndReason.DURATION_LIMIT, None
            await asyncio.wait(
                {run, stopped}, timeout=request.max_duration_s, return_when=asyncio.FIRST_COMPLETED
            )
        if run.done():
            return settle(run.result(), live)
        if detail is not None and not live.stop.is_set():
            log.error("conversation %s: %s", request.conversation_id, detail)
        live.request_stop(deadline, detail)
        return await outcome_after_stop(run, live, end_timeout_s)
    except asyncio.CancelledError:
        live.request_stop(EndReason.WORKER_STOPPED)
        live.outcome = await outcome_after_stop(run, live, end_timeout_s)
        raise
    finally:
        for waiter in (stopped, connected):
            waiter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await waiter


def settle(outcome: CallOutcome, live: LiveCall) -> CallOutcome:
    """A requested stop owns the end reason when the stop is what ended the call; a call that
    ended on its own keeps the reason the caller observed."""
    if not live.stop.is_set() or outcome.end_reason is not EndReason.USER_REQUEST:
        return outcome
    return outcome.model_copy(
        update={
            "end_reason": live.end_reason,
            "caller_error": outcome.caller_error or live.stop_detail,
        }
    )


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
    if run.cancelled():
        return live.stop_ignored()
    if (error := run.exception()) is not None:
        return live.stop_ignored(describe_exception(error))
    return run.result().model_copy(
        update={"end_reason": live.end_reason, "caller_error": STOP_IGNORED}
    )
