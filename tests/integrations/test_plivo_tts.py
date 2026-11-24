"""Nimble through Pipecat's Plivo service: Yaksh's settings reach Plivo's Realtime API, and the
voice list comes from its Voices route. The service itself is tested in Pipecat."""

import asyncio
import base64
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from pipecat.frames.frames import (
    Frame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.pipeline.worker import PipelineParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pydantic import ValidationError

from yaksh.caller.plivo_server import PlivoServer
from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings, Nimble
from yaksh.domain.voices import VoiceGender, VoiceProvider, VoiceSettings
from yaksh.integrations.speech.audio import one_shot
from yaksh.integrations.speech.nimble import tts, voices

KEY = "MAID:token"
AUTHORIZATION = "Basic " + base64.b64encode(KEY.encode()).decode()
VOICE = VoiceSettings(provider=VoiceProvider.NIMBLE, id="t4", speed=0.9)
PARAMS = PipelineParams(audio_out_sample_rate=8000)
AUDIO = bytes(16000)
"""One second of 8 kHz PCM16, so that both words are played."""
LISTED = [
    {"voice_id": "v1", "name": "Karan", "gender": "male", "languages": ["en-IN", "en-US"]},
    {"voice_id": "v2", "name": "Meera", "gender": "female", "languages": ["hi"]},
]


@dataclass
class Plivo:
    """A stand-in for Plivo's TTS API. The Realtime API answers each finished context with its
    audio, its words' timestamps and `done`."""

    url: str = ""
    requests: list[tuple[str, str]] = field(default_factory=list)
    """The Auth ID in each request's path, and its Authorization header."""
    messages: list[dict[str, Any]] = field(default_factory=list)


@pytest.fixture
async def plivo() -> AsyncIterator[Plivo]:
    fake = Plivo()
    app = FastAPI()

    @app.websocket("/v1/Account/{auth_id}/TTS/Realtime")
    async def realtime(socket: WebSocket, auth_id: str) -> None:
        fake.requests.append((auth_id, socket.headers["authorization"]))
        await socket.accept()
        async for message in socket.iter_json():
            fake.messages.append(message)
            if message.get("finish"):
                context_id = message["context_id"]
                header = len(context_id).to_bytes(2, "little") + context_id.encode()
                await socket.send_bytes(header + AUDIO)
                await socket.send_json(
                    {
                        "type": "timestamps",
                        "context_id": context_id,
                        "chars": list("Haan ji"),
                        "start_ms": [0, 0, 0, 0, 0, 480, 480],
                        "duration_ms": [80] * 7,
                    }
                )
                await socket.send_json({"type": "done", "context_id": context_id})

    @app.get("/v1/Account/{auth_id}/TTS/Voices")
    async def listed(auth_id: str, request: Request) -> JSONResponse:
        fake.requests.append((auth_id, request.headers["authorization"]))
        return JSONResponse({"api_id": "a1", "meta": {"total_count": 2}, "objects": LISTED})

    server = PlivoServer(app, port=0)
    await server.start()
    fake.url = f"http://127.0.0.1:{server.port}"
    yield fake
    await server.stop(2.0)


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


@pytest.mark.parametrize(
    ("language", "also", "sent"),
    [(Language.HI, (), "hi"), (Language.EN, (), None), (Language.TA, (Language.HI,), None)],
)
async def test_a_reply_goes_to_the_realtime_api_with_the_voice_and_comes_back_timed(
    plivo: Plivo, language: Language, also: tuple[Language, ...], sent: str | None
) -> None:
    """English goes with no language: Plivo refuses English without its region, and reads it
    in the voice's own region. A caller that can switch sends none: Plivo finds the language of
    each sentence."""
    frames = Frames()
    settings = AppSettings(nimble=Nimble(base_url=plivo.url))
    service = tts(settings, VOICE, language, KEY, one_shot=True, also=also)
    async with one_shot([service, frames], PARAMS, frames.stopped) as run:
        await run.worker.queue_frame(TTSSpeakFrame("Haan ji."))
        async with asyncio.timeout(5):
            await frames.stopped.wait()

    assert run.errors == []
    assert plivo.requests == [("MAID", AUTHORIZATION)]
    opening = plivo.messages[0]
    assert (opening["voice_id"], opening["pace"], opening.get("language")) == ("t4", 0.9, sent)
    assert opening["output_format"]["sample_rate"] == 8000
    audio = b"".join(frame.audio for frame in frames.seen if isinstance(frame, TTSAudioRawFrame))
    words = [frame.text for frame in frames.seen if isinstance(frame, TTSTextFrame)]
    assert (audio, words) == (AUDIO, ["Haan", "ji"])


async def test_the_voice_list_names_english_by_its_language_whatever_its_region(
    plivo: Plivo,
) -> None:
    listed = await voices(AppSettings(nimble=Nimble(base_url=plivo.url)), KEY)

    assert plivo.requests == [("MAID", AUTHORIZATION)]
    assert [(v.id, v.name, v.gender, v.listed_languages) for v in listed] == [
        ("v1", "Karan", VoiceGender.MALE, (Language.EN,)),
        ("v2", "Meera", VoiceGender.FEMALE, (Language.HI,)),
    ]


def test_a_nimble_voice_takes_the_pace_the_api_takes() -> None:
    assert VoiceSettings(provider=VoiceProvider.NIMBLE, id="t4", speed=1.2).speed == 1.2
    with pytest.raises(ValidationError, match=r"Nimble takes a speed from 0\.7 to 1\.2"):
        VoiceSettings(provider=VoiceProvider.NIMBLE, id="t4", speed=1.25)
