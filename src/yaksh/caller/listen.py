"""A running call's audio for listeners in the console. It is taken inside the pipeline, so it
does not depend on the transport, and it goes to the API with Postgres NOTIFY only while someone
listens."""

import asyncio
import base64
import logging
import time
import uuid
from collections import deque
from collections.abc import Iterator

import asyncpg
from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from yaksh.db.session import notify_connection
from yaksh.domain.listen import AGENT, CALLER, KEEPALIVE_S, WANT_S, channels, encode

log = logging.getLogger(__name__)

TICK_S = 0.05
"""How often the sender puts the waiting audio into NOTIFYs."""
QUEUE_LIMIT = 250
"""Messages that wait for the sender before the oldest goes: about 2.5 s of both sides."""
PAYLOAD_LIMIT = 7000
"""Postgres refuses a NOTIFY payload of 8000 bytes or more."""


class LiveAudio:
    """One call's audio for listeners, sent with NOTIFY on the call's audio channel while the
    API asks for it: the API sends a NOTIFY on the call's want channel every few seconds while a
    listener stays. A new LiveAudio sends for one such interval at once, because a listener who
    asked before it existed asks again only then. put never waits, and a Postgres error stops
    the listening, not the call. An empty NOTIFY marks the end of the call."""

    def __init__(self, database_url: str, conversation_id: uuid.UUID) -> None:
        self._audio, self._want = channels(conversation_id)
        self._queue: deque[bytes] = deque(maxlen=QUEUE_LIMIT)
        self._wanted_until = time.monotonic() + KEEPALIVE_S
        self._task = asyncio.create_task(self._send(database_url))

    def put(self, side: int, at_ms: float, pcm: bytes) -> None:
        if time.monotonic() < self._wanted_until:
            self._queue.append(encode(side, at_ms, pcm))

    def _asked(self, *_: object) -> None:
        self._wanted_until = time.monotonic() + WANT_S

    async def _send(self, database_url: str) -> None:
        try:
            async with notify_connection(database_url) as connection:
                await connection.execute("SET synchronous_commit = off")
                await connection.add_listener(self._want, self._asked)
                try:
                    while True:
                        await asyncio.sleep(TICK_S)
                        await self._flush(connection)
                finally:
                    await self._flush(connection)
                    await connection.execute("SELECT pg_notify($1, '')", self._audio)
        except Exception:
            log.exception("live audio on %s stopped", self._audio)

    async def _flush(self, connection: asyncpg.Connection) -> None:
        for payload in batches(self._queue):
            await connection.execute("SELECT pg_notify($1, $2)", self._audio, payload)

    async def close(self) -> None:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


def batches(queue: deque[bytes]) -> Iterator[str]:
    """The waiting messages as NOTIFY payloads: base64, joined by commas, each under the
    limit."""
    payload: list[str] = []
    size = 0
    while queue:
        text = base64.b64encode(queue.popleft()).decode()
        if payload and size + len(text) + 1 > PAYLOAD_LIMIT:
            yield ",".join(payload)
            payload, size = [], 0
        payload.append(text)
        size += len(text) + 1
    if payload:
        yield ",".join(payload)


class AudioTap(BaseObserver):
    """Both sides of the call as Pipecat's observer sees each push: the agent's audio from the
    input transport as it arrives, and the caller's audio from the output transport after the
    transport sent it, with the background noise mixed in. Each piece keeps the time of its push
    on the pipeline's clock, because the observer's own queue can fall behind. The observer runs
    on its own queue, so a listener cannot slow the call."""

    def __init__(
        self, transport_input: FrameProcessor, transport_output: FrameProcessor, live: LiveAudio
    ) -> None:
        super().__init__()
        self._input = transport_input
        self._output = transport_output
        self._live = live

    async def on_push_frame(self, data: FramePushed) -> None:
        if data.direction is not FrameDirection.DOWNSTREAM:
            return
        if data.source is self._input and isinstance(data.frame, InputAudioRawFrame):
            side = AGENT
        elif data.source is self._output and isinstance(data.frame, OutputAudioRawFrame):
            side = CALLER
        else:
            return
        self._live.put(side, data.timestamp / 1_000_000, data.frame.audio)
