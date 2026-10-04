"""The phone caller: dial the agent through Plivo, then talk over the stream Plivo opens."""

import asyncio
import base64
import json
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import audioop
from fastapi import WebSocket, WebSocketDisconnect
from pipecat.audio.mixers.soundfile_mixer import SoundfileMixer
from pipecat.frames.frames import (
    AudioRawFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from truman.caller.audio import (
    GAP_BYTES,
    LOUD_PEAK,
    PLAYOUT,
    SAMPLE_RATE,
    CallerReply,
    CallRecording,
    Clock,
    Playout,
    Stamper,
    save_caller_voice,
)
from truman.caller.lag import LagSampler
from truman.caller.latency import Detector
from truman.caller.pipeline import (
    CallState,
    Persona,
    converse,
    provider_keys,
)
from truman.caller.plivo_server import (
    CALLBACK_RETRIES,
    TIME_LIMIT_MARGIN_S,
    PendingStream,
    StreamRegistry,
)
from truman.caller.transcript import TranscriptBuilder, WireTap
from truman.config import Settings
from truman.domain.background_noise import NoiseMix
from truman.domain.conversations import (
    CallObserver,
    CallOutcome,
    CallRequest,
    EndReason,
    LineFacts,
    WireEvent,
    WireEventKind,
)
from truman.domain.triggers import RenderError, render
from truman.integrations.plivo import OutboundCall, PlivoApi, PlivoError
from truman.integrations.trigger import TriggerOutcome, TriggerResult, send_trigger

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
ACK_GRACE_S = 0.2
HANGUP_TIMEOUT_S = 2.0
CHUNK_BYTES = SAMPLE_RATE * 2 // 2
CALL_NEVER_COMES = frozenset({TriggerResult.REJECTED, TriggerResult.NOT_SENT})
LINEAR = "audio/x-l16"
MULAW = "audio/x-mulaw"


@dataclass
class Connected:
    socket: WebSocket
    stream_id: str
    call_uuid: str
    encoding: str


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
        return "Plivo reported nothing about the call; is TRUMAN_PUBLIC_URL reachable from Plivo?"
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
    """Who ended the call, by Plivo's hangup report. The agent is the called side when Truman
    dials and the calling side when an outbound agent calls Truman; without a hangup source
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


@dataclass(frozen=True)
class Spoken:
    """What a finished conversation leaves for the work after it."""

    state: CallState
    persona: Persona
    recording: CallRecording
    marks: AudioMarks
    serializer: StreamSerializer


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


class Checkpoints(FrameProcessor):
    """Before the transport output: stamps each reply's playout and, after every chunk of its
    audio, asks Plivo to report once the audio queued so far has played; each report moves the
    reply's sent mark, so provenance follows what the agent has actually heard."""

    def __init__(self, stream_id: str, transcript: TranscriptBuilder) -> None:
        super().__init__(enable_direct_mode=True)
        self._stream_id = stream_id
        self._transcript = transcript
        self._stamper = Stamper()
        self._reply = 0
        self._pending: dict[str, tuple[Playout, int]] = {}

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is not FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, TTSStartedFrame):
            self._reply += 1
            self._pending.clear()
        if isinstance(frame, TTSAudioRawFrame):
            for piece in pieces(frame):
                self._stamper.stamp(piece, self.get_clock().get_time())
                await self.push_frame(piece, direction)
                await self._mark()
            return
        self._stamper.stamp(frame, self.get_clock().get_time())
        await self.push_frame(frame, direction)
        if isinstance(frame, TTSStoppedFrame):
            await self._mark()

    async def _mark(self) -> None:
        playout = self._stamper.arriving
        if playout is None or playout.arrived == 0:
            return
        name = f"{self._reply}:{playout.arrived}"
        if name in self._pending:
            return
        self._pending[name] = (playout, playout.arrived)
        await self.push_frame(
            OutputTransportMessageFrame(
                {"event": "checkpoint", "streamId": self._stream_id, "name": name}
            )
        )

    def played(self, name: str) -> None:
        pending = self._pending.pop(name, None)
        if pending is None:
            return
        playout, through = pending
        playout.played(through)
        self._transcript.audio_progressed()


def pieces(frame: TTSAudioRawFrame) -> list[TTSAudioRawFrame]:
    """A reply's audio in slices short enough for a checkpoint after each."""
    if len(frame.audio) <= CHUNK_BYTES:
        return [frame]
    return [
        TTSAudioRawFrame(
            audio=frame.audio[start : start + CHUNK_BYTES],
            sample_rate=frame.sample_rate,
            num_channels=frame.num_channels,
            context_id=frame.context_id,
        )
        for start in range(0, len(frame.audio), CHUNK_BYTES)
    ]


def plivo_ms(timestamp: Any) -> int | None:
    """Plivo's media timestamp: Unix milliseconds, sent as a string."""
    try:
        return int(timestamp)
    except TypeError, ValueError:
        return None


class StreamSerializer(FrameSerializer):
    """Plivo's stream protocol in the encoding the stream opened with, plus the reports Truman
    listens for."""

    def __init__(
        self,
        stream_id: str,
        encoding: str,
        clock: Clock,
        observer: CallObserver,
        checkpoints: Checkpoints,
        recording: CallRecording,
    ) -> None:
        super().__init__()
        self._stream_id = stream_id
        self._linear = encoding.split(";")[0].strip() == LINEAR
        self._clock = clock
        self._observer = observer
        self._checkpoints = checkpoints
        self._recording = recording
        self._quiet = GAP_BYTES
        self.stopped = asyncio.Event()
        self.failed = asyncio.Event()
        self.failure: str | None = None

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            self._event(WireEventKind.CLEAR_AUDIO)
            return json.dumps({"event": "clearAudio", "streamId": self._stream_id})
        if isinstance(frame, AudioRawFrame):
            if not frame.audio:
                return None
            self._recording.caller(frame.audio, self._clock.ms())
            audio = frame.audio if self._linear else audioop.lin2ulaw(frame.audio, 2)
            media = {
                "contentType": LINEAR if self._linear else MULAW,
                "sampleRate": SAMPLE_RATE,
                "payload": base64.b64encode(audio).decode(),
            }
            return json.dumps({"event": "playAudio", "media": media})
        if isinstance(frame, OutputTransportMessageFrame | OutputTransportMessageUrgentFrame):
            return None if self.should_ignore_frame(frame) else json.dumps(frame.message)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            message = json.loads(data)
        except json.JSONDecodeError, TypeError:
            return None
        if not isinstance(message, dict):
            return None
        match message.get("event"):
            case "media":
                media = message.get("media") or {}
                payload = media.get("payload")
                if not payload:
                    return None
                raw = base64.b64decode(payload)
                pcm = raw if self._linear else audioop.ulaw2lin(raw, 2)
                self._heard(pcm)
                self._recording.agent(pcm, self._clock.ms(), plivo_ms(media.get("timestamp")))
                return InputAudioRawFrame(audio=pcm, sample_rate=SAMPLE_RATE, num_channels=1)
            case "playedStream":
                self._checkpoints.played(str(message.get("name")))
            case "stop":
                self._event(WireEventKind.STOP)
                self.stopped.set()
            case "playFailed" if not self.stopped.is_set():
                self._event(WireEventKind.CALLER_ERROR)
                log.warning("plivo could not play audio: %s", message.get("reason"))
                self.failure = (
                    self.failure or f"plivo could not play audio: {message.get('reason')}"
                )
            case "error":
                self._event(WireEventKind.CALLER_ERROR)
                fatal = f"plivo reported an error: {message.get('reason')}"
                self.failure = (
                    fatal if self.failure is None else f"{fatal}; before it, {self.failure}"
                )
                self.failed.set()
        return None

    def _heard(self, pcm: bytes) -> None:
        """The first packet louder than LOUD_PEAK after a quiet stretch: sound from the agent's
        side started, which may be speech, music, a beep or line noise."""
        if audioop.max(pcm, 2) > LOUD_PEAK:
            if self._quiet >= GAP_BYTES:
                self._event(WireEventKind.AGENT_AUDIO)
            self._quiet = 0
        else:
            self._quiet += len(pcm)

    def _event(self, kind: WireEventKind) -> None:
        self._observer.wire_event(WireEvent(kind=kind, at_ms=self._clock.ms()))


class AudioMarks(FrameProcessor):
    """After the transport output: when the persona's audio starts and stops going out. It
    keeps each reply with its playout, which its spoken words carry. A reply that the TTS
    finished stops when the output handles its TTSStoppedFrame, which then follows the stop at
    once. A reply that the call or a barge-in cut off has no such frame."""

    def __init__(self, clock: Clock, observer: CallObserver) -> None:
        super().__init__(enable_direct_mode=True)
        self._clock = clock
        self._observer = observer
        self._just_stopped = False
        self.replies: list[CallerReply] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.DOWNSTREAM:
            just_stopped, self._just_stopped = self._just_stopped, False
            if isinstance(frame, BotStartedSpeakingFrame):
                self.replies.append(CallerReply(self._mark(WireEventKind.CALLER_AUDIO_START)))
            elif isinstance(frame, BotStoppedSpeakingFrame):
                ended = self._mark(WireEventKind.CALLER_AUDIO_END)
                if self.replies and self.replies[-1].end_ms is None:
                    self.replies[-1].end_ms = ended
                    self._just_stopped = True
            elif isinstance(frame, TTSTextFrame) and self.replies and not self.replies[-1].playout:
                self.replies[-1].playout = frame.metadata.get(PLAYOUT)
            elif isinstance(frame, TTSStoppedFrame) and just_stopped:
                self.replies[-1].playout = frame.metadata.get(PLAYOUT)
                self.replies[-1].finished = True
        await self.push_frame(frame, direction)

    def _mark(self, kind: WireEventKind) -> int:
        at = self._clock.ms()
        self._observer.wire_event(WireEvent(kind=kind, at_ms=at))
        return at


def mixer(noise: NoiseMix | None) -> SoundfileMixer | None:
    """The background noise, looped under the caller's voice and through its pauses."""
    if noise is None:
        return None
    return SoundfileMixer(
        sound_files={"noise": str(noise.path)}, default_sound="noise", volume=noise.volume
    )


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


async def settled() -> None:
    """Reports for audio that played just before a cut are still in flight; give them a moment."""
    await asyncio.sleep(ACK_GRACE_S)


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
    frame ends with the conversation's duration limit."""

    def __init__(self, settings: Settings, registry: StreamRegistry, api: PlivoApi) -> None:
        if settings.public_url is None:
            raise ValueError("phone calls need TRUMAN_PUBLIC_URL, the address Plivo can reach")
        self._keys = provider_keys(settings)
        self._settings = settings
        self._registry = registry
        self._api = api
        self._dialer = Dialer(api, settings.public_url, settings.ring_timeout_s)
        self._receiver = Receiver()
        self._detector = Detector()

    def start_detector(self) -> None:
        """Start the voice detector's process now rather than at the first call's end."""
        self._detector.start()

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        clock = Clock()
        observer.wire_event(WireEvent(kind=WireEventKind.CONNECT_STARTED, at_ms=clock.ms()))
        entry = self._registry.expect(request.conversation_id)
        trigger: asyncio.Future[TriggerOutcome] | None = None
        try:
            if request.agent.outbound is None:
                dialed = await self._dialer.dial(request, entry, observer, clock.ms, stop)
            else:
                trigger = asyncio.ensure_future(self._send_trigger(request, observer, clock))
                dialed = await self._receiver.receive(
                    request, entry, observer, clock.ms, stop, trigger
                )
                if isinstance(dialed, CallOutcome) and dialed.call_uuid is not None:
                    await self._hang_up(dialed.call_uuid)
            if isinstance(dialed, CallOutcome):
                return dialed
            line = Line(dialed.call_uuid, entry.callbacks, self._hang_up)
            try:
                return await self._talk(request, observer, stop, clock, dialed, line)
            finally:
                await line.hang_up()
        finally:
            self._registry.forget(request.conversation_id)
            if trigger is not None:
                trigger.cancel()
                await asyncio.gather(trigger, return_exceptions=True)

    async def _send_trigger(
        self, request: CallRequest, observer: CallObserver, clock: Clock
    ) -> TriggerOutcome:
        """Send the outbound agent's trigger once and record its result on the wire."""
        assert request.agent.outbound is not None
        try:
            rendered = render(
                request.agent.outbound.trigger,
                number=request.caller_number,
                conversation_id=str(request.conversation_id),
                agent_data=request.agent_data,
                env=os.environ,
            )
        except RenderError as error:
            outcome = TriggerOutcome(TriggerResult.NOT_SENT, str(error))
        else:
            key = self._settings.webhook_signing_key
            outcome = await send_trigger(
                rendered,
                str(request.conversation_id),
                signing_key=key.get_secret_value() if key else None,
                allow_private=self._settings.allow_private_triggers,
            )
        observer.wire_event(
            WireEvent(kind=WireEventKind.TRIGGER_SENT, at_ms=clock.ms(), detail=outcome.detail)
        )
        return outcome

    async def _talk(
        self,
        request: CallRequest,
        observer: CallObserver,
        stop: asyncio.Event,
        clock: Clock,
        dialed: Connected,
        line: Line,
    ) -> CallOutcome:
        connected_ms = clock.ms()
        observer.wire_event(WireEvent(kind=WireEventKind.CONNECTED, at_ms=connected_ms))
        lag = LagSampler(clock.ms)
        try:
            spoken = await self._converse(request, observer, stop, clock, dialed)
        finally:
            loop_lag = lag.stop()
        ended_ms = clock.ms()
        # The line hangs up now; its report comes while the recording is saved and measured. A
        # stopped call has a deadline to finish, so it takes the report only if it already came.
        ending = asyncio.ensure_future(line.end(0 if stop.is_set() else HANGUP_REPORT_WAIT_S))
        try:
            started_ms = spoken.recording.start_ms(connected_ms)
            if started_ms < connected_ms:
                observer.wire_event(WireEvent(kind=WireEventKind.CONNECTED, at_ms=started_ms))
            talk_ms = ended_ms - started_ms
            recording_path = await asyncio.to_thread(
                spoken.recording.save, request.output_dir / "recording.wav", started_ms
            )
            caller_voice_path = request.output_dir / "caller-voice.wav"
            caller_replies = await asyncio.to_thread(
                save_caller_voice, spoken.marks.replies, caller_voice_path
            )
            measured = await self._detector.measure(
                spoken.recording.agent_track(started_ms),
                started_ms,
                connected_ms,
                spoken.marks.replies,
            )
            report = await ending
        finally:
            ending.cancel()
        agent_side = CALLED_SIDE if request.agent.outbound is None else CALLING_SIDE
        resolve_stream_end(spoken.state, report, agent_side)
        spoken.state.blame(spoken.serializer.failure)
        return CallOutcome(
            connected=True,
            end_reason=spoken.state.end_reason or EndReason.ERROR,
            caller_error=spoken.state.error,
            caller_reason=spoken.state.caller_reason,
            talk_ms=talk_ms,
            recording_path=recording_path,
            latency=measured.latency if measured else None,
            speech=measured.speech if measured else None,
            stream_opened_ms=connected_ms,
            recording_start_ms=started_ms,
            agent_media=spoken.recording.agent_media(started_ms),
            caller_replies=caller_replies,
            caller_voice_path=caller_voice_path if caller_voice_path.is_file() else None,
            caller_settings=spoken.persona.settings,
            caller_usage=spoken.persona.usage.usage(),
            line_facts=line_facts(report) if report else None,
            loop_lag=loop_lag,
            call_uuid=dialed.call_uuid,
        )

    async def _converse(
        self,
        request: CallRequest,
        observer: CallObserver,
        stop: asyncio.Event,
        clock: Clock,
        dialed: Connected,
    ) -> Spoken:
        """Build the caller around the stream and hold the conversation until it ends."""
        log.info(
            "stream %s for conversation %s, call %s, %s",
            dialed.stream_id,
            request.conversation_id,
            dialed.call_uuid,
            dialed.encoding,
        )
        transcript = TranscriptBuilder(clock, observer)
        checkpoints = Checkpoints(dialed.stream_id, transcript)
        recording = CallRecording()
        marks = AudioMarks(clock, observer)
        serializer = StreamSerializer(
            dialed.stream_id, dialed.encoding, clock, observer, checkpoints, recording
        )
        transport = FastAPIWebsocketTransport(
            dialed.socket,
            FastAPIWebsocketParams(
                serializer=serializer,
                add_wav_header=False,
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=SAMPLE_RATE,
                audio_out_sample_rate=SAMPLE_RATE,
                audio_out_10ms_chunks=2,
                audio_out_end_silence_secs=0,
                audio_out_mixer=mixer(request.background_noise),
            ),
        )
        state = CallState()
        disconnected = asyncio.Event()
        persona = Persona(
            self._settings,
            self._keys,
            request,
            clock,
            observer,
            transcript,
            transport_input=transport.input(),
            transport_output=transport.output(),
            before_output=[checkpoints],
            after_output=[marks, WireTap(transcript, settled)],
            state=state,
        )

        @transport.event_handler("on_client_connected")
        async def on_connected(_transport: Any, _socket: Any) -> None:
            if request.agent.agent_speaks_first:
                return
            if request.agent.outbound is None:
                await persona.speak_first()
            else:
                await persona.say(request.pickup)

        @transport.event_handler("on_client_disconnected")
        async def on_disconnected(_transport: Any, _socket: Any) -> None:
            disconnected.set()

        greeting = None
        if request.agent.agent_speaks_first:
            greeting = asyncio.create_task(persona.greet_if_silent())
        try:
            await converse(
                persona,
                state,
                stop,
                {
                    serializer.stopped: EndReason.STREAM_ENDED,
                    disconnected: EndReason.STREAM_ENDED,
                    serializer.failed: EndReason.ERROR,
                },
            )
        finally:
            if greeting is not None:
                greeting.cancel()
        return Spoken(state, persona, recording, marks, serializer)

    async def _hang_up(self, call_id: str) -> None:
        try:
            await asyncio.wait_for(self._api.hang_up(call_id), HANGUP_TIMEOUT_S)
        except (PlivoError, TimeoutError) as error:
            log.warning("could not hang up call %s: %r", call_id, error)
