import asyncio
import wave
from collections.abc import Callable, Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    LLMMessagesAppendFrame,
    TextFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.tests.utils import SleepFrame, run_test

from tests.caller.test_pipeline import idle_user
from tests.conftest import Observer
from yaksh.caller.answering import HANDOVER_NOTE, AnsweringScript
from yaksh.caller.audio import FRAME_BYTES, MACHINE, SAMPLE_RATE, Clock, Playout
from yaksh.caller.machines import MachineGate, SoundPlayer
from yaksh.caller.pipeline import CallState, Persona, watch_silence
from yaksh.caller.transcript import TranscriptBuilder
from yaksh.domain.answering import (
    AfterScreening,
    AnsweredBy,
    Answering,
    AnsweringPlan,
    MachineLine,
    Screener,
    Voicemail,
)
from yaksh.domain.conversations import EndReason, Role, WireEventKind
from yaksh.simulation.answering import answering_plan, line_texts


class FakePlayer:
    """Plays a line at once: the transcript closes its reply as soon as it starts."""

    def __init__(self, transcript: TranscriptBuilder) -> None:
        self.transcript = transcript
        self.played: list[tuple[MachineLine, str | None]] = []

    async def play(self, pcm: bytes, text: str | None, *, machine: MachineLine) -> None:
        self.played.append((machine, text))
        if text is None:
            return
        self.transcript.caller_started(None)
        self.transcript.transmitted(text, 0, None, self_spaced=True)
        self.transcript.reply_ended(None)


class TalkOverPlayer(FakePlayer):
    """The agent answers each screener question while the question still plays: its turn ends
    before the question does."""

    async def play(self, pcm: bytes, text: str | None, *, machine: MachineLine) -> None:
        if machine is MachineLine.SCREENER:
            self.transcript.agent_said("Hi, this is Alex from Swift Movers, about your move.")
            await asyncio.sleep(0.01)
        await super().play(pcm, text, machine=machine)


class Call:
    """A call that the persona's phone answers, with the parts the script drives."""

    def __init__(
        self,
        plan: AnsweringPlan,
        greeting: bytes | None = None,
        player: type[FakePlayer] = FakePlayer,
    ) -> None:
        clock = Clock()
        self.observer = Observer()
        self.transcript = TranscriptBuilder(clock, self.observer)
        self.player = player(self.transcript)
        self.gate = MachineGate()
        self.state = CallState()
        self.queued: list[Frame] = []
        self.picked_up = False

        async def queue_frame(frame: Frame) -> None:
            self.queued.append(frame)

        async def speak_first() -> None:
            self.picked_up = True

        persona = SimpleNamespace(
            player=self.player,
            gate=self.gate,
            worker=SimpleNamespace(queue_frame=queue_frame),
            speak_first=speak_first,
        )
        own: asyncio.Future[bytes] | None = None
        if greeting is not None:
            own = asyncio.get_running_loop().create_future()
            own.set_result(greeting)
        self.script = AnsweringScript(
            plan,
            cast(Persona, persona),
            self.state,
            self.transcript,
            self.observer,
            clock,
            own,
        )

    async def run(self, agent: Callable[[Call], Coroutine[Any, Any, None]] | None = None) -> None:
        """Run the script, with the agent's part beside it, to the end."""
        helper = asyncio.create_task(agent(self)) if agent else None
        try:
            await asyncio.wait_for(self.script.run(), 5)
        finally:
            if helper is not None:
                helper.cancel()

    def lines(self) -> list[MachineLine]:
        return [line for line, _ in self.player.played]

    async def until_played(self, count: int) -> None:
        while len(self.player.played) < count:
            await asyncio.sleep(0.01)


def short_tone(tmp_path: Path) -> str:
    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(SAMPLE_RATE)
        file.writeframes(bytes(FRAME_BYTES * 5))
    return str(path)


def fast(plan: AnsweringPlan | None, tmp_path: Path, **screener: Any) -> AnsweringPlan:
    """The plan with timings short enough for a test."""
    assert plan is not None
    voicemail = plan.voicemail and plan.voicemail.model_copy(
        update={
            "tone": short_tone(tmp_path) if plan.voicemail.tone else None,
            "tone_gap_s": 0,
            "silence_end_s": 0.2,
            "recording_limit_s": 1.0,
        }
    )
    timed = {"hold_s": 0.05, "answer_wait_s": 0.2, **screener}
    return plan.model_copy(
        update={
            "start_delay_s": 0,
            "voicemail": voicemail,
            "screener": plan.screener and plan.screener.model_copy(update=timed),
        }
    )


async def answers(call: Call) -> None:
    """The agent answers each question of the screener."""
    questions = 0
    while True:
        asked = [line for line in call.lines() if line is MachineLine.SCREENER]
        if len(asked) > questions:
            questions = len(asked)
            call.transcript.agent_said("Hi, this is Alex from Swift Movers, about your move.")
        await asyncio.sleep(0.01)


async def test_a_voicemail_plays_its_greeting_and_tone_and_stops_after_the_agents_silence(
    tmp_path: Path,
) -> None:
    plan = fast(answering_plan(AnsweredBy.VOICEMAIL, Answering()), tmp_path)
    call = Call(plan)

    await call.run()

    assert call.lines() == [MachineLine.GREETING, MachineLine.TONE]
    assert [(t.machine, t.text) for t in call.observer.turns] == [
        (MachineLine.GREETING, line_texts()["iphone_greeting"])
    ]
    assert call.observer.kinds() == [WireEventKind.CALLER_SOUND]
    assert call.observer.events[0].detail == "tone, 0.1 s"
    assert call.state.end_reason is EndReason.VOICEMAIL_ENDED
    assert call.state.caller_reason == "The voicemail stopped recording after 0.2 s of silence."


async def test_a_voicemail_records_while_the_agent_talks_up_to_its_limit(tmp_path: Path) -> None:
    plan = fast(answering_plan(AnsweredBy.VOICEMAIL, Answering()), tmp_path)
    call = Call(plan)

    async def message(call: Call) -> None:
        await call.until_played(2)
        call.transcript.agent_voice_started(0)

    await call.run(message)

    assert call.state.end_reason is EndReason.VOICEMAIL_ENDED
    assert call.state.caller_reason == "The voicemail stopped recording at its 1 s limit."


async def test_the_silence_counts_from_the_end_of_the_agents_message(tmp_path: Path) -> None:
    plan = fast(answering_plan(AnsweredBy.VOICEMAIL, Answering()), tmp_path)
    call = Call(plan)
    stopped_at: list[int] = []
    clock = Clock()

    async def message(call: Call) -> None:
        await call.until_played(2)
        call.transcript.agent_voice_started(0)
        await asyncio.sleep(0.4)
        call.transcript.agent_voice_stopped(0)
        stopped_at.append(clock.ms())

    await call.run(message)
    ended_at = clock.ms()

    assert call.state.caller_reason == "The voicemail stopped recording after 0.2 s of silence."
    assert stopped_at and ended_at - stopped_at[0] >= 200


async def test_the_persona_says_its_own_greeting_and_a_voicemail_with_no_tone_plays_none(
    tmp_path: Path,
) -> None:
    answering = Answering(voicemail=Voicemail.CARRIER_NO_TONE, greeting="Hi, it's Rachel.")
    call = Call(fast(answering_plan(AnsweredBy.VOICEMAIL, answering), tmp_path), bytes(640))

    await call.run()

    assert call.player.played == [(MachineLine.GREETING, "Hi, it's Rachel.")]
    assert call.observer.kinds() == []
    assert call.state.end_reason is EndReason.VOICEMAIL_ENDED


async def test_a_full_mailbox_says_so_and_hangs_up(tmp_path: Path) -> None:
    answering = Answering(voicemail=Voicemail.MAILBOX_FULL)
    call = Call(fast(answering_plan(AnsweredBy.VOICEMAIL, answering), tmp_path))

    await call.run()

    assert call.lines() == [MachineLine.MAILBOX_FULL]
    assert (call.state.end_reason, call.state.caller_reason) == (
        EndReason.VOICEMAIL_ENDED,
        "The mailbox is full.",
    )


async def test_the_persona_picks_up_after_the_screener_and_reads_what_the_agent_said(
    tmp_path: Path,
) -> None:
    answering = Answering(screener=Screener.PIXEL_CALL_ASSIST)
    call = Call(fast(answering_plan(AnsweredBy.SCREENER, answering), tmp_path))

    await call.run(answers)

    assert call.lines() == [MachineLine.SCREENER] * 3, "prompt, follow-up, acknowledgement"
    assert call.observer.kinds() == [WireEventKind.HOLD_STARTED, WireEventKind.HANDOVER]
    assert call.observer.events[0].detail == "50"
    assert not call.gate.closed and call.picked_up
    (note,) = call.queued
    assert isinstance(note, LLMMessagesAppendFrame) and not note.run_llm
    assert note.messages == [{"role": "system", "content": HANDOVER_NOTE}]
    assert call.state.end_reason is None
    assert [turn.role for turn in call.observer.turns] == [Role.CALLER, Role.AGENT] * 3


@pytest.mark.parametrize(
    ("after", "lines", "reason"),
    [
        (
            AfterScreening.REPLY,
            [MachineLine.SCREENER, MachineLine.SCREENER, MachineLine.REPLY],
            "The screener sent a reply.",
        ),
        (
            AfterScreening.DECLINES,
            [MachineLine.SCREENER, MachineLine.SCREENER],
            "The screener declined the call.",
        ),
    ],
)
async def test_a_screener_that_does_not_pass_the_call_on_hangs_up_with_its_reason(
    after: AfterScreening, lines: list[MachineLine], reason: str, tmp_path: Path
) -> None:
    answering = Answering(after_screening=after)
    call = Call(fast(answering_plan(AnsweredBy.SCREENER, answering), tmp_path))

    await call.run(answers)

    assert call.lines() == lines
    assert (call.state.end_reason, call.state.caller_reason) == (EndReason.SCREENER_ENDED, reason)
    assert call.gate.closed and not call.picked_up


async def test_a_screener_passes_the_call_on_to_the_voicemail_after_the_hold(
    tmp_path: Path,
) -> None:
    answering = Answering(after_screening=AfterScreening.VOICEMAIL)
    call = Call(fast(answering_plan(AnsweredBy.SCREENER, answering), tmp_path))

    await call.run(answers)

    assert call.lines() == [
        MachineLine.SCREENER,
        MachineLine.SCREENER,
        MachineLine.GREETING,
        MachineLine.TONE,
    ]
    assert call.state.end_reason is EndReason.VOICEMAIL_ENDED


async def test_a_screener_hangs_up_on_an_agent_that_does_not_answer(tmp_path: Path) -> None:
    call = Call(fast(answering_plan(AnsweredBy.SCREENER, Answering()), tmp_path))

    await call.run()

    assert call.lines() == [MachineLine.SCREENER]
    assert (call.state.end_reason, call.state.caller_reason) == (
        EndReason.SCREENER_ENDED,
        "The agent did not answer the screener.",
    )


async def test_a_screener_does_not_take_speech_that_ended_during_its_question(
    tmp_path: Path,
) -> None:
    plan = fast(answering_plan(AnsweredBy.SCREENER, Answering()), tmp_path)
    call = Call(plan, player=TalkOverPlayer)

    await call.run()

    assert (call.state.end_reason, call.state.caller_reason) == (
        EndReason.SCREENER_ENDED,
        "The agent did not answer the screener.",
    )


async def test_a_screener_waits_for_an_agent_that_is_still_speaking(tmp_path: Path) -> None:
    call = Call(fast(answering_plan(AnsweredBy.SCREENER, Answering()), tmp_path))

    async def slow(call: Call) -> None:
        await call.until_played(1)
        call.transcript.agent_voice_started(0)
        await asyncio.sleep(0.5)
        call.transcript.agent_voice_stopped(0)
        call.transcript.agent_said("Hi, this is Alex. I'm calling about your move date.")

    await call.run(slow)

    assert call.observer.kinds()[-1] is WireEventKind.HANDOVER


async def test_a_screener_with_a_limit_ends_the_call_when_it_passes(tmp_path: Path) -> None:
    answering = Answering(screener=Screener.TRUECALLER)
    plan = fast(answering_plan(AnsweredBy.SCREENER, answering), tmp_path, limit_s=0.1, hold_s=1)
    call = Call(plan)

    await call.run(answers)

    assert (call.state.end_reason, call.state.caller_reason) == (
        EndReason.SCREENER_ENDED,
        "The screener ended the call at its 0.1 s limit.",
    )


async def test_the_player_sends_a_line_as_a_reply_kept_out_of_the_persona_context() -> None:
    player = SoundPlayer()
    sent: list[Frame] = []

    async def push_frame(frame: Frame, *_: Any) -> None:
        sent.append(frame)

    player.push_frame = push_frame  # type: ignore[method-assign]
    await player.play(
        bytes(FRAME_BYTES * 2), "Thanks. Please stay on the line.", machine=MachineLine.SCREENER
    )
    await player.play(bytes(FRAME_BYTES), None, machine=MachineLine.TONE)

    assert [type(frame) for frame in sent] == [
        TTSStartedFrame,
        TTSAudioRawFrame,
        TTSAudioRawFrame,
        TTSTextFrame,
        TTSStoppedFrame,
        TTSStartedFrame,
        TTSAudioRawFrame,
        TTSStoppedFrame,
    ]
    started, words = cast(TTSStartedFrame, sent[0]), cast(TTSTextFrame, sent[3])
    assert started.metadata[MACHINE] is MachineLine.SCREENER and not started.append_to_context
    assert words.text == "Thanks. Please stay on the line." and not words.append_to_context
    assert sent[5].metadata[MACHINE] is MachineLine.TONE


async def test_the_assistant_context_keeps_none_of_a_machine_line() -> None:
    context = LLMContext()
    assistant = LLMContextAggregatorPair(context).assistant()
    words = TTSTextFrame("Thanks. Please stay on the line.", text_type="sentence")
    words.append_to_context = False

    await run_test(
        assistant,
        frames_to_send=[TTSStartedFrame(append_to_context=False), words, TTSStoppedFrame()],
    )

    assert context.get_messages() == []


async def test_a_closed_gate_keeps_the_agents_turns_and_interruptions_from_the_persona() -> None:
    gate = MachineGate()
    context = LLMContext()

    await run_test(
        gate,
        frames_to_send=[LLMContextFrame(context), InterruptionFrame(), TextFrame("kept")],
        expected_down_frames=[TextFrame],
    )
    gate.open()
    await run_test(
        gate,
        frames_to_send=[LLMContextFrame(context), TextFrame("kept")],
        expected_down_frames=[LLMContextFrame, TextFrame],
    )


async def test_the_persona_does_not_nudge_an_agent_while_a_machine_answers() -> None:
    user = idle_user()
    state = CallState()
    nudges: list[None] = []

    async def nudge() -> None:
        nudges.append(None)

    watch_silence(user, state, nudge, lambda: False)

    await run_test(user, frames_to_send=[BotStoppedSpeakingFrame(), SleepFrame(0.15)] * 3)

    assert nudges == [] and state.end_reason is None


def test_a_machine_line_is_its_own_turn_and_the_tone_is_none() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    builder.machine("At the tone, please record your message.", MachineLine.GREETING)
    for text in ("At the tone, please record your message.", None):
        playout = Playout()
        playout.received(bytes(FRAME_BYTES), 0)
        playout.played(FRAME_BYTES)
        builder.caller_started(playout)
        if text:
            builder.transmitted(text, 0, playout, self_spaced=True)
        builder.reply_ended(playout)
    builder.scripted("Hello?")

    builder.call_ended()

    assert [(turn.machine, turn.scripted, turn.text) for turn in observer.turns] == [
        (MachineLine.GREETING, False, "At the tone, please record your message."),
        (None, True, "Hello?"),
    ]
