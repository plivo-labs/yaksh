"""The audio the phone leg works in: 8 kHz in 20 ms frames, one clock per call, and the
accounting of one reply's playout."""

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
FRAME_BYTES = 320
LOUD_PEAK = 500
GAP_BYTES = SAMPLE_RATE * 2 // 5
PLAYOUT = "truman.playout"
OFFSET = "truman.offset"


class Clock:
    def __init__(self) -> None:
        self._started = time.monotonic()

    def ms(self) -> int:
        return int((time.monotonic() - self._started) * 1000)


class Playout:
    """One reply's audio: bytes that arrived from the TTS, bytes Plivo reported as played,
    and how many words were stamped against it.

    Audio counts as played with one frame of slack, which covers the trailing partial chunk
    the media sender drops.
    """

    def __init__(self) -> None:
        self._arrived = 0
        self._sent = 0
        self._origin: int | None = None
        self._words = 0

    @property
    def arrived(self) -> int:
        return self._arrived

    def received(self, size: int, now_ns: int) -> None:
        if self._origin is None:
            self._origin = now_ns
        self._arrived += size

    def stamp_word(self, pts: int | None) -> int:
        """Count a word and return where its audio starts, in bytes of the reply."""
        self._words += 1
        if pts is None or self._origin is None:
            return self._arrived
        return max(0, (pts - self._origin) * SAMPLE_RATE * 2 // 1_000_000_000)

    def played(self, through: int) -> None:
        self._sent = max(self._sent, through)

    def caught_up(self, words_in: int) -> bool:
        """All audio played and every stamped word has come through."""
        return self._sent + FRAME_BYTES >= self._arrived and words_in >= self._words

    def heard_until(self, end: int | None) -> bool:
        """Whether the audio up to byte `end`, or to the end of the reply, has played."""
        limit = self._arrived if end is None else end
        return self._sent > 0 and limit <= self._sent + FRAME_BYTES


class Stamper:
    """Marks a reply's frames with its playout as they pass the transport output, in order: the
    audio bytes that arrived, the origin of the word timestamps, and where each word starts."""

    def __init__(self) -> None:
        self.arriving: Playout | None = None

    def stamp(self, frame: Frame, now_ns: int) -> None:
        if isinstance(frame, TTSStartedFrame):
            self.arriving = frame.metadata[PLAYOUT] = Playout()
        elif isinstance(frame, TTSAudioRawFrame) and self.arriving is not None:
            self.arriving.received(len(frame.audio), now_ns)
        elif isinstance(frame, TTSTextFrame) and self.arriving is not None:
            frame.metadata[PLAYOUT] = self.arriving
            frame.metadata[OFFSET] = self.arriving.stamp_word(frame.pts)
        elif isinstance(frame, TTSStoppedFrame | LLMFullResponseEndFrame) and self.arriving:
            frame.metadata[PLAYOUT] = self.arriving
