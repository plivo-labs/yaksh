from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from truman.caller.plivo_server import PlivoServer
from truman.domain.errors import UnavailableError
from truman.domain.personas import Language
from truman.integrations.elevenlabs import LIST_TTL_S, ElevenLabsCatalog

API_KEY = "el-key"
VOICE = {
    "voice_id": "v1",
    "name": "Chris",
    "category": "premade",
    "labels": {"gender": "male", "accent": "american"},
    "preview_url": "https://example.com/v1.mp3",
    "verified_languages": [
        {"language": "en", "model_id": "eleven_turbo_v2_5"},
        {"language": "hi", "model_id": "eleven_multilingual_v2"},
    ],
}


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def elevenlabs() -> AsyncIterator[tuple[str, list[dict[str, Any]]]]:
    """A stand-in for api.elevenlabs.io that pages its voice list and records requests."""
    seen: list[dict[str, Any]] = []
    app = FastAPI()

    @app.get("/v2/voices")
    async def voices(request: Request) -> dict[str, Any]:
        token = request.query_params.get("next_page_token")
        seen.append({"key": request.headers["xi-api-key"], "token": token})
        if request.headers["xi-api-key"] == "tokenless":
            return {"voices": [VOICE], "has_more": True}
        if token is None:
            return {"voices": [VOICE], "has_more": True, "next_page_token": "p2"}
        english_only = {**VOICE, "voice_id": "v2", "labels": None}
        english_only["verified_languages"] = [{"language": "en", "model_id": "eleven_turbo_v2_5"}]
        return {"voices": [english_only], "has_more": False}

    @app.get("/v1/voices/{voice_id}")
    async def voice(voice_id: str) -> Response:
        seen.append({"lookup": voice_id})
        if voice_id == "v1":
            return JSONResponse(VOICE)
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


async def test_the_list_follows_every_page_and_is_cached_for_five_minutes(
    elevenlabs: tuple[str, list[dict[str, Any]]],
) -> None:
    base_url, seen = elevenlabs
    clock = Clock()
    catalog = ElevenLabsCatalog(API_KEY, base_url=base_url, clock=clock)

    voices = await catalog.list_voices()

    assert [voice.id for voice in voices] == ["v1", "v2"]
    assert voices[0].gender == "male" and voices[0].languages == {"en", "hi"}
    assert seen == [{"key": API_KEY, "token": None}, {"key": API_KEY, "token": "p2"}]

    clock.now = LIST_TTL_S - 1
    await catalog.list_voices()
    assert len(seen) == 2

    clock.now = LIST_TTL_S
    await catalog.list_voices()
    assert len(seen) == 4


async def test_a_lookup_tells_a_missing_voice_from_a_refused_request(
    elevenlabs: tuple[str, list[dict[str, Any]]],
) -> None:
    base_url, _ = elevenlabs
    catalog = ElevenLabsCatalog(API_KEY, base_url=base_url)

    found = await catalog.get_voice("v1")
    assert found is not None and found.name == "Chris"

    assert await catalog.get_voice("gone") is None

    with pytest.raises(UnavailableError, match="401"):
        await catalog.get_voice("locked")


async def test_an_unreachable_provider_is_reported_as_unavailable() -> None:
    catalog = ElevenLabsCatalog(API_KEY, base_url="http://127.0.0.1:9")

    with pytest.raises(UnavailableError):
        await catalog.get_voice("v1")
    with pytest.raises(UnavailableError):
        await catalog.list_voices()


async def test_a_broken_answer_is_unavailable_with_its_status_and_never_the_key(
    elevenlabs: tuple[str, list[dict[str, Any]]],
) -> None:
    base_url, _ = elevenlabs
    catalog = ElevenLabsCatalog(API_KEY, base_url=base_url)

    with pytest.raises(UnavailableError, match="not JSON"):
        await catalog.get_voice("empty")
    with pytest.raises(UnavailableError, match="502"):
        await catalog.get_voice("proxy")
    with pytest.raises(UnavailableError, match="TooManyRedirects") as looped:
        await catalog.get_voice("loop")
    assert API_KEY not in str(looped.value)
    with pytest.raises(UnavailableError, match="no page token"):
        await ElevenLabsCatalog("tokenless", base_url=base_url).list_voices()


async def test_a_language_filters_the_cached_list_to_voices_verified_for_it(
    elevenlabs: tuple[str, list[dict[str, Any]]],
) -> None:
    base_url, seen = elevenlabs
    catalog = ElevenLabsCatalog(API_KEY, base_url=base_url)

    everyone = await catalog.list_voices()
    for language in (Language.HI, Language.HINGLISH, Language.EN_HI):
        assert [voice.id for voice in await catalog.list_voices(language)] == ["v1"]
    assert [voice.id for voice in await catalog.list_voices(Language.EN)] == ["v1", "v2"]

    assert len(everyone) == 2 and len(seen) == 2
