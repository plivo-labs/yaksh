"""Where the time of each caller reply goes, from Pipecat's latency breakdown: each reply that
the caller's model spoke, with its parts, kept for the conversation and logged on one line."""

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from enum import Enum, auto
from typing import Any, NamedTuple

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    Frame,
    LLMFullResponseStartFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.observers.user_bot_latency_observer import (
    LatencyBreakdown,
    LatencyContribution,
    MeasuredFrom,
    UserBotLatencyObserver,
)
from pipecat.processors.frame_processor import FrameDirection

from yaksh.caller.audio import MACHINE
from yaksh.domain.latency import CallerReplyTime

log = logging.getLogger(__name__)

UNNAMED = "pipeline"
"""Pipecat's key for the time that no named part covers."""


class Source(Enum):
    """What made the caller speak."""

    MODEL = auto()
    FIXED = auto()
    """Fixed text that Yaksh says for the caller: the first words, a nudge, a goodbye."""
    MACHINE = auto()
    """A line of the persona's voicemail or call screener."""


def source_of(frame: Frame) -> Source | None:
    if isinstance(frame, LLMFullResponseStartFrame):
        return Source.MODEL
    if isinstance(frame, TTSSpeakFrame):
        return Source.FIXED
    if isinstance(frame, TTSStartedFrame) and MACHINE in frame.metadata:
        return Source.MACHINE
    return None


class AudioStart(NamedTuple):
    """The caller audio start that closed a breakdown: its place in the call, and when this
    observer saw it."""

    index: int
    at: float


CLOSING: ContextVar[AudioStart | None] = ContextVar("closing", default=None)
"""Set while Pipecat handles a caller audio start. Pipecat creates the breakdown's handler task
then, and a task copies the context it was created in, so the handler reads its own start."""


class ReplyTimes(UserBotLatencyObserver):
    """Pipecat times every stretch from the end of the agent's speech to the caller's next audio,
    whatever made the caller speak. A reply counts when the caller's model started a response
    in that stretch and no fixed line or machine line did: a nudge after a long silence is not
    a slow reply.

    Pipecat runs the breakdown's handler in a task of its own, which can run after later frames,
    so the handler takes the audio start that closed it from its context, never the latest one.
    Times come from `now`, the observer's own clock."""

    def __init__(self, log_fields: Mapping[str, Any], now: Callable[[], float] = time.time) -> None:
        super().__init__(time_source=now)
        self._log_fields = dict(log_fields)
        self._time = now
        self._sources: list[tuple[float, Source]] = []
        self._audio_starts = 0
        self._replies: list[CallerReplyTime] = []
        self.add_event_handler("on_latency_breakdown", self._measured)

    @property
    def replies(self) -> list[CallerReplyTime]:
        return sorted(self._replies, key=lambda reply: reply.audio_index)

    async def on_push_frame(self, data: FramePushed) -> None:
        if data.direction is FrameDirection.DOWNSTREAM:
            if isinstance(data.frame, BotStartedSpeakingFrame):
                token = CLOSING.set(AudioStart(self._audio_starts, self._time()))
                self._audio_starts += 1
                try:
                    await super().on_push_frame(data)
                finally:
                    CLOSING.reset(token)
                return
            if (source := source_of(data.frame)) is not None:
                self._sources.append((self._time(), source))
        await super().on_push_frame(data)

    async def _measured(self, _observer: Any, breakdown: LatencyBreakdown) -> None:
        closing = CLOSING.get()
        start = breakdown.user_turn_start_time
        if (
            closing is None
            or breakdown.measured_from is not MeasuredFrom.USER_SILENCE
            or start is None
        ):
            return
        if {source for at, source in self._sources if start <= at <= closing.at} != {Source.MODEL}:
            return
        reply = CallerReplyTime(
            audio_index=closing.index,
            total_ms=round((closing.at - start) * 1000),
            steps=steps_within(breakdown.contributions, start, closing.at),
        )
        self._replies.append(reply)
        fields = {
            **self._log_fields,
            "reply": reply.audio_index,
            "total_ms": reply.total_ms,
            **{f"{key}_ms": ms for key, ms in reply.step_times().items()},
        }
        log.info("caller_reply_time %s", json.dumps(fields, separators=(",", ":")))


def steps_within(parts: Sequence[LatencyContribution], start: float, end: float) -> dict[str, int]:
    """ms by part, each part cut to the reply's stretch, from the end of the agent's speech to
    the caller's audio start. Pipecat can place a part it derives from a metric after the audio
    start and count the time to it as `pipeline`; here `pipeline` is what the named parts leave
    of the stretch, so the parts add up to the reply's time."""

    def since(at: float) -> int:
        """ms from the start, rounded once per point, so the parts never add up to more than
        the stretch."""
        return round((at - start) * 1000)

    steps: dict[str, int] = {}
    for part in parts:
        if part.key == UNNAMED:
            continue
        ms = since(min(part.start_time + part.duration_secs, end)) - since(
            max(part.start_time, start)
        )
        if ms > 0:
            steps[part.key] = steps.get(part.key, 0) + ms
    rest = since(end) - sum(steps.values())
    if rest > 0:
        steps[UNNAMED] = rest
    return steps
