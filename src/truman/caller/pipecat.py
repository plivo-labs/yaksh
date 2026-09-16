"""The Pipecat caller: a persona that phones the agent over a Plivo audio stream."""

import asyncio
import contextlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    FunctionCallResultProperties,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMRunFrame,
    OutputAudioRawFrame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSTextFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.services.azure.llm import AzureLLMService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.llm import OpenAILLMService
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

from truman.caller.plivo import SAMPLE_RATE, Clock, Playout, Wire, start_message
from truman.caller.transcript import (
    OFFSET,
    PLAYOUT,
    AgentTurnTap,
    GeneratedTap,
    TranscriptBuilder,
    WireTap,
)
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

END_GRACE_S = 3.0
DRAINED = frozenset({EndReason.GOAL_REACHED, EndReason.GOAL_ABANDONED})
VAD = VADParams(stop_secs=0.4)

PERSONA_INSTRUCTIONS = (
    "You are a person on a phone call with a voice assistant. Stay in character throughout; "
    "never mention being simulated, a test, or an AI.\n\n"
    "{persona}\n\n"
    "The assistant's words arrive as the user's messages. Reply with only what you would say "
    "next: one short spoken turn, in the first person, in plain sentences, with no lists, "
    "markdown or stage directions. Ask for or give one thing at a time, as a real caller "
    "would, and do not repeat what the assistant has already understood. When your goal is "
    "achieved, or it is clear the assistant cannot help, say nothing more and call end_call "
    "with whether you succeeded and why."
)

END_CALL = FunctionSchema(
    name="end_call",
    description=(
        "End the call. Call this instead of speaking once your goal is achieved "
        "or it is clear the assistant cannot help."
    ),
    properties={
        "success": {"type": "boolean", "description": "Whether you achieved your goal."},
        "reason": {"type": "string", "description": "One sentence on why you are ending the call."},
    },
    required=["success", "reason"],
)


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
    ) -> None:
        super().__init__(transport, session, params)
        self._wire = wire
        self._input = input_transport
        self._wire_task: asyncio.Task[None] | None = None
        self._arriving: Playout | None = None
        self._playing: Playout | None = None

    async def start(self, frame: StartFrame) -> None:
        await super().start(frame)
        if self._wire_task is None:
            self._wire_task = self.create_task(self._wire.run(self._session.send, self._pace_in))

    async def stop(self, frame: EndFrame) -> None:
        """Play out what is queued, hang up, then disconnect."""
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
    def __init__(self, uri: str, params: WebsocketClientParams, wire: Wire) -> None:
        super().__init__(uri, params)
        self._wire = wire

    def output(self) -> WebsocketClientOutputTransport:
        if not self._output:
            self._output = CallerOutput(self, self._session, self._params, self._wire, self.input())
        return self._output


@dataclass
class CallState:
    connected: bool = False
    end_reason: EndReason | None = None
    error: str | None = None


class Stoppable(Protocol):
    def has_finished(self) -> bool: ...

    async def stop_when_done(self) -> None: ...

    async def cancel(self) -> None: ...


class PipecatCaller:
    def __init__(self, settings: Settings) -> None:
        keys = {
            "DEEPGRAM_API_KEY": settings.deepgram_api_key,
            "ELEVENLABS_API_KEY": settings.elevenlabs_api_key,
        }
        if settings.azure_openai_endpoint:
            keys["AZURE_OPENAI_API_KEY"] = settings.azure_openai_api_key
        else:
            keys["OPENAI_API_KEY or AZURE_OPENAI_ENDPOINT"] = settings.openai_api_key
        missing = [name for name, value in keys.items() if value is None]
        if missing:
            raise ValueError(f"the pipecat caller needs {', '.join(missing)}")
        self._keys = {name: value.get_secret_value() for name, value in keys.items() if value}
        self._settings = settings

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        clock = Clock()
        wire = Wire(str(uuid.uuid4()), clock, observer)
        state = CallState()
        ended = asyncio.Event()

        def end(reason: EndReason) -> None:
            if state.end_reason is None:
                state.end_reason = reason
                ended.set()

        observer.wire_event(WireEvent(kind=WireEventKind.CONNECT_STARTED, at_ms=clock.ms()))
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
        )
        llm = self._llm()
        context = LLMContext(
            messages=[
                {
                    "role": "system",
                    "content": PERSONA_INSTRUCTIONS.format(persona=request.persona_prompt),
                }
            ],
            tools=ToolsSchema(standard_tools=[END_CALL]),
        )
        aggregators = LLMContextAggregatorPair(context)
        transcript = TranscriptBuilder(clock, observer)
        pipeline = Pipeline(
            [
                transport.input(),
                VADProcessor(vad_analyzer=SileroVADAnalyzer(sample_rate=SAMPLE_RATE, params=VAD)),
                DeepgramSTTService(
                    api_key=self._keys["DEEPGRAM_API_KEY"],
                    base_url=self._settings.deepgram_url,
                    sample_rate=SAMPLE_RATE,
                ),
                aggregators.user(),
                AgentTurnTap(transcript),
                llm,
                GeneratedTap(transcript),
                ElevenLabsTTSService(
                    api_key=self._keys["ELEVENLABS_API_KEY"],
                    sample_rate=SAMPLE_RATE,
                    settings=ElevenLabsTTSService.Settings(
                        voice=self._settings.elevenlabs_voice_id
                    ),
                ),
                transport.output(),
                WireTap(transcript, wire.settle),
                aggregators.assistant(),
            ]
        )
        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(
                audio_in_sample_rate=SAMPLE_RATE, audio_out_sample_rate=SAMPLE_RATE
            ),
            idle_timeout_secs=None,
            cancel_timeout_secs=END_GRACE_S,
            enable_rtvi=False,
        )

        async def end_call(params: FunctionCallParams) -> None:
            success = bool(params.arguments.get("success"))
            log.info(
                "persona ended conversation %s: success=%s, %s",
                request.conversation_id,
                success,
                params.arguments.get("reason"),
            )
            await params.result_callback(
                {"status": "call ended"}, properties=FunctionCallResultProperties(run_llm=False)
            )
            end(EndReason.GOAL_REACHED if success else EndReason.GOAL_ABANDONED)

        llm.register_function(END_CALL.name, end_call, cancel_on_interruption=False)

        @transport.event_handler("on_connected")
        async def on_connected(_transport: Any, websocket: Any) -> None:
            await websocket.send(
                start_message(
                    str(request.conversation_id),
                    wire.stream_id,
                    resolve_headers(request.agent.extra_headers),
                )
            )
            state.connected = True
            observer.wire_event(WireEvent(kind=WireEventKind.CONNECTED, at_ms=clock.ms()))
            if not request.agent.agent_speaks_first:
                await worker.queue_frame(LLMRunFrame())

        @transport.event_handler("on_disconnected")
        async def on_disconnected(_transport: Any, _websocket: Any) -> None:
            end(EndReason.AGENT_HANGUP)

        @worker.event_handler("on_pipeline_error")
        async def on_error(_worker: Any, frame: ErrorFrame) -> None:
            observer.wire_event(WireEvent(kind=WireEventKind.CALLER_ERROR, at_ms=clock.ms()))
            state.error = state.error or frame.error
            processor = getattr(frame, "processor", None)
            if frame.fatal or (processor is not None and not processor.is_usable):
                end(EndReason.ERROR)

        @worker.event_handler("on_setup_timeout")
        async def on_setup_timeout(_worker: Any) -> None:
            state.error = (
                state.error or "the pipeline could not be set up: a provider did not connect"
            )

        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        running = asyncio.create_task(runner.run())
        signals = [
            asyncio.ensure_future(waiter)
            for waiter in (ended.wait(), stop.wait(), wire.hung_up.wait())
        ]
        try:
            await asyncio.wait({*signals, running}, return_when=asyncio.FIRST_COMPLETED)
            if stop.is_set():
                end(EndReason.USER_REQUEST)
            if wire.failed:
                state.error = state.error or wire.failed
                end(EndReason.ERROR)
            if wire.hung_up.is_set():
                end(EndReason.AGENT_HANGUP)
            if running.done():
                note_failure(running, state)
                state.error = state.error or "the pipeline stopped on its own"
                end(EndReason.ERROR)
        except asyncio.CancelledError:
            end(EndReason.PROCESS_RESTART)
        finally:
            for signal in signals:
                signal.cancel()
            await hang_up(state, worker, running)
        return outcome(state, wire, request.output_dir / "recording.wav")

    def _llm(self) -> OpenAILLMService:
        settings = self._settings
        if settings.azure_openai_endpoint:
            return AzureLLMService(
                endpoint=settings.azure_openai_endpoint,
                api_key=self._keys["AZURE_OPENAI_API_KEY"],
                api_version=settings.azure_openai_api_version,
                settings=AzureLLMService.Settings(model=settings.persona_model),
            )
        return OpenAILLMService(
            api_key=self._keys["OPENAI_API_KEY or AZURE_OPENAI_ENDPOINT"],
            settings=OpenAILLMService.Settings(model=settings.persona_model),
        )


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


async def hang_up(state: CallState, worker: Stoppable, running: asyncio.Task[None]) -> None:
    """Let the pipeline play out after the persona hung up, cancel it otherwise, never leave it.

    Cancellation does not make this return early: an outcome handed over while the pipeline is
    alive cannot be trusted, so the wait outlives cancellation and the worker's stop deadline
    escalates to a process exit instead.
    """
    try:
        if state.end_reason in DRAINED and not worker.has_finished():
            await worker.stop_when_done()
            await asyncio.wait({running}, timeout=END_GRACE_S)
    finally:
        if not running.done():
            if not worker.has_finished():
                await until_done(asyncio.ensure_future(cancel_pipeline(worker)))
            await until_done(running)
        note_failure(running, state)


async def cancel_pipeline(worker: Stoppable) -> None:
    with contextlib.suppress(Exception):
        await worker.cancel()


async def until_done(task: asyncio.Future[Any]) -> None:
    while not task.done():
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait({task})


def note_failure(running: asyncio.Task[None], state: CallState) -> None:
    if running.cancelled() or running.exception() is None:
        return
    log.error("pipeline failed: %r", running.exception())
    state.error = state.error or repr(running.exception())
