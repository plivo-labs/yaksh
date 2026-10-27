"""The channel between the worker and the process that holds one call: pickled messages, each
with its kind, over a socket pair. Both ends run the same code and the socket never leaves the
host, so pickle is safe here."""

import asyncio
import pickle
import socket
import struct
from enum import IntEnum


class Kind(IntEnum):
    READY = 1
    """Child to worker: the pipeline is imported and the turn models are loaded."""
    START = 2
    """Worker to child: the call to hold."""
    STOP = 3
    """Worker to child: the call's stop event was set."""
    OWN = 4
    """Worker to child: the persona's own voicemail greeting, or what speaking it raised."""
    SOCKET = 5
    """Either way: one ASGI message of the stream's WebSocket."""
    TURN = 6
    """Child to worker: a call of the observer's `turn`."""
    WIRE = 7
    """Child to worker: a call of the observer's `wire_event`."""
    ENDED = 8
    """Child to worker: when the conversation ended, as `Ended`."""
    HEARD = 9
    """Child to worker: what the finished conversation left, as `Heard`."""
    FAILED = 10
    """Child to worker: what the conversation raised."""
    CANCEL = 11
    """Worker to child: the worker gave up on the call; end it as worker_stopped."""


HEADER = struct.Struct("!IB")
CLOSE_TIMEOUT_S = 2.0


class Link:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._closed = False

    def post(self, kind: Kind, payload: object) -> None:
        """Queue a message without waiting, for callers that cannot wait, such as observers."""
        data = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
        self._writer.write(HEADER.pack(len(data), kind) + data)

    async def send(self, kind: Kind, payload: object) -> None:
        self.post(kind, payload)
        await self._writer.drain()

    async def receive(self) -> tuple[Kind, object]:
        """Raises asyncio.IncompleteReadError once the other end has closed."""
        size, kind = HEADER.unpack(await self._reader.readexactly(HEADER.size))
        return Kind(kind), pickle.loads(await self._reader.readexactly(size))

    def at_eof(self) -> bool:
        """The other end has closed, and every message it sent has been read."""
        return self._reader.at_eof()

    async def close(self) -> None:
        """Close after the queued messages are out, for at most CLOSE_TIMEOUT_S: a peer that has
        stopped reading cannot hold the caller."""
        if self._closed:
            return
        self._writer.close()
        try:
            await asyncio.wait_for(self._writer.wait_closed(), CLOSE_TIMEOUT_S)
        except TimeoutError:
            self.abort()
        except OSError:
            pass
        self._closed = True

    def abort(self) -> None:
        """Close now, dropping what is still queued."""
        if not self._closed:
            self._closed = True
            self._writer.transport.abort()


async def open_link(end: socket.socket) -> Link:
    reader, writer = await asyncio.open_connection(sock=end)
    return Link(reader, writer)
