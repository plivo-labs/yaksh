import asyncio
import uuid

import anyio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yaksha.simulation import generation


class Generations:
    """The generations this process runs after the request that started them has ended, so
    leaving the page does not stop them."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self._tasks: set[asyncio.Task[None]] = set()
        # anyio scopes, not Task.cancel: the generation's shielded end record holds only against
        # anyio cancellation.
        self._scopes: dict[uuid.UUID, anyio.CancelScope] = {}

    def start(self, prepared: generation.Prepared, generation_id: uuid.UUID) -> None:
        scope = anyio.CancelScope()
        self._scopes[generation_id] = scope

        async def run() -> None:
            try:
                with scope:
                    await generation.run_to_end(self._sessionmaker, prepared, generation_id)
            finally:
                del self._scopes[generation_id]

        task = asyncio.create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def stop(self, generation_id: uuid.UUID) -> bool:
        """False when this process does not run the generation."""
        scope = self._scopes.get(generation_id)
        if scope is None:
            return False
        scope.cancel()
        return True

    async def close(self) -> None:
        """Stops every generation; each records that it stopped."""
        for scope in self._scopes.values():
            scope.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
