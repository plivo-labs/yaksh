from collections.abc import AsyncGenerator
from dataclasses import dataclass

from yaksh.domain.files import FileStore


@dataclass(frozen=True)
class OpenedFile:
    """A stored file with its first chunk already fetched, so a storage failure is reported
    before a download starts. close() releases the storage stream however the download ends."""

    first: bytes
    rest: AsyncGenerator[bytes]

    async def chunks(self) -> AsyncGenerator[bytes]:
        yield self.first
        async for chunk in self.rest:
            yield chunk

    async def close(self) -> None:
        await self.rest.aclose()


async def open_file(store: FileStore, key: str) -> OpenedFile:
    rest = store.stream(key)
    return OpenedFile(await anext(rest, b""), rest)
