"""Dialing the agent through Plivo: place the call, then wait for its stream or learn why it
never came."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import WebSocket

from truman.caller.plivo_api import OutboundCall, PlivoApi, PlivoError
from truman.caller.plivo_server import PendingStream
from truman.domain.conversations import (
    CallObserver,
    CallOutcome,
    CallRequest,
    EndReason,
    WireEvent,
    WireEventKind,
)

log = logging.getLogger(__name__)

CALLBACK_GRACE_S = 15.0
STREAM_GRACE_S = 10.0
TIME_LIMIT_MARGIN_S = 10
RINGING = "ringing"
IN_PROGRESS = "in-progress"
UNANSWERED = frozenset({"no-answer", "timeout", "busy"})


@dataclass
class Connected:
    socket: WebSocket
    request_uuid: str
    call_uuid: str | None


class Dialer:
    """Rings the agent from the leased number and hands over the stream socket once it lands.

    Plivo reports the call through the answer fetch and the callbacks queued on the registry
    entry; the wait ends with the socket, a stop, a report that the call ended, or silence past
    the ring timeout.
    """

    def __init__(self, api: PlivoApi, public_url: str, ring_timeout_s: int) -> None:
        self._api = api
        self._base = public_url.rstrip("/")
        self._ring_timeout_s = ring_timeout_s

    async def dial(
        self,
        request: CallRequest,
        entry: PendingStream,
        observer: CallObserver,
        at_ms: Callable[[], int],
        stop: asyncio.Event,
    ) -> Connected | CallOutcome:
        if request.agent.agent_number is None:
            return unreached(EndReason.ERROR, "the agent has no phone number")
        conversation_id = request.conversation_id
        call = OutboundCall(
            from_number=request.caller_number,
            to_number=request.agent.agent_number,
            answer_url=f"{self._base}/answer/{conversation_id}",
            hangup_url=f"{self._base}/callbacks/{conversation_id}",
            ring_url=f"{self._base}/callbacks/{conversation_id}",
            ring_timeout_s=self._ring_timeout_s,
            time_limit_s=request.max_duration_s + TIME_LIMIT_MARGIN_S,
        )
        try:
            request_uuid = await self._api.create_call(call)
        except PlivoError as error:
            return unreached(EndReason.ERROR, str(error))
        call_uuid: str | None = None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._ring_timeout_s + CALLBACK_GRACE_S
        stopped = asyncio.ensure_future(stop.wait())
        report = asyncio.ensure_future(entry.callbacks.get())
        try:
            while True:
                await asyncio.wait(
                    {entry.socket, stopped, report},
                    timeout=max(deadline - loop.time(), 0),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if report.done():
                    fields = report.result()
                    report = asyncio.ensure_future(entry.callbacks.get())
                    call_uuid = fields.get("CallUUID") or call_uuid
                    status = fields.get("CallStatus", "")
                    if status == RINGING:
                        observer.wire_event(WireEvent(kind=WireEventKind.RINGING, at_ms=at_ms()))
                    elif status == IN_PROGRESS:
                        observer.wire_event(WireEvent(kind=WireEventKind.ANSWERED, at_ms=at_ms()))
                        deadline = loop.time() + STREAM_GRACE_S
                    elif not entry.socket.done():
                        return ended_early(status, fields.get("HangupCause"))
                    continue
                if entry.socket.done():
                    return Connected(entry.socket.result(), request_uuid, call_uuid)
                await self._end(request_uuid, call_uuid)
                if stopped.done():
                    return unreached(EndReason.USER_REQUEST, None)
                return unreached(EndReason.ERROR, silence(call_uuid))
        finally:
            stopped.cancel()
            report.cancel()
            await asyncio.gather(stopped, report, return_exceptions=True)

    async def _end(self, request_uuid: str, call_uuid: str | None) -> None:
        try:
            if call_uuid is None:
                await self._api.cancel_request(request_uuid)
            else:
                await self._api.hang_up(call_uuid)
        except PlivoError as error:
            log.warning("could not end the call attempt: %s", error)


def unreached(end_reason: EndReason, error: str | None) -> CallOutcome:
    return CallOutcome(connected=False, end_reason=end_reason, caller_error=error)


def silence(call_uuid: str | None) -> str:
    if call_uuid is None:
        return "Plivo reported nothing about the call; is TRUMAN_PUBLIC_URL reachable from Plivo?"
    return "the agent answered but its audio stream never reached the worker"


def ended_early(status: str, cause: str | None) -> CallOutcome:
    detail = (f"{status} ({cause})" if cause else status) or "no status"
    if status in UNANSWERED:
        return unreached(EndReason.NO_ANSWER, f"the agent did not answer: {detail}")
    if status == "completed":
        return unreached(EndReason.AGENT_HANGUP, "the agent hung up before the stream started")
    return unreached(EndReason.ERROR, f"the call ended before its stream started: {detail}")
