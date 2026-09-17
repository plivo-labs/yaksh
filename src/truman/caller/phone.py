"""The phone caller: dial the agent through Plivo, then talk over the stream Plivo opens."""

import asyncio
import base64
import json
import logging
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import audioop
from fastapi import WebSocket, WebSocketDisconnect
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
)
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from truman.caller.audio import GAP_BYTES, SAMPLE_RATE, SPEECH_PEAK, Clock, Playout, Stamper
from truman.caller.persona import CallState, Persona, converse, provider_keys
from truman.caller.plivo_api import OutboundCall, PlivoApi, PlivoError
from truman.caller.plivo_server import CALLBACK_RETRIES, PendingStream, StreamRegistry
from truman.caller.transcript import TranscriptBuilder, WireTap
from truman.config import Settings
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
ACK_GRACE_S = 0.2
HANGUP_TIMEOUT_S = 2.0
CHUNK_BYTES = SAMPLE_RATE * 2 // 5
LINEAR = "audio/x-l16"
MULAW = "audio/x-mulaw"


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
            hangup_url=f"{self._base}/callbacks/{conversation_id}?{CALLBACK_RETRIES}",
            ring_url=f"{self._base}/callbacks/{conversation_id}?{CALLBACK_RETRIES}",
            ring_timeout_s=self._ring_timeout_s,
            time_limit_s=request.max_duration_s + TIME_LIMIT_MARGIN_S,
        )
        try:
            request_uuid = await self._api.create_call(call)
        except PlivoError as error:
            return unreached(EndReason.ERROR, str(error))
        call_uuid: str | None = None
        ringing = False
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
                        if not ringing:
                            ringing = True
                            observer.wire_event(
                                WireEvent(kind=WireEventKind.RINGING, at_ms=at_ms())
                            )
                    elif status == IN_PROGRESS:
                        observer.wire_event(WireEvent(kind=WireEventKind.ANSWERED, at_ms=at_ms()))
                        deadline = loop.time() + STREAM_GRACE_S
                    elif not entry.socket.done():
                        return ended_early(status, fields.get("HangupCause"), call_uuid)
                    continue
                if entry.socket.done():
                    return Connected(entry.socket.result(), request_uuid, call_uuid)
                await self._end(request_uuid, call_uuid)
                if stopped.done():
                    return unreached(EndReason.USER_REQUEST, None, call_uuid)
                return unreached(EndReason.ERROR, silence(call_uuid), call_uuid)
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


def unreached(
    end_reason: EndReason, error: str | None, call_uuid: str | None = None
) -> CallOutcome:
    return CallOutcome(
        connected=False, end_reason=end_reason, caller_error=error, call_uuid=call_uuid
    )


def silence(call_uuid: str | None) -> str:
    if call_uuid is None:
        return "Plivo reported nothing about the call; is TRUMAN_PUBLIC_URL reachable from Plivo?"
    return "the agent answered but its audio stream never reached the worker"


def ended_early(status: str, cause: str | None, call_uuid: str | None) -> CallOutcome:
    detail = (f"{status} ({cause})" if cause else status) or "no status"
    if status in UNANSWERED:
        return unreached(EndReason.NO_ANSWER, f"the agent did not answer: {detail}", call_uuid)
    if status == "completed":
        return unreached(
            EndReason.AGENT_HANGUP, "the agent hung up before the stream started", call_uuid
        )
    return unreached(
        EndReason.ERROR, f"the call ended before its stream started: {detail}", call_uuid
    )


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
        self._pending: dict[str, Playout] = {}

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
        self._pending[name] = playout
        await self.push_frame(
            OutputTransportMessageFrame(
                {"event": "checkpoint", "streamId": self._stream_id, "name": name}
            )
        )

    def played(self, name: str) -> None:
        playout = self._pending.pop(name, None)
        if playout is None:
            return
        playout.sent = max(playout.sent, int(name.rsplit(":", 1)[1]))
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
    ) -> None:
        super().__init__()
        self._stream_id = stream_id
        self._linear = encoding.split(";")[0].strip() == LINEAR
        self._clock = clock
        self._observer = observer
        self._checkpoints = checkpoints
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
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(message, dict):
            return None
        match message.get("event"):
            case "media":
                payload = (message.get("media") or {}).get("payload")
                if not payload:
                    return None
                raw = base64.b64decode(payload)
                pcm = raw if self._linear else audioop.ulaw2lin(raw, 2)
                self._heard(pcm)
                return InputAudioRawFrame(audio=pcm, sample_rate=SAMPLE_RATE, num_channels=1)
            case "playedStream":
                self._event(WireEventKind.CHECKPOINT)
                self._checkpoints.played(str(message.get("name")))
            case "stop":
                self._event(WireEventKind.STOP)
                self.stopped.set()
            case "playFailed":
                self._event(WireEventKind.CALLER_ERROR)
                log.warning("plivo could not play audio: %s", message.get("reason"))
            case "error":
                self._event(WireEventKind.CALLER_ERROR)
                self.failure = self.failure or f"plivo reported an error: {message.get('reason')}"
                self.failed.set()
        return None

    def _heard(self, pcm: bytes) -> None:
        """The first packet with speech after a quiet stretch is the agent starting to talk."""
        if audioop.max(pcm, 2) > SPEECH_PEAK:
            if self._quiet >= GAP_BYTES:
                self._event(WireEventKind.AGENT_AUDIO)
            self._quiet = 0
        else:
            self._quiet += len(pcm)

    def _event(self, kind: WireEventKind) -> None:
        self._observer.wire_event(WireEvent(kind=kind, at_ms=self._clock.ms()))


class SpeechMarks(FrameProcessor):
    """After the transport output: when the persona's audio starts and stops going out."""

    def __init__(self, clock: Clock, observer: CallObserver) -> None:
        super().__init__(enable_direct_mode=True)
        self._clock = clock
        self._observer = observer

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.DOWNSTREAM:
            if isinstance(frame, BotStartedSpeakingFrame):
                self._mark(WireEventKind.CALLER_SPEECH_START)
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self._mark(WireEventKind.CALLER_SPEECH_END)
        await self.push_frame(frame, direction)

    def _mark(self, kind: WireEventKind) -> None:
        self._observer.wire_event(WireEvent(kind=kind, at_ms=self._clock.ms()))


class Recorder(AudioBufferProcessor):
    """Both sides of the call as a stereo 8 kHz WAV: the agent left, the caller right."""

    def __init__(self, path: Path) -> None:
        super().__init__(sample_rate=SAMPLE_RATE, num_channels=2, auto_start_recording=True)
        self.path: Path | None = None
        self._target = path
        self._audio = bytearray()

        @self.event_handler("on_audio_data")
        async def on_audio(_processor: Any, audio: bytes, _rate: int, _channels: int) -> None:
            self._audio += audio

    async def cleanup(self) -> None:
        await super().cleanup()
        if self._audio:
            await asyncio.to_thread(self._write)
            self.path = self._target

    def _write(self) -> None:
        self._target.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(self._target), "wb") as recording:
            recording.setnchannels(2)
            recording.setsampwidth(2)
            recording.setframerate(SAMPLE_RATE)
            recording.writeframes(bytes(self._audio))


async def settled() -> None:
    """Reports for audio that played just before a cut are still in flight; give them a moment."""
    await asyncio.sleep(ACK_GRACE_S)


async def handshake(socket: WebSocket) -> tuple[str, str, str]:
    """Plivo opens a stream with its start event: the stream and call ids and the encoding."""
    message = json.loads(await socket.receive_text())
    if message.get("event") != "start":
        raise ValueError(
            f"the stream did not open with a Plivo start event: {message.get('event')}"
        )
    start = message["start"]
    encoding = str((start.get("mediaFormat") or {}).get("encoding") or MULAW)
    return str(start["streamId"]), str(start["callId"]), encoding


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

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        clock = Clock()
        observer.wire_event(WireEvent(kind=WireEventKind.CONNECT_STARTED, at_ms=clock.ms()))
        entry = self._registry.expect(request.conversation_id)
        try:
            dialed = await self._dialer.dial(request, entry, observer, clock.ms, stop)
            if isinstance(dialed, CallOutcome):
                return dialed
            return await self._talk(request, observer, stop, clock, dialed)
        finally:
            self._registry.forget(request.conversation_id)

    async def _talk(
        self,
        request: CallRequest,
        observer: CallObserver,
        stop: asyncio.Event,
        clock: Clock,
        dialed: Connected,
    ) -> CallOutcome:
        socket = dialed.socket
        try:
            stream_id, call_id, encoding = await handshake(socket)
        except (WebSocketDisconnect, ValueError, KeyError) as error:
            log.warning("stream for conversation %s: %r", request.conversation_id, error)
            return unreached(
                EndReason.ERROR, f"the stream ended before it started: {error}", dialed.call_uuid
            )
        log.info(
            "stream %s for conversation %s, call %s, %s",
            stream_id,
            request.conversation_id,
            call_id,
            encoding,
        )
        transcript = TranscriptBuilder(clock, observer)
        checkpoints = Checkpoints(stream_id, transcript)
        serializer = StreamSerializer(stream_id, encoding, clock, observer, checkpoints)
        transport = FastAPIWebsocketTransport(
            socket,
            FastAPIWebsocketParams(
                serializer=serializer,
                add_wav_header=False,
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=SAMPLE_RATE,
                audio_out_sample_rate=SAMPLE_RATE,
                audio_out_10ms_chunks=2,
                audio_out_end_silence_secs=0,
            ),
        )
        state = CallState()
        recorder = Recorder(request.output_dir / "recording.wav")
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
            after_output=[SpeechMarks(clock, observer), WireTap(transcript, settled), recorder],
            state=state,
        )

        @transport.event_handler("on_client_connected")
        async def on_connected(_transport: Any, _socket: Any) -> None:
            state.connected = True
            observer.wire_event(WireEvent(kind=WireEventKind.CONNECTED, at_ms=clock.ms()))
            if not request.agent.agent_speaks_first:
                await persona.speak_first()

        @transport.event_handler("on_client_disconnected")
        async def on_disconnected(_transport: Any, _socket: Any) -> None:
            state.end(EndReason.AGENT_HANGUP)

        greeting = None
        if request.agent.agent_speaks_first:
            greeting = asyncio.create_task(persona.greet_if_silent())
        try:
            await converse(
                persona,
                state,
                stop,
                {serializer.stopped: EndReason.AGENT_HANGUP, serializer.failed: EndReason.ERROR},
            )
        finally:
            if greeting is not None:
                greeting.cancel()
            await self._hang_up(call_id)
        state.error = state.error or serializer.failure
        return CallOutcome(
            connected=state.connected,
            end_reason=state.end_reason or EndReason.ERROR,
            caller_error=state.error,
            recording_path=recorder.path,
            call_uuid=call_id,
        )

    async def _hang_up(self, call_id: str) -> None:
        try:
            await asyncio.wait_for(self._api.hang_up(call_id), HANGUP_TIMEOUT_S)
        except (PlivoError, TimeoutError) as error:
            log.warning("could not hang up call %s: %r", call_id, error)
