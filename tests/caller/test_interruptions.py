import asyncio
from array import array
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import cast

import pytest
from pipecat.audio.vad.vad_analyzer import VADState
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregator,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.tests.utils import SleepFrame, run_test
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from tests.conftest import FixedClock, Observer
from yaksh.caller import interruptions
from yaksh.caller.audio import Clock, Playout
from yaksh.caller.interruptions import (
    ANSWERED,
    GO_ON,
    NOTE,
    STOP_WINDOW_S,
    STOPPED,
    AgentTurn,
    Interrupter,
    LineGate,
    PhraseMatches,
    PlayingLine,
    TurnOrder,
)
from yaksh.caller.machines import SoundPlayer
from yaksh.caller.reply_times import ReplyTimes
from yaksh.caller.transcript import AgentTurnTap, TranscriptBuilder
from yaksh.caller.turn_models import SharedSileroVAD
from yaksh.domain.conversations import (
    InterruptionTry,
    Provenance,
    Role,
    TryReason,
    Turn,
    WireEventKind,
)
from yaksh.domain.scenarios import Interruption

LINE_AUDIO = bytes(3_200) + array("h", [8000, -8000] * 800).tobytes()
"""0.2 s of silence, then 0.2 s of sound."""
WAIT = 0.05


def matches(phrase: str, *heard: tuple[str, bool]) -> list[int]:
    """The new matches after each of the words heard in one turn, given as (text, final)."""
    turn = AgentTurn(answer=1, started_ms=0, keys=0)
    phrase_matches = PhraseMatches(phrase)
    found = []
    for text, final in heard:
        turn.heard(text, final=final)
        found.append(phrase_matches.heard(turn.words(), final=final))
    return found


def test_the_partials_and_the_final_of_one_utterance_are_one_match() -> None:
    assert matches(
        "card number",
        ("I'll need your card", False),
        ("I'll need your card number", False),
        ("I'll need your card number please", False),
        ("I'll need your card number, please.", True),
    ) == [0, 1, 0, 0]


def test_the_phrase_said_again_later_in_the_turn_is_a_new_match() -> None:
    assert matches(
        "card number",
        ("I have your card number.", True),
        ("Let me read the card number back", False),
    ) == [1, 1]


def test_a_partial_that_the_final_drops_does_not_hide_a_later_real_match() -> None:
    assert matches(
        "card number",
        ("your card number now", False),
        ("Your car number.", True),
        ("And your card number please", False),
    ) == [1, 0, 1]


def test_a_final_that_first_shows_the_phrase_is_a_new_match() -> None:
    assert matches(
        "card number",
        ("I have your car number", False),
        ("I have your card number as", True),
    ) == [0, 1]


def test_a_number_at_the_end_of_the_words_waits_for_the_next_words() -> None:
    assert matches(
        "$50",
        ("the fee is fifty", False),
        ("the fee is fifty five dollars", False),
    ) == [0, 0]
    assert matches("$50", ("The fee is fifty", True), ("five dollars.", True)) == [0, 0]
    assert matches("$50", ("the fee is fifty", False), ("the fee is fifty dollars", False)) == [
        0,
        1,
    ]


class Player:
    """Plays a line at once: Plivo reports all of its audio played, or, with `hold`, once the
    test sets it."""

    def __init__(self, transcript: TranscriptBuilder) -> None:
        self.transcript = transcript
        self.played: list[tuple[int, str]] = []
        self.hold: asyncio.Event | None = None

    async def play(self, pcm: bytes, text: str, *, interruption: int) -> None:
        self.played.append((interruption, text))
        playout = Playout()
        playout.interruption = interruption
        playout.received(pcm, 0)
        playout.played(len(pcm))
        self.transcript.caller_started(playout)
        self.transcript.audio_sent()
        self.transcript.transmitted(text, len(pcm), playout, self_spaced=False, untimed=True)
        if self.hold is not None:
            await self.hold.wait()
        self.transcript.reply_ended(playout)


class Times:
    def __init__(self) -> None:
        self.lines = 0

    def line_played(self) -> None:
        self.lines += 1


class Call:
    """An Interrupter with its gate, transcript and turn order, driven as the pipeline drives
    it: the voice detector, then the turn frames, then the words."""

    def __init__(
        self,
        *lines: Interruption,
        words_while_speaking: bool = True,
        audio: list[asyncio.Future[bytes]] | None = None,
    ) -> None:
        """Each line's audio is LINE_AUDIO, made already, unless `audio` gives the futures."""
        self.clock = Clock()
        self.observer = Observer()
        self.order = TurnOrder(self.observer)
        self.transcript = TranscriptBuilder(self.clock, self.order)
        self.vad = SimpleNamespace(state=VADState.QUIET)
        self.context = LLMContext()
        self.waited_for_agent = 0
        self.gate = LineGate(self.context, self.clock, self.wait_for_agent, lambda: None)
        self.gate_out: list[Frame] = []
        self.gate.push_frame = self.pushed  # type: ignore[method-assign]
        self.player = Player(self.transcript)
        self.times = Times()
        self.listening = True
        if audio is None:
            audio = [asyncio.get_running_loop().create_future() for _ in lines]
            for item in audio:
                item.set_result(LINE_AUDIO)
        self.interrupter = Interrupter(
            lines,
            audio,
            vad=cast(SharedSileroVAD, self.vad),
            transcript=self.transcript,
            gate=self.gate,
            order=self.order,
            player=cast(SoundPlayer, self.player),
            reply_times=cast(ReplyTimes, self.times),
            clock=self.clock,
            listening=lambda: self.listening,
            ending=lambda: False,
            words_while_speaking=words_while_speaking,
        )

    async def wait_for_agent(self) -> None:
        self.waited_for_agent += 1

    async def pushed(self, frame: Frame, _direction: FrameDirection = FrameDirection.DOWNSTREAM):
        self.gate_out.append(frame)

    async def gate_sees(self, *frames: Frame) -> None:
        for frame in frames:
            await self.gate.process_frame(frame, FrameDirection.DOWNSTREAM)

    def agent_starts(self) -> None:
        self.vad.state = VADState.SPEAKING
        self.transcript.agent_voice_started(0.2)
        self.transcript.agent_started()
        self.interrupter.turn_started()

    def agent_pauses(self) -> None:
        self.vad.state = VADState.QUIET
        self.transcript.agent_voice_stopped(0.6)

    def agent_resumes(self) -> None:
        self.vad.state = VADState.SPEAKING
        self.transcript.agent_voice_started(0.2)

    def agent_says(self, text: str, *, final: bool = True) -> None:
        self.interrupter.heard(text, final=final)

    def agent_ends(self, text: str) -> None:
        self.agent_pauses()
        self.interrupter.turn_stopped()
        self.transcript.agent_stopped()
        if text:
            self.transcript.agent_said(text)

    def persona_replies(self, text: str = "Okay.") -> None:
        self.transcript.generation_started()
        self.transcript.generated(text)
        self.transcript.generation_ended()
        playout = Playout()
        playout.received(bytes(1_600), 0)
        playout.played(1_600)
        self.transcript.caller_started(playout)
        self.transcript.audio_sent()
        self.transcript.transmitted(text, 1_600, playout, self_spaced=False, untimed=True)
        self.transcript.reply_ended(playout)

    def tries(self) -> list[InterruptionTry]:
        return [
            event.interruption
            for event in self.observer.events
            if event.kind is WireEventKind.INTERRUPTION and event.interruption is not None
        ]

    def reasons(self) -> list[TryReason | None]:
        return [attempt.reason for attempt in self.tries()]


async def ends(call: Call) -> None:
    """Let the waits run out, then end the call."""
    await asyncio.sleep(WAIT * 3)
    await call.interrupter.call_ended()


async def test_a_phrase_plays_the_line_where_the_agent_still_speaks_and_not_where_it_stopped() -> (
    None
):
    call = Call(Interruption(say="Wait.", agent_says="card number", after_s=WAIT))

    call.agent_starts()
    call.agent_says("I'll need your card number.")
    call.agent_pauses()
    await asyncio.sleep(WAIT * 2)
    call.agent_ends("I'll need your card number.")
    call.persona_replies()
    call.agent_starts()
    call.agent_says("I have your card number as ending in", final=False)
    await asyncio.sleep(WAIT * 2)
    call.agent_says("Your card number is saved.")
    await ends(call)

    assert call.player.played == [(1, "Wait.")]
    assert call.reasons() == [TryReason.AGENT_QUIET, None]
    assert [attempt.answer for attempt in call.tries()] == [1, 2]


async def test_a_second_match_in_the_same_turn_is_a_new_start() -> None:
    call = Call(Interruption(say="Wait.", agent_says="card number", after_s=WAIT))

    call.agent_starts()
    call.agent_says("I have your card number.")
    call.agent_pauses()
    await asyncio.sleep(WAIT * 2)
    call.agent_resumes()
    call.agent_says("The card number ends in", final=False)
    await ends(call)

    assert call.reasons() == [TryReason.AGENT_QUIET, None]


async def test_a_wait_that_outlives_its_turn_is_used_up_and_the_next_turn_needs_a_new_match() -> (
    None
):
    call = Call(Interruption(say="Wait.", agent_says="card number", after_s=WAIT * 2))

    call.agent_starts()
    call.agent_says("I'll need your card number.")
    call.agent_ends("I'll need your card number.")
    call.agent_starts()
    await ends(call)

    assert call.reasons() == [TryReason.TURN_ENDED]
    assert call.player.played == []


async def test_a_time_trigger_counts_answers_so_a_split_greeting_stays_skipped() -> None:
    call = Call(Interruption(say="Wait.", after_s=WAIT))

    call.agent_starts()
    call.agent_ends("Hi, thanks for calling.")
    call.agent_starts()
    await asyncio.sleep(WAIT * 2)
    call.agent_ends("This call may be recorded.")
    call.persona_replies()
    call.agent_starts()
    await ends(call)

    assert call.player.played == [(1, "Wait.")]
    assert [(attempt.answer, attempt.reason) for attempt in call.tries()] == [(2, None)]


async def test_a_time_wait_that_ends_in_a_pause_plays_at_the_next_speech_of_the_turn() -> None:
    call = Call(Interruption(say="Wait.", after_s=WAIT, from_answer=1))

    call.agent_starts()
    call.agent_pauses()
    await asyncio.sleep(WAIT * 2)
    assert call.player.played == []
    call.agent_resumes()
    await ends(call)

    assert call.player.played == [(1, "Wait.")]
    assert call.reasons() == [None]


async def test_a_waiting_time_start_is_used_up_when_its_turn_ends() -> None:
    call = Call(Interruption(say="Wait.", after_s=WAIT, from_answer=1))

    call.agent_starts()
    call.agent_pauses()
    await asyncio.sleep(WAIT * 2)
    call.agent_ends("Sure.")
    call.agent_starts()
    await ends(call)

    assert call.player.played == []
    assert call.reasons() == [TryReason.AGENT_QUIET]


async def test_a_line_starts_no_answer() -> None:
    call = Call(
        Interruption(say="Wait.", after_s=WAIT, from_answer=1),
        Interruption(say="Hold on.", after_s=WAIT, from_answer=2),
    )

    call.agent_starts()
    await asyncio.sleep(WAIT * 2)
    call.agent_ends("We open at nine, and the first visit includes a full exam.")
    await asyncio.sleep(0.6)
    call.agent_starts()
    await ends(call)

    assert call.player.played == [(1, "Wait.")]
    assert {attempt.answer for attempt in call.tries()} == {1}


async def test_a_time_line_and_a_phrase_line_in_one_turn_take_turns() -> None:
    call = Call(
        Interruption(say="Hold on.", after_s=WAIT * 10, from_answer=1),
        Interruption(say="Wait.", agent_says="card number", after_s=0),
    )

    call.agent_starts()
    call.agent_says("Your card number", final=False)
    await asyncio.sleep(WAIT * 12)
    await ends(call)

    assert call.player.played == [(2, "Wait.")]
    assert sorted((attempt.number, attempt.reason) for attempt in call.tries()) == [
        (1, TryReason.OTHER_LINE),
        (2, None),
    ]


async def test_two_waits_that_end_together_play_only_the_first_line() -> None:
    call = Call(
        Interruption(say="Wait.", agent_says="fee", after_s=WAIT),
        Interruption(say="Hold on.", agent_says="fee", after_s=WAIT),
    )

    call.agent_starts()
    call.agent_says("The fee is", final=False)
    await ends(call)

    assert call.player.played == [(1, "Wait.")]
    assert sorted((attempt.number, attempt.reason) for attempt in call.tries()) == [
        (1, None),
        (2, TryReason.OTHER_LINE),
    ]


async def test_a_line_waits_for_a_cut_that_passed_the_gate_before_it() -> None:
    call = Call(Interruption(say="Wait.", agent_says="fee", after_s=0))
    await call.gate_sees(InterruptionFrame())

    call.agent_starts()
    call.agent_says("The fee is", final=False)
    await asyncio.sleep(WAIT * 2)
    assert call.player.played == [], "the cut is still on its way down the pipeline"

    call.transcript.caller_interrupted()
    await ends(call)
    call.order.flush()

    assert call.player.played == [(1, "Wait.")]
    caller = [turn for turn in call.observer.turns if turn.role is Role.CALLER]
    assert [(turn.interruption, turn.provenance) for turn in caller] == [
        (1, Provenance.TRANSMITTED)
    ]


async def test_a_line_plays_when_a_cut_never_reaches_the_end_of_the_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(interruptions, "CUT_WAIT_S", WAIT)
    call = Call(Interruption(say="Wait.", agent_says="fee", after_s=0))
    await call.gate_sees(InterruptionFrame())

    call.agent_starts()
    call.agent_says("The fee is", final=False)
    await ends(call)

    assert call.player.played == [(1, "Wait.")]


async def test_the_caller_speaking_or_a_key_press_in_the_turn_uses_a_start_up() -> None:
    speaking = Call(Interruption(say="Wait.", agent_says="fee", after_s=WAIT))
    speaking.agent_starts()
    speaking.agent_says("The fee is", final=False)
    speaking.transcript.generation_started()
    await ends(speaking)

    pressed = Call(Interruption(say="Wait.", agent_says="fee", after_s=WAIT))
    pressed.agent_starts()
    pressed.transcript.pressed("1")
    pressed.agent_says("The fee is", final=False)
    await ends(pressed)

    assert speaking.reasons() == [TryReason.CALLER_SPEAKING]
    assert pressed.reasons() == [TryReason.KEY_PRESS]


async def test_starts_count_only_while_the_persona_is_on_the_line() -> None:
    call = Call(Interruption(say="Wait.", agent_says="fee", after_s=WAIT))
    call.listening = False

    call.agent_starts()
    call.agent_says("The fee is", final=False)
    await asyncio.sleep(WAIT * 2)
    call.agent_ends("The fee is fifty dollars.")
    call.listening = True
    call.persona_replies()
    call.agent_starts()
    call.agent_says("The fee is", final=False)
    await ends(call)

    assert [(attempt.answer, attempt.reason) for attempt in call.tries()] == [(1, None)]


async def test_a_phrase_with_a_speech_to_text_that_gives_no_words_while_speaking_is_missed() -> (
    None
):
    call = Call(
        Interruption(say="Wait.", agent_says="fee"),
        Interruption(say="Hold on."),
        words_while_speaking=False,
    )

    assert [(attempt.number, attempt.reason) for attempt in call.tries()] == [
        (1, TryReason.NO_WORDS_WHILE_SPEAKING)
    ]


async def test_a_line_whose_speech_failed_is_missed_with_the_reason() -> None:
    failed: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
    call = Call(Interruption(say="Wait.", agent_says="fee"), audio=[failed])

    failed.set_exception(RuntimeError("voice not found"))
    await asyncio.sleep(0)
    await call.interrupter.call_ended()

    assert [(attempt.reason, attempt.detail) for attempt in call.tries()] == [
        (TryReason.AUDIO_FAILED, "RuntimeError: voice not found")
    ]


async def test_a_start_waits_for_the_voice_detector_to_decide() -> None:
    call = Call(Interruption(say="Wait.", agent_says="fee", after_s=WAIT))

    call.agent_starts()
    call.agent_says("The fee is", final=False)
    call.vad.state = VADState.STOPPING
    await asyncio.sleep(WAIT * 2)
    assert call.player.played == []
    call.vad.state = VADState.SPEAKING
    await ends(call)

    assert call.player.played == [(1, "Wait.")]


async def test_a_played_line_keeps_the_words_before_it() -> None:
    call = Call(Interruption(say="Wait.", after_s=WAIT, from_answer=1))
    music = Call(Interruption(say="Wait.", after_s=WAIT, from_answer=1))

    call.agent_starts()
    call.agent_says("We open at nine", final=False)
    music.agent_starts()
    await ends(call)
    await ends(music)

    assert call.tries()[0].words == "We open at nine"
    assert music.tries()[0].words == ""


async def test_a_played_line_keeps_the_window_that_starts_at_its_first_sound() -> None:
    call = Call(Interruption(say="Wait.", after_s=WAIT, from_answer=1))

    call.agent_starts()
    await asyncio.sleep(WAIT * 3)

    [event] = [event for event in call.observer.events if event.interruption is not None]
    assert event.interruption is not None
    window = event.at_ms + 200 + round(STOP_WINDOW_S * 1000)
    assert event.interruption.window_end_ms == window, "200 ms of silence first"


async def test_the_line_is_stored_after_the_turn_it_interrupted_and_before_later_turns() -> None:
    call = Call(Interruption(say="Wait.", agent_says="fee", after_s=0))

    call.agent_starts()
    call.agent_says("The fee is", final=False)
    await asyncio.sleep(WAIT)
    assert call.observer.turns == [], "the line waits for the turn that it interrupted"
    call.agent_ends("The fee is fifty dollars.")
    call.agent_starts()
    call.agent_ends("Sure, go ahead.")

    assert [(turn.role, turn.interruption) for turn in call.observer.turns] == [
        (Role.AGENT, None),
        (Role.CALLER, 1),
        (Role.AGENT, None),
    ]


async def test_the_interrupter_reads_turn_frames_going_up_and_words_going_down() -> None:
    call = Call(Interruption(say="Wait.", agent_says="fee", after_s=0))
    call.interrupter.push_frame = call.pushed  # type: ignore[method-assign]
    feed = call.interrupter.process_frame
    words = InterimTranscriptionFrame(text="The fee is", user_id="", timestamp="")
    call.vad.state = VADState.SPEAKING
    call.transcript.agent_voice_started(0.2)
    call.transcript.agent_started()

    await feed(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await feed(words, FrameDirection.DOWNSTREAM)
    await asyncio.sleep(WAIT)
    assert call.player.played == [], "no turn: its frame went down"
    await feed(UserStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    await feed(words, FrameDirection.UPSTREAM)
    await asyncio.sleep(WAIT)
    assert call.player.played == [], "words going up are not the agent's"
    await feed(words, FrameDirection.DOWNSTREAM)
    await ends(call)

    assert call.player.played == [(1, "Wait.")]


async def test_a_reply_that_the_agent_cuts_before_its_audio_starts_no_answer() -> None:
    call = Call(Interruption(say="Wait.", after_s=WAIT))

    call.agent_starts()
    call.agent_ends("Hi, thanks for calling.")
    call.transcript.caller_started(Playout())
    call.transcript.caller_interrupted()
    call.agent_starts()
    await asyncio.sleep(WAIT * 2)
    assert call.player.played == [], "still the first answer"
    call.agent_ends("This call may be recorded.")
    call.persona_replies()
    call.agent_starts()
    await ends(call)

    assert [(attempt.answer, attempt.reason) for attempt in call.tries()] == [(2, None)]


async def test_a_key_press_starts_a_new_answer() -> None:
    call = Call(Interruption(say="Wait.", after_s=WAIT))

    call.agent_starts()
    call.agent_ends("Press 1 for appointments.")
    call.transcript.pressed("1")
    call.agent_starts()
    await ends(call)

    assert [(attempt.answer, attempt.reason) for attempt in call.tries()] == [(2, None)]


async def test_starts_that_still_wait_when_the_call_ends_are_used_up() -> None:
    call = Call(
        Interruption(say="Wait.", after_s=10, from_answer=1),
        Interruption(say="Hold on.", after_s=WAIT, from_answer=1),
    )

    call.agent_starts()
    call.agent_pauses()
    await asyncio.sleep(WAIT * 2)
    await call.interrupter.call_ended()

    assert sorted((attempt.number, attempt.reason) for attempt in call.tries()) == [
        (1, TryReason.CALL_ENDING),
        (2, TryReason.CALL_ENDING),
    ]


async def test_a_time_start_that_outlives_its_answer_names_the_last_turn_of_that_answer() -> None:
    call = Call(Interruption(say="Wait.", after_s=0.4, from_answer=1))

    call.agent_starts()
    first = call.transcript.agent_turn_started_ms
    call.agent_ends("Hi.")
    call.persona_replies()
    await asyncio.sleep(WAIT)
    call.agent_starts()
    await asyncio.sleep(0.3)
    await call.interrupter.call_ended()

    [ended, *_] = call.tries()
    assert (ended.reason, ended.turn_started_ms) == (TryReason.TURN_ENDED, first)


async def test_a_second_line_plays_in_the_turn_once_the_first_line_window_has_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(interruptions, "STOP_WINDOW_S", 0.1)
    call = Call(
        Interruption(say="Wait.", agent_says="fee", after_s=0),
        Interruption(say="Hold on.", agent_says="card", after_s=0),
    )

    call.agent_starts()
    call.agent_says("The fee is", final=False)
    await asyncio.sleep(0.4)
    call.agent_says("The fee is fifty dollars, and your card", final=False)
    await ends(call)

    assert call.player.played == [(1, "Wait."), (2, "Hold on.")]
    assert {(attempt.answer, attempt.reason) for attempt in call.tries()} == {(1, None)}


def test_the_turn_order_keeps_a_later_agent_turn_after_the_line() -> None:
    observer = Observer()
    order = TurnOrder(observer)
    cut = Turn(role=Role.AGENT, text="We open at nine.", started_at_ms=0, ended_at_ms=1_000)
    later = Turn(role=Role.AGENT, text="Sure. What day?", started_at_ms=2_000, ended_at_ms=4_000)
    said = Turn(role=Role.CALLER, text="Wait.", started_at_ms=500, ended_at_ms=6_500)

    order.line_started(1)
    order.turn(cut)
    order.turn(later)
    assert observer.turns == [], "held until the line's own turn is in"
    order.turn(said.model_copy(update={"interruption": 1}))

    assert [turn.text for turn in observer.turns] == [
        "We open at nine.",
        "Wait.",
        "Sure. What day?",
    ]


def test_the_turn_order_lets_everything_out_in_start_order_when_the_call_ends() -> None:
    observer = Observer()
    order = TurnOrder(observer)
    line = Turn(role=Role.CALLER, text="Wait.", started_at_ms=3_100, ended_at_ms=4_000)

    order.line_started(1)
    order.turn(line.model_copy(update={"interruption": 1, "provenance": Provenance.CUT}))
    order.turn(Turn(role=Role.CALLER, text="1", started_at_ms=3_000, ended_at_ms=3_000))
    order.flush()

    assert [turn.started_at_ms for turn in observer.turns] == [3_000, 3_100]


def gate(clock: Clock) -> tuple[LineGate, list[Frame], list[int]]:
    line_gate, _context, out, waited = gate_with_context(clock)
    return line_gate, out, waited


def waiter() -> tuple[Callable[[], Awaitable[None]], list[int]]:
    """A gate's `wait_for_agent`, and a list that grows at each call."""
    waited: list[int] = []

    async def wait_for_agent() -> None:
        waited.append(1)

    return wait_for_agent, waited


def gate_with_context(clock: Clock) -> tuple[LineGate, LLMContext, list[Frame], list[int]]:
    wait_for_agent, waited = waiter()
    out: list[Frame] = []
    context = LLMContext()

    async def pushed(frame: Frame, _direction: FrameDirection = FrameDirection.DOWNSTREAM):
        out.append(frame)

    line_gate = LineGate(context, clock, wait_for_agent, lambda: None)
    line_gate.push_frame = pushed  # type: ignore[method-assign]
    return line_gate, context, out, waited


async def send(line_gate: LineGate, *frames: Frame) -> None:
    for frame in frames:
        await line_gate.process_frame(frame, FrameDirection.DOWNSTREAM)


def line(clock: Clock, within_ms: int = 2_000, say: str = "Wait.") -> PlayingLine:
    now = clock.ms()
    return PlayingLine(
        1,
        Interruption(say=say),
        AgentTurn(answer=1, started_ms=now, keys=0),
        started_ms=now,
        window_end_ms=now + within_ms,
        words="",
    )


async def test_the_gate_blocks_the_cut_and_holds_the_replies_while_the_line_plays() -> None:
    clock = Clock()
    line_gate, out, _ = gate(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))

    await send(line_gate, InterruptionFrame(), LLMContextFrame(context=LLMContext()))
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.6), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    assert [type(frame) for frame in out] == [
        VADUserStartedSpeakingFrame,
        UserStartedSpeakingFrame,
        VADUserStoppedSpeakingFrame,
        UserStoppedSpeakingFrame,
    ]
    await line_gate.line_played()

    assert isinstance(out[-1], LLMContextFrame), "the reply, once the line has played"


async def test_the_persona_waits_for_the_agent_that_stopped_for_a_stop_line() -> None:
    clock = FixedClock()
    line_gate, context, out, waited = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))

    clock.now = 600
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.6), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    clock.now = 700
    await line_gate.line_played()

    await send(line_gate, EndFrame())

    notes = [cast(dict[str, str], message)["content"] for message in context.get_messages()]
    assert notes == [NOTE.format(line="Wait."), STOPPED]
    assert not any(isinstance(frame, LLMContextFrame) for frame in out)
    assert waited == [1]


async def test_a_turn_that_a_late_transcript_starts_during_the_line_gets_no_reply() -> None:
    clock = Clock()
    line_gate, out, _ = gate(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.0), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()

    await send(line_gate, UserStartedSpeakingFrame(), LLMContextFrame(context=LLMContext()))
    await send(line_gate, UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    await line_gate.line_played()

    assert not any(isinstance(frame, LLMContextFrame) for frame in out)


async def test_an_answer_during_a_long_line_gets_one_reply_once_the_line_played() -> None:
    clock = FixedClock()
    line_gate, context, out, waited = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    clock.now = 500
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.0), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    clock.now = 1_700
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    context.add_message({"role": "user", "content": "Sure, go ahead."})
    await send(line_gate, LLMContextFrame(context=context))
    clock.now = 2_600
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.0), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    assert not any(isinstance(frame, LLMContextFrame) for frame in out), "the line still plays"

    await line_gate.line_played()

    assert notes(context) == [NOTE.format(line="Wait."), "Sure, go ahead."], (
        "speech while the line plays is part of the speech that it interrupted"
    )
    assert sum(isinstance(frame, LLMContextFrame) for frame in out) == 1, "the reply to it"
    assert waited == []


async def test_a_turn_that_starts_during_the_line_is_part_of_the_speech_it_interrupted() -> None:
    clock = FixedClock()
    line_gate, context, out, waited = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    context.add_message({"role": "user", "content": "Thank you, Jordan Ellis."})
    clock.now = 450
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    clock.now = 650
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.1), UserStartedSpeakingFrame())
    await send(line_gate, InterruptionFrame())
    await line_gate.line_played()
    context.add_message({"role": "user", "content": "May I please"})
    clock.now = 1_600
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3))
    clock.now = 2_000
    await send(line_gate, LLMContextFrame(context=context), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()

    assert notes(context) == [
        "Thank you, Jordan Ellis.",
        NOTE.format(line="Wait."),
        "May I please",
        STOPPED,
    ], "a pause of 0.4 s is no stop; the agent stopped at the end of its second turn"
    assert not any(isinstance(frame, LLMContextFrame | InterruptionFrame) for frame in out)
    assert waited == [1]


async def test_two_lines_in_one_turn_get_a_note_each_and_the_last_line_decides() -> None:
    clock = FixedClock()
    line_gate, context, out, waited = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock, within_ms=0, say="Mm-hmm."))
    await line_gate.line_played()
    line_gate.line_started(line(clock))

    clock.now = 600
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.6), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    clock.now = 700
    await line_gate.line_played()

    await send(line_gate, EndFrame())

    notes = [cast(dict[str, str], message)["content"] for message in context.get_messages()]
    assert notes == [NOTE.format(line="Mm-hmm."), NOTE.format(line="Wait."), STOPPED]
    assert not any(isinstance(frame, LLMContextFrame) for frame in out)
    assert waited == [1]


async def test_the_speech_that_a_line_interrupts_is_decided_when_its_last_turn_ends() -> None:
    clock = FixedClock()
    line_gate, context, out, _ = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    clock.now = 2_800
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    clock.now = 2_900
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.1), UserStartedSpeakingFrame())
    await line_gate.line_played()
    assert not any(isinstance(frame, LLMContextFrame) for frame in out), "a turn is open"

    clock.now = 3_500
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()

    assert notes(context) == [NOTE.format(line="Wait.")], "it talked over the line"
    assert sum(isinstance(frame, LLMContextFrame) for frame in out) == 1


def notes(context: LLMContext) -> list[str]:
    return [cast(dict[str, str], message)["content"] for message in context.get_messages()]


async def test_an_agent_that_stops_for_the_line_and_answers_in_its_turn_gets_a_reply() -> None:
    clock = FixedClock()
    line_gate, context, out, waited = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    clock.now = 600
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.0))
    clock.now = 1_500
    await line_gate.line_played()
    clock.now = 1_800
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2))
    clock.now = 3_600
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.0), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()

    assert notes(context) == [NOTE.format(line="Wait."), ANSWERED], "its first stop decides"
    assert sum(isinstance(frame, LLMContextFrame) for frame in out) == 1
    assert waited == []


async def test_an_agent_that_talks_over_the_line_gets_the_usual_reply() -> None:
    clock = FixedClock()
    line_gate, context, out, waited = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    clock.now = 3_500
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.0), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    await line_gate.line_played()

    assert notes(context) == [NOTE.format(line="Wait.")]
    assert sum(isinstance(frame, LLMContextFrame) for frame in out) == 1
    assert waited == []


class Seen(FrameProcessor):
    """After the gate: each frame that passed it, and whether the line had played then. A step
    runs when the given frame of its kind passes, counted from 1."""

    def __init__(
        self,
        playing: PlayingLine,
        steps: dict[tuple[type[Frame], int], Callable[[], Awaitable[None]]],
    ) -> None:
        super().__init__(enable_direct_mode=True)
        self.playing = playing
        self.frames: list[tuple[type[Frame], bool]] = []
        self._steps = steps

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.DOWNSTREAM:
            self.frames.append((type(frame), self.playing.played))
            nth = sum(kind is type(frame) for kind, _ in self.frames)
            step = self._steps.get((type(frame), nth))
            if step is not None:
                await step()
        await self.push_frame(frame, direction)

    def played_at(self, kind: type[Frame]) -> list[bool]:
        return [played for seen, played in self.frames if seen is kind]


class ClockAt(FrameProcessor):
    """Before the turn aggregator: sets the call clock when the given frame of its kind comes
    down, counted from 1. The voice detector's frames are system frames, so they keep their
    order on the way to the gate."""

    def __init__(self, clock: FixedClock, times: dict[tuple[type[Frame], int], int]) -> None:
        super().__init__()
        self._clock = clock
        self._times = times
        self._seen: list[type[Frame]] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.DOWNSTREAM:
            self._seen.append(type(frame))
            at = self._times.get((type(frame), self._seen.count(type(frame))))
            if at is not None:
                self._clock.now = at
        await self.push_frame(frame, direction)


def aggregator() -> LLMUserAggregator:
    return LLMContextAggregatorPair(
        LLMContext(),
        user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.05)]
            ),
        ),
    ).user()


AGENT_TURN = [
    VADUserStartedSpeakingFrame(start_secs=0.2),
    TranscriptionFrame("We open at nine", "agent", "now"),
    VADUserStoppedSpeakingFrame(stop_secs=0.0),
    SleepFrame(0.2),
]


async def test_behind_a_real_aggregator_a_talked_over_line_gets_one_reply_after_it_played() -> None:
    clock = FixedClock()
    user = aggregator()
    wait_for_agent, _ = waiter()
    line_gate = LineGate(user.context, clock, wait_for_agent, lambda: None)
    playing = line(clock)

    async def starts() -> None:
        line_gate.line_started(playing)
        clock.now = 5_000  # the agent speaks on, past the line's window

    @user.event_handler("on_user_turn_stopped")
    async def turn_stopped(*_: object) -> None:
        await line_gate.turn_ended()
        await line_gate.line_played()

    seen = Seen(playing, {(InterruptionFrame, 1): starts})
    await run_test(
        Pipeline([user, AgentTurnTap(TranscriptBuilder(clock, Observer())), line_gate, seen]),
        frames_to_send=AGENT_TURN,
    )

    assert seen.played_at(LLMContextFrame) == [True], "one reply, and only once the line played"
    assert notes(user.context)[-1] == NOTE.format(line="Wait.")


async def test_behind_a_real_aggregator_an_answer_that_starts_during_the_line_gets_one_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(interruptions, "ANSWER_WAIT_S", WAIT)
    clock = FixedClock()
    user = aggregator()
    wait_for_agent, waited = waiter()
    line_gate = LineGate(user.context, clock, wait_for_agent, lambda: None)
    playing = line(clock)

    async def starts() -> None:
        line_gate.line_started(playing)

    @user.event_handler("on_user_turn_stopped")
    async def turn_stopped(*_: object) -> None:
        await line_gate.turn_ended()

    seen = Seen(
        playing,
        {(InterruptionFrame, 1): starts, (VADUserStoppedSpeakingFrame, 2): line_gate.line_played},
    )
    times: dict[tuple[type[Frame], int], int] = {
        (VADUserStoppedSpeakingFrame, 1): 500,
        (VADUserStartedSpeakingFrame, 2): 1_700,
        (VADUserStoppedSpeakingFrame, 2): 2_600,
    }
    await run_test(
        Pipeline(
            [
                ClockAt(clock, times),
                user,
                AgentTurnTap(TranscriptBuilder(clock, Observer())),
                line_gate,
                seen,
            ]
        ),
        frames_to_send=[
            *AGENT_TURN,
            VADUserStartedSpeakingFrame(start_secs=0.2),
            TranscriptionFrame("Sure, take your time.", "agent", "now"),
            VADUserStoppedSpeakingFrame(stop_secs=0.0),
            SleepFrame(WAIT * 4),
        ],
    )

    assert seen.played_at(InterruptionFrame) == [False], "only the cut before the line started"
    assert seen.played_at(LLMContextFrame) == [True], "one reply, to the answer"
    assert notes(user.context) == [
        "We open at nine",
        NOTE.format(line="Wait."),
        "Sure, take your time.",
    ], "speech while the line plays is part of the speech that it interrupted"
    assert waited == []


async def test_a_persona_that_waits_goes_on_when_the_agent_says_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, context, out, _ = await waiting_gate(monkeypatch)
    assert not any(isinstance(frame, LLMContextFrame) for frame in out), "it waits first"

    await asyncio.sleep(WAIT * 3)

    assert notes(context)[-2:] == [STOPPED, GO_ON]
    assert sum(isinstance(frame, LLMContextFrame) for frame in out) == 1


async def test_a_persona_that_waits_hears_the_agent_answer_and_does_not_go_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(interruptions, "ANSWER_WAIT_S", WAIT)
    clock = FixedClock()
    line_gate, context, out, _ = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.0), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    await line_gate.line_played()

    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    await asyncio.sleep(WAIT * 3)

    assert GO_ON not in notes(context)
    assert not any(isinstance(frame, LLMContextFrame) for frame in out)


async def waiting_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[LineGate, LLMContext, list[Frame], list[int]]:
    """A gate whose persona waits for the agent's answer to a line that the agent stopped for."""
    monkeypatch.setattr(interruptions, "ANSWER_WAIT_S", WAIT)
    clock = FixedClock()
    line_gate, context, out, waited = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    clock.now = 600
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.6), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    clock.now = 700
    await line_gate.line_played()
    return line_gate, context, out, waited


async def test_a_turn_with_no_words_while_the_persona_waits_starts_its_wait_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    line_gate, context, out, waited = await waiting_gate(monkeypatch)

    for _ in range(2):
        await send(
            line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame()
        )
        await send(
            line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.0), UserStoppedSpeakingFrame()
        )
        await line_gate.turn_ended()
        await asyncio.sleep(WAIT * 3)

    assert notes(context).count(GO_ON) == 1, "a noise with no words is no answer; one go-on"
    assert sum(isinstance(frame, LLMContextFrame) for frame in out) == 1
    assert waited == [1, 1]


async def test_a_turn_with_no_voice_while_the_persona_waits_is_no_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    line_gate, context, out, _ = await waiting_gate(monkeypatch)

    await send(line_gate, UserStartedSpeakingFrame())
    await asyncio.sleep(WAIT * 3)
    assert GO_ON not in notes(context), "the time runs only with no agent turn open"
    await send(line_gate, LLMContextFrame(context=context), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    await asyncio.sleep(WAIT * 3)

    assert notes(context).count(GO_ON) == 1, "late words of the speech that the line cut"
    assert sum(isinstance(frame, LLMContextFrame) for frame in out) == 1


async def test_late_words_while_the_persona_waits_are_no_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    line_gate, context, out, _ = await waiting_gate(monkeypatch)

    await send(line_gate, LLMContextFrame(context=context))
    await asyncio.sleep(WAIT * 3)

    assert notes(context).count(GO_ON) == 1
    assert sum(isinstance(frame, LLMContextFrame) for frame in out) == 1


async def test_a_pause_shorter_than_a_stop_after_the_line_is_no_stop() -> None:
    clock = FixedClock()
    line_gate, context, out, waited = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    clock.now = 700
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3))
    clock.now = 900
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.1))
    clock.now = 4_300
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    await line_gate.line_played()

    assert notes(context) == [NOTE.format(line="Wait.")], "a pause of 0.4 s, then more speech"
    assert sum(isinstance(frame, LLMContextFrame) for frame in out) == 1
    assert waited == []


async def test_a_turn_that_ends_in_a_pause_shorter_than_a_stop_gives_no_stop() -> None:
    clock = FixedClock()
    line_gate, context, out, waited = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    await line_gate.line_played()
    clock.now = 1_100
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    clock.now = 1_300
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.1), UserStartedSpeakingFrame())
    await asyncio.sleep(0.35)
    clock.now = 4_300
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()

    assert notes(context) == [NOTE.format(line="Wait.")], (
        "the turn ended 0.3 s into a pause of 0.4 s"
    )
    assert sum(isinstance(frame, LLMContextFrame) for frame in out) == 1
    assert waited == []


async def test_a_quiet_that_the_turn_ends_in_is_a_stop_once_it_lasts() -> None:
    clock = FixedClock()
    line_gate, context, out, waited = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    await line_gate.line_played()
    clock.now = 1_100
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    assert notes(context) == [NOTE.format(line="Wait.")], "a quiet of 0.3 s so far"

    clock.now = 1_500
    await asyncio.sleep(0.45)
    await send(line_gate, EndFrame())

    assert notes(context) == [NOTE.format(line="Wait."), STOPPED]
    assert not any(isinstance(frame, LLMContextFrame) for frame in out)
    assert waited == [1]


async def test_a_fragment_after_a_long_pause_during_the_line_is_no_answer() -> None:
    clock = FixedClock()
    line_gate, context, out, waited = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    clock.now = 800
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    clock.now = 1_300
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.1), UserStartedSpeakingFrame())
    clock.now = 1_550
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3))
    clock.now = 1_600
    await send(line_gate, UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    clock.now = 1_700
    await line_gate.line_played()
    assert not any(isinstance(frame, LLMContextFrame) for frame in out), "no reply to it"

    clock.now = 2_000
    await asyncio.sleep(0.35)
    await send(line_gate, EndFrame())

    assert notes(context) == [NOTE.format(line="Wait."), STOPPED], "its quiet after the fragment"
    assert not any(isinstance(frame, LLMContextFrame) for frame in out)
    assert waited == [1]


async def test_a_reply_to_a_later_line_ends_the_wait_for_an_earlier_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(interruptions, "ANSWER_WAIT_S", WAIT)
    clock = FixedClock()
    line_gate, context, out, _ = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    clock.now = 600
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.6), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    clock.now = 700
    await line_gate.line_played()
    clock.now = 1_500
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock, say="Hold on."))
    clock.now = 2_000
    await line_gate.line_played()
    clock.now = 4_300
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()

    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.0), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()
    await asyncio.sleep(WAIT * 3)

    assert GO_ON not in notes(context), "the agent talked over the second line, which decides"
    assert sum(isinstance(frame, LLMContextFrame) for frame in out) == 1


async def test_a_voice_that_comes_back_just_before_a_stop_is_heard_first() -> None:
    clock = FixedClock()
    line_gate, context, out, waited = gate_with_context(clock)
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.2), UserStartedSpeakingFrame())
    line_gate.line_started(line(clock))
    await line_gate.line_played()
    clock.now = 1_100
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3), UserStoppedSpeakingFrame())
    clock.now = 1_450
    await line_gate.turn_ended()
    await send(line_gate, VADUserStartedSpeakingFrame(start_secs=0.1), UserStartedSpeakingFrame())
    await asyncio.sleep(0.1)
    clock.now = 4_300
    await send(line_gate, VADUserStoppedSpeakingFrame(stop_secs=0.3), UserStoppedSpeakingFrame())
    await line_gate.turn_ended()

    assert notes(context) == [NOTE.format(line="Wait.")], "a pause of 0.55 s, heard 0.1 s late"
    assert sum(isinstance(frame, LLMContextFrame) for frame in out) == 1
    assert waited == []


async def test_a_line_tells_the_turn_limit_that_its_audio_is_no_answer() -> None:
    clock = FixedClock()
    wait_for_agent, _ = waiter()
    told: list[None] = []
    line_gate = LineGate(LLMContext(), clock, wait_for_agent, lambda: told.append(None))

    line_gate.line_started(line(clock))

    assert told == [None]
