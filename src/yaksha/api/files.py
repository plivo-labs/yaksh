from collections.abc import Mapping

from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from yaksha.simulation.files import OpenedFile


class StoredFileResponse(StreamingResponse):
    """Streams a stored file and always releases the storage stream: Starlette leaves an
    unfinished iterator to the garbage collector."""

    def __init__(
        self, opened: OpenedFile, media_type: str | None, headers: Mapping[str, str] | None = None
    ) -> None:
        super().__init__(opened.chunks(), media_type=media_type, headers=headers)
        self._opened = opened

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._opened.close()
