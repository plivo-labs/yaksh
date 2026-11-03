"""When the agent's speech stopped after each interruption line of a phone call, as the recording
shows it after the call. It tells when the speech stopped, not why: a turn that ended by itself
within the window stopped too."""

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from yaksh.domain.latency import VAD_STOP_S, AgentMedia, Span, nearest_rank

STOP_WINDOW_MS = 2_000
"""The longest time after a line's start in which the agent's speech must stop to count as a stop.
The live check uses the same length from the line's first sound."""
QUIET_MS = round(VAD_STOP_S * 1000)
"""How long Yaksh must hear the agent quiet after its speech before the speech counts as
stopped: the VAD stop of the measurement after the call."""


class StopResult(StrEnum):
    STOPPED = "stopped"
    """The agent's speech stopped within STOP_WINDOW_MS of the line's start."""
    KEPT_TALKING = "kept_talking"
    """The agent's speech went on past STOP_WINDOW_MS."""
    NOT_SPEAKING = "not_speaking"
    """The agent was not speaking when the line's speech started."""
    UNKNOWN = "unknown"


class StopReason(StrEnum):
    """Why a line has no stop time, or why its time is only the least it can be."""

    NO_LINE_SPEECH = "no_line_speech"
    """The part of the line that went out has no speech."""
    MEDIA_GAP = "media_gap"
    """Yaksh did not hear the agent's channel where it needed to."""
    RECORDING_ENDED = "recording_ended"
    """The recording ended before Yaksh heard the agent quiet for QUIET_MS."""


class LineStop(BaseModel):
    """The agent's stop after one interruption line that played."""

    model_config = ConfigDict(frozen=True)

    number: int
    """The interruption's place in the scenario, from 1."""
    line_ms: int | None = None
    """Where the line's speech started on the call clock; None when it has none."""
    result: StopResult
    stop_ms: int | None = None
    """From the line's speech start to the end of the agent's speech, for STOPPED and
    KEPT_TALKING."""
    at_least: bool = False
    """KEPT_TALKING only: Yaksh did not hear the agent stop, so the agent spoke for stop_ms or
    longer."""
    reason: StopReason | None = None
    """For UNKNOWN, and for KEPT_TALKING with at_least."""


class StopTime(BaseModel):
    """The stops of a call's lines, and the percentiles of the lines whose speech stopped in
    time. A line where the agent kept talking is counted, not put in the percentiles."""

    model_config = ConfigDict(frozen=True)

    lines: list[LineStop]
    counts: dict[StopResult, int]
    """How many lines got each result, every result named."""
    p50_ms: int | None
    p90_ms: int | None

    @classmethod
    def of(cls, lines: Sequence[LineStop]) -> StopTime:
        stopped = sorted(stopped_times(lines))
        return cls(
            lines=list(lines),
            counts={result: sum(line.result is result for line in lines) for result in StopResult},
            p50_ms=nearest_rank(stopped, 0.5),
            p90_ms=nearest_rank(stopped, 0.9),
        )

    def count(self, result: StopResult) -> int:
        return self.counts[result]


def stopped_times(lines: Sequence[LineStop]) -> list[int]:
    return [
        line.stop_ms
        for line in lines
        if line.result is StopResult.STOPPED and line.stop_ms is not None
    ]


def line_stops(
    lines: Sequence[tuple[int, Sequence[Span]]],
    agent: Sequence[Span],
    media: AgentMedia | None,
    recording_end_ms: int,
) -> list[LineStop]:
    """The stop after each line that played, given as its number and the speech of its own
    audio on the call clock. agent is the agent's speech, media where the line carried the
    agent's audio, recording_end_ms where the recording ends. The recording fills a gap in the
    agent's media, and the time before and after it, with silence: silence there is no quiet of
    the agent. The first rule that applies decides each line."""
    return [line_stop(number, speech, agent, media, recording_end_ms) for number, speech in lines]


def line_stop(
    number: int,
    speech: Sequence[Span],
    agent: Sequence[Span],
    media: AgentMedia | None,
    recording_end_ms: int,
) -> LineStop:
    if not speech:
        return LineStop(number=number, result=StopResult.UNKNOWN, reason=StopReason.NO_LINE_SPEECH)
    start = speech[0].start_ms
    if media is None or not heard(media, recording_end_ms, start, start + 1):
        return LineStop(
            number=number, line_ms=start, result=StopResult.UNKNOWN, reason=StopReason.MEDIA_GAP
        )
    span = next((span for span in agent if span.start_ms <= start < span.end_ms), None)
    if span is None:
        return LineStop(number=number, line_ms=start, result=StopResult.NOT_SPEAKING)
    stop_ms = span.end_ms - start
    quiet_end = span.end_ms + QUIET_MS
    confirmed = heard(media, recording_end_ms, span.end_ms, quiet_end)
    reason = None
    if not confirmed:
        reason = (
            StopReason.RECORDING_ENDED if quiet_end > recording_end_ms else StopReason.MEDIA_GAP
        )
    if stop_ms > STOP_WINDOW_MS:
        return LineStop(
            number=number,
            line_ms=start,
            result=StopResult.KEPT_TALKING,
            stop_ms=stop_ms,
            at_least=not confirmed,
            reason=reason,
        )
    if confirmed:
        return LineStop(number=number, line_ms=start, result=StopResult.STOPPED, stop_ms=stop_ms)
    return LineStop(number=number, line_ms=start, result=StopResult.UNKNOWN, reason=reason)


def heard(media: AgentMedia, recording_end_ms: int, start_ms: int, end_ms: int) -> bool:
    """Yaksh heard the agent's channel over [start_ms, end_ms): the agent's media and the
    recording cover it, and no gap in the media overlaps it."""
    return (
        media.first_ms <= start_ms
        and end_ms <= min(media.last_ms, recording_end_ms)
        and not any(gap.start_ms < end_ms and gap.end_ms > start_ms for gap in media.gaps)
    )


def pooled(calls: Sequence[StopTime]) -> StopTime:
    """Several calls' lines as one set, with its percentiles."""
    return StopTime.of([line for call in calls for line in call.lines])
