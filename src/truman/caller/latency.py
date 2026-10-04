"""Where each side spoke and how long the agent made the caller wait, from the call's audio as
the live voice detector finds it."""

import asyncio
import logging
import math
from collections.abc import AsyncIterator, Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from multiprocessing import get_context

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADState
from pipecat.audio.volume import VOLUME_WINDOW_SECS

from truman.caller.audio import SAMPLE_RATE, Playout, bytes_ms
from truman.caller.pipeline import VAD
from truman.domain.latency import Latency, Span, Speech, response_times

log = logging.getLogger(__name__)

type Track = tuple[int, int | None, bytes | None]
"""A caller reply as the detector process gets it: its audio start and end on the call's clock,
and the reply's own audio when the TTS finished it."""
type Window = tuple[float, float, VADState]
"""The detector's state after one window of audio: the window's end and length in ms."""


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


@dataclass(frozen=True)
class Measured:
    latency: Latency
    speech: Speech


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
        self,
        agent: bytes,
        agent_gaps: Sequence[Span],
        started_ms: int,
        connected_ms: int,
        replies: Sequence[CallerReply],
    ) -> Measured | None:
        """The call's speech and response times, from the agent's channel as recorded from
        started_ms on, its gaps in ms from there, and the moment Truman's stream opened. A
        detector that fails leaves the call unmeasured; it does not take the call's outcome
        with it."""
        loop = asyncio.get_running_loop()
        tracks = [reply.track() for reply in replies]
        try:
            agent_spans, caller_spans = await loop.run_in_executor(
                self.start(), detect, agent, tracks
            )
        except BrokenProcessPool:
            log.exception("the voice detector process stopped; the next call starts a new one")
            self._pool = None
            return None
        except Exception:
            log.exception("could not find the speech in the recording")
            return None
        agent_speech = [shifted(span, started_ms) for span in agent_spans]
        ends = [
            spans[-1].end_ms if spans else reply.end_ms
            for reply, spans in zip(replies, caller_spans, strict=True)
        ]
        latency = response_times(
            connected_ms,
            [(reply.start_ms, end) for reply, end in zip(replies, ends, strict=True)],
            [span.start_ms for span in agent_speech],
        )
        speech = Speech(
            agent=agent_speech,
            caller=[span for spans in caller_spans for span in spans],
            agent_gaps=[shifted(gap, started_ms) for gap in agent_gaps],
        )
        return Measured(latency, speech)


def shifted(span: Span, by_ms: int) -> Span:
    return Span(start_ms=span.start_ms + by_ms, end_ms=span.end_ms + by_ms)


def warm_up() -> None:
    """Load the detector's code and model once, so a call's measurement does not wait for it."""
    SileroVADAnalyzer(params=VAD)


def detect(agent: bytes, replies: Sequence[Track]) -> tuple[list[Span], list[list[Span]]]:
    """In the detector process: the agent's speech in ms from its track's start, and each
    reply's speech on the call's clock. Every track gets a fresh analyzer, so no state crosses
    from one to the next."""
    return asyncio.run(detect_all(agent, replies))


async def detect_all(agent: bytes, replies: Sequence[Track]) -> tuple[list[Span], list[list[Span]]]:
    return await speech_in(agent), [await reply_speech(reply) for reply in replies]


async def reply_speech(reply: Track) -> list[Span]:
    """Where the reply spoke, on the call's clock. Its audio stopped going out at its end, after
    a quiet tail that the TTS puts after the last word, so its speech is placed back from that
    end; the detector runs on the reply's own audio, so background noise does not move it. A
    reply cut off counts from its first audio to its last: its sent audio is not the audio the
    TTS made. A reply the call's end cut off has no end and counts no speech."""
    start_ms, end_ms, audio = reply
    if end_ms is None:
        return []
    if audio is None:
        return [Span(start_ms=start_ms, end_ms=end_ms)]
    offset = end_ms - bytes_ms(len(audio))
    return [shifted(span, offset) for span in await speech_in(audio)]


async def speech_in(pcm: bytes) -> list[Span]:
    return segments([window async for window in windows(pcm)])


def segments(windows: Iterable[Window]) -> list[Span]:
    """The speech in a run of detector states, in ms from the audio's start. Speech starts where
    the analyzer turns to speaking, less the windows it needs to decide. It ends at the end of
    its last speaking window, before the analyzer goes quiet or the audio ends; a pause that
    turns back to speaking before the stop time does not end it."""
    found: list[Span] = []
    start: float | None = None
    last_speaking = 0.0
    before = VADState.QUIET
    for end, window_ms, state in windows:
        if state is VADState.SPEAKING:
            if before in (VADState.QUIET, VADState.STARTING):
                deciding_ms = round(VAD.start_secs * 1000 / window_ms) * window_ms
                start = end - deciding_ms
            last_speaking = end
        elif state is VADState.QUIET and start is not None:
            found.append(Span(start_ms=round(start), end_ms=round(last_speaking)))
            start = None
        before = state
    if start is not None:
        found.append(Span(start_ms=round(start), end_ms=round(last_speaking)))
    return found


async def windows(pcm: bytes) -> AsyncIterator[Window]:
    """The live detector's state after each window of pcm. The analyzer first hears the
    silence that comes before pcm: its volume reads 0 until it holds VOLUME_WINDOW_SECS of
    audio, so without that it cannot hear the start of pcm. The silence fills whole windows, so
    that each window of pcm starts where its time says."""
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
