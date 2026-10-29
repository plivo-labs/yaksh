"""The phone caller: dial the agent through Plivo, then talk over the stream Plivo opens."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from functools import partial
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from yaksh.caller.audio import Clock
from yaksh.caller.conversation import (
    Connected,
    Conversation,
    Conversations,
    ConversationStart,
    LocalConversations,
    Seat,
)
from yaksh.caller.pipeline import CallState, caller_keys
from yaksh.caller.plivo_server import (
    CALLBACK_RETRIES,
    TIME_LIMIT_MARGIN_S,
    PendingStream,
    StreamRegistry,
)
from yaksh.caller.prepared import Prepared, spoken
from yaksh.caller.turn_models import TurnModels
from yaksh.config import Settings
from yaksh.domain.conversations import (
    CallObserver,
    CallOutcome,
    CallRequest,
    EndReason,
    LineFacts,
    WireEvent,
    WireEventKind,
)
from yaksh.domain.triggers import RenderError, render
from yaksh.integrations.plivo import OutboundCall, PlivoApi, PlivoError
from yaksh.integrations.trigger import TriggerOutcome, TriggerResult, send_trigger

log = logging.getLogger(__name__)

CALLBACK_GRACE_S = 15.0
STREAM_GRACE_S = 10.0
ACCEPT_GRACE_S = 2.0
"""Past the dial deadline, Plivo's report of a call accepted just in time may still be on its
way; no new call is accepted then."""
RINGING = "ringing"
IN_PROGRESS = "in-progress"
UNANSWERED = frozenset({"no-answer", "timeout", "busy"})
HANGUP_EVENT = "Hangup"
CALLED_SIDE = "Callee"
CALLING_SIDE = "Caller"
HANGUP_REPORT_WAIT_S = 2.0
HANGUP_TIMEOUT_S = 2.0
CALL_NEVER_COMES = frozenset({TriggerResult.REJECTED, TriggerResult.NOT_SENT})


class Dialer:
    """Rings the agent from the leased number and hands over the stream once Plivo opens it.

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
        assert request.caller_number is not None
        conversation_id = request.conversation_id
        call = OutboundCall(
            from_number=request.caller_number,
            to_number=request.agent.agent_number,
            answer_url=f"{self._base}/answer/{conversation_id}",
            hangup_url=f"{self._base}/callbacks/{conversation_id}#{CALLBACK_RETRIES}",
            ring_url=f"{self._base}/callbacks/{conversation_id}#{CALLBACK_RETRIES}",
            ring_timeout_s=self._ring_timeout_s,
            time_limit_s=request.max_duration_s + TIME_LIMIT_MARGIN_S,
        )
        try:
            request_uuid = await self._api.create_call(call)
        except PlivoError as error:
            return unreached(EndReason.ERROR, str(error))
        call_uuid: str | None = None
        ringing = False
        answered = False
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
                if entry.socket.done():
                    await give_back(report, entry.callbacks)
                    return await self._open(entry.socket.result(), request_uuid, call_uuid)
                if report.done():
                    fields = report.result()
                    report = asyncio.ensure_future(entry.callbacks.get())
                    call_uuid = fields.get("CallUUID") or call_uuid
                    status = fields.get("CallStatus", "")
                    if status == RINGING:
                        if not ringing:
                            ringing = True
                            observer.wire_event(
                                WireEvent(kind=WireEventKind.RINGING, at_ms=at_ms())
                            )
                    elif status == IN_PROGRESS:
                        answered = True
                        observer.wire_event(WireEvent(kind=WireEventKind.ANSWERED, at_ms=at_ms()))
                        deadline = loop.time() + STREAM_GRACE_S
                    elif status:
                        return ended_early(fields, call_uuid)
                    continue
                await self._end(request_uuid, call_uuid)
                if stopped.done():
                    return unreached(EndReason.USER_REQUEST, None, call_uuid)
                return unreached(EndReason.ERROR, no_signal_reason(call_uuid, answered), call_uuid)
        finally:
            stopped.cancel()
            report.cancel()
            await asyncio.gather(stopped, report, return_exceptions=True)

    async def _open(
        self, socket: WebSocket, request_uuid: str, call_uuid: str | None
    ) -> Connected | CallOutcome:
        try:
            stream_id, call_id, encoding = await handshake(socket)
        except (WebSocketDisconnect, ValueError) as error:
            await self._end(request_uuid, call_uuid)
            return unreached(
                EndReason.ERROR, f"the stream ended before it started: {error}", call_uuid
            )
        return Connected(socket, stream_id, call_id, encoding)

    async def _end(self, request_uuid: str, call_uuid: str | None) -> None:
        try:
            if call_uuid is None:
                await self._api.cancel_request(request_uuid)
            else:
                await self._api.hang_up(call_uuid)
        except PlivoError as error:
            log.warning("could not end the call attempt: %s", error)


def unreached(
    end_reason: EndReason, error: str | None, call_uuid: str | None = None
) -> CallOutcome:
    return CallOutcome(
        connected=False, end_reason=end_reason, caller_error=error, call_uuid=call_uuid
    )


def no_signal_reason(call_uuid: str | None, answered: bool) -> str:
    if call_uuid is None:
        return "Plivo reported nothing about the call; is YAKSH_PUBLIC_URL reachable from Plivo?"
    if not answered:
        return "the agent's phone rang, and Plivo reported no answer and no hang-up"
    return "the agent answered but its audio stream never reached the worker"


def ended_early(report: Mapping[str, str], call_uuid: str | None) -> CallOutcome:
    status = report.get("CallStatus", "")
    cause = report.get("HangupCause")
    detail = (f"{status} ({cause})" if cause else status) or "no status"
    if status in UNANSWERED:
        return unreached(EndReason.NO_ANSWER, f"the agent did not answer: {detail}", call_uuid)
    reason, error = ended_by(report, CALLED_SIDE)
    if reason is EndReason.AGENT_HANGUP:
        return unreached(reason, "the agent hung up before the stream started", call_uuid)
    return unreached(
        EndReason.ERROR,
        error or f"the call ended before its stream started: {detail}",
        call_uuid,
    )


def ended_by(report: Mapping[str, str] | None, agent_side: str) -> tuple[EndReason, str | None]:
    """Who ended the call, by Plivo's hangup report. The agent is the called side when Yaksh
    dials and the calling side when an outbound agent calls Yaksh; without a hangup source
    nobody knows which side it was."""
    source = (report or {}).get("HangupSource")
    if report is None or source is None:
        return EndReason.STREAM_ENDED, None
    if source == agent_side:
        return EndReason.AGENT_HANGUP, None
    cause = report.get("HangupCauseName") or report.get("HangupCause") or "no cause given"
    return EndReason.ERROR, f"Plivo reports hangup source {source}: {cause}"


async def hangup_report(
    callbacks: asyncio.Queue[dict[str, str]], timeout_s: float
) -> dict[str, str] | None:
    """Plivo's hangup report for the call, or None when it does not come in time."""
    try:
        async with asyncio.timeout(timeout_s):
            while (report := await callbacks.get()).get("Event") != HANGUP_EVENT:
                pass
    except TimeoutError:
        return None
    return report


def resolve_stream_end(state: CallState, report: Mapping[str, str] | None, agent_side: str) -> None:
    """A stream that stopped on its own is named by Plivo's hangup report; without one the
    call cannot count as clean, since nobody knows which side ended it."""
    if state.end_reason is not EndReason.STREAM_ENDED:
        return
    reason, error = ended_by(report, agent_side)
    state.end_reason = reason
    if reason is EndReason.STREAM_ENDED:
        error = "the stream ended and Plivo did not say which side ended the call"
    state.blame(error)


def line_facts(report: Mapping[str, str]) -> LineFacts:
    def number(name: str) -> int | None:
        value = report.get(name)
        return int(value) if value and value.isdigit() else None

    return LineFacts(
        hangup_source=report.get("HangupSource"),
        hangup_cause=report.get("HangupCauseName") or report.get("HangupCause"),
        duration_s=number("Duration"),
        bill_duration_s=number("BillDuration"),
        answer_time=report.get("AnswerTime"),
        end_time=report.get("EndTime"),
    )


class Line:
    """The phone leg of a connected call. It is hung up once, as soon as the conversation is
    over, and its one hangup report is read after that."""

    def __init__(
        self,
        call_uuid: str,
        callbacks: asyncio.Queue[dict[str, str]],
        hang_up: Callable[[str], Awaitable[None]],
    ) -> None:
        self._call_uuid = call_uuid
        self._callbacks = callbacks
        self._hang_up = hang_up
        self._hanging_up: asyncio.Future[None] | None = None

    async def hang_up(self) -> None:
        """The request runs on a task of its own: a caller cancelled while it waits does not
        cancel the hang-up, and the next call waits for the same request."""
        if self._hanging_up is None:
            self._hanging_up = asyncio.ensure_future(self._hang_up(self._call_uuid))
        await asyncio.shield(self._hanging_up)

    async def end(self, wait_s: float) -> dict[str, str] | None:
        """Hang up, then wait up to wait_s for Plivo's hangup report; a report that already
        came is taken at once. None when it does not come in time."""
        await self.hang_up()
        return await hangup_report(self._callbacks, wait_s)


async def give_back(report: asyncio.Future[dict[str, str]], callbacks: asyncio.Queue) -> None:
    """Stop waiting for the next report; one that already arrived goes back for the call."""
    report.cancel()
    await asyncio.gather(report, return_exceptions=True)
    if not report.cancelled():
        callbacks.put_nowait(report.result())


class Receiver:
    """Waits for the call an outbound agent places to the leased number, and hands over its
    stream. The trigger that makes the agent call runs beside the wait: the call may arrive
    before the trigger's response, and a trigger that fails after the call arrived does not
    end it.
    """

    async def receive(
        self,
        request: CallRequest,
        entry: PendingStream,
        observer: CallObserver,
        at_ms: Callable[[], int],
        stop: asyncio.Event,
        trigger: asyncio.Future[TriggerOutcome],
    ) -> Connected | CallOutcome:
        if request.accept_calls_until is None:
            return unreached(EndReason.ERROR, "the outbound conversation has no dial deadline")
        observer.wire_event(WireEvent(kind=WireEventKind.WAITING_FOR_CALL, at_ms=at_ms()))
        loop = asyncio.get_running_loop()
        left_s = (request.accept_calls_until - datetime.now(UTC)).total_seconds()
        deadline = loop.time() + left_s + ACCEPT_GRACE_S
        accepted: str | None = None
        triggered: TriggerOutcome | None = None
        stopped = asyncio.ensure_future(stop.wait())
        report = asyncio.ensure_future(entry.callbacks.get())
        try:
            while True:
                waits: set[asyncio.Future[Any]] = {entry.socket, stopped, report}
                if triggered is None:
                    waits.add(trigger)
                await asyncio.wait(
                    waits,
                    timeout=max(deadline - loop.time(), 0),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if report.done():
                    fields = report.result()
                    report = asyncio.ensure_future(entry.callbacks.get())
                    if fields.get("Event") == HANGUP_EVENT:
                        return ended_early_incoming(fields, accepted)
                    accepted = fields.get("CallUUID") or accepted
                    observer.wire_event(WireEvent(kind=WireEventKind.ANSWERED, at_ms=at_ms()))
                    deadline = loop.time() + STREAM_GRACE_S
                    continue
                if entry.socket.done():
                    await give_back(report, entry.callbacks)
                    return await accept_stream(entry.socket.result(), accepted)
                if triggered is None and trigger.done():
                    triggered = trigger.result()
                    if accepted is None and triggered.result in CALL_NEVER_COMES:
                        return unreached(EndReason.TRIGGER_FAILED, triggered.detail)
                    continue
                if stopped.done():
                    return unreached(EndReason.USER_REQUEST, None, accepted)
                if accepted is not None:
                    return unreached(
                        EndReason.ERROR,
                        "the call was answered but its stream never opened",
                        accepted,
                    )
                detail = f"no call reached {request.caller_number} within the dial window"
                if triggered is not None:
                    detail += f"; trigger result: {triggered.detail}"
                return unreached(EndReason.NO_CALL, detail)
        finally:
            stopped.cancel()
            report.cancel()
            await asyncio.gather(stopped, report, return_exceptions=True)


def delivered_body(trigger: asyncio.Future[TriggerOutcome] | None) -> str | None:
    """The response body of a trigger that was delivered. The call can come before the
    response, and the response can still be on its way when the call ends."""
    if trigger is None or not trigger.done() or trigger.cancelled() or trigger.exception():
        return None
    outcome = trigger.result()
    return outcome.body if outcome.result is TriggerResult.DELIVERED else None


def ended_early_incoming(report: Mapping[str, str], call_uuid: str | None) -> CallOutcome:
    reason, error = ended_by(report, CALLING_SIDE)
    if reason is EndReason.AGENT_HANGUP:
        return unreached(reason, "the agent hung up before the stream started", call_uuid)
    return unreached(
        EndReason.ERROR, error or "the call ended before its stream started", call_uuid
    )


async def accept_stream(socket: WebSocket, call_uuid: str | None) -> Connected | CallOutcome:
    """Open the stream of the accepted call; a stream for any other call is refused."""
    try:
        stream_id, call_id, encoding = await handshake(socket)
    except (WebSocketDisconnect, ValueError) as error:
        return unreached(EndReason.ERROR, f"the stream ended before it started: {error}", call_uuid)
    if call_id != call_uuid:
        return unreached(
            EndReason.ERROR,
            f"the stream belongs to call {call_id}, not the accepted call",
            call_uuid,
        )
    return Connected(socket, stream_id, call_id, encoding)


async def handshake(socket: WebSocket) -> tuple[str, str, str]:
    """Plivo opens a stream with its start event: the stream and call ids and the encoding."""
    try:
        message = json.loads(await asyncio.wait_for(socket.receive_text(), STREAM_GRACE_S))
    except TimeoutError as error:
        raise ValueError(f"no Plivo start event within {STREAM_GRACE_S:g}s") from error
    if message.get("event") != "start":
        raise ValueError(
            f"the stream did not open with a Plivo start event: {message.get('event')}"
        )
    try:
        start = message["start"]
        return str(start["streamId"]), str(start["callId"]), str(start["mediaFormat"]["encoding"])
    except (KeyError, TypeError) as error:
        raise ValueError(f"the Plivo start event is incomplete: {message}") from error


class PhoneCaller:
    """Dials the agent and talks over the stream Plivo opens. A stream that dies without a close
    frame ends with the conversation's duration limit. Each conversation runs where
    `conversations` holds it: by default in this process, with turn models loaded once."""

    def __init__(
        self,
        settings: Settings,
        registry: StreamRegistry,
        plivo_api: Callable[[str, str], PlivoApi] = PlivoApi,
        conversations: Conversations | None = None,
    ) -> None:
        """plivo_api makes the Plivo client from the Auth ID and Auth token of a call's
        settings."""
        if settings.public_url is None:
            raise ValueError("phone calls need YAKSH_PUBLIC_URL, the address Plivo can reach")
        self._settings = settings
        self._public_url = settings.public_url
        self._registry = registry
        self._plivo_api = plivo_api
        self._receiver = Receiver()
        self._conversations = conversations or LocalConversations(
            TurnModels(), str(settings.database_url)
        )

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        """The Plivo account and provider keys come from the settings the call started with."""
        credentials = request.app_settings.plivo_credentials
        if credentials is None:
            return unreached(
                EndReason.ERROR, "phone calls are off: add the Plivo Auth ID and Auth token"
            )
        try:
            keys = caller_keys(request.app_settings, request.voice.provider)
        except ValueError as error:
            return unreached(EndReason.ERROR, str(error))
        api = self._plivo_api(*credentials)
        hang_up = partial(self._hang_up, api)
        prepared = Prepared(request)
        prepared.make(partial(spoken, keys.tts, request))
        clock = Clock()
        observer.wire_event(WireEvent(kind=WireEventKind.CONNECT_STARTED, at_ms=clock.ms()))
        entry = self._registry.expect(request.conversation_id)
        trigger: asyncio.Future[TriggerOutcome] | None = None
        seat: Seat | None = None
        try:
            seat = self._conversations.reserve()
            if request.agent.outbound is None:
                dialer = Dialer(api, self._public_url, request.app_settings.phone.ring_timeout_s)
                dialed = await dialer.dial(request, entry, observer, clock.ms, stop)
            else:
                trigger = asyncio.ensure_future(self._send_trigger(request, observer, clock))
                dialed = await self._receiver.receive(
                    request, entry, observer, clock.ms, stop, trigger
                )
                if isinstance(dialed, CallOutcome) and dialed.call_uuid is not None:
                    await hang_up(dialed.call_uuid)
            if isinstance(dialed, CallOutcome):
                return dialed
            start = ConversationStart(
                request, keys, observer, stop, clock, dialed, prepared, clock.ms()
            )
            outcome = await talk(start, seat, Line(dialed.call_uuid, entry.callbacks, hang_up))
            return outcome.model_copy(
                update={
                    "trigger_response": delivered_body(trigger),
                    "clock_started_at": clock.started_at,
                }
            )
        finally:
            try:
                await prepared.close()
                self._registry.forget(request.conversation_id)
                if trigger is not None:
                    trigger.cancel()
                    await asyncio.gather(trigger, return_exceptions=True)
            finally:
                if seat is not None:
                    await seat.release()

    async def _send_trigger(
        self, request: CallRequest, observer: CallObserver, clock: Clock
    ) -> TriggerOutcome:
        """Send the outbound agent's trigger once and record its result on the wire."""
        assert request.agent.outbound is not None and request.caller_number is not None
        try:
            rendered = render(
                request.agent.outbound.trigger,
                number=request.caller_number,
                conversation_id=str(request.conversation_id),
                agent_data=request.agent_data,
                secrets={
                    name: value.get_secret_value()
                    for name, value in request.app_settings.secrets.triggers.items()
                },
            )
        except RenderError as error:
            outcome = TriggerOutcome(TriggerResult.NOT_SENT, str(error))
        else:
            key = request.app_settings.secrets.trigger_signing_key
            outcome = await send_trigger(
                rendered,
                str(request.conversation_id),
                signing_key=key.get_secret_value() if key else None,
                allow_private=self._settings.allow_private_hosts,
            )
        observer.wire_event(
            WireEvent(kind=WireEventKind.TRIGGER_SENT, at_ms=clock.ms(), detail=outcome.detail)
        )
        return outcome

    @staticmethod
    async def _hang_up(api: PlivoApi, call_id: str) -> None:
        try:
            await asyncio.wait_for(api.hang_up(call_id), HANGUP_TIMEOUT_S)
        except (PlivoError, TimeoutError) as error:
            log.warning("could not hang up call %s: %r", call_id, error)


async def talk(start: ConversationStart, seat: Seat, line: Line) -> CallOutcome:
    """Hold the conversation in its seat and make the call's outcome from what it left. The line
    hangs up once the conversation is over, and in every other case on the way out; the
    conversation is closed after that, even when the hang-up is cancelled."""
    connected_ms = start.connected_ms
    start.observer.wire_event(WireEvent(kind=WireEventKind.CONNECTED, at_ms=connected_ms))
    conversation: Conversation | None = None
    try:
        conversation = await seat.start(start)
        try:
            ended = await conversation.ended()
        except asyncio.CancelledError:
            # A stopped worker still keeps what the call recorded: the conversation ends as
            # worker_stopped and leaves its result.
            conversation.cancel()
            ended = await conversation.ended()
        if ended.started_ms < connected_ms:
            start.observer.wire_event(
                WireEvent(kind=WireEventKind.CONNECTED, at_ms=ended.started_ms)
            )
        # The line hangs up now; its report comes while the call's audio is built. A stopped call
        # has a deadline to finish, so it takes the report only if it already came.
        ending = asyncio.ensure_future(line.end(0 if start.stop.is_set() else HANGUP_REPORT_WAIT_S))
        try:
            heard = await conversation.heard()
            report = await ending
        finally:
            ending.cancel()
    finally:
        try:
            await line.hang_up()
        finally:
            if conversation is not None:
                await conversation.close()
    state = CallState(
        end_reason=heard.end_reason, error=heard.error, caller_reason=heard.caller_reason
    )
    agent_side = CALLED_SIDE if start.request.agent.outbound is None else CALLING_SIDE
    resolve_stream_end(state, report, agent_side)
    state.blame(heard.serializer_failure)
    return CallOutcome(
        connected=True,
        end_reason=state.end_reason or EndReason.ERROR,
        caller_error=state.error,
        caller_reason=state.caller_reason,
        talk_ms=ended.at_ms - ended.started_ms,
        recording=heard.recording,
        stream_opened_ms=connected_ms,
        recording_start_ms=ended.started_ms,
        agent_media=heard.agent_media,
        caller_replies=heard.caller_replies,
        caller_voice=heard.caller_voice,
        caller_settings=heard.caller_settings,
        caller_usage=heard.caller_usage,
        caller_reply_times=heard.caller_reply_times,
        line_facts=line_facts(report) if report else None,
        loop_lag=heard.loop_lag,
        call_uuid=start.dialed.call_uuid,
    )
