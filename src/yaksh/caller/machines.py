"""The pipeline's parts for fixed audio on the persona's side: a player for the voicemail's and
the screener's recordings and for the scenario's interruption lines, the wait until such a line
has played, and a gate that keeps the persona quiet while the machines answer."""

import asyncio
from collections.abc import Callable

from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from yaksh.caller.audio import FRAME_BYTES, INTERRUPTION, MACHINE, SAMPLE_RATE
from yaksh.domain.answering import MachineLine

POLL_S = 0.1
PLAY_SLACK_S = 3.0
"""How much longer than its audio a line may take to be reported played."""


async def until_played(done: Callable[[], bool], audio_s: float) -> None:
    """Return once done() holds, or when the line's audio length plus PLAY_SLACK_S has passed:
    a Plivo report that never comes does not hold the call."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + audio_s + PLAY_SLACK_S
    while not done() and loop.time() < deadline:
        await asyncio.sleep(POLL_S)


class SoundPlayer(FrameProcessor):
    """Right after the TTS: plays a machine's audio or an interruption line as a reply of its
    own, so the transcript, the recording and the played-audio reports treat it as they treat
    the persona's speech. A spoken line carries its words after its audio, as a TTS without word
    timestamps sends a sentence, kept out of the persona's context; the tone carries none."""

    def __init__(self) -> None:
        super().__init__(enable_direct_mode=True)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

    async def play(
        self,
        pcm: bytes,
        text: str | None,
        *,
        machine: MachineLine | None = None,
        interruption: int | None = None,
    ) -> None:
        """Play a machine's line or an interruption's line, marked as the one or the other."""
        started = TTSStartedFrame(append_to_context=False)
        if machine is not None:
            started.metadata[MACHINE] = machine
        if interruption is not None:
            started.metadata[INTERRUPTION] = interruption
        await self.push_frame(started)
        for at in range(0, len(pcm), FRAME_BYTES):
            await self.push_frame(TTSAudioRawFrame(pcm[at : at + FRAME_BYTES], SAMPLE_RATE, 1))
        if text:
            words = TTSTextFrame(text, text_type="sentence")
            words.append_to_context = False
            await self.push_frame(words)
        await self.push_frame(TTSStoppedFrame())


class MachineGate(FrameProcessor):
    """Between the agent's turns and the turn limit. While a machine answers, the agent's turns
    reach the transcript but the persona does not answer them, they do not count to the turn
    limit, and the agent's voice does not stop a recording: a machine neither listens nor
    stops when talked over. Once the persona picks up, every frame passes."""

    def __init__(self) -> None:
        super().__init__(enable_direct_mode=True)
        self.closed = True

    def open(self) -> None:
        self.closed = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if (
            self.closed
            and direction is FrameDirection.DOWNSTREAM
            and isinstance(frame, LLMContextFrame | InterruptionFrame)
        ):
            return
        await self.push_frame(frame, direction)
