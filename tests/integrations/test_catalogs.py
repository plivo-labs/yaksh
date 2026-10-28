from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from yaksh.caller.plivo_server import PlivoServer
from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings, Azure, Cartesia
from yaksh.domain.voices import CatalogQuery, VoiceGender
from yaksh.integrations.speech import azure, cartesia, sarvam

AZURE_VOICES = [
    {
        "ShortName": "hi-IN-SwaraNeural",
        "LocalName": "Swara",
        "Gender": "Female",
        "Locale": "hi-IN",
        "LocaleName": "Hindi (India)",
    },
    {"ShortName": "fr-FR-DeniseNeural", "Gender": "Female", "Locale": "fr-FR"},
    {
        "ShortName": "en-US-Ava:DragonHDLatestNeural",
        "DisplayName": "Ava",
        "Gender": "Female",
        "Locale": "en-US",
        "SecondaryLocaleList": ["es-ES"],
    },
]


@pytest.fixture
async def provider_api() -> AsyncIterator[tuple[str, list[dict[str, Any]]]]:
    """A stand-in for Cartesia's and Azure's voice lists that records requests."""
    seen: list[dict[str, Any]] = []
    app = FastAPI()

    @app.get("/voices")
    async def cartesia_voices(request: Request) -> Response:
        headers = {
            name: request.headers.get(name) for name in ("authorization", "cartesia-version")
        }
        seen.append({"cartesia": headers, "params": dict(request.query_params)})
        voice = {
            "id": "c1",
            "name": "Priya",
            "gender": "feminine",
            "accents": [
                {"accent": "indian", "locale": "hi-IN", "is_native": True},
                {"accent": "american", "locale": "en-US", "is_native": False},
            ],
        }
        return JSONResponse({"data": [voice], "has_more": True})

    @app.get("/cognitiveservices/voices/list")
    async def azure_voices(request: Request) -> Response:
        seen.append({"azure": request.headers.get("ocp-apim-subscription-key")})
        return JSONResponse(AZURE_VOICES)

    server = PlivoServer(app, port=0)
    await server.start()
    yield f"http://127.0.0.1:{server.port}", seen
    await server.stop(2.0)


async def test_cartesia_lists_voices_at_the_checked_host_with_its_api_version(
    provider_api: tuple[str, list[dict[str, Any]]],
) -> None:
    base_url, seen = provider_api
    settings = AppSettings(cartesia=Cartesia(url=base_url.replace("http", "ws") + "/tts/websocket"))
    query = CatalogQuery(search="priya", gender=VoiceGender.FEMALE, language=Language.HI)

    page = await cartesia.catalog(settings, "sk_car_key", query)

    assert [(v.id, v.gender, v.accent, v.listed_languages) for v in page.items] == [
        ("c1", VoiceGender.FEMALE, "indian", (Language.EN, Language.HI))
    ]
    assert page.next_cursor == "c1"
    assert seen == [
        {
            "cartesia": {"authorization": "Bearer sk_car_key", "cartesia-version": "2026-08-14"},
            "params": {"limit": "30", "q": "priya", "gender": "feminine", "language": "hi"},
        }
    ]


async def test_azure_lists_the_region_voices_that_speak_a_yaksh_language_once_an_hour(
    provider_api: tuple[str, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    base_url, seen = provider_api
    monkeypatch.setattr(azure, "VOICE_LIST_URL", f"{base_url}/cognitiveservices/voices/list")
    monkeypatch.setattr(azure, "VOICE_LISTS", {})
    settings = AppSettings(azure=Azure(region="centralindia"))

    every = await azure.catalog(settings, "key", CatalogQuery())
    spanish = await azure.catalog(settings, "key", CatalogQuery(language=Language.ES))

    assert [voice.id for voice in every.items] == [
        "hi-IN-SwaraNeural",
        "en-US-Ava:DragonHDLatestNeural",
    ]
    assert [voice.id for voice in spanish.items] == ["en-US-Ava:DragonHDLatestNeural"]
    assert seen == [{"azure": "key"}]


async def test_sarvam_lists_the_speakers_of_the_model_that_speak_the_language() -> None:
    marathi = CatalogQuery(language=Language.MR)

    flash = await sarvam.catalog(AppSettings(), "key", marathi)
    v3 = await sarvam.catalog(
        AppSettings(), "key", marathi.model_copy(update={"model": "bulbul:v3"})
    )

    assert flash.items and all(voice.listed_languages == (Language.MR,) for voice in flash.items)
    assert all("_mr_" in voice.id for voice in flash.items)
    assert len(v3.items) == 30 and v3.next_cursor == "30"
    assert not {voice.id for voice in flash.items} & {voice.id for voice in v3.items}
    assert not any("_pa_" in voice.id for voice in sarvam.speaker_lists()["bulbul:v4-flash"])
