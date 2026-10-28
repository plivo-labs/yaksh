"""The pipeline that plays a persona over a transport: its ears, brain and voice, the
transcript taps, and how a call ends."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Protocol
from urllib.parse import urlsplit

# The OpenAI client imports about 600 modules at its first request. Import them with this module,
# at worker start, and not on the event loop of a live call.
import openai.resources.responses  # noqa: F401
from openai import APIError, AsyncStream
from openai.types.responses import ResponseStreamEvent
from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    FunctionCallResultFrame,
    FunctionCallResultProperties,
    LLMContextFrame,
    OutputDTMFUrgentFrame,
    TTSSpeakFrame,
)
from pipecat.observers.base_observer import BaseObserver
from pipecat.observers.service_metrics_observer import ServiceMetricsObserver
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
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.responses.llm import OpenAIResponsesHttpLLMService
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from yaksh.caller.audio import SAMPLE_RATE, Clock
from yaksh.caller.interruptions import Interrupter, LineGate, TurnOrder
from yaksh.caller.machines import MachineGate, SoundPlayer
from yaksh.caller.prepared import Prepared
from yaksh.caller.reply_times import ReplyTimes
from yaksh.caller.transcript import (
    AgentTurnTap,
    GeneratedTap,
    TranscriptBuilder,
)
from yaksh.caller.turn_models import TurnModels
from yaksh.caller.usage import UsageMeter
from yaksh.diagnostics import describe_exception
from yaksh.domain.conversations import (
    CallerSettings,
    CallObserver,
    CallRequest,
    EndReason,
    WireEvent,
    WireEventKind,
)
from yaksh.domain.latency import VAD_CONFIDENCE, VAD_START_S, VAD_STOP_S
from yaksh.domain.settings import AppSettings, CallerModel
from yaksh.domain.voices import VoiceProvider
from yaksh.integrations.openai_models import caller_effort, failure, retry_rate_limits
from yaksh.integrations.speech.audio import Resample8k
from yaksh.integrations.speech.stt import stt_language, stt_model, stt_service
from yaksh.integrations.speech.tts import tts_service

log = logging.getLogger(__name__)

END_GRACE_S = 3.0
DRAINED = frozenset({EndReason.CALLER_HANGUP, EndReason.TURN_LIMIT})
"""The ends the caller chooses: Yaksh closes the call before it hangs up."""
CLOSING_QUIET_S = 8.0
"""How long both sides stay silent, after the caller ends the call, before Yaksh hangs up."""
CLOSING_LIMIT_S = 30.0
"""The longest a close lasts, for a reply that Plivo never reports played."""
QUIET_POLL_S = 0.25
VAD = VADParams(confidence=VAD_CONFIDENCE, start_secs=VAD_START_S, stop_secs=VAD_STOP_S)
IDLE_S = 15.0
IDLE_NUDGES = 2

END_CALL = FunctionSchema(
    name="end_call",
    description=(
        "End the call. Use it only in a reply that is nothing but a short goodbye, and only when "
        "the agent's latest turn shows that your instructions are done, or shows the point where "
        "they tell you to end. Never use it in a reply that greets, answers a question, gives a "
        "value, agrees or asks something: then the call goes on."
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
PRESS_KEYS = FunctionSchema(
    name="press_keys",
    description=(
        "Press keys on your phone keypad. Use it only when the agent asks you to type or enter "
        "something on your phone keypad. Enter the value exactly as your facts give it, adding # "
        "when the agent says to press pound. A reply that presses keys has no spoken words."
    ),
    properties={
        "keys": {"type": "string", "description": "The keys to press in order: 0-9, * and #."},
    },
    required=["keys"],
)
BAD_KEYS = "Nothing was pressed, because a phone keypad has only the keys 0 to 9, * and #."


@dataclass(frozen=True)
class CallerKeys:
    llm: str
    stt: str
    """The key of the speech-to-text provider in use."""
    tts: str
    """The credential of the persona's voice provider."""


def caller_keys(settings: AppSettings, voice: VoiceProvider) -> CallerKeys:
    """The keys of a call with a voice of `voice`; raises ValueError naming each one that is
    not saved."""
    tts = settings.tts_credential(voice)
    missing = [*settings.missing_caller_keys, *([voice.label] if tts is None else [])]
    if missing:
        raise ValueError(f"the caller needs the {', '.join(missing)} key; add it in Settings")
    assert settings.secrets.llm_api_key and settings.stt_key and tts
    return CallerKeys(
        llm=settings.secrets.llm_api_key.get_secret_value(),
        stt=settings.stt_key.get_secret_value(),
        tts=tts,
    )


class Replayed(AsyncStream[ResponseStreamEvent]):
    """A stream whose first event was read to check it: it gives that event again, then the
    rest. It overrides each method that reads the stream; the inherited close() closes the
    response that it shares with the stream."""

    def __init__(self, first: ResponseStreamEvent, rest: AsyncStream[ResponseStreamEvent]) -> None:
        self.response = rest.response
        self._first: ResponseStreamEvent | None = first
        self._rest = rest

    async def __anext__(self) -> ResponseStreamEvent:
        if self._first is None:
            return await self._rest.__anext__()
        first, self._first = self._first, None
        return first

    async def __aiter__(self) -> AsyncIterator[ResponseStreamEvent]:
        while True:
            try:
                yield await self.__anext__()
            except StopAsyncIteration:
                return


class PersonaLLM(OpenAIResponsesHttpLLMService):
    """Asks again after a rate limit that comes before the reply's first event. The stream goes
    to Pipecat only after its first event is in, so a retry never repeats part of a reply."""

    refusal: str | None = None
    """Why the model refused the latest request, until a later request gets its first event."""
    on_silence: Callable[[], Awaitable[None]] | None = None
    """Runs when the caller's reply has no words."""

    async def _create_stream(self, params: dict) -> AsyncStream[ResponseStreamEvent]:
        return await retry_rate_limits(lambda: self._opened(params), self._refused)

    async def _opened(self, params: dict) -> AsyncStream[ResponseStreamEvent]:
        stream = await super()._create_stream(params)
        try:
            first = await anext(stream)
        except StopAsyncIteration:
            return stream
        self.refusal = None
        return Replayed(first, stream)

    def _refused(self, error: APIError) -> None:
        self.refusal = failure(error)

    async def _report_empty_response(
        self, response_id: str | None, output: list[dict], *, incremental: bool | None = None
    ) -> None:
        """A response with only empty messages is the caller saying nothing, as its prompt asks
        when the agent only asks it to wait. Any other response with no text and no tool call
        is still an error."""
        if silent(output):
            if self.on_silence is not None:
                await self.on_silence()
            return
        await super()._report_empty_response(response_id, output, incremental=incremental)


def silent(output: list[dict]) -> bool:
    """At least one message, and every item besides the reasoning is a message of empty text."""
    said = [item for item in output if item.get("type") != "reasoning"]
    return bool(said) and all(
        item.get("type") == "message"
        and all(
            part.get("type") == "output_text" and not part.get("text", "").strip()
            for part in item.get("content") or []
        )
        for item in said
    )


async def wait_for_agent(user: LLMUserAggregator) -> None:
    """Restart the agent's idle timer after a caller reply with no words. Pipecat restarts it
    when the caller stops speaking, which a reply with no words never does; Pipecat restarts it
    the same way after an agent turn with no words."""
    await user._user_idle_controller.wait_for_user()


def llm_service(
    settings: AppSettings, caller: CallerModel, keys: CallerKeys, instructions: str
) -> PersonaLLM:
    """The persona's model over the Responses API, at `caller_effort`. A reply calls at most one
    tool, so it can end the call only once."""
    effort = caller_effort(caller.model, caller.reasoning_effort)
    return PersonaLLM(
        api_key=keys.llm,
        base_url=settings.llm.base_url,
        settings=PersonaLLM.Settings(
            model=caller.model,
            system_instruction=instructions,
            reasoning=PersonaLLM.ReasoningConfig(effort=effort) if effort else None,
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

    def end(self, reason: EndReason) -> bool:
        """True when this reason is the one that ends the call."""
        if self.end_reason is not None:
            return False
        self.end_reason = reason
        self.ended.set()
        return True

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
    user: LLMUserAggregator,
    state: CallState,
    nudge: Callable[[], Awaitable[None]],
    listening: Callable[[], bool] = lambda: True,
) -> None:
    """A quiet agent gets a nudge; silence through every nudge ends the call. A call that is
    ending gets no nudge, and neither does one that a machine answers while it is not
    `listening`: the machine decides what silence does."""
    silence = Silence(IDLE_NUDGES)

    @user.event_handler("on_user_turn_started")
    async def on_agent_turn(_aggregator: Any, _strategy: Any) -> None:
        silence.heard()

    @user.event_handler("on_user_turn_idle")
    async def on_idle(_aggregator: Any) -> None:
        if state.end_reason is not None or not listening():
            return
        if silence.give_up():
            state.end(EndReason.AGENT_SILENT)
            return
        await nudge()


class TurnLimit(FrameProcessor):
    """Between the agent's turns and the persona model: the model answers at most `turns` agent
    turns. At the next one, `at_limit` runs instead, once."""

    def __init__(self, turns: int, at_limit: Callable[[], Awaitable[None]]) -> None:
        super().__init__()
        self._left = turns
        self._at_limit = at_limit
        self._reached = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and direction is FrameDirection.DOWNSTREAM:
            answers = not frame.speculation
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


class Ending:
    """How the caller ends a call: its own end_call tool, or the goodbye at the turn limit.
    Each one leaves a wire event, so the record shows who ended the call and when."""

    def __init__(
        self,
        request: CallRequest,
        state: CallState,
        transcript: TranscriptBuilder,
        observer: CallObserver,
        clock: Clock,
        say: Callable[[str], Awaitable[None]],
    ) -> None:
        self._request = request
        self._state = state
        self._transcript = transcript
        self._observer = observer
        self._clock = clock
        self._say = say
        self._retried_silent_end = False

    def _mark(self, kind: WireEventKind, detail: str | None = None) -> None:
        self._observer.wire_event(WireEvent(kind=kind, at_ms=self._clock.ms(), detail=detail))

    async def goodbye(self) -> None:
        if self._state.end(EndReason.TURN_LIMIT):
            self._mark(WireEventKind.TURN_LIMIT)
        await self._say(self._request.goodbye)

    async def end_call(self, params: FunctionCallParams) -> None:
        """A reply that ends the call without a word would leave the agent's last turn
        unanswered: the model gets one more reply to speak in, and after that Yaksh says the
        goodbye itself. The handler runs on its own task, when a later reply can have started,
        so the generated tap notes the words when the tool calls start."""
        reason = str(params.arguments.get("reason") or "")
        silent = not self._transcript.called_after_words(params.tool_call_id)
        if silent and not self._retried_silent_end and self._state.end_reason is None:
            self._retried_silent_end = True
            log.info(
                "caller tried to end conversation %s without a word: %s",
                self._request.conversation_id,
                reason,
            )
            await params.result_callback(
                {"status": SILENT_END}, properties=FunctionCallResultProperties(run_llm=True)
            )
            return
        log.info("caller ended conversation %s: %s", self._request.conversation_id, reason)
        accepted = self._state.end(EndReason.CALLER_HANGUP)
        if accepted:
            self._state.caller_reason = reason
            self._mark(WireEventKind.END_CALL, reason)
        await params.result_callback(
            {"status": "call ended"}, properties=FunctionCallResultProperties(run_llm=False)
        )
        if silent and accepted:
            await self._say(self._request.goodbye)


class Keypad:
    """The persona's phone keypad: its keys go out as one DTMF frame and into the transcript
    as a caller turn."""

    def __init__(self, transcript: TranscriptBuilder, user: LLMUserAggregator) -> None:
        self._transcript = transcript
        self._silent: set[str] = set()

        @user.event_handler("on_after_process_frame")
        async def on_frame(_user: Any, frame: Frame) -> None:
            # Pipecat keeps the idle timer off until the press's result reaches `user`, which is
            # after the handler returns, so the timer can only start again from here.
            if isinstance(frame, FunctionCallResultFrame) and frame.tool_call_id in self._silent:
                self._silent.remove(frame.tool_call_id)
                await wait_for_agent(user)

    async def press_keys(self, params: FunctionCallParams) -> None:
        """Keys that are not on a phone keypad press nothing, and the model is told why. A reply
        that only presses keys makes no sound, so the agent's idle timer starts again after it."""
        spoke = self._transcript.called_after_words(params.tool_call_id)
        keys = str(params.arguments.get("keys") or "").replace(" ", "").replace("-", "")
        try:
            press = OutputDTMFUrgentFrame.from_string(keys)
        except ValueError:
            await params.result_callback(
                {"status": BAD_KEYS}, properties=FunctionCallResultProperties(run_llm=True)
            )
            return
        await params.llm.push_frame(press)
        self._transcript.pressed(keys)
        if not spoke:
            self._silent.add(params.tool_call_id)
        await params.result_callback(
            {"status": "keys pressed"}, properties=FunctionCallResultProperties(run_llm=False)
        )


class Persona:
    """One call's persona pipeline around a transport, with the transcript taps in place.

    `before_output` processors sit right before the transport output and `after_output` right
    after it, where the stamps on spoken words are complete.
    """

    def __init__(
        self,
        keys: CallerKeys,
        request: CallRequest,
        clock: Clock,
        observer: CallObserver,
        transcript: TranscriptBuilder,
        *,
        transport_input: FrameProcessor,
        transport_output: FrameProcessor,
        after_output: Sequence[FrameProcessor],
        state: CallState,
        turn_models: TurnModels,
        prepared: Prepared,
        order: TurnOrder,
        before_output: Sequence[FrameProcessor] = (),
        observers: Sequence[BaseObserver] = (),
    ) -> None:
        """`prepared` and `order` play the scenario's interruptions: the lines' speech, and the
        observer that keeps the transcript's turns in order around a line."""
        settings = request.app_settings
        self.llm = llm_service(settings, request.caller, keys, request.instructions)
        hearer = settings.speech.stt
        hearing = stt_language(hearer, request.agent.languages, request.caller_language)
        self.settings = CallerSettings(
            llm_model=request.caller.model,
            reasoning_effort=caller_effort(request.caller.model, request.caller.reasoning_effort),
            scenario_model=request.scenario_model,
            stt_provider=hearer,
            stt_model=stt_model(settings, hearer),
            stt_language=hearing,
            tts_model=request.voice.model_in_use.id,
            voice=request.voice,
        )
        metrics = ServiceMetricsObserver()
        self.usage = UsageMeter(metrics)
        self.reply_times = ReplyTimes(
            request.conversation_id, self.settings, urlsplit(str(settings.llm.base_url)).hostname
        )
        self.stt = stt_service(settings, hearer, keys.stt, hearing)
        self.tts = tts_service(settings, request.voice, request.caller_language, keys.tts)

        self.ending = Ending(request, state, transcript, observer, clock, self.say)
        aggregators = LLMContextAggregatorPair(
            LLMContext(tools=ToolsSchema(standard_tools=[END_CALL, PRESS_KEYS])),
            user_params=LLMUserAggregatorParams(
                user_idle_timeout=IDLE_S,
                # The user here is the agent under test: a turn of line noise with no words must
                # not make the persona ask it to repeat.
                empty_user_turn=None,
                user_turn_strategies=UserTurnStrategies(
                    stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=turn_models.end_of_turn())]
                ),
            ),
        )
        user = aggregators.user()
        self.llm.on_silence = partial(wait_for_agent, user)
        self.gate = MachineGate() if request.answering else None
        """Closed while the persona's voicemail or call screener answers."""
        lines = request.interruptions
        self.player = SoundPlayer() if request.answering or lines else None
        vad = turn_models.vad(sample_rate=SAMPLE_RATE, params=VAD)
        interrupters: list[FrameProcessor] = []
        line_gates: list[FrameProcessor] = []
        if lines:
            assert self.player is not None
            line_gate = LineGate(user.context, clock, partial(wait_for_agent, user))
            interrupter = Interrupter(
                lines,
                prepared.lines,
                vad=vad,
                transcript=transcript,
                gate=line_gate,
                order=order,
                player=self.player,
                reply_times=self.reply_times,
                clock=clock,
                listening=self.listening,
                ending=lambda: state.end_reason is not None,
                words_while_speaking=settings.speech.stt.traits.words_while_speaking,
            )
            interrupters.append(interrupter)
            line_gates.append(line_gate)

            @user.event_handler("on_user_turn_stopped")
            async def on_turn_stopped(_user: Any, _strategy: Any, _message: Any) -> None:
                await line_gate.turn_ended()

        pipeline = Pipeline(
            [
                transport_input,
                VADProcessor(vad_analyzer=vad),
                self.stt,
                *interrupters,
                user,
                AgentTurnTap(transcript),
                *([self.gate] if self.gate else []),
                *line_gates,
                TurnLimit(request.max_turns, self.ending.goodbye),
                self.llm,
                GeneratedTap(transcript),
                self.tts,
                Resample8k(),
                *([self.player] if self.player else []),
                *before_output,
                transport_output,
                *after_output,
                aggregators.assistant(),
            ]
        )
        self.worker = PipelineWorker(
            pipeline,
            params=PipelineParams(
                audio_in_sample_rate=SAMPLE_RATE,
                audio_out_sample_rate=SAMPLE_RATE,
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            idle_timeout_secs=None,
            cancel_timeout_secs=END_GRACE_S,
            enable_rtvi=False,
            observers=[metrics, self.reply_times, *observers],
        )

        self.llm.register_function(END_CALL.name, self.ending.end_call)
        self.llm.register_function(
            PRESS_KEYS.name, Keypad(transcript, aggregators.user()).press_keys
        )
        self._transcript = transcript
        self._observer = observer
        self._clock = clock
        self._first_words = request.first_words

        async def nudge() -> None:
            await self.say(request.nudge)

        watch_silence(aggregators.user(), state, nudge, self.listening)

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

    def listening(self) -> bool:
        """The persona is on the line: no machine of its phone is answering."""
        return self.gate is None or not self.gate.closed

    async def speak_first(self) -> None:
        await self.say(self._first_words)

    async def say(self, text: str) -> None:
        """Speak fixed text for the caller, such as the idle nudge, without the model."""
        self._transcript.scripted(text)
        await self.worker.queue_frame(TTSSpeakFrame(text))

    def quiet(self) -> bool:
        return self._transcript.quiet

    async def greet_if_silent(self) -> None:
        """An agent that should speak first but says nothing gets the first words, as a caller
        would say hello."""
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
    if persona.llm.refusal is not None:
        state.blame(f"the caller's model refused its last request: {persona.llm.refusal}")


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
