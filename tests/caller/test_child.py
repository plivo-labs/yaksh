import asyncio
import socket
from collections.abc import AsyncIterator
from typing import cast

import pytest
from starlette.types import Message

from yaksh.caller import child
from yaksh.caller.child import GONE, listen, relayed_socket
from yaksh.caller.conversation import Spoken
from yaksh.caller.link import Kind, Link, open_link


@pytest.fixture
async def links() -> AsyncIterator[tuple[Link, Link]]:
    one, other = socket.socketpair()
    worker, process = await open_link(one), await open_link(other)
    yield worker, process
    worker.abort()
    process.abort()


async def test_the_relayed_socket_carries_the_stream_both_ways(links: tuple[Link, Link]) -> None:
    worker, process = links
    inbox: asyncio.Queue[Message] = asyncio.Queue()

    stream = await relayed_socket(process, inbox)
    inbox.put_nowait({"type": "websocket.receive", "text": "media"})
    await stream.send_text("playAudio")

    assert await stream.receive_text() == "media"
    assert await worker.receive() == (Kind.SOCKET, {"type": "websocket.send", "text": "playAudio"})


async def test_the_worker_stops_cancels_and_greets_the_call_through_its_messages(
    links: tuple[Link, Link],
) -> None:
    worker, process = links
    inbox: asyncio.Queue[Message] = asyncio.Queue()
    stop, own = asyncio.Event(), asyncio.get_running_loop().create_future()
    holding = cast(asyncio.Future[Spoken], asyncio.ensure_future(asyncio.sleep(3600)))
    listening = asyncio.create_task(listen(process, inbox, stop, own, holding))

    await worker.send(Kind.SOCKET, {"type": "websocket.receive", "text": "media"})
    await worker.send(Kind.OWN, b"greeting")
    await worker.send(Kind.STOP, None)
    await worker.send(Kind.CANCEL, None)
    await asyncio.wait_for(stop.wait(), 5)
    await asyncio.wait({holding}, timeout=5)
    listening.cancel()

    assert inbox.get_nowait() == {"type": "websocket.receive", "text": "media"}
    assert own.result() == b"greeting" and holding.cancelled()


async def test_a_worker_that_goes_away_ends_the_call(
    links: tuple[Link, Link], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(child, "WORKER_GONE_EXIT_S", 3600)
    worker, process = links
    inbox: asyncio.Queue[Message] = asyncio.Queue()
    stop = asyncio.Event()
    holding = cast(asyncio.Future[Spoken], asyncio.ensure_future(asyncio.sleep(3600)))

    await worker.close()
    await listen(process, inbox, stop, None, holding)

    assert stop.is_set() and inbox.get_nowait() == GONE
    holding.cancel()
