"""The worker's Plivo-facing surface: the answer XML, the stream websocket, and the callbacks.

Plivo reaches the worker directly, at one public URL, because the pipeline that owns a call
lives in the worker. A stream is matched to its conversation by the id Truman put in the
websocket path when it wrote the answer XML, never by headers.
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Generator
from dataclasses import dataclass, field

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response

log = logging.getLogger(__name__)

STREAM_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><Response>'
    '<Stream bidirectional="true" keepCallAlive="false" contentType="audio/x-mulaw;rate=8000">'
    "{stream_url}</Stream></Response>"
)
HANGUP_XML = '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'
NO_CALL = "no call expects this stream"


@dataclass
class PendingStream:
    """One conversation waiting for Plivo: the socket lands here, the callbacks queue here."""

    socket: asyncio.Future[WebSocket] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    callbacks: asyncio.Queue[dict[str, str]] = field(default_factory=asyncio.Queue)


class StreamRegistry:
    def __init__(self) -> None:
        self._pending: dict[uuid.UUID, PendingStream] = {}

    def expect(self, conversation_id: uuid.UUID) -> PendingStream:
        if conversation_id in self._pending:
            raise KeyError(f"conversation {conversation_id} already expects a stream")
        entry = self._pending[conversation_id] = PendingStream()
        return entry

    def get(self, conversation_id: uuid.UUID) -> PendingStream | None:
        return self._pending.get(conversation_id)

    def forget(self, conversation_id: uuid.UUID) -> None:
        """Release the entry; a socket handler still waiting on it returns and closes."""
        entry = self._pending.pop(conversation_id, None)
        if entry is not None:
            entry.finished.set()


def stream_base(public_url: str) -> str:
    if public_url.startswith("https://"):
        return "wss://" + public_url.removeprefix("https://").rstrip("/")
    return "ws://" + public_url.removeprefix("http://").rstrip("/")


def create_app(registry: StreamRegistry, public_url: str) -> FastAPI:
    app = FastAPI(title="Truman worker", docs_url=None, redoc_url=None, openapi_url=None)

    def expected(conversation_id: str) -> PendingStream | None:
        """Ids come from Truman's own URLs; anything else is treated like an unknown call."""
        try:
            return registry.get(uuid.UUID(conversation_id))
        except ValueError:
            return None

    @app.api_route("/answer/{conversation_id}", methods=["GET", "POST"])
    async def answer(conversation_id: str) -> Response:
        """Plivo fetches this when the agent answers; an error here reads as a platform fault."""
        if expected(conversation_id) is None:
            return Response(HANGUP_XML, media_type="application/xml")
        url = f"{stream_base(public_url)}/stream/{conversation_id}"
        return Response(STREAM_XML.format(stream_url=url), media_type="application/xml")

    @app.post("/callbacks/{conversation_id}")
    async def callback(conversation_id: str, request: Request) -> Response:
        form = await request.form()
        entry = expected(conversation_id)
        if entry is not None:
            entry.callbacks.put_nowait({key: str(value) for key, value in form.items()})
        return Response(status_code=200)

    @app.websocket("/stream/{conversation_id}")
    async def stream(websocket: WebSocket, conversation_id: str) -> None:
        """Hand the socket to the caller that expects it and hold it open until that call ends."""
        await websocket.accept()
        entry = expected(conversation_id)
        if entry is None or entry.socket.done():
            await websocket.close(code=1008, reason=NO_CALL)
            return
        entry.socket.set_result(websocket)
        await entry.finished.wait()

    return app


class QuietServer(uvicorn.Server):
    """uvicorn would replace the worker's signal handlers; stop ownership stays with the worker."""

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None]:
        yield


class PlivoServer:
    def __init__(self, app: FastAPI, port: int) -> None:
        self._server = QuietServer(
            uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
        )
        self._task: asyncio.Task[None] | None = None

    @property
    def port(self) -> int:
        return self._server.servers[0].sockets[0].getsockname()[1]

    async def start(self) -> None:
        self._task = asyncio.create_task(self._server.serve())
        while not self._server.started:
            if self._task.done():
                self._task.result()
                raise RuntimeError("the plivo server stopped before it started")
            await asyncio.sleep(0.01)
        log.info("plivo server listening on port %d", self.port)

    async def stop(self, timeout_s: float) -> None:
        """Ask uvicorn to finish; a server that will not stop in time is cancelled."""
        if self._task is None:
            return
        self._server.should_exit = True
        await asyncio.wait({self._task}, timeout=timeout_s)
        if not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
