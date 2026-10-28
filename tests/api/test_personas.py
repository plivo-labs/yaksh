import uuid

from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import (
    ENGLISH_VOICE,
    HINDI_VOICE,
    PERSONA,
    UNLISTED_VOICE,
    Db,
    FakeVoiceClient,
    create_agent_id,
    create_persona,
    create_scenario,
    listed_voice_id,
)


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
        "model": "eleven_flash_v2_5",
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


async def test_a_persona_voice_must_be_in_the_voices_list(
    client: AsyncClient, voice_client: FakeVoiceClient
) -> None:
    def voice(voice_id: str) -> dict[str, object]:
        return {**PERSONA, "voice": {"provider": "elevenlabs", "id": voice_id}}

    on_account_only = await client.post("/api/v1/personas", json=voice(UNLISTED_VOICE.id))
    dotted = await client.post("/api/v1/personas", json=voice(".."))

    assert on_account_only.status_code == 422
    assert "is not in the voices list" in on_account_only.json()["error"]["message"]
    assert dotted.status_code == 422
    assert (await client.get("/api/v1/personas")).json()["total"] == 0
    assert voice_client.lookups == []


async def test_a_deleted_voice_cannot_be_picked_again(client: AsyncClient) -> None:
    persona = await create_persona(client)
    hindi = {"provider": "elevenlabs", "id": HINDI_VOICE.id}
    await client.delete(f"/api/v1/voices/{await listed_voice_id(client, HINDI_VOICE.id)}")

    created = await client.post("/api/v1/personas", json={**PERSONA, "name": "B", "voice": hindi})
    moved = await client.patch(f"/api/v1/personas/{persona['id']}", json={"voice": hindi})

    assert created.status_code == moved.status_code == 422


async def test_a_persona_is_saved_while_the_voice_provider_is_down(
    client: AsyncClient, voice_client: FakeVoiceClient
) -> None:
    voice_client.down = True

    persona = await create_persona(client)

    assert persona["voice_gender"] == "male"


async def test_an_update_checks_the_voice_only_when_it_changes(client: AsyncClient) -> None:
    persona = await create_persona(client)
    url = f"/api/v1/personas/{persona['id']}"
    english = await listed_voice_id(client, ENGLISH_VOICE.id)
    await client.delete(f"/api/v1/voices/{english}")

    kept = await client.patch(url, json={"voice": {**persona["voice"], "speed": 0.9}})
    assert kept.status_code == 200 and kept.json()["current_version"] == 2

    unknown = await client.patch(url, json={"voice": {"provider": "elevenlabs", "id": "nope"}})
    assert unknown.status_code == 422

    moved = await client.patch(
        url, json={"voice": {"provider": "elevenlabs", "id": HINDI_VOICE.id}}
    )
    assert moved.json()["voice"] == {**persona["voice"], "id": HINDI_VOICE.id}
    assert moved.json()["current_version"] == 3


async def test_an_update_to_a_missing_persona_is_not_found_before_any_voice_check(
    client: AsyncClient,
) -> None:
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


async def test_the_voice_gender_comes_from_the_voices_list_and_follows_the_voice(
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


async def test_a_persona_lists_the_scenarios_that_use_it_and_cannot_be_deleted_while_any_do(
    client: AsyncClient,
) -> None:
    agent = await create_agent_id(client)
    persona = await create_persona(client)
    other = await create_persona(client, name="Calm caller")
    kept = await create_scenario(client, agent, persona_id=persona["id"])
    dropped = await create_scenario(
        client, agent, name="Cancel a cleaning", persona_id=persona["id"]
    )
    url = f"/api/v1/personas/{persona['id']}"

    listed_twice = (await client.get(f"{url}/scenarios")).json()
    used_twice = await client.delete(url)
    await client.delete(f"/api/v1/scenarios/{dropped['id']}")
    listed_once = (await client.get(f"{url}/scenarios")).json()
    used_once = await client.delete(url)
    await client.patch(f"/api/v1/scenarios/{kept['id']}", json={"persona_id": other["id"]})
    deleted = await client.delete(url)

    assert [(s["name"], s["agent_id"]) for s in listed_twice] == sorted(
        [("Cancel a cleaning", agent), (kept["name"], agent)]
    )
    assert [s["id"] for s in listed_once] == [kept["id"]]
    assert used_twice.status_code == 409
    assert used_twice.json()["error"]["message"] == (
        "2 scenarios use this persona; give them another persona first"
    )
    assert used_once.json()["error"]["message"] == (
        "1 scenario uses this persona; give it another persona first"
    )
    assert deleted.status_code == 204
    assert (await client.get(url)).status_code == 404
    assert (await client.get(f"{url}/scenarios")).status_code == 404


async def test_a_persona_keeps_its_surroundings_and_a_change_makes_a_version(
    client: AsyncClient,
) -> None:
    quiet = await create_persona(client)
    street = {"sounds": [{"sound": "street", "db": -5}]}
    noisy = await create_persona(client, name="Street caller", surroundings=street)
    url = f"/api/v1/personas/{noisy['id']}"
    speaker = {"kind": "talks_to_caller", "db": -6, "start_s": 5}

    busy = await client.patch(
        url, json={"surroundings": {"auto": {"db": -10, "seed": 2}, "speaker": speaker}}
    )
    both = await client.patch(url, json={"surroundings": {**street, "auto": {"db": -10}}})
    cleared = await client.patch(url, json={"surroundings": None})
    off = await client.patch(url, json={"surroundings": {}})
    off_again = await client.patch(url, json={"surroundings": {"sounds": []}})
    versions = (await client.get(f"{url}/versions")).json()["items"]

    assert quiet["surroundings"] == {"sounds": [], "auto": None, "speaker": None}
    assert noisy["surroundings"]["sounds"] == street["sounds"]
    assert busy.json()["current_version"] == 2
    assert busy.json()["surroundings"]["speaker"] == speaker
    assert both.status_code == 422 and "sounds or auto noise" in both.json()["error"]["message"]
    assert cleared.status_code == 422 and cleared.json()["error"]["message"] == (
        "surroundings: surroundings cannot be null"
    )
    assert off.json()["surroundings"] == {"sounds": [], "auto": None, "speaker": None}
    assert off.json()["current_version"] == off_again.json()["current_version"] == 3
    assert [v["config"]["surroundings"]["auto"] for v in versions] == [
        None,
        {"db": -10, "seed": 2},
        None,
    ]


async def test_spaces_around_the_behavior_are_not_a_change(client: AsyncClient) -> None:
    persona = await create_persona(client, prompt="  You are calm.\n")
    url = f"/api/v1/personas/{persona['id']}"

    same = await client.patch(url, json={"prompt": "You are calm."})

    assert persona["prompt"] == "You are calm."
    assert same.json()["current_version"] == 1


async def test_a_sample_line_is_kept_and_cleared_like_any_setting(client: AsyncClient) -> None:
    plain = await create_persona(client)
    persona = await create_persona(
        client, name="Caller with a line", sample_line="  Quick one, please. "
    )
    url = f"/api/v1/personas/{persona['id']}"

    changed = await client.patch(url, json={"sample_line": "Hi, I have no time."})
    cleared = await client.patch(url, json={"sample_line": None})
    too_long = await client.patch(url, json={"sample_line": "x" * 201})

    assert plain["sample_line"] is None
    assert persona["sample_line"] == "Quick one, please."
    assert changed.json()["sample_line"] == "Hi, I have no time."
    assert changed.json()["current_version"] == 2
    assert cleared.json()["sample_line"] is None
    assert cleared.json()["current_version"] == 3
    assert too_long.status_code == 422


async def test_a_persona_keeps_its_voicemail_and_screener_and_a_change_makes_a_version(
    client: AsyncClient,
) -> None:
    plain = await create_persona(client)
    phone = {
        "voicemail": "carrier",
        "greeting": "  Hi, it's Rachel. Leave a message. ",
        "screener": "truecaller",
        "after_screening": "reply",
    }
    persona = await create_persona(client, name="Screened caller", answering=phone)
    url = f"/api/v1/personas/{persona['id']}"

    changed = await client.patch(url, json={"answering": {"voicemail": "mailbox_full"}})
    cleared = await client.patch(url, json={"answering": None})
    long = await client.patch(url, json={"answering": {"greeting": "x" * 201}})
    fork = await client.post(f"{url}/fork")
    versions = (await client.get(f"{url}/versions")).json()["items"]

    assert plain["answering"] == {
        "voicemail": "iphone",
        "greeting": None,
        "screener": "iphone",
        "after_screening": "picks_up",
    }
    assert persona["answering"] == {**phone, "greeting": "Hi, it's Rachel. Leave a message."}
    assert changed.json()["answering"] == {**plain["answering"], "voicemail": "mailbox_full"}
    assert changed.json()["current_version"] == 2
    assert cleared.status_code == 422 and cleared.json()["error"]["message"] == (
        "answering: answering cannot be null"
    )
    assert long.status_code == 422
    assert fork.json()["answering"] == changed.json()["answering"]
    assert [v["config"]["answering"]["voicemail"] for v in versions] == ["mailbox_full", "carrier"]


async def test_a_persona_voice_keeps_its_model_and_changes_it_only_to_a_listed_one(
    client: AsyncClient, db: Db
) -> None:
    persona = await create_persona(client)
    url = f"/api/v1/personas/{persona['id']}"
    other_model = {**persona["voice"], "model": "eleven_multilingual_v2"}

    unlisted = await client.patch(url, json={"voice": other_model})
    await client.post(
        "/api/v1/voices",
        json={
            "provider": "elevenlabs",
            "provider_voice_id": ENGLISH_VOICE.id,
            "languages": ["en"],
            "model": "eleven_multilingual_v2",
        },
    )
    listed = await client.patch(url, json={"voice": other_model})
    no_model = {key: value for key, value in other_model.items() if key != "model"}
    kept = await client.patch(url, json={"voice": {**no_model, "speed": 1.1}})
    async with db() as session:
        stored_voice, stored_model = (
            await session.execute(
                text(
                    "SELECT config -> 'voice', voice_model FROM persona_versions"
                    " WHERE persona_id = :id ORDER BY version DESC LIMIT 1"
                ),
                {"id": persona["id"]},
            )
        ).one()

    assert unlisted.status_code == 422
    assert listed.json()["voice"]["model"] == "eleven_multilingual_v2"
    assert (kept.json()["voice"]["model"], kept.json()["voice"]["speed"]) == (
        "eleven_multilingual_v2",
        1.1,
    )
    assert "model" not in stored_voice and stored_model == "eleven_multilingual_v2"
