"""The pipeline that plays a persona over a transport: its ears, brain and voice, the
transcript taps, and how a call ends."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    ErrorFrame,
    FunctionCallResultProperties,
    LLMRunFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregator,
    LLMUserAggregatorParams,
)
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.azure.llm import AzureLLMService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from truman.caller.audio import SAMPLE_RATE, Clock
from truman.caller.transcript import AgentTurnTap, GeneratedTap, TranscriptBuilder
from truman.config import Settings
from truman.diagnostics import describe_exception
from truman.domain.conversations import (
    CallerClaim,
    CallObserver,
    CallRequest,
    EndReason,
    WireEvent,
    WireEventKind,
)
from truman.domain.languages import Language
from truman.integrations import elevenlabs

log = logging.getLogger(__name__)

END_GRACE_S = 3.0
DRAINED = frozenset({EndReason.CALLER_HANGUP})
VAD = VADParams(confidence=0.5, start_secs=0.1, stop_secs=0.6)
IDLE_S = 15.0
IDLE_NUDGES = 2
# Deepgram language per persona language. Hinglish uses the Hindi model, which also
# transcribes the English words in it.
DEEPGRAM_LANGUAGES: dict[Language, str] = {
    Language.EN: "en",
    Language.HINGLISH: "hi",
}

END_CALL = FunctionSchema(
    name="end_call",
    description=(
        "End the call. Call this instead of speaking once your goal is achieved "
        "or it is clear the agent cannot help."
    ),
    properties={
        "success": {"type": "boolean", "description": "Whether you achieved your goal."},
        "reason": {"type": "string", "description": "One sentence on why you are ending the call."},
    },
    required=["success", "reason"],
)


def provider_keys(settings: Settings) -> dict[str, str]:
    keys = {
        "DEEPGRAM_API_KEY": settings.deepgram_api_key,
        "ELEVENLABS_API_KEY": settings.elevenlabs_api_key,
    }
    if settings.azure_openai_endpoint:
        keys["AZURE_OPENAI_API_KEY"] = settings.azure_openai_api_key
    else:
        keys["OPENAI_API_KEY"] = settings.openai_api_key
    missing = [name for name, value in keys.items() if value is None]
    if missing:
        raise ValueError(f"the caller needs {', '.join(missing)}")
    return {name: value.get_secret_value() for name, value in keys.items() if value}


def llm_service(settings: Settings, keys: dict[str, str], instructions: str) -> OpenAILLMService:
    if settings.azure_openai_endpoint:
        return AzureLLMService(
            endpoint=settings.azure_openai_endpoint,
            api_key=keys["AZURE_OPENAI_API_KEY"],
            api_version=settings.azure_openai_api_version,
            settings=AzureLLMService.Settings(
                model=settings.persona_model, system_instruction=instructions
            ),
        )
    return OpenAILLMService(
        api_key=keys["OPENAI_API_KEY"],
        settings=OpenAILLMService.Settings(
            model=settings.persona_model, system_instruction=instructions
        ),
    )


@dataclass
class CallState:
    """How the call stands; the first end reason and the first error win."""

    connected: bool = False
    end_reason: EndReason | None = None
    error: str | None = None
    claim: CallerClaim | None = None
    ended: asyncio.Event = field(default_factory=asyncio.Event)

    def end(self, reason: EndReason) -> None:
        if self.end_reason is None:
            self.end_reason = reason
            self.ended.set()

    def blame(self, error: str | None) -> None:
        self.error = self.error or error


class Silence:
    """How many times the persona has nudged a quiet agent in the current stretch of silence."""

    def __init__(self, nudges: int) -> None:
        self._limit = nudges
        self._nudges = 0

    def heard(self) -> None:
        self._nudges = 0

    def give_up(self) -> bool:
        self._nudges += 1
        return self._nudges > self._limit


def watch_silence(
    user: LLMUserAggregator, state: CallState, nudge: Callable[[], Awaitable[None]]
) -> None:
    """A quiet agent gets a nudge; silence through every nudge ends the call."""
    silence = Silence(IDLE_NUDGES)

    @user.event_handler("on_user_turn_started")
    async def on_agent_turn(_aggregator: Any, _strategy: Any) -> None:
        silence.heard()

    @user.event_handler("on_user_turn_idle")
    async def on_idle(_aggregator: Any) -> None:
        if silence.give_up():
            state.end(EndReason.AGENT_SILENT)
            return
        await nudge()


class Stoppable(Protocol):
    def has_finished(self) -> bool: ...

    async def stop_when_done(self) -> None: ...

    async def cancel(self) -> None: ...


class Persona:
    """One call's persona pipeline around a transport, with the transcript taps in place.

    `before_output` processors sit right before the transport output and `after_output` right
    after it, where the stamps on spoken words are complete.
    """

    def __init__(
        self,
        settings: Settings,
        keys: dict[str, str],
        request: CallRequest,
        clock: Clock,
        observer: CallObserver,
        transcript: TranscriptBuilder,
        *,
        transport_input: FrameProcessor,
        transport_output: FrameProcessor,
        after_output: Sequence[FrameProcessor],
        state: CallState,
        before_output: Sequence[FrameProcessor] = (),
    ) -> None:
        self.llm = llm_service(settings, keys, request.instructions)
        self.stt = DeepgramSTTService(
            api_key=keys["DEEPGRAM_API_KEY"],
            base_url=settings.deepgram_url,
            sample_rate=SAMPLE_RATE,
            settings=DeepgramSTTService.Settings(
                model=settings.deepgram_model, language=DEEPGRAM_LANGUAGES[request.language]
            ),
        )
        self.tts = ElevenLabsTTSService(
            api_key=keys["ELEVENLABS_API_KEY"],
            sample_rate=SAMPLE_RATE,
            settings=ElevenLabsTTSService.Settings(
                model=elevenlabs.MODEL,
                voice=request.voice.id,
                speed=request.voice.speed,
                stability=request.voice.stability,
                language=elevenlabs.LANGUAGE_PINS[request.language],
            ),
        )
        aggregators = LLMContextAggregatorPair(
            LLMContext(tools=ToolsSchema(standard_tools=[END_CALL])),
            user_params=LLMUserAggregatorParams(
                user_idle_timeout=IDLE_S,
                user_turn_strategies=UserTurnStrategies(
                    stop=[
                        TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())
                    ]
                ),
            ),
        )
        pipeline = Pipeline(
            [
                transport_input,
                VADProcessor(vad_analyzer=SileroVADAnalyzer(sample_rate=SAMPLE_RATE, params=VAD)),
                self.stt,
                aggregators.user(),
                AgentTurnTap(transcript),
                self.llm,
                GeneratedTap(transcript),
                self.tts,
                *before_output,
                transport_output,
                *after_output,
                aggregators.assistant(),
            ]
        )
        self.worker = PipelineWorker(
            pipeline,
            params=PipelineParams(
                audio_in_sample_rate=SAMPLE_RATE, audio_out_sample_rate=SAMPLE_RATE
            ),
            idle_timeout_secs=None,
            cancel_timeout_secs=END_GRACE_S,
            enable_rtvi=False,
        )

        async def end_call(params: FunctionCallParams) -> None:
            claim = CallerClaim(
                success=bool(params.arguments.get("success")),
                reason=str(params.arguments.get("reason") or ""),
            )
            log.info("caller ended conversation %s: %s", request.conversation_id, claim)
            await params.result_callback(
                {"status": "call ended"}, properties=FunctionCallResultProperties(run_llm=False)
            )
            if state.end_reason is None:
                state.claim = claim
            state.end(EndReason.CALLER_HANGUP)

        self.llm.register_function(END_CALL.name, end_call, cancel_on_interruption=False)
        self._transcript = transcript

        async def nudge() -> None:
            await self.worker.queue_frame(TTSSpeakFrame(request.nudge))

        watch_silence(aggregators.user(), state, nudge)

        @self.worker.event_handler("on_pipeline_error")
        async def on_error(_worker: Any, frame: ErrorFrame) -> None:
            observer.wire_event(WireEvent(kind=WireEventKind.CALLER_ERROR, at_ms=clock.ms()))
            state.blame(frame.error)
            processor = getattr(frame, "processor", None)
            if frame.fatal or (processor is not None and not processor.is_usable):
                state.end(EndReason.ERROR)

        @self.worker.event_handler("on_setup_timeout")
        async def on_setup_timeout(_worker: Any) -> None:
            state.blame("the pipeline could not be set up: a provider did not connect")

    async def speak_first(self) -> None:
        await self.worker.queue_frame(LLMRunFrame())

    async def greet_if_silent(self) -> None:
        """An agent that should speak first but says nothing gets a hello, as a caller would."""
        await asyncio.sleep(IDLE_S)
        if not self._transcript.agent_spoke and not self._transcript.agent_speaking:
            await self.speak_first()

    def unusable(self) -> list[str]:
        return [service.name for service in (self.stt, self.llm, self.tts) if not service.is_usable]


async def converse(
    persona: Persona,
    state: CallState,
    stop: asyncio.Event,
    wake: Mapping[asyncio.Event, EndReason] | None = None,
) -> None:
    """Run the pipeline until the call ends, a stop arrives, or a transport event in `wake`
    fires with its end reason; then hang up and note anything that broke."""
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(persona.worker)
    running = asyncio.create_task(runner.run())
    wake = wake or {}
    waiters = [asyncio.ensure_future(event.wait()) for event in (state.ended, stop, *wake)]
    try:
        await asyncio.wait({*waiters, running}, return_when=asyncio.FIRST_COMPLETED)
        if stop.is_set():
            state.end(EndReason.USER_REQUEST)
        for event, reason in wake.items():
            if event.is_set():
                state.end(reason)
        if running.done():
            note_failure(running, state)
            state.blame("the pipeline stopped on its own")
            state.end(EndReason.ERROR)
    except asyncio.CancelledError:
        state.end(EndReason.WORKER_STOPPED)
    finally:
        for waiter in waiters:
            waiter.cancel()
        await hang_up(state, persona.worker, running)
    broken = persona.unusable()
    if broken:
        state.blame(f"{', '.join(broken)} stopped working")


async def hang_up(state: CallState, worker: Stoppable, running: asyncio.Task[None]) -> None:
    """Let the pipeline play out after the persona hung up, cancel it otherwise, never leave it.

    Cancellation does not make this return early: an outcome handed over while the pipeline is
    alive cannot be trusted, so the wait outlives cancellation and the worker's stop deadline
    escalates to a process exit instead.
    """
    try:
        if state.end_reason in DRAINED and not worker.has_finished():
            await worker.stop_when_done()
            await until_done(running)
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
    error = None if running.cancelled() else running.exception()
    if error is None:
        return
    failure = describe_exception(error)
    log.error("pipeline failed: %s", failure)
    state.blame(failure)
