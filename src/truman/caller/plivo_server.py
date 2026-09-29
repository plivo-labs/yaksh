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
from html import escape

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response

from truman.integrations.plivo_signature import is_signed

log = logging.getLogger(__name__)

STREAM_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><Response>'
    '<Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-l16;rate=8000" '
    'extraHeaders="conversation_id={conversation_id}" '
    'statusCallbackUrl="{status_url}" statusCallbackMethod="POST">'
    "{stream_url}</Stream></Response>"
)
REPORT_KEYS = ("Event", "Status", "Cause", "Source", "Reason", "Error")
CALLBACK_RETRIES = "rc=5&ct=2000&rd=1000&rp=5xx,ct"
HANGUP_XML = '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'
NO_CALL = "no call expects this stream"


@dataclass
class PendingStream:
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


def public_request_url(base: str, path: str, query: str) -> str:
    """The URL Plivo called, as Plivo sees it: requests reach the worker through a tunnel or
    proxy, so the signed URL is rebuilt from the configured public address."""
    return f"{base.rstrip('/')}{path}" + (f"?{query}" if query else "")


async def signed_fields(
    request: Request, public_url: str, auth_token: str
) -> dict[str, str] | None:
    """The request's query and form fields, or None when Plivo did not sign it."""
    form = await request.form()
    params: dict[str, list[str]] = {}
    for key, value in form.multi_items():
        params.setdefault(key, []).append(str(value))
    url = public_request_url(public_url, request.url.path, request.url.query)
    if not is_signed(request.headers, auth_token, "POST", url, params):
        log.warning("refused an unsigned request to %s", request.url.path)
        return None
    return {key: str(value) for key, value in (*request.query_params.items(), *form.items())}


def summary(report: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in report.items() if any(k in key for k in REPORT_KEYS)}


def stream_signature_base(public_url: str) -> str:
    """Plivo signs a stream's websocket upgrade against http://host/path, whatever the scheme
    of the stream URL (checked on live calls; its docs say the full wss URI)."""
    return "http://" + public_url.split("://", 1)[-1].rstrip("/")


def stream_base(public_url: str) -> str:
    if public_url.startswith("https://"):
        return "wss://" + public_url.removeprefix("https://").rstrip("/")
    return "ws://" + public_url.removeprefix("http://").rstrip("/")


def create_app(registry: StreamRegistry, public_url: str, auth_token: str) -> FastAPI:
    app = FastAPI(title="Truman worker", docs_url=None, redoc_url=None, openapi_url=None)

    def expected(conversation_id: str) -> PendingStream | None:
        """Ids come from Truman's own URLs; anything else is treated like an unknown call."""
        try:
            return registry.get(uuid.UUID(conversation_id))
        except ValueError:
            return None

    @app.post("/answer/{conversation_id}")
    async def answer(conversation_id: str, request: Request) -> Response:
        """Plivo fetches this when the agent answers; an error here reads as a platform fault."""
        report = await signed_fields(request, public_url, auth_token)
        if report is None:
            return Response(status_code=403)
        entry = expected(conversation_id)
        if entry is None:
            return Response(HANGUP_XML, media_type="application/xml")
        entry.callbacks.put_nowait(report)
        xml = STREAM_XML.format(
            conversation_id=conversation_id,
            stream_url=f"{stream_base(public_url)}/stream/{conversation_id}",
            status_url=escape(
                f"{public_url.rstrip('/')}/callbacks/{conversation_id}#{CALLBACK_RETRIES}"
            ),
        )
        return Response(xml, media_type="application/xml")

    @app.post("/callbacks/{conversation_id}")
    async def callback(conversation_id: str, request: Request) -> Response:
        report = await signed_fields(request, public_url, auth_token)
        if report is None:
            return Response(status_code=403)
        log.info("plivo reported %s for conversation %s", summary(report), conversation_id)
        entry = expected(conversation_id)
        if entry is not None:
            entry.callbacks.put_nowait(report)
        return Response(status_code=200)

    @app.websocket("/stream/{conversation_id}")
    async def stream(websocket: WebSocket, conversation_id: str) -> None:
        """Hand the socket to the caller that expects it and hold it open until that call ends."""
        url = public_request_url(
            stream_signature_base(public_url), websocket.url.path, websocket.url.query
        )
        if not is_signed(websocket.headers, auth_token, "GET", url, {}):
            log.warning("refused an unsigned stream for conversation %s", conversation_id)
            await websocket.close(code=1008)
            return
        await websocket.accept()
        entry = expected(conversation_id)
        if entry is None or entry.socket.done():
            log.warning("refused a stream for conversation %s: %s", conversation_id, NO_CALL)
            await websocket.close(code=1008, reason=NO_CALL)
            return
        log.info("stream connected for conversation %s", conversation_id)
        entry.socket.set_result(websocket)
        await entry.finished.wait()
        log.info("stream released for conversation %s", conversation_id)

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
        if self._task is None:
            return
        self._server.should_exit = True
        await asyncio.wait({self._task}, timeout=timeout_s)
        if not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
