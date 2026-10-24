"""The pipeline's parts for the persona's phone: a player for the voicemail's and the screener's
recordings, and a gate that keeps the persona quiet while they play."""

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

from yaksh.caller.audio import FRAME_BYTES, MACHINE, SAMPLE_RATE
from yaksh.domain.answering import MachineLine


class SoundPlayer(FrameProcessor):
    """Right after the TTS: plays machine audio as a reply of its own, so the transcript, the
    recording and the played-audio reports treat it as they treat the persona's speech. A
    spoken line carries its words, kept out of the persona's context; the tone carries none."""

    def __init__(self) -> None:
        super().__init__(enable_direct_mode=True)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

    async def play(self, pcm: bytes, text: str | None, line: MachineLine) -> None:
        started = TTSStartedFrame(append_to_context=False)
        started.metadata[MACHINE] = line
        await self.push_frame(started)
        if text:
            words = TTSTextFrame(text, text_type="sentence")
            words.append_to_context = False
            await self.push_frame(words)
        for at in range(0, len(pcm), FRAME_BYTES):
            await self.push_frame(TTSAudioRawFrame(pcm[at : at + FRAME_BYTES], SAMPLE_RATE, 1))
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
