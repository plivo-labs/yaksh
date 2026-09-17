"""The phone caller: dial the agent through Plivo, then talk over the stream Plivo opens."""

import asyncio
import json
import logging
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pipecat.frames.frames import Frame, OutputAudioRawFrame, TTSStartedFrame
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.processors.frame_processor import FrameDirection
from pipecat.serializers.plivo import PlivoFrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketClient,
    FastAPIWebsocketOutputTransport,
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from truman.caller.audio import PLAYOUT, SAMPLE_RATE, Clock, Playout, Stamper
from truman.caller.persona import CallState, Persona, converse, provider_keys
from truman.caller.plivo_api import OutboundCall, PlivoApi, PlivoError
from truman.caller.plivo_server import PendingStream, StreamRegistry
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


class PhoneOutput(FastAPIWebsocketOutputTransport):
    """Stamps each reply's playout; until checkpoints land, audio counts as heard once written."""

    def __init__(
        self,
        transport: FastAPIWebsocketTransport,
        client: FastAPIWebsocketClient,
        params: FastAPIWebsocketParams,
        **kwargs: Any,
    ) -> None:
        super().__init__(transport, client, params, **kwargs)
        self._stamper = Stamper()
        self._playing: Playout | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        self._stamper.stamp(frame, self.get_clock().get_time())
        await super().process_frame(frame, direction)

    async def write_transport_frame(self, frame: Frame) -> None:
        if isinstance(frame, TTSStartedFrame):
            self._playing = frame.metadata.get(PLAYOUT)
        await super().write_transport_frame(frame)

    async def write_audio_frame(self, frame: OutputAudioRawFrame) -> bool:
        written = await super().write_audio_frame(frame)
        if written and self._playing is not None:
            self._playing.sent += len(frame.audio)
        return written


class PhoneTransport(FastAPIWebsocketTransport):
    def __init__(self, websocket: WebSocket, params: FastAPIWebsocketParams) -> None:
        super().__init__(websocket, params)
        self._output = PhoneOutput(self, self._client, self._params, name=self._output_name)


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


def plivo_credentials(settings: Settings) -> tuple[str, str]:
    if settings.plivo_auth_id is None or settings.plivo_auth_token is None:
        raise ValueError("phone calls need PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN")
    return settings.plivo_auth_id.get_secret_value(), settings.plivo_auth_token.get_secret_value()


async def settled() -> None:
    return None


async def handshake(socket: WebSocket) -> tuple[str, str]:
    """Plivo opens a stream with its start event; the stream and call ids are in it."""
    message = json.loads(await socket.receive_text())
    if message.get("event") != "start":
        raise ValueError(
            f"the stream did not open with a Plivo start event: {message.get('event')}"
        )
    start = message["start"]
    return str(start["streamId"]), str(start["callId"])


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
            return await self._talk(request, observer, stop, clock, dialed.socket)
        finally:
            self._registry.forget(request.conversation_id)

    async def _talk(
        self,
        request: CallRequest,
        observer: CallObserver,
        stop: asyncio.Event,
        clock: Clock,
        socket: WebSocket,
    ) -> CallOutcome:
        try:
            stream_id, call_id = await handshake(socket)
        except (WebSocketDisconnect, ValueError, KeyError) as error:
            log.warning("stream for conversation %s: %r", request.conversation_id, error)
            return unreached(EndReason.ERROR, f"the stream ended before it started: {error}")
        log.info(
            "stream %s for conversation %s, call %s", stream_id, request.conversation_id, call_id
        )
        transport = PhoneTransport(
            socket,
            FastAPIWebsocketParams(
                serializer=PlivoFrameSerializer(
                    stream_id, call_id, self._api.auth_id, self._api.auth_token
                ),
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
        transcript = TranscriptBuilder(clock, observer)
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
            after_output=[recorder, WireTap(transcript, settled)],
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

        await converse(persona, state, stop)
        return CallOutcome(
            connected=state.connected,
            end_reason=state.end_reason or EndReason.ERROR,
            caller_error=state.error,
            recording_path=recorder.path,
        )
