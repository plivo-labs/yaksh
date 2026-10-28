import asyncio
import base64
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from pipecat.frames.frames import (
    Frame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.pipeline.worker import PipelineParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from websockets.asyncio.server import ServerConnection, serve

from yaksh.domain.errors import UnavailableError
from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings, Nimble
from yaksh.domain.voices import VoiceProvider, VoiceSettings
from yaksh.integrations.speech.audio import one_shot, speak_once
from yaksh.integrations.speech.nimble import NimbleTTSService, tts

CREDENTIAL = "MAID:token"
VOICE = VoiceSettings(provider=VoiceProvider.NIMBLE, id="t4", speed=0.9)
PARAMS = PipelineParams(audio_out_sample_rate=8000)


def audio_frame(context_id: str, audio: bytes) -> bytes:
    gateway_id = context_id.encode()
    return len(gateway_id).to_bytes(2, "little") + gateway_id + audio


@dataclass
class Gateway:
    """A stand-in for Nimble's live socket. `reply` answers each finished context."""

    reply: Callable[[ServerConnection, str], Awaitable[None]]
    messages: list[dict[str, Any]] = field(default_factory=list)
    authorization: list[str] = field(default_factory=list)
    url: str = ""

    async def handle(self, socket: ServerConnection) -> None:
        assert socket.request is not None
        self.authorization.append(socket.request.headers["Authorization"])
        async for raw in socket:
            message = json.loads(raw)
            self.messages.append(message)
            if message.get("finish"):
                await self.reply(socket, message["context_id"])

    def openings(self) -> list[dict[str, Any]]:
        return [message for message in self.messages if "voice_id" in message]

    def cancels(self) -> list[str]:
        return [m["context_id"] for m in self.messages if m.get("type") == "cancel"]


@pytest.fixture
async def gateway() -> AsyncIterator[Callable[..., Awaitable[Gateway]]]:
    servers = []

    async def start(reply: Callable[[ServerConnection, str], Awaitable[None]]) -> Gateway:
        fake = Gateway(reply)
        server = await serve(fake.handle, "127.0.0.1", 0)
        servers.append(server)
        fake.url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        return fake

    yield start
    for server in servers:
        server.close()
        await server.wait_closed()


def settings_for(fake: Gateway) -> AppSettings:
    return AppSettings(nimble=Nimble(base_url=fake.url))


class Frames(FrameProcessor):
    def __init__(self) -> None:
        super().__init__()
        self.seen: list[Frame] = []
        self.stopped = asyncio.Event()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        self.seen.append(frame)
        if isinstance(frame, TTSStoppedFrame):
            self.stopped.set()
        await self.push_frame(frame, direction)


async def frames_of(settings: AppSettings, text: str) -> list[Frame]:
    """Every frame a one-shot Nimble service sends for the text."""
    frames = Frames()
    service = tts(settings, VOICE, Language.HI, CREDENTIAL, one_shot=True)
    async with one_shot([service, frames], PARAMS, frames.stopped) as run:
        await run.worker.queue_frame(TTSSpeakFrame(text))
        async with asyncio.timeout(5):
            await frames.stopped.wait()
    assert run.errors == []
    return frames.seen


async def until(condition: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not condition():
            await asyncio.sleep(0.01)


async def test_a_reply_opens_a_context_streams_its_audio_and_times_each_word(
    gateway: Callable[..., Awaitable[Gateway]],
) -> None:
    async def reply(socket: ServerConnection, context_id: str) -> None:
        await socket.send(audio_frame("someone-else", bytes(999)))
        await socket.send(audio_frame(context_id, bytes(1600)))
        timestamps = {"chars": list("Haan ji"), "start_ms": [0, 0, 0, 0, 0, 480, 480]}
        await socket.send(
            json.dumps({"type": "timestamps", "context_id": context_id, **timestamps})
        )
        await socket.send(json.dumps({"type": "done", "context_id": context_id}))

    fake = await gateway(reply)

    seen = await frames_of(settings_for(fake), "Haan ji.")

    opening = fake.openings()[0]
    assert {key: opening[key] for key in ("voice_id", "language", "pace", "timestamps")} == {
        "voice_id": "t4",
        "language": "hi",
        "pace": 0.9,
        "timestamps": True,
    }
    assert opening["output_format"] == {
        "container": "raw",
        "encoding": "pcm_s16le",
        "sample_rate": 8000,
    }
    assert fake.authorization == ["Basic " + base64.b64encode(CREDENTIAL.encode()).decode()]
    audio = b"".join(frame.audio for frame in seen if isinstance(frame, TTSAudioRawFrame))
    assert len(audio) == 1600
    assert [frame.text for frame in seen if isinstance(frame, TTSTextFrame)] == ["Haan", "ji"]
    assert fake.cancels() == []


async def test_a_reply_without_audio_is_tried_once_more_after_an_error_that_may_pass(
    gateway: Callable[..., Awaitable[Gateway]],
) -> None:
    refused: list[str] = []

    async def reply(socket: ServerConnection, context_id: str) -> None:
        if not refused:
            refused.append(context_id)
            await socket.send(
                json.dumps({"type": "error", "context_id": context_id, "code": "at_capacity"})
            )
            return
        await socket.send(audio_frame(context_id, bytes(800)))
        await socket.send(json.dumps({"type": "done", "context_id": context_id}))

    fake = await gateway(reply)

    audio = await speak_once(
        tts(settings_for(fake), VOICE, Language.HI, CREDENTIAL, one_shot=True), "Haan ji."
    )

    first, retry = fake.openings()
    assert retry["context_id"] != first["context_id"]
    assert (retry["text"], retry["finish"]) == (first["text"], True)
    assert len(audio) == 800


async def test_an_error_after_the_first_audio_ends_the_speech(
    gateway: Callable[..., Awaitable[Gateway]],
) -> None:
    async def reply(socket: ServerConnection, context_id: str) -> None:
        await socket.send(audio_frame(context_id, bytes(800)))
        await socket.send(
            json.dumps({"type": "error", "context_id": context_id, "code": "backend_error"})
        )

    fake = await gateway(reply)

    with pytest.raises(UnavailableError, match="backend_error"):
        await speak_once(
            tts(settings_for(fake), VOICE, Language.HI, CREDENTIAL, one_shot=True), "Haan ji."
        )
    assert len(fake.openings()) == 1


async def test_a_socket_lost_during_a_call_reply_ends_the_call(
    gateway: Callable[..., Awaitable[Gateway]],
) -> None:
    async def reply(socket: ServerConnection, context_id: str) -> None:
        await socket.send(audio_frame(context_id, bytes(800)))
        await socket.close(code=1011)

    fake = await gateway(reply)
    service = tts(settings_for(fake), VOICE, Language.HI, CREDENTIAL, one_shot=False)
    failed = asyncio.Event()

    async with one_shot([service], PARAMS, failed) as run:
        await run.worker.queue_frame(TTSSpeakFrame("Haan ji."))
        async with asyncio.timeout(5):
            await failed.wait()

    assert run.errors == ["Nimble's socket closed during a reply"]
    assert not service.is_usable
    assert len(fake.authorization) == 1


async def test_a_reply_that_goes_quiet_is_stopped_and_a_later_lost_socket_opens_again(
    gateway: Callable[..., Awaitable[Gateway]],
) -> None:
    sockets: list[ServerConnection] = []

    async def reply(socket: ServerConnection, context_id: str) -> None:
        sockets.append(socket)
        await socket.send(audio_frame(context_id, bytes(800)))

    fake = await gateway(reply)
    service = NimbleTTSService(
        credential=CREDENTIAL,
        base_url=fake.url,
        voice="t4",
        language=Language.HI,
        pace=0.9,
        stop_frame_timeout_s=0.2,
        reconnect_on_error=True,
    )

    async with one_shot([service], PARAMS, asyncio.Event()) as run:
        await run.worker.queue_frame(TTSSpeakFrame("Haan ji."))
        await until(lambda: len(fake.cancels()) == 1)
        await sockets[0].close(code=1011)
        await until(lambda: len(fake.authorization) == 2)

    assert fake.cancels() == [fake.openings()[0]["context_id"]]
    assert run.errors == []
    assert service.is_usable
