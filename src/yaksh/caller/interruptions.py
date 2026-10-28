"""The scenario's interruptions on a phone call: when a line plays while the agent speaks, the
gate that keeps the line and the persona's replies in order around it, and the order of the
transcript's turns around a line."""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import partial
from typing import Any

from pipecat.audio.vad.vad_analyzer import VADState
from pipecat.frames.frames import (
    CancelFrame,
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
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from yaksh.caller.audio import Clock, bytes_ms, first_sound_ms
from yaksh.caller.machines import SoundPlayer, until_played
from yaksh.caller.reply_times import ReplyTimes
from yaksh.caller.transcript import TranscriptBuilder
from yaksh.caller.turn_models import SharedSileroVAD
from yaksh.diagnostics import describe_exception
from yaksh.domain.canonical import count, settled
from yaksh.domain.conversations import (
    CallObserver,
    InterruptionTry,
    Role,
    TryReason,
    Turn,
    WireEvent,
    WireEventKind,
)
from yaksh.domain.scenarios import Interruption

NOTE = 'While the agent said the turn above, you interrupted it and said: "{line}"'
WAIT_OVER = (
    "If your words only asked it to wait, you are the one it waits for: if it {answers} only that"
    " it will wait, say that you are back and go on with the call."
)
STOPPED = "The agent stopped for you. Wait for its answer. " + WAIT_OVER.format(answers="answers")
ANSWERED = "The agent stopped for you and answered you in the turn above. " + WAIT_OVER.format(
    answers="answered"
)
GO_ON = "The agent has said nothing more. Go on with the call."
STOP_WINDOW_S = 2.0
"""How long after a line's first sound a stop of the agent counts as a stop for the line."""
ANSWER_WAIT_S = 3.0
"""How long the persona waits for the agent's answer to a line before it goes on with the call:
an agent that finished its own question inside the line's window waits for the caller too."""
DECIDE_POLL_S = 0.02
"""How often a start looks again at the voice detector, while it decides or the agent pauses."""


class PhraseMatches:
    """The new matches of a phrase in one turn of the agent, as its words come. A count above
    the highest count so far is a new match. After a final, the highest count is the count in
    the finals, so a partial guess that the final drops does not hide a later real match."""

    def __init__(self, phrase: str) -> None:
        self._phrase = phrase
        self._highest = 0

    def heard(self, words: str, *, final: bool) -> int:
        """How many new matches the turn's words bring: its finals joined, then the current
        partial."""
        found = count(settled(words), self._phrase)
        new = max(0, found - self._highest)
        self._highest = found if final else max(self._highest, found)
        return new


class TurnOrder:
    """Between the transcript and the call's observer. From a line's start it holds every turn,
    and lets them out in start order once each line that started has its caller turn in and an
    agent turn came after the last line started: the interrupted turn often ends after its line,
    because an incomplete stop keeps it open. `flush` lets out the rest when the call ends."""

    def __init__(self, observer: CallObserver) -> None:
        self._observer = observer
        self._held: list[Turn] = []
        self._lines: set[int] = set()
        self._agent_after = True

    def line_started(self, number: int) -> None:
        self._lines.add(number)
        self._agent_after = False

    def turn(self, turn: Turn) -> None:
        if not self._held and not self._lines and self._agent_after:
            self._observer.turn(turn)
            return
        self._held.append(turn)
        if turn.interruption is not None:
            self._lines.discard(turn.interruption)
        elif turn.role is Role.AGENT:
            self._agent_after = True
        if not self._lines and self._agent_after:
            self.flush()

    def wire_event(self, event: WireEvent) -> None:
        self._observer.wire_event(event)

    def flush(self) -> None:
        held, self._held = self._held, []
        for turn in sorted(held, key=lambda turn: turn.started_at_ms):
            self._observer.turn(turn)


@dataclass
class AgentTurn:
    """A turn of the agent as the Interrupter follows it."""

    answer: int
    started_ms: int | None
    """As TranscriptBuilder computes it, so the evaluation finds the stored turn."""
    keys: int
    """The caller's key presses so far when the turn started."""
    open: bool = True
    finals: list[str] = field(default_factory=list)
    partial: str = ""

    def heard(self, text: str, *, final: bool) -> None:
        if final:
            self.finals.append(text)
            self.partial = ""
        else:
            self.partial = text

    def words(self) -> str:
        return " ".join([*self.finals, self.partial]).strip()


@dataclass
class LineState:
    """One interruption of the scenario as the Interrupter follows it during the call."""

    number: int
    spec: Interruption
    audio: asyncio.Future[bytes]
    done: bool = False
    """It played, or it is missed at once: it tries no more."""
    matches: PhraseMatches | None = None


@dataclass
class PlayingLine:
    """A line that plays, on the call clock, as the gate and its try follow it."""

    number: int
    spec: Interruption
    turn: AgentTurn
    """The agent turn that the line interrupts."""
    started_ms: int
    window_end_ms: int
    """STOP_WINDOW_S after the first sound of the line's audio."""
    words: str
    """The agent's words in its turn up to the line's start."""
    played: bool = False
    saved: bool = False


class After(Enum):
    """What the persona does once the lines have played."""

    NOTHING = auto()
    WAIT = auto()
    """The agent stopped for the last line of its turn and said nothing more in that turn: wait
    for its answer."""
    REPLY = auto()
    """A reply is owed: the end of the agent turn in progress gives it, or the gate."""


class LineGate(FrameProcessor):
    """After the agent's turns are stored and before the persona's model. While a line plays,
    the agent cannot cut it and the persona does not answer over it: the gate drops the agent's
    cut and every context frame. When the turn that the lines interrupted ends, the gate writes
    a note for each line into the context, and the last line decides what the persona does. The
    agent stopped for it when its first stop after the line started came within the line's
    window. Then, if the agent said nothing more in that turn, the persona waits for its answer,
    and goes on with the call when the agent says nothing for ANSWER_WAIT_S; if it spoke again,
    the persona answers it. In every other case the persona answers the turn as usual. A later
    turn of the agent that ends during a line owes a reply too. The end of the next agent turn
    gives the reply, or the gate itself once the line has played and no agent turn is open."""

    def __init__(
        self,
        context: LLMContext,
        clock: Clock,
        wait_for_agent: Callable[[], Awaitable[None]],
    ) -> None:
        super().__init__(enable_direct_mode=True)
        self._context = context
        self._clock = clock
        self._wait_for_agent = wait_for_agent
        self._latest: PlayingLine | None = None
        self._interrupting: list[PlayingLine] = []
        """The lines of the turn that they interrupted, until that turn ends."""
        self._after = After.NOTHING
        self._turn_open = False
        self._turn_voiced = False
        self._voice = False
        self._first_stop_ms: int | None = None
        """When the agent first stopped after the latest line started."""
        self._spoke_again = False
        """Whether the agent spoke again after that first stop."""
        self._going_on: asyncio.Task[None] | None = None
        """While the persona waits for the agent's answer: the time after which it goes on."""

    @property
    def owed(self) -> bool:
        return self._after is After.REPLY

    def busy(self) -> bool:
        """A line plays, or the window of the last line is still open."""
        line = self._latest
        return line is not None and (not line.played or self._clock.ms() < line.window_end_ms)

    def line_started(self, line: PlayingLine) -> None:
        self._interrupting.append(line)
        self._latest = line
        self._first_stop_ms = None
        self._spoke_again = False

    async def line_played(self) -> None:
        assert self._latest is not None
        self._latest.played = True
        await self._settle()

    async def turn_ended(self) -> None:
        """The aggregator's `on_user_turn_stopped`: the turn's words, if it had any, are in the
        context, and its context frame came before. The turn that the lines interrupted is
        decided here."""
        if self._interrupting:
            lines, self._interrupting = self._interrupting, []
            last = lines[-1]
            stopped = (
                self._first_stop_ms is not None
                and last.started_ms <= self._first_stop_ms <= last.window_end_ms
            )
            notes = [NOTE.format(line=playing.spec.say) for playing in lines]
            if stopped:
                notes.append(ANSWERED if self._spoke_again else STOPPED)
            for note in notes:
                self._context.add_message({"role": "system", "content": note})
            self._after = After.WAIT if stopped and not self._spoke_again else After.REPLY
        await self._settle()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.DOWNSTREAM and not self._let_through(frame):
            return
        await self.push_frame(frame, direction)

    def _let_through(self, frame: Frame) -> bool:
        playing = self._latest is not None and not self._latest.played
        if isinstance(frame, InterruptionFrame):
            return not playing
        if isinstance(frame, LLMContextFrame):
            if playing or self._interrupting:
                if not self._interrupting and self._turn_voiced:
                    self._after = After.REPLY
                return False
            self._after = After.NOTHING
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            self._voice = self._turn_voiced = True
            self._spoke_again = self._spoke_again or self._first_stop_ms is not None
            self._stop_going_on()
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._voice = False
            if self._interrupting and self._first_stop_ms is None:
                self._first_stop_ms = self._clock.ms() - round(frame.stop_secs * 1000)
        elif isinstance(frame, UserStartedSpeakingFrame):
            # A turn that starts with no voice was started by a late transcript alone.
            self._turn_open, self._turn_voiced = True, self._voice
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._turn_open = False
        elif isinstance(frame, EndFrame | CancelFrame):
            self._stop_going_on()
        return True

    async def _settle(self) -> None:
        if self._latest is None or not self._latest.played or self._interrupting:
            return
        if self._after is After.REPLY and not self._turn_open:
            self._after = After.NOTHING
            await self.push_frame(LLMContextFrame(context=self._context))
        elif self._after is After.WAIT:
            self._after = After.NOTHING
            await self._wait_for_agent()
            self._going_on = asyncio.create_task(self._go_on())

    async def _go_on(self) -> None:
        await asyncio.sleep(ANSWER_WAIT_S)
        self._going_on = None
        self._context.add_message({"role": "system", "content": GO_ON})
        await self.push_frame(LLMContextFrame(context=self._context))

    def _stop_going_on(self) -> None:
        if self._going_on is not None:
            self._going_on.cancel()
            self._going_on = None


class Interrupter(FrameProcessor):
    """Between the speech to text and the turn aggregator. It follows the agent's answers and
    turns, the words of each turn and the voice detector, and plays a line when a start's wait
    ends with the agent still speaking. It runs in direct mode, with its waits and plays in tasks
    of their own, so the cut that the aggregator sends up the pipeline at each turn start cannot
    cancel them. The aggregator sends its turn frames up and down; this reads the ones going
    up."""

    def __init__(
        self,
        interruptions: Sequence[Interruption],
        audio: Sequence[asyncio.Future[bytes]],
        *,
        vad: SharedSileroVAD,
        transcript: TranscriptBuilder,
        gate: LineGate,
        order: TurnOrder,
        player: SoundPlayer,
        reply_times: ReplyTimes,
        clock: Clock,
        listening: Callable[[], bool],
        ending: Callable[[], bool],
        words_while_speaking: bool,
    ) -> None:
        super().__init__(enable_direct_mode=True)
        self._vad = vad
        self._transcript = transcript
        self._gate = gate
        self._order = order
        self._player = player
        self._reply_times = reply_times
        self._clock = clock
        self._listening = listening
        self._ending = ending
        self._lines = [
            LineState(number, spec, item)
            for number, (spec, item) in enumerate(zip(interruptions, audio, strict=True), 1)
        ]
        self._answer = 0
        self._seen: tuple[int, int] | None = None
        self._turn: AgentTurn | None = None
        self._last_turns: dict[int, AgentTurn] = {}
        """The latest turn of each answer, which a time start's try names."""
        self._playing: list[PlayingLine] = []
        self._tasks: set[asyncio.Task[None]] = set()
        for line in self._lines:
            if line.spec.agent_says is not None and not words_while_speaking:
                self._missed(line, TryReason.NO_WORDS_WHILE_SPEAKING)
            else:
                line.audio.add_done_callback(partial(self._made, line))

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.UPSTREAM:
            if isinstance(frame, UserStartedSpeakingFrame):
                self.turn_started()
            elif isinstance(frame, UserStoppedSpeakingFrame):
                self.turn_stopped()
        elif isinstance(frame, TranscriptionFrame | InterimTranscriptionFrame):
            self.heard(frame.text, final=isinstance(frame, TranscriptionFrame))
        elif isinstance(frame, EndFrame | CancelFrame):
            await self.call_ended()
        await self.push_frame(frame, direction)

    def turn_started(self) -> None:
        """A turn of the agent started. A new answer starts with the first turn while the
        persona is on the line, and with each turn after a persona reply went out or a key
        press, since the agent's previous turn started; an interruption line starts none."""
        if not self._listening():
            self._turn = None
            return
        seen = (self._transcript.replies_out, self._transcript.keys_pressed)
        if seen != self._seen:
            self._answer += 1
            self._answer_started()
        self._seen = seen
        self._turn = self._last_turns[self._answer] = AgentTurn(
            self._answer, self._transcript.agent_turn_started_ms, self._transcript.keys_pressed
        )
        for line in self._open():
            if line.spec.agent_says is not None:
                line.matches = PhraseMatches(line.spec.agent_says)

    def turn_stopped(self) -> None:
        """The turn ended, so no start can play in it any more."""
        if self._turn is not None:
            self._turn.open = False

    def heard(self, text: str, *, final: bool) -> None:
        """Words of the agent: each new match of a phrase starts a wait."""
        turn = self._turn
        if turn is None or not turn.open:
            return
        turn.heard(text, final=final)
        for line in self._open():
            if line.matches is None or turn.answer < line.spec.from_answer:
                continue
            for _ in range(line.matches.heard(turn.words(), final=final)):
                until_ms = self._clock.ms() + round(line.spec.after_s * 1000)
                self._task(self._phrase_waited(line, until_ms, turn))

    async def call_ended(self) -> None:
        """A played line's try is saved now, and each start that still waits is used up."""
        for playing in self._playing:
            self._save(playing)
        tasks, self._tasks = self._tasks, set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _answer_started(self) -> None:
        """Each time trigger counts from the start of each answer, from its `from_answer` on."""
        started = self._transcript.agent_turn_started_ms or self._clock.ms()
        for line in self._open():
            if line.spec.agent_says is None and self._answer >= line.spec.from_answer:
                until_ms = started + round(line.spec.after_s * 1000)
                self._task(self._time_waited(line, until_ms, self._answer))

    async def _phrase_waited(self, line: LineState, until_ms: int, turn: AgentTurn) -> None:
        """A phrase start lives in its turn: the line plays if the agent still speaks in it."""
        try:
            await asyncio.sleep(max(0, until_ms - self._clock.ms()) / 1000)
            state = await self._decided() if turn.open and not line.done else None
        except asyncio.CancelledError:
            self._cut_short(line, turn.answer, turn)
            raise
        if line.done:
            return
        if turn.open and state is VADState.SPEAKING:
            self._play(line, turn)
            return
        reason = TryReason.AGENT_QUIET if turn.open else TryReason.TURN_ENDED
        self._try(line, reason, turn.answer, turn)

    async def _time_waited(self, line: LineState, until_ms: int, answer: int) -> None:
        """A time start lives in its answer. When its wait ends, the line plays at the agent's
        speech in the turn that is open then, at once or after a pause; the end of that turn
        uses the start up, and so does a wait that ends with no turn of the answer open."""
        try:
            await asyncio.sleep(max(0, until_ms - self._clock.ms()) / 1000)
            turn = self._turn
            if self._answer != answer or turn is None or not turn.open:
                if not line.done:
                    self._try(line, TryReason.TURN_ENDED, answer, self._last_turns.get(answer))
                return
            while not line.done and turn.open and self._vad.state is not VADState.SPEAKING:
                await asyncio.sleep(DECIDE_POLL_S)
        except asyncio.CancelledError:
            self._cut_short(line, answer, self._last_turns.get(answer))
            raise
        if line.done:
            return
        if turn.open:
            self._play(line, turn)
        else:
            self._try(line, TryReason.AGENT_QUIET, answer, turn)

    def _cut_short(self, line: LineState, answer: int, turn: AgentTurn | None) -> None:
        """The call ended during a start's wait."""
        if not line.done:
            self._try(line, TryReason.CALL_ENDING, answer, turn)

    async def _decided(self) -> VADState:
        """The voice detector's state once it has decided: while it is starting or stopping, it
        needs more windows."""
        while self._vad.state in (VADState.STARTING, VADState.STOPPING):
            await asyncio.sleep(DECIDE_POLL_S)
        return self._vad.state

    def _play(self, line: LineState, turn: AgentTurn) -> None:
        """Play the line, unless something blocks it. The gate learns of the line at once, so
        that a second wait that ends in the same moment finds it busy."""
        reason = self._blocked(line, turn)
        if reason is not None:
            self._try(line, reason, turn.answer, turn)
            return
        line.done = True
        pcm = line.audio.result()
        started = self._clock.ms()
        playing = PlayingLine(
            line.number,
            line.spec,
            turn,
            started_ms=started,
            window_end_ms=started + first_sound_ms(pcm) + round(STOP_WINDOW_S * 1000),
            words=turn.words(),
        )
        self._playing.append(playing)
        self._order.line_started(line.number)
        self._gate.line_started(playing)
        self._transcript.interruption(line.spec.say, line.number)
        self._task(self._save_at_window_end(playing))
        self._task(self._sound(line, pcm))

    def _blocked(self, line: LineState, turn: AgentTurn) -> TryReason | None:
        if not line.audio.done():
            return TryReason.AUDIO_NOT_READY
        if self._ending():
            return TryReason.CALL_ENDING
        if self._gate.busy():
            return TryReason.OTHER_LINE
        if self._gate.owed:
            return TryReason.REPLY_OWED
        if not self._transcript.caller_quiet:
            return TryReason.CALLER_SPEAKING
        if self._transcript.keys_pressed != turn.keys:
            return TryReason.KEY_PRESS
        return None

    async def _sound(self, line: LineState, pcm: bytes) -> None:
        await self._player.play(pcm, line.spec.say, interruption=line.number)
        await until_played(lambda: self._transcript.caller_quiet, bytes_ms(len(pcm)) / 1000)
        self._reply_times.line_played()
        await self._gate.line_played()

    async def _save_at_window_end(self, playing: PlayingLine) -> None:
        await asyncio.sleep(max(0, playing.window_end_ms - self._clock.ms()) / 1000)
        self._save(playing)

    def _save(self, playing: PlayingLine) -> None:
        if playing.saved:
            return
        playing.saved = True
        self._event(
            playing.started_ms,
            InterruptionTry(
                number=playing.number,
                answer=playing.turn.answer,
                turn_started_ms=playing.turn.started_ms,
                words=playing.words,
                turn_words=bool(playing.turn.words()),
                window_end_ms=playing.window_end_ms,
            ),
        )

    def _made(self, line: LineState, audio: asyncio.Future[bytes]) -> None:
        if audio.cancelled():
            return
        error = audio.exception()
        if error is not None:
            self._missed(line, TryReason.AUDIO_FAILED, describe_exception(error))

    def _missed(self, line: LineState, reason: TryReason, detail: str | None = None) -> None:
        """The interruption can never play: one try says why."""
        if line.done:
            return
        line.done = True
        self._event(
            self._clock.ms(), InterruptionTry(number=line.number, reason=reason, detail=detail)
        )

    def _try(
        self, line: LineState, reason: TryReason, answer: int, turn: AgentTurn | None = None
    ) -> None:
        self._event(
            self._clock.ms(),
            InterruptionTry(
                number=line.number,
                answer=answer,
                turn_started_ms=turn.started_ms if turn else None,
                reason=reason,
            ),
        )

    def _event(self, at_ms: int, attempt: InterruptionTry) -> None:
        self._order.wire_event(
            WireEvent(kind=WireEventKind.INTERRUPTION, at_ms=at_ms, interruption=attempt)
        )

    def _open(self) -> list[LineState]:
        return [line for line in self._lines if not line.done]

    def _task(self, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
