"""The agent's response times, from its speech in the call recording as the live voice detector
finds it."""

import logging
from collections.abc import Sequence

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADState

from truman.caller.audio import SAMPLE_RATE
from truman.caller.pipeline import VAD
from truman.domain.latency import Latency, response_times

log = logging.getLogger(__name__)


async def measure(
    agent: bytes, connected_ms: int, caller_replies: Sequence[tuple[int, int | None]]
) -> Latency | None:
    """The call's response times. A detector that fails leaves the call unmeasured; it does not
    take the call's outcome with it."""
    try:
        starts = await speech_starts(agent)
    except Exception:
        log.exception("could not find the agent's speech in the recording")
        return None
    return response_times(connected_ms, caller_replies, [connected_ms + at for at in starts])


async def speech_starts(agent: bytes) -> list[int]:
    """Where speech starts in the agent's channel, in ms from its first sample. The analyzer turns
    to speaking only after a few windows of speech; the start is that many windows earlier."""
    analyzer = SileroVADAnalyzer(params=VAD)
    analyzer.set_sample_rate(SAMPLE_RATE)  # what a pipeline does at start; it sets the windows
    window = analyzer.num_frames_required() * 2
    window_ms = analyzer.num_frames_required() * 1000 / SAMPLE_RATE
    deciding_ms = round(VAD.start_secs * 1000 / window_ms) * window_ms
    starts: list[int] = []
    before = VADState.QUIET
    try:
        for at in range(0, len(agent) - window + 1, window):
            state = await analyzer.analyze_audio(agent[at : at + window])
            if state is VADState.SPEAKING and before in (VADState.QUIET, VADState.STARTING):
                starts.append(round((at + window) * 1000 / (2 * SAMPLE_RATE) - deciding_ms))
            before = state
    finally:
        await analyzer.cleanup()
    return starts
