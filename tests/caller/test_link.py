import asyncio
import socket
from collections.abc import AsyncIterator
from typing import cast

import pytest

from yaksh.caller.link import HEADER, Kind, Link, open_link


@pytest.fixture
async def links() -> AsyncIterator[tuple[Link, Link]]:
    one, other = socket.socketpair()
    worker, child = await open_link(one), await open_link(other)
    yield worker, child
    worker.abort()
    child.abort()


async def test_messages_arrive_whole_and_in_order(links: tuple[Link, Link]) -> None:
    worker, child = links
    audio = {"type": "websocket.receive", "text": "x" * 200_000}

    async def three() -> list[tuple[Kind, object]]:
        return [await child.receive() for _ in range(3)]

    received = asyncio.create_task(three())

    worker.post(Kind.SOCKET, audio)
    await worker.send(Kind.STOP, None)
    await worker.send(Kind.SPEECH, (1, ValueError("no greeting")))
    first, second, (kind, speech) = await received
    index, error = cast(tuple[int, Exception], speech)

    assert first == (Kind.SOCKET, audio)
    assert second == (Kind.STOP, None)
    assert (kind, index) == (Kind.SPEECH, 1)
    assert isinstance(error, ValueError) and error.args == ("no greeting",)


async def test_a_closed_or_cut_peer_ends_the_receiver(links: tuple[Link, Link]) -> None:
    worker, child = links
    await worker.close()
    with pytest.raises(asyncio.IncompleteReadError):
        await child.receive()

    one, other = socket.socketpair()
    reader = await open_link(one)
    other.sendall(HEADER.pack(10, Kind.HEARD) + b"part")
    other.close()
    with pytest.raises(asyncio.IncompleteReadError):
        await reader.receive()
    reader.abort()


async def test_close_sends_what_is_queued(links: tuple[Link, Link]) -> None:
    worker, child = links
    worker.post(Kind.HEARD, b"result")
    await worker.close()

    assert await child.receive() == (Kind.HEARD, b"result")


async def test_closing_after_an_abort_does_nothing_more(links: tuple[Link, Link]) -> None:
    worker, child = links
    worker.abort()
    await worker.close()

    with pytest.raises(asyncio.IncompleteReadError):
        await child.receive()
