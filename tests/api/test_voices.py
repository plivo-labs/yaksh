from typing import Any

from httpx import AsyncClient

from tests.conftest import (
    ENGLISH_VOICE,
    HINDI_VOICE,
    SPOKEN,
    UNLISTED_VOICE,
    FakeVoiceClient,
    listed_voice_id,
)
from yaksh.domain.languages import Language
from yaksh.domain.voices import ProviderVoice, VoiceProvider
from yaksh.simulation.languages import LANGUAGES

NEW_VOICE = {"provider": "elevenlabs", "provider_voice_id": UNLISTED_VOICE.id}


async def voices(client: AsyncClient, **params: str | int) -> dict[str, Any]:
    return (await client.get("/api/v1/voices", params=params)).json()


async def test_languages_read_back_and_filter_the_list(client: AsyncClient) -> None:
    everyone = await voices(client)
    hindi = await voices(client, language="hi")
    first, second = await voices(client, page_size=1), await voices(client, page_size=1, page=2)

    by_id = {voice["provider_voice_id"]: voice for voice in everyone["items"]}
    assert by_id[HINDI_VOICE.id]["languages"] == ["en", "hi"]
    assert by_id[ENGLISH_VOICE.id]["languages"] == ["en"]
    assert [voice["provider_voice_id"] for voice in hindi["items"]] == [HINDI_VOICE.id]
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]


async def test_a_lookup_shows_the_provider_details_and_saves_nothing(
    client: AsyncClient, voice_client: FakeVoiceClient
) -> None:
    url = "/api/v1/voices/lookup"
    found = await client.get(url, params=NEW_VOICE)
    unknown = await client.get(url, params={**NEW_VOICE, "provider_voice_id": "nope"})

    assert found.json() == {
        "id": UNLISTED_VOICE.id,
        "name": "Riya",
        "gender": "female",
        "accent": "indian",
        "listed_languages": [],
    }
    assert unknown.status_code == 422
    assert "add it to the account first" in unknown.json()["error"]["message"]
    assert (await voices(client))["total"] == 2

    voice_client.down = True
    assert (await client.get(url, params=NEW_VOICE)).status_code == 503


async def test_adding_a_voice_takes_the_provider_details(client: AsyncClient) -> None:
    added = await client.post("/api/v1/voices", json={**NEW_VOICE, "languages": ["hi"]})
    named = await client.post(
        "/api/v1/voices",
        json={
            "provider": "elevenlabs",
            "provider_voice_id": HINDI_VOICE.id,
            "languages": ["en"],
            "name": "My Ananya",
        },
    )

    assert added.status_code == 201
    body = added.json()
    assert (body["name"], body["gender"], body["accent"]) == ("Riya", "female", "indian")
    assert (body["languages"], body["listed_languages"], body["builtin"]) == (
        ["hi"],
        [],
        False,
    )
    assert named.status_code == 409 and named.json()["error"]["code"] == "conflict"


async def test_a_voice_can_be_added_again_after_it_is_deleted(client: AsyncClient) -> None:
    hindi = await listed_voice_id(client, HINDI_VOICE.id)
    assert (await client.delete(f"/api/v1/voices/{hindi}")).status_code == 204

    again = await client.post(
        "/api/v1/voices",
        json={
            "provider": "elevenlabs",
            "provider_voice_id": HINDI_VOICE.id,
            "languages": ["en"],
            "name": "My Ananya",
        },
    )

    assert again.status_code == 201 and again.json()["name"] == "My Ananya"
    assert (await client.patch(f"/api/v1/voices/{hindi}", json={"name": "x"})).status_code == 404
    listed = [voice["name"] for voice in (await voices(client))["items"]]
    assert sorted(listed) == ["Chris", "My Ananya"]


async def test_nothing_is_added_for_an_unknown_voice_or_a_provider_that_is_down(
    client: AsyncClient,
    voice_client: FakeVoiceClient,
    voice_clients: dict[VoiceProvider, FakeVoiceClient],
) -> None:
    unknown = await client.post(
        "/api/v1/voices", json={**NEW_VOICE, "provider_voice_id": "nope", "languages": ["en"]}
    )
    voice_client.down = True
    down = await client.post("/api/v1/voices", json={**NEW_VOICE, "languages": ["en"]})
    voice_clients.clear()
    unset = await client.post("/api/v1/voices", json={**NEW_VOICE, "languages": ["en"]})

    assert unknown.status_code == 422
    assert down.status_code == 503
    assert unset.status_code == 503
    assert unset.json()["error"]["message"] == "voice provider ElevenLabs is not set up"
    assert (await voices(client))["total"] == 2


async def test_an_edit_changes_name_and_languages_but_never_to_empty(client: AsyncClient) -> None:
    url = f"/api/v1/voices/{await listed_voice_id(client, ENGLISH_VOICE.id)}"

    edited = await client.patch(url, json={"name": "Chris (calm)", "languages": ["hi", "en"]})
    relabeled = await client.patch(url, json={"languages": ["hi"]})
    no_languages = await client.patch(url, json={"languages": []})
    cleared = await client.patch(url, json={"name": None})
    moved = await client.patch(url, json={"provider_voice_id": HINDI_VOICE.id})

    assert edited.json()["name"] == "Chris (calm)"
    assert edited.json()["languages"] == ["en", "hi"]
    assert (relabeled.json()["name"], relabeled.json()["languages"]) == (
        "Chris (calm)",
        ["hi"],
    )
    assert no_languages.status_code == cleared.status_code == moved.status_code == 422


async def test_a_preview_speaks_the_sample_line_or_the_language_sample_with_the_call_settings(
    client: AsyncClient, voice_client: FakeVoiceClient
) -> None:
    voice = {"provider": "elevenlabs", "id": HINDI_VOICE.id, "speed": 1.15, "stability": 0.3}

    heard = await client.post("/api/v1/voices/preview", json={"voice": voice, "language": "hi"})
    unknown = await client.post(
        "/api/v1/voices/preview",
        json={"voice": {**voice, "id": "nope"}, "language": "hi"},
    )

    assert heard.status_code == 200 and heard.headers["content-type"] == "audio/wav"
    assert heard.content == SPOKEN
    spoken_voice, language, text = voice_client.spoken[0]
    assert (spoken_voice.speed, spoken_voice.stability, language) == (1.15, 0.3, Language.HI)
    assert text == LANGUAGES[Language.HI].sample
    assert unknown.status_code == 422

    await client.post(
        "/api/v1/voices/preview",
        json={
            "voice": voice,
            "language": "hi",
            "sample_line": "Haan ji, booking ke baare mein.",
        },
    )
    assert voice_client.spoken[-1][2] == "Haan ji, booking ke baare mein."

    voice_client.down = True
    down = await client.post("/api/v1/voices/preview", json={"voice": voice, "language": "en"})
    assert down.status_code == 422 and "did not answer" in down.text


async def test_a_preview_in_a_model_outside_the_list_is_refused_before_the_provider_speaks(
    client: AsyncClient, voice_client: FakeVoiceClient
) -> None:
    voice = {"provider": "elevenlabs", "id": HINDI_VOICE.id, "model": "eleven_turbo_v2"}

    refused = await client.post("/api/v1/voices/preview", json={"voice": voice, "language": "hi"})

    assert refused.status_code == 422
    assert "ElevenLabs has no model eleven_turbo_v2" in refused.text
    assert voice_client.spoken == []


async def test_one_voice_is_listed_once_for_each_model(client: AsyncClient) -> None:
    flash = await client.post("/api/v1/voices", json={**NEW_VOICE, "languages": ["en"]})
    multilingual = await client.post(
        "/api/v1/voices",
        json={**NEW_VOICE, "languages": ["en"], "model": "eleven_multilingual_v2"},
    )
    again = await client.post(
        "/api/v1/voices",
        json={**NEW_VOICE, "languages": ["en"], "model": "eleven_multilingual_v2"},
    )

    assert (flash.json()["model"], multilingual.json()["model"]) == (
        "eleven_flash_v2_5",
        "eleven_multilingual_v2",
    )
    assert again.status_code == 409


async def test_a_voice_of_a_provider_without_lookup_is_saved_once_it_speaks_a_line(
    client: AsyncClient, voice_clients: dict[VoiceProvider, FakeVoiceClient]
) -> None:
    sarvam = FakeVoiceClient()
    sarvam.voices["shubh"] = ProviderVoice(id="shubh", name="unused")
    voice_clients[VoiceProvider.SARVAM] = sarvam
    voice = {
        "provider": "sarvam",
        "provider_voice_id": "shubh",
        "languages": ["hi", "en"],
        "name": "Shubh",
        "gender": "male",
        "accent": "indian",
    }

    unnamed = await client.post("/api/v1/voices", json={**voice, "name": None})
    unknown = await client.post("/api/v1/voices", json={**voice, "provider_voice_id": "nobody"})
    lookup = await client.get(
        "/api/v1/voices/lookup", params={"provider": "sarvam", "provider_voice_id": "shubh"}
    )
    saved = await client.post("/api/v1/voices", json=voice)

    assert unnamed.status_code == unknown.status_code == lookup.status_code == 422
    assert "nobody" in unknown.text
    assert saved.status_code == 201, saved.text
    assert (saved.json()["name"], saved.json()["gender"], saved.json()["accent"]) == (
        "Shubh",
        "male",
        "indian",
    )
    assert sarvam.spoken[-1][1:] == (Language.EN, LANGUAGES[Language.EN].sample)
    assert sarvam.lookups == []


async def test_a_voice_never_lists_a_language_its_provider_cannot_speak(
    client: AsyncClient, voice_clients: dict[VoiceProvider, FakeVoiceClient]
) -> None:
    sarvam = FakeVoiceClient()
    sarvam.voices["shubh"] = ProviderVoice(id="shubh", name="unused")
    voice_clients[VoiceProvider.SARVAM] = sarvam
    voice = {"provider": "sarvam", "provider_voice_id": "shubh", "name": "Shubh"}

    spanish = await client.post("/api/v1/voices", json={**voice, "languages": ["hi", "es"]})
    saved = await client.post("/api/v1/voices", json={**voice, "languages": ["hi"]})
    edited = await client.patch(f"/api/v1/voices/{saved.json()['id']}", json={"languages": ["es"]})

    assert spanish.status_code == edited.status_code == 422
    assert "Sarvam Bulbul v4 Flash does not speak Spanish" in spanish.text
    assert "Sarvam Bulbul v4 Flash does not speak Spanish" in edited.text


async def test_the_providers_list_their_models_with_speed_and_languages(
    client: AsyncClient,
) -> None:
    providers = {
        entry["provider"]: entry for entry in (await client.get("/api/v1/voices/providers")).json()
    }

    elevenlabs = {model["id"]: model for model in providers["elevenlabs"]["models"]}
    assert providers["elevenlabs"]["models"][0]["id"] == "eleven_flash_v2_5"
    assert (elevenlabs["eleven_v4"]["speed_min"], elevenlabs["eleven_v4"]["speed_max"]) == (1, 1)
    assert "mr" in elevenlabs["eleven_v4"]["languages"]
    assert "es" not in providers["sarvam"]["models"][0]["languages"]
    assert [model["id"] for model in providers["azure"]["models"]] == [None]


async def test_the_catalog_searches_the_provider_voices(
    client: AsyncClient, voice_clients: dict[VoiceProvider, FakeVoiceClient]
) -> None:
    voice_clients[VoiceProvider.CARTESIA] = FakeVoiceClient()
    url = "/api/v1/voices/catalog"

    found = await client.get(url, params={"provider": "elevenlabs", "search": HINDI_VOICE.name})
    missing = await client.get(url, params={"provider": "azure"})

    assert found.status_code == 200, found.text
    assert [voice["id"] for voice in found.json()["items"]] == [HINDI_VOICE.id]
    assert found.json()["next_cursor"] is None
    assert missing.status_code == 503


async def test_only_the_models_that_the_account_offers_are_listed_and_added(
    client: AsyncClient, voice_client: FakeVoiceClient
) -> None:
    voice_client.offered = frozenset({"eleven_flash_v2_5", "eleven_v3"})

    listed = await client.get("/api/v1/voices/models", params={"provider": "elevenlabs"})
    refused = await client.post(
        "/api/v1/voices", json={**NEW_VOICE, "languages": ["en"], "model": "eleven_v4"}
    )

    assert [model["id"] for model in listed.json()] == ["eleven_flash_v2_5", "eleven_v3"]
    assert refused.status_code == 422
    assert "ElevenLabs v4 is not available to this ElevenLabs account" in refused.text
    assert voice_client.spoken == []
