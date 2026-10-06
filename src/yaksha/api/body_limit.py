"""Refuses a request body over a size limit while it arrives. FastAPI reads a body before it
checks the token, so without this any client could make the API buffer an unbounded upload."""

from starlette.exceptions import HTTPException
from starlette.status import HTTP_413_CONTENT_TOO_LARGE
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from yaksha.api.errors import error_response


class BodySizeLimit:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.message = f"the request body is larger than {max_bytes // (1024 * 1024)} MB"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await error_response(HTTP_413_CONTENT_TOO_LARGE, self.message)(scope, receive, send)
            return
        received = 0

        async def limited() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # An HTTPException, because FastAPI turns any other error while it reads
                    # a body into a 400 and passes this one on unchanged.
                    raise HTTPException(HTTP_413_CONTENT_TOO_LARGE, self.message)
            return message

        await self.app(scope, limited, send)
