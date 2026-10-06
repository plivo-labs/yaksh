"""The audio the phone leg works in: 8 kHz in 20 ms frames, one clock per call, the
accounting of one reply's playout, and the call's recording."""

import time
import wave
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
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

from yaksha.domain.latency import AgentMedia, CallerReplyWindow, Span

SAMPLE_RATE = 8000
FRAME_BYTES = 320
LOUD_PEAK = 500
GAP_BYTES = SAMPLE_RATE * 2 // 5
PLAYOUT = "yaksha.playout"
OFFSET = "yaksha.offset"


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
        self.audio = bytearray()
        """The reply's audio as the TTS made it, before any background noise."""
        self._sent = 0
        self._origin: int | None = None
        self._words = 0

    @property
    def arrived(self) -> int:
        return self._arrived

    def received(self, audio: bytes, now_ns: int) -> None:
        if self._origin is None:
            self._origin = now_ns
        self._arrived += len(audio)
        self.audio += audio

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
            self.arriving.received(frame.audio, now_ns)
        elif isinstance(frame, TTSTextFrame) and self.arriving is not None:
            frame.metadata[PLAYOUT] = self.arriving
            frame.metadata[OFFSET] = self.arriving.stamp_word(frame.pts)
        elif isinstance(frame, TTSStoppedFrame | LLMFullResponseEndFrame) and self.arriving:
            frame.metadata[PLAYOUT] = self.arriving


@dataclass
class CallerReply:
    """One reply of the persona: when its audio started and stopped going out, and, when the
    TTS finished it, its playout with the audio before any background noise."""

    start_ms: int
    end_ms: int | None = None
    playout: Playout | None = None
    finished: bool = False
    """The TTS finished the reply: its playout holds all of it."""


def save_caller_voice(replies: Sequence[CallerReply], path: Path) -> list[CallerReplyWindow]:
    """Write each reply's own audio, back to back, as a mono WAV, and say where each one is. A
    reply cut off keeps only as much as went out before the cut; one that the end of the call
    cut off keeps all it had."""
    voice = bytearray()
    windows = []
    for reply in replies:
        own = bytes(reply.playout.audio) if reply.playout else b""
        if not reply.finished and reply.end_ms is not None:
            own = own[: ms_bytes(reply.end_ms - reply.start_ms)]
        windows.append(
            CallerReplyWindow(
                start_ms=reply.start_ms,
                end_ms=reply.end_ms,
                finished=reply.finished,
                audio_start_ms=bytes_ms(len(voice)),
                audio_ms=bytes_ms(len(own)),
            )
        )
        voice += own
    if voice:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as file:
            file.setnchannels(1)
            file.setsampwidth(2)
            file.setframerate(SAMPLE_RATE)
            file.writeframes(voice)
    return windows


class CallRecording:
    """Both sides of a call as a stereo WAV on Yaksha's clock: left, the agent at the
    timestamp Plivo puts on each frame; right, the caller at the time Yaksha sent each frame.

    Plivo's timestamps move onto Yaksha's clock by the shortest delay that any frame had, so
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

    def agent_track(self, start_ms: int) -> bytes:
        """The agent's side from start_ms on, as the recording holds it."""
        return bytes(track(self._agent_frames(), start_ms))

    def agent_media(self, start_ms: int) -> AgentMedia | None:
        """Where the line carried the agent's audio, on the call's clock; None when no audio
        came."""
        frames = self._agent_frames()
        if not frames:
            return None
        audio, gaps = placed(frames, start_ms)
        return AgentMedia(
            first_ms=start_ms + (gaps[0].end_ms if gaps and gaps[0].start_ms == 0 else 0),
            last_ms=start_ms + bytes_ms(len(audio)),
            gaps=[
                Span(start_ms=start_ms + gap.start_ms, end_ms=start_ms + gap.end_ms)
                for gap in gaps
                if gap.start_ms > 0
            ],
        )

    def save(self, path: Path, start_ms: int) -> Path | None:
        """Write the recording from start_ms on, if any audio came after it."""
        agent = self.agent_track(start_ms)
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
    """One side from start_ms on, each frame at its time on Yaksha's clock."""
    return placed(frames, start_ms)[0]


def placed(frames: Iterable[tuple[int, bytes]], start_ms: int) -> tuple[bytearray, list[Span]]:
    """One side from start_ms on, and the stretches between frames that it fills with silence,
    in ms from start_ms."""
    audio = bytearray()
    gaps: list[Span] = []
    for at_ms, pcm in frames:
        at = (at_ms - start_ms) * SAMPLE_RATE // 1000 * 2
        if at > len(audio) + FRAME_BYTES:
            gaps.append(Span(start_ms=bytes_ms(len(audio)), end_ms=bytes_ms(at)))
            audio += bytes(at - len(audio))
        audio += pcm[max(0, -at) :]
    return audio, gaps


def bytes_ms(size: int) -> int:
    return round(size * 1000 / (2 * SAMPLE_RATE))


def ms_bytes(ms: int) -> int:
    return max(0, ms) * SAMPLE_RATE // 1000 * 2
