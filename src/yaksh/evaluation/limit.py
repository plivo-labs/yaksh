import asyncio
from types import TracebackType
from typing import Protocol


class Slots(Protocol):
    """What bounds the judge calls in flight: a Limit, or a semaphore in tests."""

    async def __aenter__(self) -> None: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


class Limit:
    """Bounds the work in flight, like a semaphore whose size can change while work runs.
    A smaller size lets the work in flight finish and holds new work until it fits."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._active = 0
        self._changed = asyncio.Condition()

    @property
    def size(self) -> int:
        return self._size

    async def resize(self, size: int) -> None:
        async with self._changed:
            self._size = size
            self._changed.notify_all()

    async def __aenter__(self) -> None:
        async with self._changed:
            await self._changed.wait_for(lambda: self._active < self._size)
            self._active += 1

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        async with self._changed:
            self._active -= 1
            self._changed.notify_all()
