import asyncio
import base64
import json
import time
from collections.abc import Callable
from typing import Any

import audioop

from truman.caller.plivo import FRAME_BYTES, SILENCE, Clock, Playout, Wire
from truman.domain.conversations import Turn, WireEvent, WireEventKind

SPEECH_FRAME = b"\x10\x00" * (FRAME_BYTES // 2)
SILENCE_PAYLOAD = base64.b64encode(audioop.lin2ulaw(SILENCE, 2)).decode()


class Observer:
    def __init__(self) -> None:
        self.events: list[WireEvent] = []
        self.turns: list[Turn] = []

    def turn(self, turn: Turn) -> None:
        self.turns.append(turn)

    def wire_event(self, event: WireEvent) -> None:
        self.events.append(event)

    def kinds(self) -> list[WireEventKind]:
        return [event.kind for event in self.events]


class Socket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.pushed: list[bytes] = []

    async def send(self, message: str) -> bool:
        self.sent.append(json.loads(message))
        return True

    async def push(self, pcm: bytes) -> None:
        self.pushed.append(pcm)

    def events(self, name: str) -> list[dict[str, Any]]:
        return [message for message in self.sent if message["event"] == name]

    def speech_frames(self) -> int:
        return sum(1 for m in self.events("media") if m["media"]["payload"] != SILENCE_PAYLOAD)


def play_audio(ms: int) -> dict[str, Any]:
    ulaw = audioop.lin2ulaw(SPEECH_FRAME * (ms // 20), 2)
    return {"event": "playAudio", "media": {"payload": base64.b64encode(ulaw).decode()}}


async def running(wire: Wire, socket: Socket) -> asyncio.Task[None]:
    task = asyncio.create_task(wire.run(socket.send, socket.push))
    await asyncio.sleep(0)
    return task


async def test_a_checkpoint_is_acknowledged_once_its_audio_has_played() -> None:
    observer, socket = Observer(), Socket()
    wire = Wire("stream", Clock(), observer)
    wire.handle(play_audio(400))
    wire.handle({"event": "checkpoint", "name": "greeting"})
    task = await running(wire, socket)

    await asyncio.sleep(0.1)
    assert not socket.events("playedStream") and socket.pushed[0] != SILENCE
    await asyncio.sleep(0.6)
    task.cancel()

    assert [m["name"] for m in socket.events("playedStream")] == ["greeting"]
    assert socket.pushed[-1] == SILENCE
    assert observer.kinds() == [WireEventKind.AGENT_AUDIO, WireEventKind.CHECKPOINT]


async def test_clear_audio_drops_the_rest_and_is_acknowledged_at_once() -> None:
    observer, socket = Observer(), Socket()
    wire = Wire("stream", Clock(), observer)
    wire.handle(play_audio(1000))
    wire.handle({"event": "checkpoint", "name": "greeting"})
    task = await running(wire, socket)
    await asyncio.sleep(0.1)

    wire.handle({"event": "clearAudio"})
    await asyncio.sleep(0.1)
    task.cancel()

    assert socket.events("clearedAudio") and not socket.events("playedStream")
    assert socket.pushed[-1] == SILENCE
    assert observer.kinds()[-1] is WireEventKind.CLEAR_AUDIO


async def test_a_reply_right_after_the_caller_stops_is_stamped_from_the_wire() -> None:
    observer, socket = Observer(), Socket()
    wire = Wire("stream", Clock(), observer)
    task = await running(wire, socket)

    assert await wire.transmit(SPEECH_FRAME * 5, None)
    wire.handle(play_audio(40))
    await asyncio.sleep(0.1)
    task.cancel()

    events = {event.kind: event.at_ms for event in observer.events}
    assert 0 <= events[WireEventKind.AGENT_AUDIO] - events[WireEventKind.CALLER_SPEECH_END] <= 60
    assert observer.kinds()[0] is WireEventKind.CALLER_SPEECH_START


async def test_transmit_paces_the_wire_and_an_interruption_drops_what_is_left() -> None:
    observer, socket = Observer(), Socket()
    wire = Wire("stream", Clock(), observer)
    task = await running(wire, socket)

    playout = Playout()
    started = time.monotonic()
    assert await wire.transmit(SPEECH_FRAME * 10, playout)
    elapsed = time.monotonic() - started
    await asyncio.sleep(0.3)
    later = asyncio.create_task(wire.transmit(SPEECH_FRAME * 50, playout))
    await asyncio.sleep(0.1)
    wire.drop_outbound()
    assert await later
    await asyncio.sleep(0.05)
    task.cancel()

    assert 0.18 <= elapsed <= 0.5
    assert 10 < socket.speech_frames() < 30
    assert playout.sent == socket.speech_frames() * FRAME_BYTES


async def test_a_frame_sent_under_backpressure_is_credited_to_its_reply_once_settled() -> None:
    gate = asyncio.Event()
    gate.set()

    class Gated(Socket):
        entered = 0

        async def send(self, message: str) -> bool:
            self.entered += 1
            await gate.wait()
            return await super().send(message)

    observer, socket = Observer(), Gated()
    wire = Wire("stream", Clock(), observer)
    first, second = Playout(), Playout()
    task = await running(wire, socket)
    sending_first = asyncio.create_task(wire.transmit(SPEECH_FRAME * 2, first))
    await wait_until(lambda: socket.speech_frames() == 1)
    gate.clear()
    await wait_until(lambda: socket.entered == len(socket.sent) + 1)

    wire.drop_outbound()
    assert await sending_first
    settled = asyncio.create_task(wire.settle())
    await asyncio.sleep(0.02)
    assert not settled.done() and first.sent == FRAME_BYTES
    sending_second = asyncio.create_task(wire.transmit(SPEECH_FRAME * 3, second))
    gate.set()
    await settled
    assert first.sent == 2 * FRAME_BYTES
    assert await sending_second
    task.cancel()

    assert second.sent == 3 * FRAME_BYTES


async def wait_until(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.005)


async def test_a_send_that_stalls_ends_the_wire_within_its_bound() -> None:
    class Stuck(Socket):
        entered = 0

        async def send(self, message: str) -> bool:
            self.entered += 1
            if self.entered > 1:
                await asyncio.sleep(3600)
            return await super().send(message)

    observer, socket = Observer(), Stuck()
    wire = Wire("stream", Clock(), observer, send_timeout_s=0.2)
    task = await running(wire, socket)
    sending = asyncio.create_task(wire.transmit(SPEECH_FRAME * 5, Playout()))
    started = time.monotonic()

    await asyncio.wait({task}, timeout=2)

    assert task.done() and time.monotonic() - started < 1.0
    assert wire.failed and wire.hung_up.is_set() and not await sending
    assert observer.kinds()[-1] is WireEventKind.CALLER_ERROR
