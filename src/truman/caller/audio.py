"""The audio every transport shares: 8 kHz mu-law in 20 ms frames, one clock per call, and
the accounting of one reply's playout."""

import time

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)

SAMPLE_RATE = 8000
FRAME_S = 0.02
FRAME_BYTES = 320
SILENCE = b"\x00" * FRAME_BYTES
PLAYOUT = "truman.playout"
OFFSET = "truman.offset"


class Clock:
    def __init__(self) -> None:
        self._started = time.monotonic()

    def ms(self) -> int:
        return int((time.monotonic() - self._started) * 1000)


class Playout:
    """One reply's audio: bytes that arrived from the TTS, bytes the wire has sent, and how
    many words were stamped against it."""

    def __init__(self) -> None:
        self.arrived = 0
        self.sent = 0
        self.origin: int | None = None
        self.words = 0

    def offset_of(self, pts: int | None) -> int:
        """Where audio stamped `pts` on the pipeline clock starts, in bytes of the reply."""
        if pts is None or self.origin is None:
            return self.arrived
        return max(0, (pts - self.origin) * SAMPLE_RATE * 2 // 1_000_000_000)


class Stamper:
    """Marks a reply's frames with its playout as they pass the transport output, in order: the
    audio bytes that arrived, the origin of the word timestamps, and where each word starts."""

    def __init__(self) -> None:
        self.arriving: Playout | None = None

    def stamp(self, frame: Frame, now_ns: int) -> None:
        if isinstance(frame, TTSStartedFrame):
            self.arriving = frame.metadata[PLAYOUT] = Playout()
        elif isinstance(frame, TTSAudioRawFrame) and self.arriving is not None:
            if self.arriving.origin is None:
                self.arriving.origin = now_ns
            self.arriving.arrived += len(frame.audio)
        elif isinstance(frame, TTSTextFrame) and self.arriving is not None:
            frame.metadata[PLAYOUT] = self.arriving
            frame.metadata[OFFSET] = self.arriving.offset_of(frame.pts)
            self.arriving.words += 1
        elif isinstance(frame, TTSStoppedFrame | LLMFullResponseEndFrame) and self.arriving:
            frame.metadata[PLAYOUT] = self.arriving
