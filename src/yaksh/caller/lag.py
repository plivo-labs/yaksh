"""How late the event loops that carry a call run during it. Every call on a worker shares the
worker's loop, so anything that holds it, such as loading a model, delays the audio of all of
them. A call in a process of its own also has that process's loop."""

import asyncio
import time
from array import array
from collections.abc import Callable

from yaksh.domain.latency import LoopLag, nearest_rank

TICK_S = 0.02
"""How often the ticker expects to run: a stall longer than this shows as lateness."""


class Watch:
    """One call's ticks: when each was due, on the call clock, and how late it ran."""

    def __init__(self, clock_ms: Callable[[], int]) -> None:
        self._clock_ms = clock_ms
        self._due_ms = array("q")
        self._late_ms = array("i")

    def add(self, late_ms: int) -> None:
        self._due_ms.append(self._clock_ms() - late_ms)
        self._late_ms.append(late_ms)

    def lag(self, ended_ms: int | None) -> LoopLag | None:
        """The lag of the ticks that were due by `ended_ms`, or of every tick. A stall counts
        when the tick that it delayed was due by then, so a stall that begins after the end of
        the call never counts. None when no tick counts."""
        kept = array("i")
        worst = (0, 0)
        for due, late in zip(self._due_ms, self._late_ms, strict=True):
            if ended_ms is None or due <= ended_ms:
                kept.append(late)
                worst = max(worst, (late, due + late))
        if not kept:
            return None
        return LoopLag(
            max_ms=worst[0],
            max_at_ms=worst[1],
            p99_ms=nearest_rank(sorted(kept), 0.99) or 0,
            samples=len(kept),
        )


class LagTicker:
    """Measures how late an event loop runs, for each call while it is watched. One ticker
    serves every call on the loop: a ticker for each call would wake the loop once for each call
    every tick."""

    def __init__(self) -> None:
        self._watches: list[Watch] = []
        self._due = 0.0
        self._task: asyncio.Task[None] | None = None

    def watch(self, clock_ms: Callable[[], int]) -> Watch:
        """Watch from now on: a tick that is already late belongs to the calls before."""
        self._settle()
        if self._task is None:
            self._due = time.monotonic() + TICK_S
            self._task = asyncio.create_task(self._run(), name="yaksh-loop-lag")
        watch = Watch(clock_ms)
        self._watches.append(watch)
        return watch

    def unwatch(self, watch: Watch, ended_ms: int | None = None) -> LoopLag | None:
        """Stop watching and give the call's lag until `ended_ms` on the call clock, or until
        now. None for a watch that stopped before, or when no tick counts."""
        if watch not in self._watches:
            return None
        self._settle()
        self._watches.remove(watch)
        if not self._watches and self._task is not None:
            self._task.cancel()
            self._task = None
        return watch.lag(ended_ms)

    def _settle(self) -> None:
        """Give a tick that is due to the calls watching now, also before the loop runs it."""
        now = time.monotonic()
        if self._task is not None and now >= self._due:
            late = round((now - self._due) * 1000)
            for watch in self._watches:
                watch.add(late)
            self._due = now + TICK_S

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(max(0.0, self._due - time.monotonic()))
            self._settle()


def worse(child: LoopLag | None, worker: LoopLag | None) -> LoopLag | None:
    """The lag of a call that two loops carried: the larger stall with its time, and the larger
    of the two loops' own 99th percentiles. The samples are the child's when it has any."""
    if child is None or worker is None:
        return child or worker
    top = worker if worker.max_ms > child.max_ms else child
    return LoopLag(
        max_ms=top.max_ms,
        max_at_ms=top.max_at_ms,
        p99_ms=max(child.p99_ms, worker.p99_ms),
        samples=child.samples,
    )
