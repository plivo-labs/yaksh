import io
import wave
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from yaksh.caller.plivo_server import PlivoServer
from yaksh.domain.errors import UnavailableError
from yaksh.domain.languages import Language
from yaksh.domain.voices import VoiceGender, VoiceProvider, VoiceSettings
from yaksh.integrations.elevenlabs import ElevenLabsClient

API_KEY = "el-key"
VOICE = {
    "voice_id": "v1",
    "name": "Chris",
    "category": "premade",
    "labels": {"gender": "male", "accent": "american"},
    "verified_languages": [
        {"language": "en", "model_id": "eleven_turbo_v2_5"},
        {"language": "hi", "model_id": "eleven_multilingual_v2"},
        {"language": "fr", "model_id": "eleven_multilingual_v2"},
        {"language": "ta", "model_id": "eleven_multilingual_v2"},
    ],
}


@pytest.fixture
async def elevenlabs() -> AsyncIterator[tuple[str, list[dict[str, Any]]]]:
    """A stand-in for api.elevenlabs.io that records requests."""
    seen: list[dict[str, Any]] = []
    app = FastAPI()

    @app.post("/v1/text-to-speech/{voice_id}")
    async def speak(voice_id: str, request: Request) -> Response:
        seen.append(
            {"speak": voice_id, "query": dict(request.query_params), **await request.json()}
        )
        if voice_id == "gone":
            return Response('{"detail": {"code": "voice_not_found"}}', status_code=400)
        if voice_id == "busy":
            return Response('{"detail": {"code": "too_many_concurrent_requests"}}', status_code=429)
        return Response(b"\x01\x00" * 800, media_type="audio/basic")

    @app.get("/v1/voices/{voice_id}")
    async def voice(voice_id: str) -> Response:
        seen.append({"lookup": voice_id})
        if voice_id == "v1":
            return JSONResponse(VOICE)
        if voice_id == "unlabeled":
            return JSONResponse({"voice_id": "unlabeled", "name": "Plain", "labels": None})
        if voice_id == "locked":
            return Response('{"detail": {"code": "invalid_api_key"}}', status_code=401)
        if voice_id == "empty":
            return Response(status_code=200)
        if voice_id == "proxy":
            return Response("<html>bad gateway</html>", status_code=502)
        if voice_id == "loop":
            return RedirectResponse("/v1/voices/loop")
        return Response('{"detail": {"code": "voice_not_found"}}', status_code=400)

    server = PlivoServer(app, port=0)
    await server.start()
    yield f"http://127.0.0.1:{server.port}", seen
    await server.stop(2.0)


async def test_a_lookup_tells_a_missing_voice_from_a_refused_request(
    elevenlabs: tuple[str, list[dict[str, Any]]],
) -> None:
    base_url, _ = elevenlabs
    client = ElevenLabsClient(API_KEY, base_url=base_url)

    found = await client.get_voice("v1")
    plain = await client.get_voice("unlabeled")
    assert found is not None and found.name == "Chris"
    assert (found.gender, found.accent) == (VoiceGender.MALE, "american")
    assert found.listed_languages == (Language.EN, Language.HI, Language.TA)
    assert plain is not None and (plain.gender, plain.listed_languages) == (None, ())

    assert await client.get_voice("gone") is None

    with pytest.raises(UnavailableError, match="401"):
        await client.get_voice("locked")


async def test_an_unreachable_provider_is_reported_as_unavailable() -> None:
    client = ElevenLabsClient(API_KEY, base_url="http://127.0.0.1:9")

    with pytest.raises(UnavailableError):
        await client.get_voice("v1")
    with pytest.raises(UnavailableError):
        await client.speak(
            VoiceSettings(provider=VoiceProvider.ELEVENLABS, id="v1"), Language.EN, "Hi"
        )


async def test_a_broken_answer_is_unavailable_with_its_status_and_never_the_key(
    elevenlabs: tuple[str, list[dict[str, Any]]],
) -> None:
    base_url, _ = elevenlabs
    client = ElevenLabsClient(API_KEY, base_url=base_url)

    with pytest.raises(UnavailableError, match="not JSON"):
        await client.get_voice("empty")
    with pytest.raises(UnavailableError, match="502"):
        await client.get_voice("proxy")
    with pytest.raises(UnavailableError, match="TooManyRedirects") as looped:
        await client.get_voice("loop")
    assert API_KEY not in str(looped.value)


async def test_speech_uses_the_call_model_voice_settings_and_a_pin_the_model_takes(
    elevenlabs: tuple[str, list[dict[str, Any]]],
) -> None:
    base_url, seen = elevenlabs
    client = ElevenLabsClient(API_KEY, base_url=base_url)
    voice = VoiceSettings(provider=VoiceProvider.ELEVENLABS, id="v1", speed=0.8, stability=0.3)

    hindi = await client.speak(voice, Language.HI, "नमस्ते")
    await client.speak(voice, Language.EN, "Hello")
    await client.speak(voice, Language.MR, "नमस्कार")
    gone = await client.speak(voice.model_copy(update={"id": "gone"}), Language.EN, "Hi")

    assert gone is None and hindi is not None
    with pytest.raises(UnavailableError, match="429"):
        await client.speak(voice.model_copy(update={"id": "busy"}), Language.EN, "Hi")
    with wave.open(io.BytesIO(hindi)) as audio:
        assert (audio.getframerate(), audio.getsampwidth(), audio.getnframes()) == (8000, 2, 800)
    assert seen[0] == {
        "speak": "v1",
        "query": {"output_format": "pcm_8000"},
        "text": "नमस्ते",
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {"speed": 0.8, "stability": 0.3},
        "language_code": "hi",
    }
    assert seen[1]["language_code"] == "en"
    assert "language_code" not in seen[2]
