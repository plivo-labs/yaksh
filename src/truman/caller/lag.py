"""How late the worker's event loop runs during a call. Every call on a worker shares one loop,
so anything that holds it, such as loading a model, delays the audio of all of them."""

import asyncio
import time

from truman.domain.latency import LoopLag, nearest_rank

TICK_S = 0.02
"""How often the sampler expects to run: a stall longer than this shows as lateness."""


class LagSampler:
    def __init__(self) -> None:
        self._lates_ms: list[int] = []
        self._due = time.monotonic() + TICK_S
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(max(0.0, self._due - time.monotonic()))
            now = time.monotonic()
            self._lates_ms.append(round((now - self._due) * 1000))
            self._due = now + TICK_S

    def stop(self) -> LoopLag | None:
        """The lag since the sampler started; None when it never ran."""
        self._task.cancel()
        if not self._lates_ms:
            return None
        ordered = sorted(self._lates_ms)
        return LoopLag(
            max_ms=ordered[-1], p99_ms=nearest_rank(ordered, 0.99) or 0, samples=len(ordered)
        )
