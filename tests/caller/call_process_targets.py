"""What the call processes in the tests run: each speaks the worker's protocol in one way. They
are module functions, so a spawned or forked process can import them by name."""

import asyncio
import os
import socket
import time
from collections.abc import Awaitable, Callable

from yaksh.caller.conversation import Ended, Heard
from yaksh.caller.link import Kind, Link, open_link
from yaksh.domain.conversations import (
    CallerSettings,
    CallerUsage,
    EndReason,
    WireEvent,
    WireEventKind,
)

ENDED = Ended(at_ms=60_000, started_ms=1_000)
"""Late on the call clock, so a stall during a test falls inside the call."""
HOLDING = WireEvent(kind=WireEventKind.AGENT_AUDIO, at_ms=0)
"""What each process sends once it holds the call."""
HEARD = Heard(
    end_reason=EndReason.AGENT_HANGUP,
    error=None,
    caller_reason=None,
    serializer_failure=None,
    recording=b"wav",
    agent_media=None,
    caller_replies=[],
    caller_voice=None,
    caller_settings=CallerSettings(llm_model="model", reasoning_effort=None),
    caller_usage=CallerUsage(),
    caller_reply_times=[],
    loop_lag=None,
)


def run(end: socket.socket, script: Callable[[Link], Awaitable[None]]) -> None:
    async def main() -> None:
        link = await open_link(end)
        await link.send(Kind.READY, os.getpid())
        await link.receive()  # START
        await link.send(Kind.WIRE, HOLDING)
        await script(link)

    asyncio.run(main())
    os._exit(0)


async def until(link: Link, kind: Kind) -> None:
    while (await link.receive())[0] is not kind:
        pass


async def finish(link: Link) -> None:
    await link.send(Kind.ENDED, ENDED)
    await link.send(Kind.HEARD, HEARD)
    await link.close()


def holds(end: socket.socket, _preloaded: bool) -> None:
    run(end, finish)


def never_ready(_end: socket.socket, _preloaded: bool) -> None:
    time.sleep(3600)


def dies_at_start(end: socket.socket, _preloaded: bool) -> None:
    async def die(_link: Link) -> None:
        os._exit(3)

    run(end, die)


def ignores_cancel(end: socket.socket, _preloaded: bool) -> None:
    async def ignore(link: Link) -> None:
        while True:
            await link.receive()

    run(end, ignore)


def ends_but_never_hears(end: socket.socket, _preloaded: bool) -> None:
    async def stall(link: Link) -> None:
        await until(link, Kind.CANCEL)
        await link.send(Kind.ENDED, ENDED)
        time.sleep(3600)

    run(end, stall)


def hears_but_stays(end: socket.socket, _preloaded: bool) -> None:
    async def stay(link: Link) -> None:
        await until(link, Kind.CANCEL)
        await link.send(Kind.ENDED, ENDED)
        await link.send(Kind.HEARD, HEARD)
        time.sleep(3600)

    run(end, stay)


def ends_when_told(end: socket.socket, _preloaded: bool) -> None:
    """The conversation ends at the start of the call clock, but the process tells the worker
    only once the stream gives a message; the result follows the worker's cancel."""

    async def end_late(link: Link) -> None:
        await until(link, Kind.SOCKET)
        await link.send(Kind.ENDED, Ended(at_ms=0, started_ms=0))
        await until(link, Kind.CANCEL)
        await link.send(Kind.HEARD, HEARD)
        await link.close()

    run(end, end_late)


def sends_audio(end: socket.socket, _preloaded: bool) -> None:
    """One audio message, then the end once the worker cancels."""

    async def speak(link: Link) -> None:
        await link.send(Kind.SOCKET, {"type": "websocket.send", "text": "audio"})
        await until(link, Kind.CANCEL)
        await finish(link)

    run(end, speak)


def closes_the_stream(end: socket.socket, _preloaded: bool) -> None:
    async def close(link: Link) -> None:
        await link.send(Kind.SOCKET, {"type": "websocket.send", "text": "goodbye"})
        await link.send(Kind.SOCKET, {"type": "websocket.close", "code": 1000, "reason": ""})
        await finish(link)

    run(end, close)
