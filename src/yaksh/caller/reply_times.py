"""Where the time of each caller reply goes, from Pipecat's latency breakdown: each reply that
the caller's model spoke, with its parts, kept for the conversation and logged on one line."""

import json
import logging
import time
import uuid
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from enum import Enum, auto
from typing import Any, NamedTuple

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    Frame,
    LLMFullResponseStartFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.observers.user_bot_latency_observer import (
    LatencyBreakdown,
    LatencyContribution,
    LatencyOwnerKind,
    MeasuredFrom,
    UserBotLatencyObserver,
)
from pipecat.processors.frame_processor import FrameDirection

from yaksh import __version__
from yaksh.caller.audio import MACHINE
from yaksh.domain.conversations import CallerSettings
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
    INTERRUPTION = auto()
    """A line of the scenario's interruption, counted once it has played: a reply after it is
    then not measured with the rest of the line in its time."""


def source_of(frame: Frame) -> Source | None:
    if isinstance(frame, LLMFullResponseStartFrame):
        return Source.MODEL
    if isinstance(frame, TTSSpeakFrame):
        return Source.FIXED
    if isinstance(frame, TTSStartedFrame) and MACHINE in frame.metadata:
        return Source.MACHINE
    return None


class Heard(NamedTuple):
    """Something that made the caller speak: when this observer saw it, and when the STT pushed
    the agent's latest final transcript before it."""

    at: float
    source: Source
    transcribed: float | None


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
    Times come from `now`, the observer's own clock.

    A reply also keeps the STT's TTFS: from the end of the agent's speech to the last final
    transcript before the caller's model started. Pipecat tells this observer of a frame once, at
    its first push, so a transcript's time is when the STT pushed it. Pipecat's STT TTFB is no
    measure of it: with Deepgram it stops at the answer to the finalize request sent at the VAD
    stop, so it always holds the stop_secs."""

    def __init__(
        self,
        conversation_id: uuid.UUID,
        settings: CallerSettings,
        llm_host: str | None,
        now: Callable[[], float] = time.time,
    ) -> None:
        """`llm_host` is the host of the LLM base URL, for the log line: never its path or a key."""
        super().__init__(time_source=now)
        self._log_fields = {
            "conversation_id": str(conversation_id),
            "caller_model": settings.llm_model,
            "reasoning_effort": settings.reasoning_effort,
            "llm_host": llm_host,
            "stt_provider": settings.stt_provider,
            "stt_model": settings.stt_model,
            "tts_provider": settings.voice.provider if settings.voice else None,
            "tts_model": settings.tts_model,
            "language": settings.stt_language,
            "vad_stop_s": settings.vad_stop_s,
            "turn_max_wait_s": settings.turn_max_wait_s,
            "version": __version__,
        }
        self._time = now
        self._transcribed: float | None = None
        """When the STT pushed the latest final transcript of the agent's speech."""
        self._sources: list[Heard] = []
        self._audio_starts = 0
        self._replies: list[CallerReplyTime] = []
        self.add_event_handler("on_latency_breakdown", self._measured)

    def line_played(self) -> None:
        """An interruption line finished playing."""
        self._sources.append(Heard(self._time(), Source.INTERRUPTION, self._transcribed))

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
                self._sources.append(Heard(self._time(), source, self._transcribed))
            elif isinstance(data.frame, VADUserStartedSpeakingFrame):
                self._transcribed = None
            elif isinstance(data.frame, TranscriptionFrame):
                self._transcribed = self._time()
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
        heard = [seen for seen in self._sources if start <= seen.at <= closing.at]
        if {seen.source for seen in heard} != {Source.MODEL}:
            return
        asked = heard[0]
        parts = with_turn_detection(breakdown.contributions, asked=asked.at)
        reply = CallerReplyTime(
            audio_index=closing.index,
            total_ms=round((closing.at - start) * 1000),
            steps=steps_within(parts, start, closing.at),
            stt_ttfs_ms=None
            if asked.transcribed is None
            else round((asked.transcribed - start) * 1000),
        )
        self._replies.append(reply)
        fields = {
            **self._log_fields,
            "reply": reply.audio_index,
            "total_ms": reply.total_ms,
            **{f"{key}_ms": ms for key, ms in reply.step_times().items()},
            "stt_ttfs_ms": reply.stt_ttfs_ms,
        }
        log.info("caller_reply_time %s", json.dumps(fields, separators=(",", ":")))


def with_turn_detection(
    parts: Sequence[LatencyContribution], asked: float
) -> Sequence[LatencyContribution]:
    """The parts with the turn detection named when Pipecat left it out. Pipecat 1.14 drops a
    transcript that arrives before the voice detector calls the agent's turn over
    (pipecat-ai/pipecat#5921), and then names neither the transcription nor the turn detection:
    the wait from that call to the model's request counts as `pipeline`. With the transcript
    already in, that wait is the turn detection. `asked` is when the caller's model was asked."""
    keys = {part.key for part in parts}
    stopped = next(
        (part.start_time + part.duration_secs for part in parts if part.key == "endpointing_wait"),
        None,
    )
    if "transcription" in keys or "turn_detection" in keys or stopped is None or asked <= stopped:
        return parts
    return [
        *parts,
        LatencyContribution(
            key="turn_detection",
            label="turn detection",
            owner="config: user turn strategies",
            owner_kind=LatencyOwnerKind.SETTING,
            start_time=stopped,
            duration_secs=asked - stopped,
        ),
    ]


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
