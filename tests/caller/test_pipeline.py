import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    LLMContextFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregator,
    LLMUserAggregatorParams,
)
from pipecat.services.llm_service import FunctionCallParams
from pipecat.tests.utils import SleepFrame, run_test
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from tests.conftest import FakeProvider, make_settings
from truman.caller import pipeline
from truman.caller.audio import Clock
from truman.caller.pipeline import (
    CallState,
    Ending,
    Persona,
    TurnLimit,
    llm_service,
    watch_silence,
)
from truman.caller.transcript import TranscriptBuilder
from truman.config import Settings
from truman.domain.conversations import CallObserver, CallRequest, EndReason, WireEvent

KEYS = ("deepgram_api_key", "elevenlabs_api_key", "openai_api_key")


def model_settings(tmp_path: Path, base: str, model: str, effort: str | None) -> Settings:
    return make_settings(
        tmp_path,
        **dict.fromkeys(KEYS, "test"),
        openai_base_url=f"{base}/v1",
        persona_llm_model=model,
        persona_llm_reasoning_effort=effort,
    )


def idle_user() -> LLMUserAggregator:
    return LLMContextAggregatorPair(
        LLMContext(),
        user_params=LLMUserAggregatorParams(
            user_idle_timeout=0.05,
            user_turn_strategies=UserTurnStrategies(
                stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.05)]
            ),
        ),
    ).user()


async def test_the_persona_gives_up_on_a_quiet_agent_only_after_two_nudges_in_one_silence() -> None:
    user = idle_user()
    state = CallState()
    nudges: list[EndReason | None] = []

    async def nudge() -> None:
        nudges.append(state.end_reason)

    watch_silence(user, state, nudge)
    quiet = [BotStoppedSpeakingFrame(), SleepFrame(0.15)]
    agent_turn = [
        VADUserStartedSpeakingFrame(),
        TranscriptionFrame("Hello.", "agent", "now"),
        VADUserStoppedSpeakingFrame(),
        SleepFrame(0.3),
    ]

    await run_test(user, frames_to_send=[*quiet, *quiet, *agent_turn, *quiet, *quiet, *quiet])

    assert nudges == [None, None, None, None]
    assert state.end_reason is EndReason.AGENT_SILENT


async def test_a_call_that_is_ending_gets_no_nudge() -> None:
    user = idle_user()
    state = CallState()
    state.end(EndReason.CALLER_HANGUP)
    nudges: list[None] = []

    async def nudge() -> None:
        nudges.append(None)

    watch_silence(user, state, nudge)

    await run_test(user, frames_to_send=[BotStoppedSpeakingFrame(), SleepFrame(0.15)])

    assert nudges == []


@pytest.mark.parametrize(
    ("model", "effort", "reasoning"),
    [
        ("gpt-6-luna", None, {"effort": "none"}),
        ("gpt-4.1", None, None),
        ("gpt-6-luna", "low", {"effort": "low"}),
    ],
    ids=["reasoning model", "gpt-4.x", "configured effort"],
)
async def test_the_persona_asks_the_responses_api_with_reasoning_off_unless_configured(
    provider: tuple[str, FakeProvider],
    tmp_path: Path,
    model: str,
    effort: str | None,
    reasoning: dict | None,
) -> None:
    base, fake = provider
    settings = model_settings(tmp_path, base, model, effort)
    llm = llm_service(settings, {"OPENAI_API_KEY": "test"}, "Be a caller.")

    await llm.run_inference(LLMContext(messages=[{"role": "user", "content": "Hello."}]))

    path, _, body = fake.requests[0]
    assert (path, body["model"], body.get("reasoning")) == ("/v1/responses", model, reasoning)


async def test_the_persona_answers_its_most_agent_turns_and_then_the_limit_takes_over() -> None:
    reached: list[str] = []

    async def at_limit() -> None:
        reached.append("goodbye")

    def after(*agent_turns: str) -> LLMContext:
        return LLMContext(messages=[{"role": "user", "content": turn} for turn in agent_turns])

    opening = LLMContextFrame(context=after())
    turns = [
        opening,
        LLMContextFrame(context=after("Hi.")),
        LLMContextFrame(context=after("Hi.", "Your name?"), speculation=True),
        LLMContextFrame(context=after("Hi.", "Your name?")),
        LLMContextFrame(context=after("Hi.", "Your name?", "Age?"), speculation=True),
        LLMContextFrame(context=after("Hi.", "Your name?", "Age?")),
        LLMContextFrame(context=after("Hi.", "Your name?", "Age?", "Hello?")),
    ]

    down, _ = await run_test(TurnLimit(2, at_limit), frames_to_send=turns)

    asked = [frame for frame in down if isinstance(frame, LLMContextFrame)]
    assert asked[0] is opening
    assert [frame.speculation for frame in asked] == [False, False, True, False]
    assert reached == ["goodbye"]


class Line:
    """A persona with a pipeline that does nothing, for driving converse()."""

    def __init__(self, *, quiet: bool) -> None:
        self.worker = PipelineWorker(Pipeline([]), idle_timeout_secs=None, enable_rtvi=False)
        self._quiet = quiet

    def quiet(self) -> bool:
        return self._quiet

    def unusable(self) -> list[str]:
        return []


async def test_a_close_ends_once_both_sides_have_been_quiet_long_enough_without_a_break(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline, "CLOSING_QUIET_S", 0.3)
    monkeypatch.setattr(pipeline, "QUIET_POLL_S", 0.01)
    loop = asyncio.get_running_loop()
    started = loop.time()
    answers = [True] * 5 + [False] * 3
    last_break = [started]

    def quiet() -> bool:
        if not answers:
            return True
        if not answers[0]:
            last_break[0] = loop.time()
        return answers.pop(0)

    await pipeline.close(quiet, [])

    ended = loop.time()
    assert not answers
    assert ended - last_break[0] >= 0.3
    assert ended - started < 5.0


async def test_a_close_that_never_gets_quiet_ends_at_its_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline, "CLOSING_LIMIT_S", 0.1)
    loop = asyncio.get_running_loop()
    started = loop.time()

    await pipeline.close(lambda: False, [])

    assert 0.1 <= loop.time() - started < 5.0


async def test_a_caller_that_ends_a_call_whose_stream_is_already_gone_does_not_hold_the_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline, "CLOSING_LIMIT_S", 10.0)
    state = CallState()
    gone = asyncio.Event()
    state.end(EndReason.CALLER_HANGUP)
    gone.set()
    loop = asyncio.get_running_loop()
    started = loop.time()

    await pipeline.converse(
        cast(Persona, Line(quiet=False)), state, asyncio.Event(), {gone: EndReason.STREAM_ENDED}
    )

    assert loop.time() - started < 5.0
    assert state.end_reason is EndReason.CALLER_HANGUP


async def test_an_agent_that_hangs_up_during_the_close_ends_it_and_the_callers_reason_stays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline, "CLOSING_LIMIT_S", 10.0)
    state = CallState()
    gone = asyncio.Event()
    state.end(EndReason.TURN_LIMIT)
    loop = asyncio.get_running_loop()
    started = loop.time()
    loop.call_later(0.2, gone.set)

    await pipeline.converse(
        cast(Persona, Line(quiet=False)), state, asyncio.Event(), {gone: EndReason.STREAM_ENDED}
    )

    assert 0.2 <= loop.time() - started < 5.0
    assert state.end_reason is EndReason.TURN_LIMIT


class Recorder:
    """The parts of a call that an Ending touches, recording what it does in order."""

    def __init__(self, *, spoke: bool) -> None:
        self.log: list[str] = []
        self.results: list[dict] = []
        self.spoke = spoke
        self.state = CallState()
        self.request = cast(CallRequest, SimpleNamespace(conversation_id="c-1", goodbye="Bye now."))

    def wire_event(self, event: WireEvent) -> None:
        self.log.append(f"{event.kind}@{event.at_ms}:{event.detail}")

    def ms(self) -> int:
        return 4200

    def called_after_words(self, _tool_call_id: str) -> bool:
        return self.spoke

    async def say(self, text: str) -> None:
        self.log.append(f"say:{text}")

    def ending(self) -> Ending:
        return Ending(
            self.request,
            self.state,
            cast(TranscriptBuilder, self),
            cast(CallObserver, self),
            cast(Clock, self),
            self.say,
        )

    def params(self, reason: str) -> FunctionCallParams:
        async def result_callback(result: dict, **_: object) -> None:
            self.results.append(result)

        return cast(
            FunctionCallParams,
            SimpleNamespace(
                arguments={"reason": reason}, tool_call_id="t-1", result_callback=result_callback
            ),
        )


async def test_the_turn_limit_goodbye_is_marked_before_the_caller_says_it() -> None:
    line = Recorder(spoke=True)

    await line.ending().goodbye()

    assert line.log == ["turn_limit@4200:None", "say:Bye now."]
    assert line.state.end_reason is EndReason.TURN_LIMIT


async def test_ending_the_call_after_speaking_is_marked_with_the_callers_reason() -> None:
    line = Recorder(spoke=True)

    await line.ending().end_call(line.params("the table is booked"))

    assert line.log == ["end_call@4200:the table is booked"]
    assert line.results == [{"status": "call ended"}]
    assert (line.state.end_reason, line.state.caller_reason) == (
        EndReason.CALLER_HANGUP,
        "the table is booked",
    )


async def test_a_silent_end_gets_one_more_reply_and_only_the_real_end_is_marked() -> None:
    line = Recorder(spoke=False)
    ending = line.ending()

    await ending.end_call(line.params("done"))
    assert line.log == [] and line.state.end_reason is None
    await ending.end_call(line.params("done"))

    assert line.results == [{"status": pipeline.SILENT_END}, {"status": "call ended"}]
    assert line.log == ["end_call@4200:done", "say:Bye now."]
    assert line.state.end_reason is EndReason.CALLER_HANGUP


async def test_a_call_that_already_ended_records_no_second_end() -> None:
    line = Recorder(spoke=True)
    line.state.end(EndReason.AGENT_HANGUP)
    ending = line.ending()

    await ending.end_call(line.params("done"))
    await ending.goodbye()

    assert line.log == ["say:Bye now."]
    assert (line.state.end_reason, line.state.caller_reason) == (EndReason.AGENT_HANGUP, None)
