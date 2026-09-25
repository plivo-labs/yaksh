from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import PERSONA, create_persona
from truman.config import Settings
from truman.db.session import create_engine, create_sessionmaker
from truman.simulation.personas import builtin_personas, seed_builtin_personas
from truman.simulation.voices import builtin_voices, seed_builtin_voices


@pytest.fixture
async def session(client: AsyncClient, settings: Settings) -> AsyncIterator[AsyncSession]:
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        yield session
    await engine.dispose()


async def test_seeding_adds_each_builtin_voice_once_and_keeps_user_changes(
    client: AsyncClient, session: AsyncSession
) -> None:
    names = [voice.name for voice in builtin_voices()]
    assert await seed_builtin_voices(session) == names
    assert await seed_builtin_voices(session) == []

    listed = {v["name"]: v for v in (await client.get("/api/v1/voices")).json()["items"]}
    alice, bill = (
        listed["Alice - Clear, Engaging Educator"],
        listed["Bill - Wise, Mature, Balanced"],
    )
    assert alice["builtin"] and alice["languages"] == ["en", "hinglish"]
    await client.patch(f"/api/v1/voices/{alice['id']}", json={"name": "Alice"})
    await client.delete(f"/api/v1/voices/{bill['id']}")

    assert await seed_builtin_voices(session) == []
    names_now = {v["name"] for v in (await client.get("/api/v1/voices")).json()["items"]}
    assert "Alice" in names_now and bill["name"] not in names_now


async def test_builtin_personas_take_the_gender_of_their_builtin_voice(
    client: AsyncClient, session: AsyncSession
) -> None:
    genders = {voice.provider_voice_id: voice.gender for voice in builtin_voices()}
    await seed_builtin_voices(session)
    await seed_builtin_personas(session)

    for persona in (await client.get("/api/v1/personas")).json()["items"]:
        if persona["builtin_key"] is not None:
            assert persona["voice_gender"] == genders[persona["voice"]["id"]]


async def test_a_builtin_persona_must_use_a_builtin_voice(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("truman.simulation.personas.builtin_voices", list)

    with pytest.raises(RuntimeError, match="not a built-in voice"):
        await seed_builtin_personas(session)


async def test_seeding_adds_each_builtin_persona_once_and_keeps_user_changes(
    client: AsyncClient, session: AsyncSession
) -> None:
    await seed_builtin_voices(session)
    keys = [key for key, _ in builtin_personas()]
    assert await seed_builtin_personas(session) == keys
    assert await seed_builtin_personas(session) == []

    listed = (await client.get("/api/v1/personas")).json()["items"]
    by_key = {persona["builtin_key"]: persona for persona in listed}
    edited, deleted = by_key["rushed"], by_key["chatty"]
    await client.patch(f"/api/v1/personas/{edited['id']}", json={"prompt": "My own prompt."})
    await client.delete(f"/api/v1/personas/{deleted['id']}")

    assert await seed_builtin_personas(session) == []
    assert (await client.get(f"/api/v1/personas/{edited['id']}")).json()["prompt"] == (
        "My own prompt."
    )
    assert (await client.get(f"/api/v1/personas/{deleted['id']}")).status_code == 404
    assert (await client.get("/api/v1/personas")).json()["total"] == len(keys) - 1


async def test_a_user_persona_keeps_its_name_over_a_builtin(
    client: AsyncClient, session: AsyncSession
) -> None:
    mine = await create_persona(client, name="Rushed caller")

    await seed_builtin_voices(session)
    seeded = await seed_builtin_personas(session)

    assert "rushed" not in seeded and len(seeded) == len(builtin_personas()) - 1
    assert (await client.get(f"/api/v1/personas/{mine['id']}")).json()["prompt"] == (
        PERSONA["prompt"]
    )
