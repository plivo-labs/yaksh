"""The agent's response times, from its speech in the call recording as the live voice detector
finds it."""

import logging
import math
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADState
from pipecat.audio.volume import VOLUME_WINDOW_SECS

from truman.caller.audio import SAMPLE_RATE, Playout
from truman.caller.pipeline import VAD
from truman.domain.latency import Latency, response_times

log = logging.getLogger(__name__)


@dataclass
class CallerReply:
    """One reply of the persona: when its audio started and stopped going out, and, when the
    TTS finished it, its playout with the audio before any background noise."""

    start_ms: int
    end_ms: int | None = None
    playout: Playout | None = None


async def measure(
    agent: bytes, started_ms: int, connected_ms: int, caller_replies: Sequence[CallerReply]
) -> Latency | None:
    """The call's response times, from the agent's channel as recorded from started_ms on and
    the moment Truman's stream opened. A detector that fails leaves the call unmeasured; it does
    not take the call's outcome with it."""
    try:
        starts = await speech_starts(agent)
        replies = [(reply.start_ms, await speech_stopped(reply)) for reply in caller_replies]
    except Exception:
        log.exception("could not find the speech in the recording")
        return None
    return response_times(connected_ms, replies, [started_ms + at for at in starts])


async def speech_stopped(reply: CallerReply) -> int | None:
    """When the reply's speech ended on the call's clock: its audio stopped going out at end_ms,
    after a quiet tail that the TTS puts after the last word. The same detector finds the last
    word in the reply's own audio, so background noise does not move it. A reply cut off keeps
    end_ms: its sent audio is not the audio the TTS made."""
    if reply.end_ms is None or reply.playout is None:
        return reply.end_ms
    audio = bytes(reply.playout.audio)
    ends = [end async for end, _, state in windows(audio) if state is VADState.SPEAKING]
    if not ends:
        return reply.end_ms
    return reply.end_ms - round(len(audio) * 1000 / (2 * SAMPLE_RATE) - ends[-1])


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
