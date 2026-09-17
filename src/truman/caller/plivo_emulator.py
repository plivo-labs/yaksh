"""Truman playing Plivo's side of a stream toward the agent under test.

This emulator stands in until the phone leg lands and Plivo carries the audio itself.

Plivo carries 8 kHz mu-law in 20 ms frames both ways, and the agent under test expects a
continuous inbound stream. One clock therefore sends caller audio or silence every tick and
paces the agent's audio into the pipeline at the same rate, so a checkpoint is acknowledged
when its audio has actually played. Every latency-relevant moment is recorded as a wire
event with its time; latency is derived after the call, never measured online.
"""

import asyncio
import base64
import contextlib
import json
import time
import wave
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import audioop

from truman.caller.audio import (
    FRAME_BYTES,
    FRAME_S,
    GAP_BYTES,
    SAMPLE_RATE,
    SILENCE,
    SPEECH_PEAK,
    Clock,
    Playout,
)
from truman.domain.conversations import CallObserver, WireEvent, WireEventKind

STOP_SEND_S = 1.0
SEND_TIMEOUT_S = 2.0
STALLED = "the agent stopped reading the stream"

Send = Callable[[str], Awaitable[bool]]
Push = Callable[[bytes], Awaitable[None]]


def start_message(call_id: str, stream_id: str, extra_headers: dict[str, str]) -> str:
    return json.dumps(
        {
            "event": "start",
            "sequenceNumber": 1,
            "start": {
                "callId": call_id,
                "streamId": stream_id,
                "accountId": "truman",
                "tracks": ["inbound"],
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": SAMPLE_RATE},
            },
            "extra_headers": json.dumps(extra_headers),
        }
    )


def stop_message() -> str:
    return json.dumps({"event": "stop"})


async def sleep_until(deadline: float) -> float:
    """Sleep to the deadline and return it, or return now when already late: no catch-up bursts."""
    delay = deadline - time.monotonic()
    if delay <= 0:
        return time.monotonic()
    await asyncio.sleep(delay)
    return deadline


class Wire:
    """Both directions of the stream on one 20 ms clock, and the recording of each side."""

    def __init__(
        self,
        stream_id: str,
        clock: Clock,
        observer: CallObserver,
        *,
        send_timeout_s: float = SEND_TIMEOUT_S,
    ) -> None:
        self.stream_id = stream_id
        self.hung_up = asyncio.Event()
        self.closed = asyncio.Event()
        self.failed: str | None = None
        self._send_timeout_s = send_timeout_s
        self.agent_pcm = bytearray()
        self.caller_pcm = bytearray()
        self._clock = clock
        self._observer = observer
        self._out = bytearray()
        self._in = bytearray()
        self._received = 0
        self._played = 0
        self._checkpoints: deque[tuple[int, str]] = deque()
        self._acks: list[str] = []
        self._drained = asyncio.Event()
        self._sequence = 0
        self._speaking = False
        self._last_speech_ms = 0
        self._quiet = GAP_BYTES
        self._playout: Playout | None = None
        self._in_flight = asyncio.Event()
        self._in_flight.set()
        self._socket_lost = False

    async def transmit(self, pcm: bytes, playout: Playout | None) -> bool:
        """Queue caller audio and return once the clock has sent it, or False if the wire closed."""
        if self.closed.is_set():
            return False
        self._playout = playout
        self._out.extend(pcm)
        self._drained.clear()
        await self._drained.wait()
        return not self.closed.is_set()

    def drop_outbound(self) -> None:
        self._out.clear()
        self._drained.set()

    async def settle(self) -> None:
        """Return once no caller frame is mid-send, so every credit for sent audio is in."""
        await self._in_flight.wait()

    def handle(self, message: dict[str, Any]) -> None:
        """Apply one message from the agent."""
        match message.get("event"):
            case "playAudio":
                payload = (message.get("media") or {}).get("payload")
                if payload:
                    self._receive(audioop.ulaw2lin(base64.b64decode(payload), 2))
            case "checkpoint":
                self._event(WireEventKind.CHECKPOINT)
                self._checkpoints.append((self._received, str(message.get("name"))))
            case "clearAudio":
                self._event(WireEventKind.CLEAR_AUDIO)
                self._in.clear()
                self._played = self._received
                self._checkpoints.clear()
                self._acks.append(json.dumps({"event": "clearedAudio", "streamId": self.stream_id}))
            case "stop":
                self._event(WireEventKind.STOP)
                self.hung_up.set()

    async def run(self, send: Send, push: Push, opening: str) -> None:
        """Open the stream, then every tick: acknowledgments, one caller frame out, one agent
        frame in.

        Ends by telling the agent the stream stopped, unless the agent went away first, which
        counts as its hangup. A send that stalls past the bound fails the call: the agent has
        stopped reading.
        """
        next_tick = time.monotonic()
        try:
            if not await self._deliver(send, opening):
                return
            while True:
                for ack in self._acks:
                    if not await self._deliver(send, ack):
                        return
                self._acks.clear()
                payload, sent, playout = self._outbound()
                self._in_flight.clear()
                try:
                    delivered = await self._deliver(send, payload)
                finally:
                    self._in_flight.set()
                if not delivered:
                    return
                if sent and playout is not None:
                    playout.sent += sent
                if not self._out:
                    self._drained.set()
                await push(self._inbound())
                while self._checkpoints and self._checkpoints[0][0] <= self._played:
                    _, name = self._checkpoints.popleft()
                    played = {"event": "playedStream", "streamId": self.stream_id, "name": name}
                    if not await self._deliver(send, json.dumps(played)):
                        return
                next_tick = await sleep_until(next_tick + FRAME_S)
        finally:
            self.closed.set()
            self._drained.set()
            if self.failed:
                self._event(WireEventKind.CALLER_ERROR)
                self.hung_up.set()
            elif self._socket_lost:
                self.hung_up.set()
            elif not self.hung_up.is_set():
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(send(stop_message()), STOP_SEND_S)
                self._event(WireEventKind.STOP)

    async def _deliver(self, send: Send, payload: str) -> bool:
        try:
            delivered = await asyncio.wait_for(send(payload), self._send_timeout_s)
        except TimeoutError:
            self.failed = STALLED
            delivered = False
        if not delivered:
            self._socket_lost = True
        return delivered

    def write_recording(self, path: Path) -> Path | None:
        """A stereo 8 kHz WAV of the stream as it went: the agent left, the caller right."""
        frames = min(len(self.agent_pcm), len(self.caller_pcm)) // 2
        if not frames:
            return None
        interleaved = bytearray(frames * 4)
        interleaved[0::4] = self.agent_pcm[0 : frames * 2 : 2]
        interleaved[1::4] = self.agent_pcm[1 : frames * 2 : 2]
        interleaved[2::4] = self.caller_pcm[0 : frames * 2 : 2]
        interleaved[3::4] = self.caller_pcm[1 : frames * 2 : 2]
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as recording:
            recording.setnchannels(2)
            recording.setsampwidth(2)
            recording.setframerate(SAMPLE_RATE)
            recording.writeframes(bytes(interleaved))
        return path

    def _event(self, kind: WireEventKind) -> None:
        self._observer.wire_event(WireEvent(kind=kind, at_ms=self._clock.ms()))

    def _receive(self, pcm: bytes) -> None:
        """Buffer agent audio; the first packet with speech after a quiet stretch is an event.

        Quiet is silence received or played, since an agent may stream silence between
        replies or send nothing at all.
        """
        if audioop.max(pcm, 2) > SPEECH_PEAK:
            if self._quiet >= GAP_BYTES:
                self._event(WireEventKind.AGENT_AUDIO)
            self._quiet = 0
        else:
            self._quiet += len(pcm)
        self._in.extend(pcm)
        self._received += len(pcm)

    def _outbound(self) -> tuple[str, int, Playout | None]:
        """The next frame to send, how many bytes of caller audio it carries, and whose."""
        sent = min(len(self._out), FRAME_BYTES)
        if sent:
            pcm = bytes(self._out[:sent]).ljust(FRAME_BYTES, b"\x00")
            del self._out[:sent]
        else:
            pcm = SILENCE
        speech = sent > 0
        now = self._clock.ms()
        if speech and not self._speaking:
            self._event(WireEventKind.CALLER_SPEECH_START)
        elif self._speaking and not speech:
            self._observer.wire_event(
                WireEvent(kind=WireEventKind.CALLER_SPEECH_END, at_ms=self._last_speech_ms)
            )
        if speech:
            self._last_speech_ms = now
        self._speaking = speech
        self.caller_pcm.extend(pcm)
        self._sequence += 1
        payload = json.dumps(
            {
                "event": "media",
                "sequenceNumber": self._sequence,
                "streamId": self.stream_id,
                "media": {
                    "track": "inbound",
                    "timestamp": str(self._sequence * 20),
                    "chunk": self._sequence,
                    "payload": base64.b64encode(audioop.lin2ulaw(pcm, 2)).decode(),
                },
            }
        )
        return payload, sent, self._playout

    def _inbound(self) -> bytes:
        if self._in:
            taken = min(len(self._in), FRAME_BYTES)
            pcm = bytes(self._in[:taken]).ljust(FRAME_BYTES, b"\x00")
            del self._in[:taken]
            self._played += taken
        else:
            pcm = SILENCE
            self._quiet += FRAME_BYTES
        self.agent_pcm.extend(pcm)
        return pcm
