"""The agent's response times, from its speech in the call recording as the live voice detector
finds it."""

import asyncio
import logging
import math
from collections.abc import AsyncIterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from multiprocessing import get_context

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADState
from pipecat.audio.volume import VOLUME_WINDOW_SECS

from truman.caller.audio import SAMPLE_RATE, Playout
from truman.caller.pipeline import VAD
from truman.domain.latency import Latency, response_times

log = logging.getLogger(__name__)

type Track = tuple[int, int | None, bytes | None]
"""A caller reply as the detector process gets it: its audio start and end on the call's clock,
and the reply's own audio when the TTS finished it."""


@dataclass
class CallerReply:
    """One reply of the persona: when its audio started and stopped going out, and, when the
    TTS finished it, its playout with the audio before any background noise."""

    start_ms: int
    end_ms: int | None = None
    playout: Playout | None = None

    def track(self) -> Track:
        audio = None if self.end_ms is None or self.playout is None else bytes(self.playout.audio)
        return self.start_ms, self.end_ms, audio


class Detector:
    """The voice detector for finished calls, in a process of its own. Loading the Silero model
    holds the GIL for about 35 ms, and a call loads it once per track, so in the worker's
    process every load would stall the audio of the calls still running. The worker starts the
    process when it starts, so the first call does not wait for it; otherwise the first
    measurement starts it."""

    def __init__(self) -> None:
        self._pool: ProcessPoolExecutor | None = None

    def start(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"))
            self._pool.submit(warm_up)
        return self._pool

    async def measure(
        self, agent: bytes, started_ms: int, connected_ms: int, replies: Sequence[CallerReply]
    ) -> Latency | None:
        """The call's response times, from the agent's channel as recorded from started_ms on
        and the moment Truman's stream opened. A detector that fails leaves the call
        unmeasured; it does not take the call's outcome with it."""
        loop = asyncio.get_running_loop()
        tracks = [reply.track() for reply in replies]
        try:
            starts, stops = await loop.run_in_executor(self.start(), detect, agent, tracks)
        except BrokenProcessPool:
            log.exception("the voice detector process stopped; the next call starts a new one")
            self._pool = None
            return None
        except Exception:
            log.exception("could not find the speech in the recording")
            return None
        return response_times(
            connected_ms,
            [(reply.start_ms, stop) for reply, stop in zip(replies, stops, strict=True)],
            [started_ms + at for at in starts],
        )


def warm_up() -> None:
    """Load the detector's code and model once, so a call's measurement does not wait for it."""
    SileroVADAnalyzer(params=VAD)


def detect(agent: bytes, replies: Sequence[Track]) -> tuple[list[int], list[int | None]]:
    """In the detector process: where the agent's speech starts, and where each reply's speech
    ends. Every track gets a fresh analyzer, so no state crosses from one to the next."""
    return asyncio.run(detect_all(agent, replies))


async def detect_all(agent: bytes, replies: Sequence[Track]) -> tuple[list[int], list[int | None]]:
    return await speech_starts(agent), [await speech_stopped(reply) for reply in replies]


async def speech_stopped(reply: Track) -> int | None:
    """When the reply's speech ended on the call's clock: its audio stopped going out at its
    end, after a quiet tail that the TTS puts after the last word. The same detector finds the
    last word in the reply's own audio, so background noise does not move it. A reply cut off
    keeps its end: its sent audio is not the audio the TTS made."""
    _start_ms, end_ms, audio = reply
    if end_ms is None or audio is None:
        return end_ms
    ends = [end async for end, _, state in windows(audio) if state is VADState.SPEAKING]
    if not ends:
        return end_ms
    return end_ms - round(len(audio) * 1000 / (2 * SAMPLE_RATE) - ends[-1])


async def speech_starts(agent: bytes) -> list[int]:
    """Where speech starts in the agent's channel, in ms from its first sample. The analyzer turns
    to speaking only after a few windows of speech; the start is that many windows earlier."""
    starts: list[int] = []
    before = VADState.QUIET
    async for end, window_ms, state in windows(agent):
        if state is VADState.SPEAKING and before in (VADState.QUIET, VADState.STARTING):
            deciding_ms = round(VAD.start_secs * 1000 / window_ms) * window_ms
            starts.append(round(end - deciding_ms))
        before = state
    return starts


async def windows(pcm: bytes) -> AsyncIterator[tuple[float, float, VADState]]:
    """The live detector's state after each window of pcm, with the window's end and length in
    ms. The analyzer first hears the silence that comes before pcm: its volume reads 0 until it
    holds VOLUME_WINDOW_SECS of audio, so without that it cannot hear the start of pcm. The
    silence fills whole windows, so that each window of pcm starts where its time says."""
    analyzer = SileroVADAnalyzer(params=VAD)
    analyzer.set_sample_rate(SAMPLE_RATE)  # what a pipeline does at start; it sets the windows
    window = analyzer.num_frames_required() * 2
    window_ms = window * 1000 / (2 * SAMPLE_RATE)
    try:
        await analyzer.analyze_audio(
            bytes(math.ceil(VOLUME_WINDOW_SECS * 1000 / window_ms) * window)
        )
        for at in range(0, len(pcm) - window + 1, window):
            state = await analyzer.analyze_audio(pcm[at : at + window])
            yield (at + window) * 1000 / (2 * SAMPLE_RATE), window_ms, state
    finally:
        await analyzer.cleanup()
