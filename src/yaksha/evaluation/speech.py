"""Where each side spoke, from a saved call's audio, as the live call's voice detector finds
it (decision 0019)."""

import io
import math
import wave
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass

import audioop
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams, VADState
from pipecat.audio.volume import VOLUME_WINDOW_SECS

from yaksha.domain.latency import (
    VAD_CONFIDENCE,
    VAD_START_S,
    VAD_STOP_S,
    CallerReplyWindow,
    Span,
    Speech,
)

VAD = VADParams(confidence=VAD_CONFIDENCE, start_secs=VAD_START_S, stop_secs=VAD_STOP_S)
type Window = tuple[float, float, VADState]
"""The detector's state after one window of audio: the window's end and length in ms."""


def read_mono(data: bytes) -> tuple[bytes, int]:
    """The first channel of a 16-bit WAV, and its sample rate."""
    with wave.open(io.BytesIO(data)) as file:
        rate, channels = file.getframerate(), file.getnchannels()
        if file.getsampwidth() != 2:
            raise ValueError(f"the WAV holds {8 * file.getsampwidth()}-bit samples")
        frames = file.readframes(file.getnframes())
    if channels == 1:
        return frames, rate
    return audioop.tomono(frames, 2, 1, 0), rate


@dataclass(frozen=True)
class Heard:
    """What the detector found in a saved call, on the call's clock."""

    speech: Speech
    replies: list[tuple[int, int | None]]
    """Each caller reply's start and the end of its speech for the response time."""
    end_ms: int
    """Where the recording ends."""


async def measure(
    agent: bytes,
    voice: bytes,
    rate: int,
    recording_start_ms: int,
    replies: Sequence[CallerReplyWindow],
) -> Heard:
    """agent is the recording's agent channel, which starts at recording_start_ms; voice holds
    each reply's own audio at the place its window names."""
    agent_end_ms = bytes_ms(len(agent), rate)
    agent_speech = [shifted(span, recording_start_ms) for span in await speech_in(agent, rate)]
    caller: list[Span] = []
    reply_ends: list[int | None] = []
    for reply in replies:
        own = voice[
            ms_bytes(reply.audio_start_ms, rate) : ms_bytes(
                reply.audio_start_ms + reply.audio_ms, rate
            )
        ]
        windows = [window async for window in detect(own, rate)]
        spans, last_word_ms = placed_reply(
            reply, windows, bytes_ms(len(own), rate), recording_start_ms + agent_end_ms
        )
        caller += spans
        reply_ends.append(last_word_ms)
    return Heard(
        speech=Speech(agent=agent_speech, caller=caller),
        replies=[(reply.start_ms, end) for reply, end in zip(replies, reply_ends, strict=True)],
        end_ms=recording_start_ms + agent_end_ms,
    )


def placed_reply(
    reply: CallerReplyWindow, windows: Sequence[Window], own_ms: int, call_end_ms: int
) -> tuple[list[Span], int | None]:
    """Where the reply spoke on the call's clock, from the detector's windows over its own
    audio, and where its last word ended for the response time. A finished reply's audio
    stopped going out at its end, after a quiet tail that the TTS puts after the last word, so
    it is placed back from that end. A reply cut off went out from its start: as far as its
    end, or to the end of the call when the call cut it. The response time of a reply that the
    end of the call cut off has no end."""
    if reply.finished and reply.end_ms is not None:
        offset = reply.end_ms - own_ms
        spans = [shifted(span, offset) for span in segments(windows, own_ms)]
        last_words = [end for end, _, state in windows if state is VADState.SPEAKING]
        return spans, offset + round(last_words[-1]) if last_words else reply.end_ms
    sent_until = reply.end_ms if reply.end_ms is not None else call_end_ms
    sent_ms = max(0, min(own_ms, sent_until - reply.start_ms))
    sent = [window for window in windows if window[0] <= sent_ms]
    return [shifted(span, reply.start_ms) for span in segments(sent, sent_ms)], reply.end_ms


def shifted(span: Span, by_ms: int) -> Span:
    return Span(start_ms=span.start_ms + by_ms, end_ms=span.end_ms + by_ms)


def bytes_ms(size: int, rate: int) -> int:
    return round(size * 1000 / (2 * rate))


def ms_bytes(ms: int, rate: int) -> int:
    return max(0, ms) * rate // 1000 * 2


async def speech_in(pcm: bytes, rate: int) -> list[Span]:
    return segments([window async for window in detect(pcm, rate)], bytes_ms(len(pcm), rate))


def segments(windows: Iterable[Window], length_ms: int) -> list[Span]:
    """The speech in a run of detector states, in ms from the audio's start. Speech starts where
    the analyzer turns to speaking, less the windows it needs to decide. It ends at the end of
    its last speaking window before the analyzer goes quiet; a pause that turns back to
    speaking before the stop time does not end it. Speech still going when the audio ends ends
    there; speech that was stopping ends at its last speaking window."""
    found: list[Span] = []
    start: float | None = None
    last_speaking = 0.0
    state = VADState.QUIET
    for end, window_ms, state in windows:
        if state is VADState.SPEAKING:
            if start is None:
                deciding_ms = round(VAD.start_secs * 1000 / window_ms) * window_ms
                start = end - deciding_ms
            last_speaking = end
        elif state is VADState.QUIET and start is not None:
            found.append(Span(start_ms=round(start), end_ms=round(last_speaking)))
            start = None
    if start is not None:
        end_ms = length_ms if state is VADState.SPEAKING else round(last_speaking)
        found.append(Span(start_ms=round(start), end_ms=end_ms))
    return found


async def detect(pcm: bytes, rate: int) -> AsyncIterator[Window]:
    """The live detector's state after each window of pcm. The analyzer first hears the
    silence that comes before pcm: its volume reads 0 until it holds VOLUME_WINDOW_SECS of
    audio, so without that it cannot hear the start of pcm. The silence fills whole windows, so
    that each window of pcm starts where its time says. A fresh analyzer for each track keeps
    one track's state out of the next."""
    analyzer = SileroVADAnalyzer(params=VAD)
    analyzer.set_sample_rate(rate)
    window = analyzer.num_frames_required() * 2
    window_ms = window * 1000 / (2 * rate)
    try:
        await analyzer.analyze_audio(
            bytes(math.ceil(VOLUME_WINDOW_SECS * 1000 / window_ms) * window)
        )
        for at in range(0, len(pcm) - window + 1, window):
            state = await analyzer.analyze_audio(pcm[at : at + window])
            yield (at + window) * 1000 / (2 * rate), window_ms, state
    finally:
        await analyzer.cleanup()
