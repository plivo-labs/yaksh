from typing import Any

from httpx import AsyncClient

from tests.conftest import (
    ENGLISH_VOICE,
    HINDI_VOICE,
    UNLISTED_VOICE,
    FakeVoiceClient,
    listed_voice_id,
)
from truman.domain.languages import Language
from truman.domain.voices import VoiceProvider
from truman.simulation.languages import LANGUAGES

NEW_VOICE = {"provider": "elevenlabs", "provider_voice_id": UNLISTED_VOICE.id}


async def voices(client: AsyncClient, **params: str | int) -> dict[str, Any]:
    return (await client.get("/api/v1/voices", params=params)).json()


async def test_languages_read_back_and_filter_the_list(client: AsyncClient) -> None:
    everyone = await voices(client)
    hinglish = await voices(client, language="hinglish")
    first, second = await voices(client, page_size=1), await voices(client, page_size=1, page=2)

    by_id = {voice["provider_voice_id"]: voice for voice in everyone["items"]}
    assert by_id[HINDI_VOICE.id]["languages"] == ["en", "hinglish"]
    assert by_id[ENGLISH_VOICE.id]["languages"] == ["en"]
    assert [voice["provider_voice_id"] for voice in hinglish["items"]] == [HINDI_VOICE.id]
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
    assert "must be added to the account first" in unknown.json()["error"]["message"]
    assert (await voices(client))["total"] == 2

    voice_client.down = True
    assert (await client.get(url, params=NEW_VOICE)).status_code == 503


async def test_adding_a_voice_takes_the_provider_details(client: AsyncClient) -> None:
    added = await client.post("/api/v1/voices", json={**NEW_VOICE, "languages": ["hinglish"]})
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
        ["hinglish"],
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

    edited = await client.patch(url, json={"name": "Chris (calm)", "languages": ["hinglish", "en"]})
    relabeled = await client.patch(url, json={"languages": ["hinglish"]})
    no_languages = await client.patch(url, json={"languages": []})
    cleared = await client.patch(url, json={"name": None})
    moved = await client.patch(url, json={"provider_voice_id": HINDI_VOICE.id})

    assert edited.json()["name"] == "Chris (calm)"
    assert edited.json()["languages"] == ["en", "hinglish"]
    assert (relabeled.json()["name"], relabeled.json()["languages"]) == (
        "Chris (calm)",
        ["hinglish"],
    )
    assert no_languages.status_code == cleared.status_code == moved.status_code == 422


async def test_a_preview_speaks_the_language_sample_with_the_call_settings(
    client: AsyncClient, voice_client: FakeVoiceClient
) -> None:
    voice = {"provider": "elevenlabs", "id": HINDI_VOICE.id, "speed": 1.15, "stability": 0.3}

    heard = await client.post(
        "/api/v1/voices/preview", json={"voice": voice, "language": "hinglish"}
    )
    unknown = await client.post(
        "/api/v1/voices/preview",
        json={"voice": {**voice, "id": "nope"}, "language": "hinglish"},
    )

    assert heard.status_code == 200 and heard.headers["content-type"] == "audio/wav"
    assert heard.content == b"RIFF fake wav"
    spoken_voice, language, text = voice_client.spoken[0]
    assert (spoken_voice.speed, spoken_voice.stability, language) == (1.15, 0.3, Language.HINGLISH)
    assert text == LANGUAGES[Language.HINGLISH].sample
    assert unknown.status_code == 422

    voice_client.down = True
    down = await client.post("/api/v1/voices/preview", json={"voice": voice, "language": "en"})
    assert down.status_code == 503
