"""Readers of an agent's trace, one for each framework. Each gives the agent's speech starts and,
for each reply to the caller, the agent's own total and the parts of it, on the agent's clock.
A value that the trace does not have is unknown, never 0."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

NS_PER_MS = 1_000_000
NS_PER_S = 1_000_000_000


class Framework(StrEnum):
    LIVEKIT = "livekit"
    PIPECAT = "pipecat"


@dataclass(frozen=True)
class TraceSpan:
    """A kept span, as a reader needs it."""

    span_id: str
    parent_span_id: str | None
    name: str
    start_ns: int
    end_ns: int
    attributes: Mapping[str, Any]


@dataclass(frozen=True)
class AgentReply:
    speech_ns: int
    """When the agent started to speak, on the agent's clock."""
    total_ms: int | None
    """The agent's own measurement of the wait; None when the trace does not have it."""
    parts: dict[str, int] = field(default_factory=dict)
    """ms by part key, the remainder `pipeline` included; empty for an incomplete reply."""
    stt_ttfs_ms: int | None = None
    incomplete: str | None = None
    """Why the parts are unknown: a span or a value that the trace lacks."""
    overlapping: bool = False
    """The parts add up to more than the agent's total, so `pipeline` is 0."""


@dataclass(frozen=True)
class Reading:
    framework: Framework
    core: tuple[str, ...]
    """The parts that this framework's reader gives for every complete reply, in order."""
    anchors_ns: list[int]
    """Every speech start of the agent, a reply or not: they align the trace with the call."""
    replies: list[AgentReply]


def covered_ns(ranges: Iterable[tuple[int, int]], start_ns: int, end_ns: int) -> int:
    """How much of [start_ns, end_ns] the ranges cover, each range counted once where they
    overlap."""
    clipped = sorted(
        (max(low, start_ns), min(high, end_ns))
        for low, high in ranges
        if min(high, end_ns) > max(low, start_ns)
    )
    total, reach = 0, start_ns
    for low, high in clipped:
        if high > reach:
            total += high - max(low, reach)
            reach = high
    return total


def seconds(span: TraceSpan, key: str) -> int | None:
    """A value in seconds as ns; None when the span does not have it."""
    value = span.attributes.get(key)
    return None if value is None else round(float(value) * NS_PER_S)


def ms(ns: int) -> int:
    return round(ns / NS_PER_MS)


def with_remainder(total_ns: int, parts_ns: dict[str, int]) -> tuple[dict[str, int], bool]:
    """The parts in ms with `pipeline`, the agent's total less the named parts; 0 and
    overlapping when they add up to more. The sum is in ns, so that rounding alone never makes
    parts that fill the total overlap."""
    rest = total_ns - sum(parts_ns.values())
    parts = {key: ms(value) for key, value in parts_ns.items()}
    return parts | {"pipeline": ms(max(rest, 0))}, rest < 0
