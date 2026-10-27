"""Turns as judges should read them: what the agent said, and what it actually heard."""

from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    FunctionCallsStartedFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from yaksh.caller.audio import OFFSET, PLAYOUT, Clock, Playout
from yaksh.domain.answering import MachineLine
from yaksh.domain.conversations import CallObserver, Provenance, Role, Turn


@dataclass(frozen=True)
class Queued:
    """Text that a reply about to be spoken carries: generated, fixed, or a machine's line."""

    text: str
    scripted: bool = False
    machine: MachineLine | None = None


@dataclass
class Reply:
    """The persona reply being spoken: its playout, the words released so far, and whether
    the TTS has finished it. A word is its text, the byte where its audio starts, its playout,
    and whether it is untimed: a TTS without word timestamps releases a whole sentence after
    its audio, at the byte where that audio ends."""

    playout: Playout | None
    words: list[tuple[str, int, Playout | None, bool]] = field(default_factory=list)
    started_ms: int = 0
    self_spaced: bool = False
    ended: bool = False

    def add(
        self,
        word: str,
        offset: int,
        playout: Playout | None,
        now_ms: int,
        *,
        self_spaced: bool,
        untimed: bool,
    ) -> None:
        if not self.words:
            self.started_ms = now_ms
            self.self_spaced = self_spaced
        self.words.append((word, offset, playout, untimed))

    def finished(self) -> bool:
        """Ended, and the wire has played its audio and every stamped word is in."""
        return self.ended and (self.playout is None or self.playout.caught_up(len(self.words)))

    def heard(self) -> list[str]:
        """The leading words whose audio has played: a word's up to the next word, an untimed
        sentence's up to its own end."""
        heard: list[str] = []
        for index, (word, offset, playout, untimed) in enumerate(self.words):
            following = self.words[index + 1 : index + 2]
            end = offset if untimed else following[0][1] if following else None
            if playout is None or not playout.heard_until(end):
                break
            heard.append(word)
        return heard


def remainder(generated: str, heard: str) -> str | None:
    """What follows `heard` in `generated`, matched on visible characters; None when the two
    differ, for example when the TTS dropped a character."""
    wanted = [char for char in heard if not char.isspace()]
    matched = index = 0
    while matched < len(wanted):
        if index == len(generated):
            return None
        char = generated[index]
        if not char.isspace():
            if char != wanted[matched]:
                return None
            matched += 1
        index += 1
    return generated[index:].strip()


class TranscriptBuilder:
    """Assembles turns from pipeline events.

    A caller turn holds the words whose audio Plivo reported as played by the time the reply
    ended or was cut off. The rest of the generated reply is kept apart, so a judge never
    reads what the agent may not have heard: as cut after a barge-in, as unconfirmed
    otherwise.

    Caller times are Yaksh's: a turn starts when its first word left Yaksh's output and ends
    when the reply closed. Agent turns run from the first voice activity to the last, each
    moved back by the delay the voice detector needed to decide.
    """

    def __init__(self, clock: Clock, observer: CallObserver) -> None:
        self._clock = clock
        self._observer = observer
        self._agent_started: int | None = None
        self._agent_stopped: int | None = None
        self._voice_started: int | None = None
        self._voice_stopped: int | None = None
        self._generating: list[str] | None = None
        self._generated: deque[Queued] = deque()
        self._reply: Reply | None = None
        self._closed: Playout | None = None
        self.agent_speaking = False
        self.agent_spoke = False
        self._agent_turn_ended_ms: int | None = None
        self.caller_closed_ms: int | None = None
        """When the last caller reply closed: its audio played, or it was cut."""
        self.agent_voice = False
        """The voice detector hears the agent now."""
        self.agent_voice_ended_ms: int | None = None
        """When the voice detector last heard the agent stop."""
        self._generated_words = False
        self._called_after_words: dict[str, bool] = {}

    @property
    def caller_quiet(self) -> bool:
        """No caller reply is being generated, waits to be spoken, or has audio that Plivo has
        not reported played."""
        return self._generating is None and not self._generated and self._reply is None

    @property
    def quiet(self) -> bool:
        """Neither side is speaking: no agent turn is open, and no caller reply is being
        generated, waits to be spoken, or has audio that Plivo has not reported played."""
        return not (
            self.agent_speaking
            or self._generating is not None
            or self._generated
            or self._reply is not None
        )

    def agent_started(self) -> None:
        self.agent_speaking = True
        if self._agent_started is None:
            self._agent_started = self._clock.ms()
            self._agent_stopped = None

    def agent_stopped(self) -> None:
        self.agent_speaking = False
        self._agent_stopped = self._clock.ms()

    def agent_voice_started(self, start_secs: float) -> None:
        self.agent_voice = True
        if self._voice_stopped is not None and not self.agent_speaking:
            self._voice_started = self._voice_stopped = None
            self._agent_started = self._agent_stopped = None
        if self._voice_started is None:
            self._voice_started = self._clock.ms() - round(start_secs * 1000)

    def agent_voice_stopped(self, stop_secs: float) -> None:
        self.agent_voice = False
        self._voice_stopped = self.agent_voice_ended_ms = self._clock.ms() - round(stop_secs * 1000)

    def agent_turn_ended_since(self, ms: int) -> bool:
        """An agent turn ended at or after ms, timed by its voice when the detector heard it."""
        return self._agent_turn_ended_ms is not None and self._agent_turn_ended_ms >= ms

    def agent_said(self, text: str) -> None:
        self.agent_spoke = True
        now = self._clock.ms()
        started = self._voice_started if self._voice_started is not None else self._agent_started
        stopped = self._voice_stopped if self._voice_stopped is not None else self._agent_stopped
        started = now if started is None else started
        stopped = now if stopped is None else stopped
        self._agent_turn_ended_ms = max(started, stopped)
        self._observer.turn(
            Turn(
                role=Role.AGENT,
                text=text,
                started_at_ms=started,
                ended_at_ms=self._agent_turn_ended_ms,
            )
        )
        self._agent_started = self._agent_stopped = None
        self._voice_started = self._voice_stopped = None

    def scripted(self, text: str) -> None:
        """Fixed text about to be spoken for the caller; it takes the place of a generation."""
        self._generated.append(Queued(text, scripted=True))

    def machine(self, text: str, line: MachineLine) -> None:
        """A recorded line of the persona's phone about to play."""
        self._generated.append(Queued(text, machine=line))

    def pressed(self, keys: str) -> None:
        """Keys the caller pressed on its keypad: a turn now, with no audio to wait for."""
        now = self._clock.ms()
        self._observer.turn(
            Turn(role=Role.CALLER, text=keys, started_at_ms=now, ended_at_ms=now, dtmf=True)
        )

    def generation_started(self) -> None:
        self._generating = []
        self._generated_words = False

    def generated(self, text: str) -> None:
        if self._generating is not None:
            self._generating.append(text)
            self._generated_words = self._generated_words or bool(text.strip())

    def calls_started(self, tool_call_ids: Iterable[str]) -> None:
        """The reply being generated calls tools; each call keeps whether the reply had words."""
        for tool_call_id in tool_call_ids:
            self._called_after_words[tool_call_id] = self._generated_words

    def called_after_words(self, tool_call_id: str) -> bool:
        return self._called_after_words.pop(tool_call_id, False)

    def generation_ended(self) -> None:
        if self._generating is None:
            return
        text = "".join(self._generating).strip()
        if text:
            self._generated.append(Queued(text))
        self._generating = None

    def caller_started(self, playout: Playout | None) -> None:
        if self._reply is not None and self._reply.playout is playout:
            return
        if self._reply is not None:
            self._close(cut=False)
        self._reply = Reply(playout)

    def transmitted(
        self,
        word: str,
        offset: int,
        playout: Playout | None,
        *,
        self_spaced: bool,
        untimed: bool = False,
    ) -> None:
        """A spoken word whose audio starts `offset` bytes into its reply.

        Words and the reply's end travel on different transport tasks, so a word can land after
        its reply closed; a stamped word for the reply that just closed is dropped rather than
        starting a phantom reply.
        """
        if playout is not None and playout is self._closed:
            return
        if self._reply is None:
            self._reply = Reply(playout)
        self._reply.add(
            word, offset, playout, self._clock.ms(), self_spaced=self_spaced, untimed=untimed
        )
        self.audio_progressed()

    def reply_ended(self, playout: Playout | None = None) -> None:
        """The TTS finished the reply; it closes once the wire has sent its audio and every
        stamped word is in."""
        if self._reply is None or (playout is not None and playout is not self._reply.playout):
            return
        self._reply.ended = True
        self.audio_progressed()

    def audio_progressed(self) -> None:
        if self._reply is not None and self._reply.finished():
            self._close(cut=False)

    def call_ended(self) -> None:
        """Close the open reply; text generated but never started is kept as unconfirmed."""
        if self._reply is not None:
            self._close(cut=False)
        now = self._clock.ms()
        while self._generated:
            self._caller_turn(self._generated.popleft(), None, now, now, Provenance.UNCONFIRMED)

    def caller_interrupted(self) -> None:
        self.generation_ended()
        self._close(cut=True)

    def _close(self, *, cut: bool) -> None:
        reply = self._reply
        if reply is None and not cut:
            return
        reply = reply if reply is not None else Reply(None)
        self._reply = None
        if reply.playout is not None:
            self._closed = reply.playout
        now = self.caller_closed_ms = self._clock.ms()
        queued = self._generated.popleft() if self._generated else Queued("")
        heard = reply.heard()
        text = ("" if reply.self_spaced else " ").join(heard).strip()
        if text:
            self._caller_turn(queued, text, reply.started_ms, now, Provenance.TRANSMITTED)
        if cut or len(heard) < len(reply.words) or not text:
            rest = remainder(queued.text, text) if queued.text else None
            if rest is None:
                rest = " ".join(word for word, *_ in reply.words[len(heard) :]).strip()
            if rest:
                provenance = Provenance.CUT if cut else Provenance.UNCONFIRMED
                self._caller_turn(queued, rest, now, now, provenance)
        if cut:
            while self._generated:
                self._caller_turn(self._generated.popleft(), None, now, now, Provenance.CUT)

    def _caller_turn(
        self, queued: Queued, text: str | None, started: int, ended: int, provenance: Provenance
    ) -> None:
        """text is the part of the queued text that the turn holds; None holds all of it."""
        self._observer.turn(
            Turn(
                role=Role.CALLER,
                text=queued.text if text is None else text,
                started_at_ms=started,
                ended_at_ms=ended,
                provenance=provenance,
                scripted=queued.scripted,
                machine=queued.machine,
            )
        )


def last_user_message(context: LLMContext) -> str | None:
    messages = context.get_messages()
    last: Any = messages[-1] if messages else None
    if not isinstance(last, dict) or last.get("role") != "user":
        return None
    content = last.get("content")
    return content if isinstance(content, str) else None


class AgentTurnTap(FrameProcessor):
    """After the user aggregator: the agent's turns, timed by voice activity when it is known
    and by the turn detector otherwise, worded by the aggregator."""

    def __init__(self, transcript: TranscriptBuilder) -> None:
        super().__init__(enable_direct_mode=True)
        self._transcript = transcript

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.DOWNSTREAM:
            if isinstance(frame, VADUserStartedSpeakingFrame):
                self._transcript.agent_voice_started(frame.start_secs)
            elif isinstance(frame, VADUserStoppedSpeakingFrame):
                self._transcript.agent_voice_stopped(frame.stop_secs)
            elif isinstance(frame, UserStartedSpeakingFrame):
                self._transcript.agent_started()
            elif isinstance(frame, UserStoppedSpeakingFrame):
                self._transcript.agent_stopped()
            elif isinstance(frame, LLMContextFrame) and not frame.speculation:
                text = last_user_message(frame.context)
                if text:
                    self._transcript.agent_said(text)
        await self.push_frame(frame, direction)


class GeneratedTap(FrameProcessor):
    """After the persona LLM: the reply as generated, before any of it is spoken."""

    def __init__(self, transcript: TranscriptBuilder) -> None:
        super().__init__(enable_direct_mode=True)
        self._transcript = transcript

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.DOWNSTREAM:
            if isinstance(frame, LLMFullResponseStartFrame):
                self._transcript.generation_started()
            elif isinstance(frame, LLMTextFrame):
                self._transcript.generated(frame.text)
            elif isinstance(frame, FunctionCallsStartedFrame):
                self._transcript.calls_started(call.tool_call_id for call in frame.function_calls)
            elif isinstance(frame, LLMFullResponseEndFrame | InterruptionFrame):
                self._transcript.generation_ended()
        await self.push_frame(frame, direction)


class WireTap(FrameProcessor):
    """After the transport: a reply's spoken words, each stamped by the transport with where
    it starts in the reply's audio, until the reply ends or is cut.

    Runs in direct mode, on the pushing task, so no word waits in a queue an interruption
    would flush. A reply ends with the response end frame the TTS re-pushes after its last
    word and is finalized once the wire has sent the audio; a cut waits for the wire to
    settle, so a frame that lands late still counts.
    """

    def __init__(
        self, transcript: TranscriptBuilder, settle: Callable[[], Awaitable[None]]
    ) -> None:
        super().__init__(enable_direct_mode=True)
        self._transcript = transcript
        self._settle = settle

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.DOWNSTREAM:
            if isinstance(frame, TTSStartedFrame):
                self._transcript.caller_started(frame.metadata.get(PLAYOUT))
            elif isinstance(frame, TTSTextFrame):
                self._transcript.transmitted(
                    frame.text,
                    frame.metadata.get(OFFSET, 0),
                    frame.metadata.get(PLAYOUT),
                    self_spaced=frame.includes_inter_frame_spaces,
                    untimed=frame.pts is None,
                )
            elif isinstance(frame, TTSAudioRawFrame):
                self._transcript.audio_progressed()
            elif isinstance(frame, LLMFullResponseEndFrame | TTSStoppedFrame):
                self._transcript.reply_ended(frame.metadata.get(PLAYOUT))
            elif isinstance(frame, EndFrame):
                self._transcript.call_ended()
            elif isinstance(frame, CancelFrame):
                await self._settle()
                self._transcript.call_ended()
            elif isinstance(frame, InterruptionFrame):
                await self._settle()
                self._transcript.caller_interrupted()
        await self.push_frame(frame, direction)
