import uuid
from typing import Any

from httpx import AsyncClient

from tests.conftest import ENGLISH_VOICE, HINDI_VOICE, PERSONA, FakeCatalog, create_persona
from truman.domain.personas import Language, VoiceProvider
from truman.simulation.languages import LANGUAGES


async def test_changing_config_creates_a_version_but_renaming_does_not(
    client: AsyncClient,
) -> None:
    persona = await create_persona(client)
    url = f"/api/v1/personas/{persona['id']}"
    assert persona["current_version"] == 1
    assert persona["voice"] == {
        "provider": "elevenlabs",
        "id": ENGLISH_VOICE.id,
        "speed": 1.0,
        "stability": 0.5,
    }

    renamed = await client.patch(url, json={"name": "Hurried caller"})
    assert renamed.json()["current_version"] == 1

    changed = await client.patch(url, json={"prompt": "You are late for a flight."})
    assert changed.json()["current_version"] == 2

    unchanged = await client.patch(url, json={"prompt": "You are late for a flight."})
    assert unchanged.json()["current_version"] == 2

    faster = await client.patch(
        url, json={"voice": {"provider": "elevenlabs", "id": ENGLISH_VOICE.id, "speed": 1.15}}
    )
    assert faster.json()["current_version"] == 3

    versions = (await client.get(f"{url}/versions")).json()
    assert [v["version"] for v in versions["items"]] == [3, 2, 1]
    assert versions["items"][1]["config"]["prompt"] == "You are late for a flight."
    assert versions["items"][0]["config"]["voice"]["speed"] == 1.15
    first = (await client.get(f"{url}/versions/1")).json()
    assert first["config"]["prompt"] == PERSONA["prompt"]


async def test_names_are_unique_among_live_personas_ignoring_case(client: AsyncClient) -> None:
    persona = await create_persona(client, name="Rushed")

    taken = await client.post("/api/v1/personas", json={**PERSONA, "name": "rushed"})
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "conflict"
    other = await create_persona(client, name="Chatty")
    renamed = await client.patch(f"/api/v1/personas/{other['id']}", json={"name": "RUSHED"})
    assert renamed.status_code == 409

    await client.delete(f"/api/v1/personas/{persona['id']}")
    await create_persona(client, name="RUSHED")


async def test_a_voice_must_exist_on_the_provider_account(
    client: AsyncClient, catalog: FakeCatalog
) -> None:
    def voice(voice_id: str) -> dict[str, object]:
        return {**PERSONA, "voice": {"provider": "elevenlabs", "id": voice_id}}

    unknown = await client.post("/api/v1/personas", json=voice("nope"))
    dotted = await client.post("/api/v1/personas", json=voice(".."))

    assert unknown.status_code == 422
    assert "voice nope was not found" in unknown.json()["error"]["message"]
    assert dotted.status_code == 422 and catalog.lookups == ["nope"]
    assert (await client.get("/api/v1/personas")).json()["total"] == 0


async def test_nothing_is_saved_while_the_voice_provider_is_down(
    client: AsyncClient, catalog: FakeCatalog
) -> None:
    catalog.down = True

    response = await client.post("/api/v1/personas", json=PERSONA)

    assert response.status_code == 503 and response.json()["error"]["code"] == "unavailable"
    assert (await client.get("/api/v1/personas")).json()["total"] == 0


async def test_a_voice_provider_without_a_key_is_unavailable(
    client: AsyncClient, catalogs: dict[VoiceProvider, FakeCatalog]
) -> None:
    catalogs.clear()

    created = await client.post("/api/v1/personas", json=PERSONA)
    listed = await client.get("/api/v1/voices", params={"provider": "elevenlabs"})

    for response in (created, listed):
        assert response.status_code == 503
        assert response.json()["error"]["message"] == "voice provider elevenlabs is not set up"


async def test_an_update_checks_the_voice_only_when_it_changes(
    client: AsyncClient, catalog: FakeCatalog
) -> None:
    persona = await create_persona(client)
    url = f"/api/v1/personas/{persona['id']}"
    catalog.lookups.clear()

    await client.patch(url, json={"prompt": "You are calm.", "language": "hinglish"})
    slower = {**persona["voice"], "speed": 0.9}
    assert (await client.patch(url, json={"voice": slower})).status_code == 200
    assert catalog.lookups == []

    unknown = await client.patch(url, json={"voice": {"provider": "elevenlabs", "id": "nope"}})
    assert unknown.status_code == 422
    assert catalog.lookups == ["nope"]

    moved = await client.patch(
        url, json={"voice": {"provider": "elevenlabs", "id": HINDI_VOICE.id}}
    )
    assert moved.json()["voice"] == {**persona["voice"], "id": HINDI_VOICE.id}
    assert moved.json()["current_version"] == 4


async def test_an_update_to_a_missing_persona_is_not_found_before_any_voice_check(
    client: AsyncClient, catalog: FakeCatalog
) -> None:
    catalog.down = True
    voice = {"provider": "elevenlabs", "id": "nope"}

    response = await client.patch(f"/api/v1/personas/{uuid.uuid4()}", json={"voice": voice})

    assert response.status_code == 404


async def test_a_deleted_persona_is_gone_but_its_versions_remain(client: AsyncClient) -> None:
    persona = await create_persona(client)
    url = f"/api/v1/personas/{persona['id']}"

    assert (await client.delete(url)).status_code == 204

    assert (await client.get(url)).status_code == 404
    assert (await client.patch(url, json={"name": "Back"})).status_code == 404
    assert (await client.get("/api/v1/personas")).json()["total"] == 0
    assert (await client.get(f"{url}/versions")).json()["total"] == 1


async def test_voices_are_listed_a_page_at_a_time_for_a_language(
    client: AsyncClient, catalog: FakeCatalog
) -> None:
    async def voices(**params: str | int) -> dict[str, Any]:
        response = await client.get("/api/v1/voices", params={"provider": "elevenlabs", **params})
        return response.json()

    first, second = await voices(page_size=1), await voices(page_size=1, page=2)
    await voices(language="hinglish")

    assert first["total"] == second["total"] == 2
    assert catalog.listed_for == [None, None, Language.HINGLISH]
    assert {v["id"] for v in first["items"] + second["items"]} == {ENGLISH_VOICE.id, HINDI_VOICE.id}


async def test_the_voice_gender_comes_from_the_provider_and_follows_the_voice(
    client: AsyncClient,
) -> None:
    persona = await create_persona(client)
    url = f"/api/v1/personas/{persona['id']}"
    assert persona["voice_gender"] == "male"

    faster = await client.patch(url, json={"voice": {**persona["voice"], "speed": 1.1}})
    assert faster.json()["voice_gender"] == "male"

    moved = await client.patch(
        url, json={"voice": {"provider": "elevenlabs", "id": HINDI_VOICE.id}}
    )
    assert moved.json()["voice_gender"] == "female"

    claimed = await client.post("/api/v1/personas", json={**PERSONA, "voice_gender": "female"})
    assert claimed.status_code == 422


async def test_a_preview_speaks_the_language_sample_with_the_call_settings(
    client: AsyncClient, catalog: FakeCatalog
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
    spoken_voice, language, text = catalog.spoken[0]
    assert (spoken_voice.speed, spoken_voice.stability, language) == (1.15, 0.3, Language.HINGLISH)
    assert text == LANGUAGES[Language.HINGLISH].sample
    assert unknown.status_code == 422

    catalog.down = True
    down = await client.post("/api/v1/voices/preview", json={"voice": voice, "language": "en"})
    assert down.status_code == 503
