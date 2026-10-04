"""The pipeline that plays a persona over a transport: its ears, brain and voice, the
transcript taps, and how a call ends."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    FunctionCallResultProperties,
    LLMContextFrame,
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
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.responses.llm import OpenAIResponsesHttpLLMService
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from truman.caller.audio import SAMPLE_RATE, Clock
from truman.caller.transcript import (
    AgentTurnTap,
    GeneratedTap,
    TranscriptBuilder,
    last_user_message,
)
from truman.config import Settings
from truman.diagnostics import describe_exception
from truman.domain.conversations import (
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
DRAINED = frozenset({EndReason.CALLER_HANGUP, EndReason.TURN_LIMIT})
"""The ends the caller chooses: Truman closes the call before it hangs up."""
CLOSING_QUIET_S = 8.0
"""How long both sides stay silent, after the caller ends the call, before Truman hangs up."""
CLOSING_LIMIT_S = 30.0
"""The longest a close lasts, for a reply that Plivo never reports played."""
QUIET_POLL_S = 0.25
VAD = VADParams(confidence=0.5, start_secs=0.1, stop_secs=0.6)
IDLE_S = 15.0
IDLE_NUDGES = 2
# Deepgram language per agent language: Truman hears the agent in the language the agent
# speaks. Hinglish uses the Hindi model, which also transcribes the English words in it.
DEEPGRAM_LANGUAGES: dict[Language, str] = {
    Language.EN: "en",
    Language.HINGLISH: "hi",
}

END_CALL = FunctionSchema(
    name="end_call",
    description=(
        "End the call. Call it only when the agent's latest turn shows that your goal is "
        "achieved; never in a normal turn."
    ),
    properties={
        "reason": {
            "type": "string",
            "description": "One sentence on why you are ending the call, naming only what was "
            "said in it.",
        },
    },
    required=["reason"],
)
SILENT_END = (
    "The call did not end, because you said nothing. Answer the agent's latest turn aloud. To "
    "end the call, say a short goodbye in the same reply that calls end_call."
)


def provider_keys(settings: Settings) -> dict[str, str]:
    keys = {
        "DEEPGRAM_API_KEY": settings.deepgram_api_key,
        "ELEVENLABS_API_KEY": settings.elevenlabs_api_key,
        "OPENAI_API_KEY": settings.openai_api_key,
    }
    missing = [name for name, value in keys.items() if value is None]
    if missing:
        raise ValueError(f"the caller needs {', '.join(missing)}")
    return {name: value.get_secret_value() for name, value in keys.items() if value}


def llm_service(
    settings: Settings, keys: dict[str, str], instructions: str
) -> OpenAIResponsesHttpLLMService:
    """The persona's model over the Responses API. With no effort configured, Pipecat asks a
    reasoning model that accepts it for effort none, for the fastest first word; other models
    get no effort. A reply calls at most one tool, so it can end the call only once."""
    effort = settings.persona_llm_reasoning_effort
    return OpenAIResponsesHttpLLMService(
        api_key=keys["OPENAI_API_KEY"],
        base_url=settings.openai_base_url,
        settings=OpenAIResponsesHttpLLMService.Settings(
            model=settings.persona_llm_model,
            system_instruction=instructions,
            reasoning=OpenAIResponsesHttpLLMService.ReasoningConfig(effort=effort)
            if effort
            else None,
            extra={"parallel_tool_calls": False},
        ),
    )


@dataclass
class CallState:
    """How the call stands; the first end reason and the first error win."""

    end_reason: EndReason | None = None
    error: str | None = None
    caller_reason: str | None = None
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
    """A quiet agent gets a nudge; silence through every nudge ends the call. A call that is
    ending gets no nudge."""
    silence = Silence(IDLE_NUDGES)

    @user.event_handler("on_user_turn_started")
    async def on_agent_turn(_aggregator: Any, _strategy: Any) -> None:
        silence.heard()

    @user.event_handler("on_user_turn_idle")
    async def on_idle(_aggregator: Any) -> None:
        if state.end_reason is not None:
            return
        if silence.give_up():
            state.end(EndReason.AGENT_SILENT)
            return
        await nudge()


class TurnLimit(FrameProcessor):
    """Between the agent's turns and the persona model: the model answers at most `turns` agent
    turns. At the next one, `at_limit` runs instead, once. A run of the model that answers no
    agent turn, such as the caller's opening, does not count."""

    def __init__(self, turns: int, at_limit: Callable[[], Awaitable[None]]) -> None:
        super().__init__()
        self._left = turns
        self._at_limit = at_limit
        self._reached = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and direction is FrameDirection.DOWNSTREAM:
            answers = not frame.speculation and last_user_message(frame.context) is not None
            if self._left == 0:
                if answers and not self._reached:
                    self._reached = True
                    await self._at_limit()
                return
            if answers:
                self._left -= 1
        await self.push_frame(frame, direction)


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
            base_url=settings.deepgram_base_url,
            sample_rate=SAMPLE_RATE,
            settings=DeepgramSTTService.Settings(
                model=settings.deepgram_model, language=DEEPGRAM_LANGUAGES[request.agent.language]
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
                language=elevenlabs.LANGUAGE_PINS[request.caller_language],
            ),
        )

        async def goodbye() -> None:
            await self.say(request.goodbye)
            state.end(EndReason.TURN_LIMIT)

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
                TurnLimit(request.max_turns, goodbye),
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

        retried_silent_end = False

        async def end_call(params: FunctionCallParams) -> None:
            """A reply that ends the call without a word would leave the agent's last turn
            unanswered: the model gets one more reply to speak in, and after that Truman says
            the goodbye itself. The handler runs on its own task, when a later reply can have
            started, so the generated tap notes the words when the tool calls start."""
            nonlocal retried_silent_end
            reason = str(params.arguments.get("reason") or "")
            silent = not transcript.called_after_words(params.tool_call_id)
            if silent and not retried_silent_end and state.end_reason is None:
                retried_silent_end = True
                log.info(
                    "caller tried to end conversation %s without a word: %s",
                    request.conversation_id,
                    reason,
                )
                await params.result_callback(
                    {"status": SILENT_END}, properties=FunctionCallResultProperties(run_llm=True)
                )
                return
            log.info("caller ended conversation %s: %s", request.conversation_id, reason)
            await params.result_callback(
                {"status": "call ended"}, properties=FunctionCallResultProperties(run_llm=False)
            )
            if silent and state.end_reason is None:
                await self.say(request.goodbye)
            if state.end_reason is None:
                state.caller_reason = reason
            state.end(EndReason.CALLER_HANGUP)

        self.llm.register_function(END_CALL.name, end_call, cancel_on_interruption=False)
        self._transcript = transcript
        self._observer = observer
        self._clock = clock

        async def nudge() -> None:
            await self.say(request.nudge)

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

    async def say(self, text: str) -> None:
        """Speak fixed text for the caller, such as the idle nudge, without the model."""
        self._transcript.scripted(text)
        await self.worker.queue_frame(TTSSpeakFrame(text))

    def quiet(self) -> bool:
        return self._transcript.quiet

    async def greet_if_silent(self) -> None:
        """An agent that should speak first but says nothing gets a hello, as a caller would."""
        await asyncio.sleep(IDLE_S)
        if not self._transcript.agent_spoke and not self._transcript.agent_speaking:
            self._observer.wire_event(
                WireEvent(kind=WireEventKind.SILENCE_GREETING, at_ms=self._clock.ms())
            )
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
    fires with its end reason; close a call that the caller ended, then hang up and note
    anything that broke."""
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(persona.worker)
    running = asyncio.create_task(runner.run())
    wake = wake or {}
    ended = asyncio.ensure_future(state.ended.wait())
    interrupts = [asyncio.ensure_future(event.wait()) for event in (stop, *wake)]
    try:
        await asyncio.wait({ended, *interrupts, running}, return_when=asyncio.FIRST_COMPLETED)
        if state.end_reason in DRAINED:
            await close(persona.quiet, [*interrupts, running])
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
        for waiter in (ended, *interrupts):
            waiter.cancel()
        await hang_up(state, persona.worker, running)
    broken = persona.unusable()
    if broken:
        state.blame(f"{', '.join(broken)} stopped working")


async def close(quiet: Callable[[], bool], interrupts: Iterable[asyncio.Future[Any]]) -> None:
    """The caller ended the call: keep the line open, so its last words play and the agent can
    answer, until both sides have been quiet for CLOSING_QUIET_S, an interrupt fires (a stop, the
    stream ending, the pipeline stopping), or CLOSING_LIMIT_S passes."""
    silence = asyncio.ensure_future(until_quiet(quiet))
    try:
        await asyncio.wait(
            {silence, *interrupts}, timeout=CLOSING_LIMIT_S, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        silence.cancel()
        await asyncio.gather(silence, return_exceptions=True)


async def until_quiet(quiet: Callable[[], bool]) -> None:
    """Return once `quiet` has held for CLOSING_QUIET_S without a break."""
    loop = asyncio.get_running_loop()
    since: float | None = None
    while True:
        if not quiet():
            since = None
        elif since is None:
            since = loop.time()
        elif loop.time() - since >= CLOSING_QUIET_S:
            return
        await asyncio.sleep(QUIET_POLL_S)


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
