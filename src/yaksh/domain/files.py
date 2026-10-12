"""Where Yaksh keeps files: uploaded documents and the audio of each call."""

from collections.abc import AsyncGenerator
from typing import Protocol


class FileStore(Protocol):
    """Keeps files under keys. A put to an existing key replaces the file."""

    async def put(self, key: str, data: bytes, media_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    def stream(self, key: str) -> AsyncGenerator[bytes]: ...

    async def close(self) -> None: ...
