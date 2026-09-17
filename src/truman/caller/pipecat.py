"""The websocket caller: a persona that dials the agent's Plivo stream endpoint directly."""

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    OutputAudioRawFrame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.websocket.client import (
    WebsocketClientInputTransport,
    WebsocketClientOutputTransport,
    WebsocketClientParams,
    WebsocketClientSession,
    WebsocketClientTransport,
)
from pipecat.workers.runner import WorkerRunner

from truman.caller.audio import SAMPLE_RATE, Clock, Playout
from truman.caller.persona import CallState, Persona, hang_up, note_failure, provider_keys
from truman.caller.plivo_emulator import Wire, start_message
from truman.caller.transcript import OFFSET, PLAYOUT, TranscriptBuilder, WireTap
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


def resolve_headers(headers: dict[str, str]) -> dict[str, str]:
    """Header values written as env:NAME are read from the environment at connect time."""
    resolved: dict[str, str] = {}
    for name, value in headers.items():
        if value.startswith("env:"):
            variable = value[4:]
            if variable not in os.environ:
                raise ValueError(f"header {name} needs the environment variable {variable}")
            value = os.environ[variable]
        resolved[name] = value
    return resolved


class PlivoCallerSerializer(FrameSerializer):
    """Feeds the agent's messages to the wire; the wire clock does all the sending."""

    def __init__(self, wire: Wire) -> None:
        super().__init__()
        self._wire = wire

    async def serialize(self, frame: Frame) -> str | bytes | None:
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            message = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        if isinstance(message, dict):
            self._wire.handle(message)
        return None


class CallerOutput(WebsocketClientOutputTransport):
    """Hands each audio chunk to the wire clock, which sends it in its own time.

    Each reply gets a Playout: as its frames arrive here, in order, the audio bytes are
    counted, the first chunk fixes the origin of the reply's word timestamps, and every
    word is stamped with where it starts in that audio; the wire adds what it sent.
    """

    def __init__(
        self,
        transport: BaseTransport,
        session: WebsocketClientSession,
        params: WebsocketClientParams,
        wire: Wire,
        input_transport: WebsocketClientInputTransport,
        opening: str,
    ) -> None:
        super().__init__(transport, session, params)
        self._wire = wire
        self._input = input_transport
        self._opening = opening
        self._wire_task: asyncio.Task[None] | None = None
        self._arriving: Playout | None = None
        self._playing: Playout | None = None

    async def start(self, frame: StartFrame) -> None:
        await super().start(frame)
        if self._wire_task is None:
            self._wire_task = self.create_task(
                self._wire.run(self._session.send, self._pace_in, self._opening)
            )

    async def stop(self, frame: EndFrame) -> None:
        await BaseOutputTransport.stop(self, frame)
        await self._stop_wire()
        await self._session.disconnect()

    async def cancel(self, frame: CancelFrame) -> None:
        await self._stop_wire()
        await super().cancel(frame)

    async def cleanup(self) -> None:
        await self._stop_wire()
        await super().cleanup()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, InterruptionFrame):
            self._wire.drop_outbound()
        elif isinstance(frame, TTSStartedFrame):
            self._arriving = frame.metadata[PLAYOUT] = Playout()
        elif isinstance(frame, TTSAudioRawFrame) and self._arriving is not None:
            if self._arriving.origin is None:
                self._arriving.origin = self.get_clock().get_time()
            self._arriving.arrived += len(frame.audio)
        elif isinstance(frame, TTSTextFrame) and self._arriving is not None:
            frame.metadata[PLAYOUT] = self._arriving
            frame.metadata[OFFSET] = self._arriving.offset_of(frame.pts)
            self._arriving.words += 1
        elif isinstance(frame, TTSStoppedFrame | LLMFullResponseEndFrame) and self._arriving:
            frame.metadata[PLAYOUT] = self._arriving
        await super().process_frame(frame, direction)

    async def write_transport_frame(self, frame: Frame) -> None:
        if isinstance(frame, TTSStartedFrame):
            self._playing = frame.metadata.get(PLAYOUT)

    async def write_audio_frame(self, frame: OutputAudioRawFrame) -> bool:
        if self._session.is_closing or not self._session.is_connected:
            return False
        return await self._wire.transmit(frame.audio, self._playing)

    async def _pace_in(self, pcm: bytes) -> None:
        await self._input.push_audio_frame(
            InputAudioRawFrame(audio=pcm, sample_rate=SAMPLE_RATE, num_channels=1)
        )

    async def _stop_wire(self) -> None:
        if self._wire_task is not None:
            await self.cancel_task(self._wire_task)
            self._wire_task = None


class CallerTransport(WebsocketClientTransport):
    """Opens the stream only once the pipeline runs, so the agent's first words are not
    queued behind the caller's own startup."""

    def __init__(self, uri: str, params: WebsocketClientParams, wire: Wire, opening: str) -> None:
        super().__init__(uri, params)
        self._wire = wire
        self._opening = opening

    def output(self) -> WebsocketClientOutputTransport:
        if not self._output:
            self._output = CallerOutput(
                self, self._session, self._params, self._wire, self.input(), self._opening
            )
        return self._output


class PipecatCaller:
    def __init__(self, settings: Settings) -> None:
        self._keys = provider_keys(settings)
        self._settings = settings

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        clock = Clock()
        wire = Wire(str(uuid.uuid4()), clock, observer)
        state = CallState()
        observer.wire_event(WireEvent(kind=WireEventKind.CONNECT_STARTED, at_ms=clock.ms()))
        opening = start_message(
            str(request.conversation_id),
            wire.stream_id,
            resolve_headers(request.agent.extra_headers),
        )
        transport = CallerTransport(
            str(request.agent.websocket_url),
            WebsocketClientParams(
                serializer=PlivoCallerSerializer(wire),
                add_wav_header=False,
                additional_headers=resolve_headers(request.agent.upgrade_headers) or None,
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=SAMPLE_RATE,
                audio_out_sample_rate=SAMPLE_RATE,
                audio_out_10ms_chunks=2,
                audio_out_end_silence_secs=0,
            ),
            wire,
            opening,
        )
        transcript = TranscriptBuilder(clock, observer)
        persona = Persona(
            self._settings,
            self._keys,
            request,
            clock,
            observer,
            transcript,
            transport_input=transport.input(),
            transport_output=transport.output(),
            wire_tap=WireTap(transcript, wire.settle),
            state=state,
        )

        @transport.event_handler("on_connected")
        async def on_connected(_transport: Any, _websocket: Any) -> None:
            state.connected = True
            observer.wire_event(WireEvent(kind=WireEventKind.CONNECTED, at_ms=clock.ms()))
            if not request.agent.agent_speaks_first:
                await persona.speak_first()

        @transport.event_handler("on_disconnected")
        async def on_disconnected(_transport: Any, _websocket: Any) -> None:
            if not wire.closed.is_set():
                state.end(EndReason.AGENT_HANGUP)

        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(persona.worker)
        running = asyncio.create_task(runner.run())
        signals = [
            asyncio.ensure_future(waiter)
            for waiter in (state.ended.wait(), stop.wait(), wire.hung_up.wait())
        ]
        try:
            await asyncio.wait({*signals, running}, return_when=asyncio.FIRST_COMPLETED)
            if stop.is_set():
                state.end(EndReason.USER_REQUEST)
            if wire.failed:
                state.error = state.error or wire.failed
                state.end(EndReason.ERROR)
            if wire.hung_up.is_set():
                state.end(EndReason.AGENT_HANGUP)
            if running.done():
                note_failure(running, state)
                state.error = state.error or "the pipeline stopped on its own"
                state.end(EndReason.ERROR)
        except asyncio.CancelledError:
            state.end(EndReason.PROCESS_RESTART)
        finally:
            for signal in signals:
                signal.cancel()
            await hang_up(state, persona.worker, running)
        broken = persona.unusable()
        if broken:
            state.error = state.error or f"{', '.join(broken)} stopped working"
        return outcome(state, wire, request.output_dir / "recording.wav")


def outcome(state: CallState, wire: Wire, recording: Path) -> CallOutcome:
    """The call as it ended; a wire that failed at any point, even while draining, is an error."""
    if wire.failed:
        state.error = state.error or wire.failed
        state.end_reason = EndReason.ERROR
    return CallOutcome(
        connected=state.connected,
        end_reason=state.end_reason or EndReason.ERROR,
        caller_error=state.error,
        recording_path=wire.write_recording(recording),
    )
