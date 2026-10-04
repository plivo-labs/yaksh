"""How long the agent made the caller wait: one reply per caller turn, timed on the call's clock."""

import math
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict


class Span(BaseModel):
    """A stretch of a call, in ms on the call's clock."""

    model_config = ConfigDict(frozen=True)

    start_ms: int
    end_ms: int


class Speech(BaseModel):
    """Where each side spoke, as the voice detector found it after the call. The caller's
    speech comes from its replies' own audio, before any background noise; a reply cut off
    before its TTS finished counts from its first audio to its last. Gaps are stretches of the
    agent's channel with no audio from the line, which the recording fills with silence: they
    are missing media, not the agent being quiet."""

    model_config = ConfigDict(frozen=True)

    agent: list[Span]
    caller: list[Span]
    agent_gaps: list[Span]


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
    """When the caller's reply ended, or when Truman's stream opened if the caller had not
    spoken."""
    speech_ms: int
    """When the agent's first speech after the start of that reply began."""

    @property
    def response_ms(self) -> int | None:
        """The wait, or None when the agent started before the caller finished: a talk-over."""
        wait = self.speech_ms - self.start_ms
        return wait if wait >= 0 else None


class Latency(BaseModel):
    model_config = ConfigDict(frozen=True)

    replies: list[Reply]
    p50_ms: int | None
    p90_ms: int | None


def response_times(
    connected_ms: int,
    caller_replies: Sequence[tuple[int, int | None]],
    speech_starts: Sequence[int],
) -> Latency:
    """Pair each caller reply, given as (start, end), with the first agent speech that starts
    after the reply began and before the next reply begins. Before the first caller reply, the
    call's start counts as a reply that ended when Truman's stream opened, at connected_ms, and
    the agent's first speech answers it. Speech that started by then was under way: it gets no
    value, as its true start is unknown. A reply with no end, cut off by the end of the call,
    still bounds the reply before it but gets no value: without its end, a wait cannot be told
    from a talk-over."""
    windows: list[tuple[int | None, int | None]] = [(None, connected_ms), *caller_replies]
    next_starts = [start for start, _ in caller_replies]
    replies = []
    for index, (began, ended) in enumerate(windows):
        until = next_starts[index] if index < len(next_starts) else None
        answer = next(
            (
                at
                for at in speech_starts
                if (began is None or at >= began) and (until is None or at < until)
            ),
            None,
        )
        under_way = began is None and answer is not None and answer <= connected_ms
        if answer is not None and ended is not None and not under_way:
            replies.append(Reply(start_ms=ended, speech_ms=answer))
    waits = sorted(r.response_ms for r in replies if r.response_ms is not None)
    return Latency(
        replies=replies, p50_ms=nearest_rank(waits, 0.5), p90_ms=nearest_rank(waits, 0.9)
    )


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
