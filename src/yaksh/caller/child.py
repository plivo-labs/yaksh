"""The process that holds one phone conversation for the worker. It has the pipeline imported
and the turn models loaded before the call, waits on its socket for the call, holds it, sends
back what the call left, and leaves. The stream's WebSocket stays in the worker: this process
gets a Starlette WebSocket whose ASGI messages travel over the link, so the pipeline runs as it
does in the worker."""

import asyncio
import ctypes
import logging
import os
import signal
import socket
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn, cast

from starlette.types import Message
from starlette.websockets import WebSocket

from yaksh.caller.audio import Clock
from yaksh.caller.conversation import (
    Connected,
    ConversationStart,
    Ended,
    Heard,
    Spoken,
    hear,
    hold_conversation,
)
from yaksh.caller.lag import LagSampler
from yaksh.caller.link import Kind, Link, open_link
from yaksh.caller.listen import LiveAudio
from yaksh.caller.pipeline import CallerKeys
from yaksh.caller.turn_models import TurnModels
from yaksh.diagnostics import describe_exception
from yaksh.domain.conversations import CallRequest, Turn, WireEvent

log = logging.getLogger(__name__)

LOADED_BY = os.getpid()
"""The process that imported this module: the forkserver, when its preload worked."""
PR_SET_PDEATHSIG = 1
OOM_SCORE_ADJ = "500"
"""Out of memory, the kernel kills a call process before the worker, which holds every call."""
WORKER_GONE_EXIT_S = 10.0
"""How long a call may take to end after its worker went away."""
GONE: Message = {"type": "websocket.disconnect", "code": 1006, "reason": "the worker is gone"}
SCOPE: dict[str, Any] = {
    "type": "websocket",
    "asgi": {"version": "3.0"},
    "scheme": "ws",
    "path": "/stream",
    "raw_path": b"/stream",
    "root_path": "",
    "query_string": b"",
    "headers": [],
    "subprotocols": [],
    "client": None,
    "server": None,
}


@dataclass(frozen=True)
class ChildStart:
    request: CallRequest
    keys: CallerKeys
    clock: tuple[float, datetime]
    """The origin of the worker's call clock."""
    stream_id: str
    call_uuid: str
    encoding: str
    connected_ms: int
    own: bool
    """The worker speaks the persona's own voicemail greeting and sends it when it is ready."""
    database_url: str


def die_with_parent() -> None:
    """On Linux, have the kernel kill this process when its parent dies, also when it is stopped
    or busy in C code. The parent is the thread that started this process."""
    if not sys.platform.startswith("linux"):
        return
    parent = os.getppid()
    if ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGKILL) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")
    if os.getppid() != parent:
        os._exit(1)


def prefer_oom_kill() -> None:
    try:
        with open("/proc/self/oom_score_adj", "w") as adjust:
            adjust.write(OOM_SCORE_ADJ)
    except OSError:
        pass


class LinkedObserver:
    """The worker's observer of the call, called over the link."""

    def __init__(self, link: Link) -> None:
        self._link = link

    def turn(self, turn: Turn) -> None:
        self._link.post(Kind.TURN, turn)

    def wire_event(self, event: WireEvent) -> None:
        self._link.post(Kind.WIRE, event)


def main(end: socket.socket, preloaded: bool) -> NoReturn:
    """`preloaded`: the process comes from a forkserver that should have imported this module."""
    die_with_parent()
    prefer_oom_kill()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(process)d %(message)s"
    )
    if preloaded and os.getpid() == LOADED_BY:
        log.warning("the forkserver did not preload the call process; each call starts slower")
    turns = TurnModels()
    asyncio.run(serve(end, turns))
    raise AssertionError("serve leaves the process")


async def serve(end: socket.socket, turns: TurnModels) -> None:
    """Leaves with os._exit on every path: what a cancelled pipeline left behind, such as a
    thread still in a model, must not hold the process after its result is out."""
    code = 1
    try:
        link = await open_link(end)
        await link.send(Kind.READY, os.getpid())
        try:
            kind, start = await link.receive()
        except asyncio.IncompleteReadError:
            code = 0  # the worker gave the seat back, or stopped
        else:
            if isinstance(start, ChildStart):
                await link.send(*await reply(link, start, turns))
                await link.close()
                code = 0
            else:
                log.error("a call process expected a call, not %s", kind.name)
    finally:
        leave(code)


async def reply(link: Link, start: ChildStart, turns: TurnModels) -> tuple[Kind, object]:
    """HEARD with what the call left, or FAILED with what it raised, a cancel included."""
    try:
        return Kind.HEARD, await hold(link, start, turns)
    except BaseException as error:
        log.exception("conversation %s failed", start.request.conversation_id)
        return Kind.FAILED, describe_exception(error)


def leave(code: int) -> NoReturn:
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


async def hold(link: Link, start: ChildStart, turns: TurnModels) -> Heard:
    inbox: asyncio.Queue[Message] = asyncio.Queue()
    stop = asyncio.Event()
    own = asyncio.get_running_loop().create_future() if start.own else None
    clock = Clock(start.clock)
    live = LiveAudio(start.database_url, start.request.conversation_id)
    listener: asyncio.Task[None] | None = None
    try:
        dialed = Connected(
            await relayed_socket(link, inbox), start.stream_id, start.call_uuid, start.encoding
        )
        conversation = ConversationStart(
            start.request,
            start.keys,
            LinkedObserver(link),
            stop,
            clock,
            dialed,
            own,
            start.connected_ms,
        )
        lag = LagSampler(clock.ms)
        holding = asyncio.ensure_future(hold_conversation(conversation, live, turns))
        listener = asyncio.create_task(listen(link, inbox, stop, own, holding))
        try:
            spoken = await holding
        finally:
            loop_lag = lag.stop()
        started_ms = spoken.recording.start_ms(start.connected_ms)
        await link.send(Kind.ENDED, Ended(clock.ms(), started_ms))
        await live.close()
        return await hear(spoken, started_ms, loop_lag)
    finally:
        if listener is not None:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
        await live.close()


async def listen(
    link: Link,
    inbox: asyncio.Queue[Message],
    stop: asyncio.Event,
    own: asyncio.Future[bytes] | None,
    holding: asyncio.Future[Spoken],
) -> None:
    """What the worker sends during the call. A worker that goes away ends the call, and the
    process leaves WORKER_GONE_EXIT_S later even if the call does not end."""
    try:
        while True:
            kind, payload = await link.receive()
            if kind is Kind.SOCKET:
                inbox.put_nowait(cast(Message, payload))
            elif kind is Kind.STOP:
                stop.set()
            elif kind is Kind.CANCEL:
                holding.cancel()
            elif kind is Kind.OWN and own is not None and not own.done():
                if isinstance(payload, BaseException):
                    own.set_exception(payload)
                else:
                    own.set_result(cast(bytes, payload))
    except asyncio.IncompleteReadError, OSError:
        stop.set()
        inbox.put_nowait(GONE)
        asyncio.get_running_loop().call_later(WORKER_GONE_EXIT_S, os._exit, 1)


async def relayed_socket(link: Link, inbox: asyncio.Queue[Message]) -> WebSocket:
    """A connected WebSocket whose messages are those of the stream in the worker."""
    opened = False

    async def receive() -> Message:
        nonlocal opened
        if not opened:
            opened = True
            return {"type": "websocket.connect"}
        return await inbox.get()

    async def send(message: Message) -> None:
        if message["type"] != "websocket.accept":
            await link.send(Kind.SOCKET, message)

    socket = WebSocket(SCOPE, receive, send)
    await socket.accept()
    return socket
