"""How long the agent made the caller wait: one reply per caller turn, timed on the call's clock."""

import math
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict


class Reply(BaseModel):
    """The agent's answer to one caller reply, or to the start of the call."""

    model_config = ConfigDict(frozen=True)

    start_ms: int
    """When the caller's reply ended, or when the call connected if the caller had not spoken."""
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
    call's start counts as a reply that began and ended when the call connected. A reply with
    no end, cut off by the end of the call, still bounds the reply before it but gets no value:
    without its end, a wait cannot be told from a talk-over."""
    windows: list[tuple[int, int | None]] = [(connected_ms, connected_ms), *caller_replies]
    next_starts = [start for start, _ in caller_replies]
    replies = []
    for index, (began, ended) in enumerate(windows):
        until = next_starts[index] if index < len(next_starts) else None
        answer = next(
            (at for at in speech_starts if at >= began and (until is None or at < until)), None
        )
        if answer is not None and ended is not None:
            replies.append(Reply(start_ms=ended, speech_ms=answer))
    waits = sorted(r.response_ms for r in replies if r.response_ms is not None)
    return Latency(
        replies=replies, p50_ms=nearest_rank(waits, 0.5), p90_ms=nearest_rank(waits, 0.9)
    )


def nearest_rank(ordered: Sequence[int], fraction: float) -> int | None:
    """The value at that fraction of the sorted values, a value that happened: with fewer than
    ten values, the 90th percentile is the largest."""
    if not ordered:
        return None
    return ordered[math.ceil(fraction * len(ordered)) - 1]
