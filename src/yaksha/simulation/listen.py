"""A live call's audio for one listener, from the worker's NOTIFYs on the call's audio
channel."""

import asyncio
import base64
import uuid
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yaksha.db.session import notify_connection
from yaksha.domain.conversations import LIVE_STATUSES
from yaksha.domain.listen import KEEPALIVE_S, channels, framed
from yaksha.simulation.conversations import get_conversation

QUEUE_LIMIT = 250
"""Messages that wait for a slow listener before the oldest goes: about 2.5 s of both sides."""


async def live_audio(
    sessionmaker: async_sessionmaker[AsyncSession], database_url: str, conversation_id: uuid.UUID
) -> AsyncIterator[bytes]:
    """The call's audio from now on, each message with its length in front, until the call
    ends or the connection to Postgres fails. It listens before it asks, so the first audio is
    not lost. A listener that falls behind loses the oldest audio; the call never waits for
    it."""
    audio, want = channels(conversation_id)
    queue: asyncio.Queue[bytes | None] = asyncio.Queue(QUEUE_LIMIT)

    def heard(_connection: object, _pid: int, _channel: str, payload: str) -> None:
        if not payload:
            offer(queue, None)
            return
        for text in payload.split(","):
            offer(queue, base64.b64decode(text))

    loop = asyncio.get_running_loop()
    async with notify_connection(database_url) as connection:
        connection.add_termination_listener(lambda _connection: offer(queue, None))
        await connection.add_listener(audio, heard)
        while await live(sessionmaker, conversation_id):
            await connection.execute("SELECT pg_notify($1, '')", want)
            asked = loop.time()
            while (left := asked + KEEPALIVE_S - loop.time()) > 0:
                try:
                    message = await asyncio.wait_for(queue.get(), left)
                except TimeoutError:
                    break
                if message is None:
                    return
                yield framed(message)


def offer(queue: asyncio.Queue[bytes | None], message: bytes | None) -> None:
    if queue.full():
        queue.get_nowait()
    queue.put_nowait(message)


async def live(sessionmaker: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID) -> bool:
    async with sessionmaker() as session:
        conversation = await get_conversation(session, conversation_id)
    return conversation.status in LIVE_STATUSES
