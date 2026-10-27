"""How long the agent made the caller wait: one reply per caller turn, timed on the call's clock."""

import math
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from yaksh.domain.answering import MachineLine

VAD_CONFIDENCE = 0.5
VAD_START_S = 0.1
VAD_STOP_S = 0.6
"""The voice detector's settings, shared by the live caller and the measurement after the call,
so both find speech the same way."""


class Span(BaseModel):
    """A stretch of a call, in ms on the call's clock."""

    model_config = ConfigDict(frozen=True)

    start_ms: int
    end_ms: int


class Speech(BaseModel):
    """Where each side spoke, as the voice detector found it after the call. The caller's
    speech comes from its replies' own audio, before any background noise."""

    model_config = ConfigDict(frozen=True)

    agent: list[Span]
    caller: list[Span]


class AgentMedia(BaseModel):
    """Where the line carried the agent's audio, on the call's clock. The recording fills a gap
    with silence, but a gap is missing media, not the agent being quiet."""

    model_config = ConfigDict(frozen=True)

    first_ms: int
    last_ms: int
    gaps: list[Span]


class CallerReplyWindow(BaseModel):
    """One reply of the caller: when its audio went out, and where its own audio, as the TTS
    made it before any background noise, sits in the conversation's caller voice file."""

    model_config = ConfigDict(frozen=True)

    start_ms: int
    end_ms: int | None
    """When its last audio went out; None when the end of the call cut it off."""
    finished: bool
    """The TTS finished it, so its own audio is the whole reply; a reply cut off sent only the
    first end_ms - start_ms of it."""
    audio_start_ms: int
    audio_ms: int
    machine: MachineLine | None = None
    """Audio of the persona's voicemail or call screener: not a reply that waits for the
    agent."""


class LoopLag(BaseModel):
    """How late the worker's event loop woke up while a call was live, in ms: a lag here also
    delays the call's audio."""

    model_config = ConfigDict(frozen=True)

    max_ms: int
    max_at_ms: int
    """When the worst stall ended, on the call's clock."""
    p99_ms: int
    samples: int


class Reply(BaseModel):
    """The agent's answer to one caller reply, or to the start of the call."""

    model_config = ConfigDict(frozen=True)

    start_ms: int
    """When the caller's reply ended, or when Yaksh's stream opened if the caller had not
    spoken."""
    speech_ms: int
    """When the agent's first speech after the start of that reply began."""

    @property
    def response_ms(self) -> int | None:
        """The wait, or None when the agent started before the caller finished: a talk-over."""
        wait = self.speech_ms - self.start_ms
        return wait if wait >= 0 else None


class Wait(BaseModel):
    """What followed one caller reply, or the start of the call: when the agent answered, and
    how long the caller waited in silence for it."""

    model_config = ConfigDict(frozen=True)

    start_ms: int | None
    """When the caller's speech ended, or later, when the agent was still speaking then; when
    Yaksh's stream opened, for the start of the call. None for a reply that the end of the
    call cut off."""
    answer_ms: int | None
    """When the agent's first speech after the reply began started; None when the agent did
    not speak before the caller's next reply or the end of the call."""
    until_ms: int
    """How far the wait is known to have lasted: to the answer, else the caller's next reply,
    else the end of the call; or to the first gap in the agent's media, where Yaksh could not
    hear whether the agent spoke."""
    expects_answer: bool
    """False for the caller's goodbye and the replies after it, for a reply that the end of
    the call cut off, and for the start of a call that Yaksh's caller opens."""
    media_gap: bool = False
    """A gap in the agent's media cut the wait short, so its length is a lower bound."""
    ran_to_end: bool = False
    """Neither an answer nor a caller reply came before the call ended."""

    @property
    def wait_ms(self) -> int | None:
        """How long the caller waited; None for a talk-over and for a reply with no end."""
        if self.start_ms is None or self.until_ms < self.start_ms:
            return None
        return self.until_ms - self.start_ms

    @property
    def talked_over(self) -> bool:
        return (
            self.start_ms is not None
            and self.answer_ms is not None
            and self.answer_ms < self.start_ms
        )

    @property
    def unanswered(self) -> bool:
        """The caller spoke again before the agent answered, and no media gap can have hidden
        the answer."""
        return (
            self.expects_answer
            and self.answer_ms is None
            and not self.ran_to_end
            and not self.media_gap
        )


class Latency(BaseModel):
    model_config = ConfigDict(frozen=True)

    replies: list[Reply]
    p50_ms: int | None
    p90_ms: int | None

    @classmethod
    def of(cls, replies: list[Reply]) -> Latency:
        waits = sorted(r.response_ms for r in replies if r.response_ms is not None)
        return cls(
            replies=replies, p50_ms=nearest_rank(waits, 0.5), p90_ms=nearest_rank(waits, 0.9)
        )

    @classmethod
    def answered(cls, found: Sequence[Wait]) -> Latency:
        """The response times of the waits that expected an answer and got one, leaving out
        those that a media gap cut short."""
        return cls.of(
            [
                Reply(start_ms=wait.start_ms, speech_ms=wait.answer_ms)
                for wait in found
                if wait.expects_answer
                and not wait.media_gap
                and wait.start_ms is not None
                and wait.answer_ms is not None
            ]
        )


def waits(
    connected_ms: int,
    caller_replies: Sequence[tuple[int, int | None]],
    agent: Sequence[Span],
    call_end_ms: int,
    *,
    goodbye_from_ms: int | None,
    gaps: Sequence[Span],
    agent_opens: bool,
) -> list[Wait]:
    """Pair each caller reply, given as (start, end of speech), with the first agent speech
    that starts after the reply began and before the next reply begins. Before the first
    caller reply, the call's start counts as a reply that ended when Yaksh's stream opened,
    at connected_ms, and the agent's first speech answers it. Speech that started by then was
    under way: the call's start then has no wait, as its true start is unknown. The call's
    start expects an answer when the agent opens the call; a reply that starts at
    goodbye_from_ms or later expects none."""
    windows: list[tuple[int | None, int | None]] = [(None, connected_ms), *caller_replies]
    next_starts = [start for start, _ in caller_replies]
    found = []
    for index, (began, ended) in enumerate(windows):
        until = next_starts[index] if index < len(next_starts) else call_end_ms
        answer = next(
            (
                span.start_ms
                for span in agent
                if (began is None or span.start_ms >= began) and span.start_ms < until
            ),
            None,
        )
        if began is None and answer is not None and answer <= connected_ms:
            continue
        start = None if ended is None else silent_from(agent, began, ended)
        stop = answer if answer is not None else until
        heard = stop if start is None else heard_until(start, stop, gaps)
        found.append(
            Wait(
                start_ms=start,
                answer_ms=answer,
                until_ms=heard,
                expects_answer=agent_opens
                if began is None
                else expects_answer(began, ended, goodbye_from_ms),
                media_gap=heard < stop,
                ran_to_end=answer is None and index >= len(next_starts),
            )
        )
    return found


def silent_from(agent: Sequence[Span], began: int | None, ended: int) -> int:
    """Where the line went quiet after the caller's speech: at its end, or where the agent's
    speech that started before the reply and was still going then ended."""
    return max(
        (
            span.end_ms
            for span in agent
            if (began is None or span.start_ms < began) and span.start_ms < ended < span.end_ms
        ),
        default=ended,
    )


def heard_until(start: int, stop: int, gaps: Sequence[Span]) -> int:
    """How far Yaksh heard the line from start without a gap in the agent's media."""
    first = min(
        (gap.start_ms for gap in gaps if gap.start_ms < stop and gap.end_ms > start), default=None
    )
    return stop if first is None else max(start, first)


def expects_answer(began: int, ended: int | None, goodbye_from_ms: int | None) -> bool:
    return ended is not None and (goodbye_from_ms is None or began < goodbye_from_ms)


def pooled(calls: Sequence[Latency]) -> Latency:
    """Several calls' replies as one set, with its percentiles."""
    return Latency.of([reply for call in calls for reply in call.replies])


TURN_SLACK_MS = 100
"""How much earlier than the recording's speech start a transcript turn can start: the live
detector and the recording's detector can disagree by a few windows."""


def place(agent_turn_starts: Sequence[int], replies: Sequence[Reply]) -> list[Reply | None]:
    """The reply each agent turn starts with, in the order of the turns. A reply goes to the first
    agent turn that starts no earlier than its speech, less the slack, and before the next
    reply's speech. The transcript times agent turns when the live pipeline gets to them, so
    they start late, not early: a turn just before the next reply's speech is a late turn of
    this reply. A reply whose speech never became a turn goes nowhere."""
    placed: list[Reply | None] = [None] * len(agent_turn_starts)
    turn = 0
    for index, reply in enumerate(replies):
        following = replies[index + 1].speech_ms if index + 1 < len(replies) else None
        while (
            turn < len(agent_turn_starts)
            and agent_turn_starts[turn] < reply.speech_ms - TURN_SLACK_MS
        ):
            turn += 1
        if turn < len(agent_turn_starts) and (
            following is None or agent_turn_starts[turn] < following
        ):
            placed[turn] = reply
            turn += 1
    return placed


def nearest_rank(ordered: Sequence[int], fraction: float) -> int | None:
    """The value at that fraction of the sorted values, a value that happened: with fewer than
    ten values, the 90th percentile is the largest."""
    if not ordered:
        return None
    return ordered[math.ceil(fraction * len(ordered)) - 1]


STEP_KEYS = (
    "endpointing_wait",
    "first_request",
    "transcription",
    "turn_detection",
    "llm_inference",
    "turn_completion",
    "waiting_for_user",
    "llm_tool_call",
    "function_handler",
    "awaiting_speakable_text",
    "sentence_aggregation",
    "speech_synthesis",
    "output_transport",
    "pipeline",
)
"""The parts of a reply that Pipecat's latency breakdown names, in the order they happen;
`pipeline` is the time that no named part covers."""


class CallerReplyTime(BaseModel):
    """Where the time of one caller reply went, from the end of the agent's speech to the
    caller's first audio, as Pipecat's latency breakdown split it."""

    model_config = ConfigDict(frozen=True)

    audio_index: int
    """Which caller audio start of the call the reply is: its window in the transcript's caller
    replies."""
    total_ms: int
    steps: dict[str, int]
    """ms by Pipecat's key; a part that did not happen is absent."""

    def step_times(self) -> dict[str, int]:
        """Every known part, 0 when absent, then any part that a later Pipecat adds, by name,
        so the parts of every reply count the same way."""
        known = {key: self.steps.get(key, 0) for key in STEP_KEYS}
        return known | {key: self.steps[key] for key in sorted(self.steps) if key not in known}
