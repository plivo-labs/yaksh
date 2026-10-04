"""The audio the phone leg works in: 8 kHz in 20 ms frames, one clock per call, the
accounting of one reply's playout, and the call's recording."""

import time
import wave
from collections.abc import Iterable
from pathlib import Path

import audioop
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


class CallRecording:
    """Both sides of a call as a stereo WAV on Truman's clock: left, the agent at the
    timestamp Plivo puts on each frame; right, the caller at the time Truman sent each frame.

    Plivo's timestamps move onto Truman's clock by the shortest delay that any frame had, so
    frames that waited in a queue keep their place. A frame without a timestamp counts at its
    arrival. A frame that starts before the end of its side, or up to one frame after it,
    follows it directly, as Plivo plays queued audio back to back; a later frame leaves
    silence. After a clearAudio, the right side can hold audio that Plivo dropped and the
    agent never heard.
    """

    def __init__(self) -> None:
        self._agent: list[tuple[int, int | None, bytes]] = []
        self._caller: list[tuple[int, bytes]] = []

    def agent(self, pcm: bytes, at_ms: int, plivo_ms: int | None) -> None:
        self._agent.append((at_ms, plivo_ms, pcm))

    def caller(self, pcm: bytes, at_ms: int) -> None:
        self._caller.append((at_ms, pcm))

    def start_ms(self, connected_ms: int) -> int:
        """Where the call's audio starts: at connected_ms, or earlier at the agent's first
        frame. An agent that speaks first starts when Plivo answers, and Plivo stamps that audio
        from before it opens the stream."""
        return min([connected_ms] + [at for at, _ in self._agent_frames()])

    def save(self, path: Path, start_ms: int) -> Path | None:
        """Write the recording from start_ms on, if any audio came after it."""
        agent = track(self._agent_frames(), start_ms)
        caller = track(self._caller, start_ms)
        size = max(len(agent), len(caller))
        if size == 0:
            return None
        stereo = audioop.add(
            audioop.tostereo(agent.ljust(size, b"\0"), 2, 1, 0),
            audioop.tostereo(caller.ljust(size, b"\0"), 2, 0, 1),
            2,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as recording:
            recording.setnchannels(2)
            recording.setsampwidth(2)
            recording.setframerate(SAMPLE_RATE)
            recording.writeframes(stereo)
        return path

    def _agent_frames(self) -> list[tuple[int, bytes]]:
        offset = min((at - plivo for at, plivo, _ in self._agent if plivo is not None), default=0)
        return [(at if plivo is None else plivo + offset, pcm) for at, plivo, pcm in self._agent]


def track(frames: Iterable[tuple[int, bytes]], start_ms: int) -> bytearray:
    """One side from start_ms on, each frame at its time on Truman's clock."""
    audio = bytearray()
    for at_ms, pcm in frames:
        at = (at_ms - start_ms) * SAMPLE_RATE // 1000 * 2
        if at > len(audio) + FRAME_BYTES:
            audio += bytes(at - len(audio))
        audio += pcm[max(0, -at) :]
    return audio
