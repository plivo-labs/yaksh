"""The audio every transport shares: 8 kHz mu-law in 20 ms frames, one clock per call, and
the accounting of one reply's playout."""

import time

SAMPLE_RATE = 8000
FRAME_S = 0.02
FRAME_BYTES = 320
SILENCE = b"\x00" * FRAME_BYTES


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
