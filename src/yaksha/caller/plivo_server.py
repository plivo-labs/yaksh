"""The worker's Plivo-facing surface: the answer XML for calls Yaksha places, the answer XML
for calls an outbound agent places to Yaksha, the stream websocket, and the callbacks.

Plivo reaches the worker directly, at one public URL, because the pipeline that owns a call
lives in the worker. A stream is matched to its conversation by the id Yaksha put in the
websocket path when it wrote the answer XML, never by headers.
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass, field
from html import escape

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response

from yaksha import __version__
from yaksha.domain.conversations import Admission, IncomingCall
from yaksha.integrations.plivo_signature import is_signed

log = logging.getLogger(__name__)

STREAM_ELEMENT = (
    '<Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-l16;rate=8000" '
    'extraHeaders="conversation_id={conversation_id}" '
    'statusCallbackUrl="{status_url}" statusCallbackMethod="POST">'
    "{stream_url}</Stream>"
)
XML_HEAD = '<?xml version="1.0" encoding="UTF-8"?><Response>'
REPORT_KEYS = ("Event", "Status", "Cause", "Source", "Reason", "Error")
CALLBACK_RETRIES = "rc=5&ct=2000&rd=1000&rp=5xx,ct"
HANGUP_XML = f"{XML_HEAD}<Hangup/></Response>"
REJECT_XML = f'{XML_HEAD}<Hangup reason="rejected"/></Response>'
NO_CALL = "no call expects this stream"
TIME_LIMIT_MARGIN_S = 30
"""Past the talk-time limit, Plivo itself ends the call, in case the worker cannot."""

type Accept = Callable[[IncomingCall], Awaitable[Admission | str]]


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
        self._calls: dict[str, uuid.UUID] = {}

    def expect(self, conversation_id: uuid.UUID) -> PendingStream:
        if conversation_id in self._pending:
            raise KeyError(f"conversation {conversation_id} already expects a stream")
        entry = self._pending[conversation_id] = PendingStream()
        return entry

    def get(self, conversation_id: uuid.UUID) -> PendingStream | None:
        return self._pending.get(conversation_id)

    def bind(self, call_uuid: str, conversation_id: uuid.UUID) -> None:
        """Route a call's hangup report, which names only its CallUUID, to its conversation."""
        self._calls[call_uuid] = conversation_id

    def for_call(self, call_uuid: str) -> PendingStream | None:
        conversation_id = self._calls.get(call_uuid)
        return None if conversation_id is None else self._pending.get(conversation_id)

    def forget(self, conversation_id: uuid.UUID) -> None:
        """Release the entry; a socket handler still waiting on it returns and closes."""
        entry = self._pending.pop(conversation_id, None)
        if entry is not None:
            entry.finished.set()
        self._calls = {call: cid for call, cid in self._calls.items() if cid != conversation_id}


def public_request_url(base: str, path: str, query: str) -> str:
    """The URL Plivo called, as Plivo sees it: requests reach the worker through a tunnel or
    proxy, so the signed URL is rebuilt from the configured public address."""
    return f"{base.rstrip('/')}{path}" + (f"?{query}" if query else "")


async def signed_fields(
    request: Request, public_url: str, auth_token: str | None
) -> dict[str, str] | None:
    """The request's query and form fields, or None when Plivo did not sign it. Without a
    saved auth token no request counts as signed."""
    if auth_token is None:
        log.warning("refused a request to %s: no Plivo auth token is saved", request.url.path)
        return None
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


def stream_xml(
    public_url: str, conversation_id: uuid.UUID | str, hangup_after_s: int | None
) -> str:
    """Answer XML that connects the call to the conversation's stream. With hangup_after_s,
    Plivo hangs up after that many seconds even if the worker is gone."""
    stream = STREAM_ELEMENT.format(
        conversation_id=conversation_id,
        stream_url=f"{stream_base(public_url)}/stream/{conversation_id}",
        status_url=escape(
            f"{public_url.rstrip('/')}/stream-status/{conversation_id}#{CALLBACK_RETRIES}"
        ),
    )
    hangup = "" if hangup_after_s is None else f'<Hangup schedule="{hangup_after_s}"/>'
    return f"{XML_HEAD}{hangup}{stream}</Response>"


def plus_e164(number: str) -> str:
    """Plivo sends numbers with or without the leading +."""
    return "+" + number.strip().lstrip("+")


def create_app(
    registry: StreamRegistry,
    public_url: str | None,
    auth_token: Callable[[], str | None],
    accept: Accept,
) -> FastAPI:
    """accept admits calls to Yaksha's numbers, or says why it refuses them. auth_token gives
    the Plivo auth token of the current settings, so a changed token applies at once. Without a
    public URL, Plivo cannot reach the worker, so the app has only its health route."""
    app = FastAPI(title="Yaksha worker", docs_url=None, redoc_url=None, openapi_url=None)

    def expected(conversation_id: str) -> PendingStream | None:
        """Ids come from Yaksha's own URLs; anything else is treated like an unknown call."""
        try:
            return registry.get(uuid.UUID(conversation_id))
        except ValueError:
            return None

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    if public_url is None:
        return app

    @app.post("/answer/{conversation_id}")
    async def answer(conversation_id: str, request: Request) -> Response:
        """Plivo fetches this when the agent answers; an error here reads as a platform fault."""
        report = await signed_fields(request, public_url, auth_token())
        if report is None:
            return Response(status_code=403)
        entry = expected(conversation_id)
        if entry is None:
            return Response(HANGUP_XML, media_type="application/xml")
        entry.callbacks.put_nowait(report)
        return Response(
            stream_xml(public_url, conversation_id, hangup_after_s=None),
            media_type="application/xml",
        )

    @app.post("/incoming")
    async def incoming(request: Request) -> Response:
        """An outbound agent calls one of Yaksha's numbers; answer it for the conversation
        waiting on that number, or refuse it."""
        report = await signed_fields(request, public_url, auth_token())
        if report is None:
            return Response(status_code=403)
        call = IncomingCall(
            to_number=plus_e164(report.get("To", "")),
            from_number=plus_e164(report.get("From", "")),
            call_uuid=report.get("CallUUID", ""),
        )
        verdict = await accept(call)
        entry = registry.get(verdict.conversation_id) if isinstance(verdict, Admission) else None
        if not isinstance(verdict, Admission) or entry is None:
            reason = verdict if isinstance(verdict, str) else "no call on this worker waits for it"
            log.warning(
                "refused a call from %s to %s: %s", call.from_number, call.to_number, reason
            )
            return Response(REJECT_XML, media_type="application/xml")
        registry.bind(call.call_uuid, verdict.conversation_id)
        entry.callbacks.put_nowait(report)
        return Response(
            stream_xml(
                public_url,
                verdict.conversation_id,
                hangup_after_s=verdict.max_duration_s + TIME_LIMIT_MARGIN_S,
            ),
            media_type="application/xml",
        )

    @app.post("/incoming/hangup")
    async def incoming_hangup(request: Request) -> Response:
        report = await signed_fields(request, public_url, auth_token())
        if report is None:
            return Response(status_code=403)
        log.info("plivo reported %s for incoming call %s", summary(report), report.get("CallUUID"))
        entry = registry.for_call(report.get("CallUUID", ""))
        if entry is not None:
            entry.callbacks.put_nowait(report)
        return Response(status_code=200)

    @app.post("/callbacks/{conversation_id}")
    async def callback(conversation_id: str, request: Request) -> Response:
        report = await signed_fields(request, public_url, auth_token())
        if report is None:
            return Response(status_code=403)
        log.info("plivo reported %s for conversation %s", summary(report), conversation_id)
        entry = expected(conversation_id)
        if entry is not None:
            entry.callbacks.put_nowait(report)
        return Response(status_code=200)

    @app.post("/stream-status/{conversation_id}")
    async def stream_status(conversation_id: str, request: Request) -> Response:
        """Stream events (started, audio cleared, stopped) are only logged: the socket and the
        hangup report already tell a call what happened."""
        report = await signed_fields(request, public_url, auth_token())
        if report is None:
            return Response(status_code=403)
        log.info("plivo reported %s for the stream of %s", summary(report), conversation_id)
        return Response(status_code=200)

    @app.websocket("/stream/{conversation_id}")
    async def stream(websocket: WebSocket, conversation_id: str) -> None:
        """Hand the socket to the caller that expects it and hold it open until that call ends."""
        url = public_request_url(
            stream_signature_base(public_url), websocket.url.path, websocket.url.query
        )
        token = auth_token()
        if token is None or not is_signed(websocket.headers, token, "GET", url, {}):
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
