import asyncio
from functools import partial
from types import SimpleNamespace
from typing import cast

import pytest
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    Frame,
    FunctionCallResultProperties,
    LLMContextFrame,
    LLMMessagesAppendFrame,
    OutputDTMFUrgentFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext, LLMContextMessage
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregator,
    LLMUserAggregatorParams,
)
from pipecat.services.llm_service import FunctionCallFromLLM, FunctionCallParams
from pipecat.tests.utils import SleepFrame, run_test
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from tests.conftest import FakeProvider, FixedClock, Observer
from yaksh.caller import pipeline
from yaksh.caller.audio import Clock
from yaksh.caller.pipeline import (
    CallerKeys,
    CallState,
    Ending,
    Keypad,
    Persona,
    TurnLimit,
    llm_service,
    wait_for_agent,
    watch_silence,
)
from yaksh.caller.transcript import TranscriptBuilder
from yaksh.domain.conversations import CallObserver, CallRequest, EndReason, Role, WireEvent
from yaksh.domain.settings import AppSettings, CallerModel, Llm


def model_settings(base: str, model: str, effort: str | None) -> AppSettings:
    return AppSettings(
        llm=Llm(base_url=f"{base}/v1"), caller=CallerModel(model=model, reasoning_effort=effort)
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
        ("gpt-6-luna", None, {"effort": "low"}),
        ("gpt-5", None, {"effort": "low"}),
        ("o3", None, {"effort": "low"}),
        ("gpt-5.2-pro", None, {"effort": "medium"}),
        ("gpt-5-pro", None, {"effort": "high"}),
        ("gpt-6-luna-2026-01-01", None, {"effort": "low"}),
        ("gpt-4.1", None, None),
        ("gpt-6-luna", "none", {"effort": "none"}),
    ],
    ids=[
        "lowest none",
        "lowest minimal",
        "lowest low",
        "lowest medium",
        "lowest high",
        "dated snapshot",
        "gpt-4.x",
        "configured effort",
    ],
)
async def test_the_persona_asks_for_low_effort_or_the_models_lowest_unless_configured(
    provider: tuple[str, FakeProvider],
    model: str,
    effort: str | None,
    reasoning: dict | None,
) -> None:
    base, fake = provider
    settings = model_settings(base, model, effort)
    keys = CallerKeys(llm="test", stt="", tts="")
    llm = llm_service(settings, settings.caller, keys, "Be a caller.")

    await llm.run_inference(LLMContext(messages=[{"role": "user", "content": "Hello."}]))

    path, _, body = fake.requests[0]
    assert (path, body["model"], body.get("reasoning")) == ("/v1/responses", model, reasoning)


async def test_an_empty_message_is_the_caller_saying_nothing_and_any_other_empty_reply_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = model_settings("http://127.0.0.1:9", "gpt-6-luna", None)
    keys = CallerKeys(llm="test", stt="", tts="")
    llm = llm_service(settings, settings.caller, keys, "Be a caller.")
    errors: list[str] = []

    async def push_error(error_msg: str, **_: object) -> None:
        errors.append(error_msg)

    monkeypatch.setattr(llm, "push_error", push_error)
    empty = {"type": "message", "content": [{"type": "output_text", "text": " "}]}
    refused = {"type": "message", "content": [{"type": "refusal", "refusal": "No."}]}

    await llm._report_empty_response("silent", [{"type": "reasoning"}, empty])
    await llm._report_empty_response("refused", [{"type": "reasoning"}, empty, refused])
    await llm._report_empty_response("thought", [{"type": "reasoning"}])

    assert [error.split()[2] for error in errors] == ["refused", "thought"]


LATER: LLMContextMessage = {"role": "user", "content": "Are you still there?"}


@pytest.mark.parametrize(("reasoning_ids", "later"), [(["rs_a", "rs_b"], [LATER]), ([], [])])
async def test_a_reply_with_no_words_leaves_none_of_its_reasoning_in_the_context(
    reasoning_ids: list[str], later: list[LLMContextMessage]
) -> None:
    settings = model_settings("http://127.0.0.1:9", "gpt-6-luna", None)
    llm = llm_service(settings, settings.caller, CallerKeys("test", "", ""), "Be a caller.")
    adapter = llm.get_llm_adapter()
    earlier = adapter.create_llm_specific_message(
        {"type": "reasoning", "id": "rs_spoke", "summary": [], "encrypted_content": "e"}
    )
    context = LLMContext(
        [
            {"role": "user", "content": "Am I speaking with Ana?"},
            earlier,
            {"role": "assistant", "content": "Yes, speaking."},
            {"role": "user", "content": "Let me pull up your file."},
        ]
    )
    empty = {"type": "message", "content": [{"type": "output_text", "text": ""}]}

    async def says_nothing() -> None:
        await asyncio.sleep(0.05)
        for item_id in reasoning_ids:
            await llm._append_reasoning_message(item_id, [], "e")
        if later:
            await llm.push_frame(LLMMessagesAppendFrame(later))
        reasoning = [{"type": "reasoning", "id": item_id} for item_id in reasoning_ids]
        await llm._report_empty_response("silent", [*reasoning, empty])

    assistant = LLMContextAggregatorPair(context).assistant()
    await asyncio.gather(
        says_nothing(), run_test(Pipeline([llm, assistant]), frames_to_send=[SleepFrame(0.3)])
    )

    assert context.get_messages() == [
        {"role": "user", "content": "Am I speaking with Ana?"},
        earlier,
        {"role": "assistant", "content": "Yes, speaking."},
        {"role": "user", "content": "Let me pull up your file."},
        *later,
    ]


async def test_a_quiet_agent_still_gets_a_nudge_after_the_caller_says_nothing() -> None:
    user = idle_user()
    state = CallState()
    nudges: list[None] = []

    async def nudge() -> None:
        nudges.append(None)

    watch_silence(user, state, nudge)
    settings = model_settings("http://127.0.0.1:9", "gpt-6-luna", None)
    llm = llm_service(settings, settings.caller, CallerKeys("test", "", ""), "Be a caller.")
    llm.on_silence = partial(wait_for_agent, user)
    empty = {"type": "message", "content": [{"type": "output_text", "text": ""}]}

    @user.event_handler("on_user_turn_stopped")
    async def says_nothing(*_: object) -> None:
        await llm._report_empty_response("silent", [empty])

    agent_turn = [
        VADUserStartedSpeakingFrame(),
        TranscriptionFrame("One moment.", "agent", "now"),
        VADUserStoppedSpeakingFrame(),
    ]
    await run_test(user, frames_to_send=[*agent_turn, SleepFrame(0.3)])

    assert nudges == [None]


async def test_a_quiet_agent_still_gets_a_nudge_after_the_caller_only_presses_keys() -> None:
    user = idle_user()
    nudges: list[None] = []

    async def nudge() -> None:
        nudges.append(None)

    watch_silence(user, CallState(), nudge)
    settings = model_settings("http://127.0.0.1:9", "gpt-6-luna", None)
    llm = llm_service(settings, settings.caller, CallerKeys("test", "", ""), "Be a caller.")
    llm.register_function(
        "press_keys", Keypad(TranscriptBuilder(FixedClock(), Observer()), user).press_keys
    )
    press = FunctionCallFromLLM(
        function_name="press_keys",
        tool_call_id="t-1",
        arguments={"keys": "1#"},
        context=LLMContext(),
    )

    async def presses() -> None:
        await asyncio.sleep(0.1)
        await llm.run_function_calls([press])

    await asyncio.gather(
        presses(), run_test(Pipeline([user, llm]), frames_to_send=[SleepFrame(0.3)])
    )

    assert nudges == [None]


async def test_the_persona_answers_its_most_agent_turns_and_then_the_limit_takes_over() -> None:
    reached: list[str] = []

    async def at_limit() -> None:
        reached.append("goodbye")

    def after(*agent_turns: str) -> LLMContext:
        return LLMContext(messages=[{"role": "user", "content": turn} for turn in agent_turns])

    turns = [
        LLMContextFrame(context=after("Hi.")),
        LLMContextFrame(context=after("Hi.", "Your name?"), speculation=True),
        LLMContextFrame(context=after("Hi.", "Your name?")),
        LLMContextFrame(context=after("Hi.", "Your name?", "Age?"), speculation=True),
        LLMContextFrame(context=after("Hi.", "Your name?", "Age?")),
        LLMContextFrame(context=after("Hi.", "Your name?", "Age?", "Hello?")),
    ]

    down, _ = await run_test(TurnLimit(2, at_limit), frames_to_send=turns)

    asked = [frame for frame in down if isinstance(frame, LLMContextFrame)]
    assert [frame.speculation for frame in asked] == [False, True, False]
    assert reached == ["goodbye"]


class Line:
    """A persona with a pipeline that does nothing, for driving converse()."""

    def __init__(self, *, quiet: bool) -> None:
        self.worker = PipelineWorker(Pipeline([]), idle_timeout_secs=None, enable_rtvi=False)
        self.llm = SimpleNamespace(refusal=None)
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


async def test_pressed_keys_go_out_as_one_dtmf_frame_and_a_keypad_turn() -> None:
    clock = FixedClock()
    clock.now = 4200
    observer = Observer()
    transcript = TranscriptBuilder(clock, observer)
    pushed: list[Frame] = []
    results: list[tuple[dict, bool | None]] = []

    async def push_frame(frame: Frame) -> None:
        pushed.append(frame)

    async def result_callback(result: dict, *, properties: FunctionCallResultProperties) -> None:
        results.append((result, properties.run_llm))

    def params(keys: str) -> FunctionCallParams:
        return cast(
            FunctionCallParams,
            SimpleNamespace(
                arguments={"keys": keys},
                tool_call_id="t-1",
                llm=SimpleNamespace(push_frame=push_frame),
                result_callback=result_callback,
            ),
        )

    keypad = Keypad(transcript, idle_user())
    await keypad.press_keys(params("4111 1111 1111 111A#"))
    await keypad.press_keys(params("4111 1111-1111 1111#"))

    [press] = pushed
    assert isinstance(press, OutputDTMFUrgentFrame) and press.to_string() == "4111111111111111#"
    assert [(t.role, t.text, t.dtmf, t.started_at_ms, t.ended_at_ms) for t in observer.turns] == [
        (Role.CALLER, "4111111111111111#", True, 4200, 4200)
    ]
    assert results == [({"status": pipeline.BAD_KEYS}, True), ({"status": "keys pressed"}, False)]
