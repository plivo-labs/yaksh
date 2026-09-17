"""Turns as judges should read them: what the agent said, and what it actually heard."""

from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
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
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from truman.caller.audio import FRAME_BYTES, OFFSET, PLAYOUT, Clock, Playout
from truman.domain.conversations import CallObserver, Provenance, Role, Turn


class TranscriptBuilder:
    """Assembles turns from pipeline events.

    A caller turn holds the words whose audio the wire had sent in full by the time the reply
    ended or was cut off; the rest of the generated reply is kept apart as cut, so a judge
    never reads what the agent did not hear. A reply with no audio evidence is all cut.
    """

    def __init__(self, clock: Clock, observer: CallObserver) -> None:
        self._clock = clock
        self._observer = observer
        self._agent_started: int | None = None
        self._agent_stopped: int | None = None
        self._generating: list[str] | None = None
        self._generated: deque[str] = deque()
        self._open = False
        self._ended = False
        self._playout: Playout | None = None
        self._closed: Playout | None = None
        self._words: list[tuple[str, int, Playout | None]] = []
        self._words_started = 0
        self._self_spaced = False
        self.agent_speaking = False
        self.agent_spoke = False

    def agent_started(self) -> None:
        self.agent_speaking = True
        if self._agent_started is None:
            self._agent_started = self._clock.ms()
            self._agent_stopped = None

    def agent_stopped(self) -> None:
        self.agent_speaking = False
        self._agent_stopped = self._clock.ms()

    def agent_said(self, text: str) -> None:
        self.agent_spoke = True
        now = self._clock.ms()
        started = now if self._agent_started is None else self._agent_started
        stopped = now if self._agent_stopped is None else self._agent_stopped
        self._observer.turn(
            Turn(
                role=Role.AGENT, text=text, started_at_ms=started, ended_at_ms=max(started, stopped)
            )
        )
        self._agent_started = self._agent_stopped = None

    def generation_started(self) -> None:
        self._generating = []

    def generated(self, text: str) -> None:
        if self._generating is not None:
            self._generating.append(text)

    def generation_ended(self) -> None:
        if self._generating is None:
            return
        text = "".join(self._generating).strip()
        if text:
            self._generated.append(text)
        self._generating = None

    def caller_started(self, playout: Playout | None) -> None:
        if self._open and self._playout is playout:
            return
        if self._open:
            self._close(cut=False)
        self._open_reply(playout)

    def transmitted(
        self, word: str, offset: int, playout: Playout | None, *, self_spaced: bool
    ) -> None:
        """A spoken word whose audio starts `offset` bytes into its reply.

        Words and the reply's end travel on different transport tasks, so a word can land after
        its reply closed; a stamped word for the reply that just closed is dropped rather than
        starting a phantom reply.
        """
        if playout is not None and playout is self._closed:
            return
        if not self._open:
            self._open_reply(playout)
        if not self._words:
            self._words_started = self._clock.ms()
            self._self_spaced = self_spaced
        self._words.append((word, offset, playout))
        self.audio_progressed()

    def reply_ended(self, playout: Playout | None = None) -> None:
        """The TTS finished the reply; it closes once the wire has sent its audio and every
        stamped word is in."""
        if playout is not None and playout is not self._playout:
            return
        self._ended = True
        self.audio_progressed()

    def audio_progressed(self) -> None:
        playout = self._playout
        caught_up = playout is None or (
            playout.sent + FRAME_BYTES >= playout.arrived and len(self._words) >= playout.words
        )
        if self._open and self._ended and caught_up:
            self._close(cut=False)

    def call_ended(self) -> None:
        if self._open:
            self._close(cut=False)

    def caller_interrupted(self) -> None:
        self.generation_ended()
        self._close(cut=True)

    def _open_reply(self, playout: Playout | None) -> None:
        self._open = True
        self._ended = False
        self._playout = playout
        self._words = []

    def _close(self, *, cut: bool) -> None:
        if not self._open and not cut:
            return
        self._open = False
        self._ended = False
        if self._playout is not None:
            self._closed = self._playout
        self._playout = None
        now = self._clock.ms()
        generated = self._generated.popleft() if self._generated else None
        heard = self._heard()
        text = ("" if self._self_spaced else " ").join(heard).strip()
        if text:
            self._caller_turn(text, self._words_started, now, Provenance.TRANSMITTED)
        if cut or len(heard) < len(self._words) or not text:
            rest = (
                generated.split()[len(heard) :]
                if generated
                else [word for word, _, _ in self._words[len(heard) :]]
            )
            if rest:
                self._caller_turn(" ".join(rest), now, now, Provenance.CUT)
        self._words = []

    def _heard(self) -> list[str]:
        """The leading words whose audio, up to the next word, the wire sent in full.

        One frame of slack covers the trailing partial chunk the media sender drops.
        """
        heard: list[str] = []
        for index, (word, _, playout) in enumerate(self._words):
            if playout is None or playout.sent <= 0:
                break
            following = self._words[index + 1 : index + 2]
            end = following[0][1] if following else playout.arrived
            if end > playout.sent + FRAME_BYTES:
                break
            heard.append(word)
        return heard

    def _caller_turn(self, text: str, started: int, ended: int, provenance: Provenance) -> None:
        self._observer.turn(
            Turn(
                role=Role.CALLER,
                text=text,
                started_at_ms=started,
                ended_at_ms=ended,
                provenance=provenance,
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
    """After the user aggregator: the agent's turns, timed by VAD, worded by the aggregator."""

    def __init__(self, transcript: TranscriptBuilder) -> None:
        super().__init__(enable_direct_mode=True)
        self._transcript = transcript

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.DOWNSTREAM:
            if isinstance(frame, UserStartedSpeakingFrame):
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
                )
            elif isinstance(frame, TTSAudioRawFrame):
                self._transcript.audio_progressed()
            elif isinstance(frame, LLMFullResponseEndFrame | TTSStoppedFrame):
                self._transcript.reply_ended(frame.metadata.get(PLAYOUT))
            elif isinstance(frame, EndFrame):
                self._transcript.call_ended()
            elif isinstance(frame, InterruptionFrame | CancelFrame):
                await self._settle()
                self._transcript.caller_interrupted()
        await self.push_frame(frame, direction)
