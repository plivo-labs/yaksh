"""Readers of an agent's trace, one for each framework."""

from collections.abc import Sequence

from yaksh.evaluation.trace_maps import livekit, pipecat
from yaksh.evaluation.trace_maps.reading import Reading, TraceSpan


def reading(spans: Sequence[TraceSpan]) -> Reading | None:
    """The trace as the reader of its framework sees it; None when no reader knows its
    spans."""
    return livekit.read(spans) or pipecat.read(spans)
