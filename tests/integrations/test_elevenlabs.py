from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from yaksh.caller.plivo_server import PlivoServer
from yaksh.domain.errors import UnavailableError
from yaksh.domain.languages import Language
from yaksh.domain.voices import CatalogQuery, CatalogSource, VoiceGender
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

    @app.get("/v2/voices")
    async def account_voices(request: Request) -> Response:
        seen.append({"account": dict(request.query_params)})
        first = "next_page_token" not in request.query_params
        return JSONResponse(
            {"voices": [VOICE] if first else [], "has_more": first, "next_page_token": "token-2"}
        )

    @app.get("/v1/shared-voices")
    async def library_voices(request: Request) -> Response:
        seen.append({"library": dict(request.query_params)})
        shared = {
            "voice_id": "lib1",
            "name": "Kavya",
            "gender": "female",
            "accent": "indian",
            "language": "mr",
            "verified_languages": [{"language": "hi", "model_id": "eleven_v4"}],
        }
        return JSONResponse({"voices": [shared], "has_more": True})

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


async def test_the_voice_list_pages_the_account_and_the_public_library(
    elevenlabs: tuple[str, list[dict[str, Any]]],
) -> None:
    base_url, seen = elevenlabs
    client = ElevenLabsClient(API_KEY, base_url=base_url)

    account = await client.voices(CatalogQuery(search="chris", language=Language.HI))
    following = await client.voices(CatalogQuery(cursor=account.next_cursor))
    library = await client.voices(
        CatalogQuery(source=CatalogSource.LIBRARY, gender=VoiceGender.FEMALE)
    )

    assert ([voice.id for voice in account.items], account.next_cursor) == (["v1"], "token-2")
    assert following.next_cursor is None
    assert [(voice.id, voice.gender, voice.listed_languages) for voice in library.items] == [
        ("lib1", VoiceGender.FEMALE, (Language.HI, Language.MR))
    ]
    assert library.next_cursor == "1"
    assert seen[-3:] == [
        {"account": {"page_size": "30", "search": "chris", "language": "hi"}},
        {"account": {"page_size": "30", "next_page_token": "token-2"}},
        {"library": {"page_size": "30", "gender": "female", "page": "0"}},
    ]
