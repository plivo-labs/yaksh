import asyncio
import json
import sys

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from yaksh.db.base import Base
from yaksh.db.migrate import MIGRATIONS_DIR

UPGRADE = "import sys; from yaksh.db.migrate import upgrade_to_head; upgrade_to_head(sys.argv[1])"
PHONE = {"phone": {"timezone": "Asia/Kolkata"}}


def diff_against_models(connection: Connection) -> list[object]:
    context = MigrationContext.configure(connection)
    return compare_metadata(context, Base.metadata)


async def test_migrations_produce_the_schema_the_models_describe(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        diff = await connection.run_sync(diff_against_models)
    await engine.dispose()

    assert diff == []


async def test_processes_starting_together_migrate_a_fresh_database_once(
    database_url: str,
) -> None:
    admin = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text("CREATE DATABASE race"))
    await admin.dispose()
    race_url = database_url.rsplit("/", 1)[0] + "/race"

    processes = [
        await asyncio.create_subprocess_exec(sys.executable, "-c", UPGRADE, race_url)
        for _ in range(4)
    ]
    try:
        exit_codes = await asyncio.wait_for(
            asyncio.gather(*(process.wait() for process in processes)), timeout=60
        )
    finally:
        for process in processes:
            if process.returncode is None:
                process.kill()
                await process.wait()
    assert exit_codes == [0, 0, 0, 0]

    engine = create_async_engine(race_url)
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    await engine.dispose()
    assert {"agents", "agent_versions", "conversations"} <= set(tables)


async def models_by_provider(connection: AsyncConnection, query: str) -> dict[str, str | None]:
    return {provider: model for provider, model in (await connection.execute(text(query))).all()}


def migrate(database_url: str, revision: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["database_url"] = database_url
    command.upgrade(config, revision)


async def database_at(database_url: str, name: str, revision: str) -> str:
    admin = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f"CREATE DATABASE {name}"))
    await admin.dispose()
    url = database_url.rsplit("/", 1)[0] + f"/{name}"
    await asyncio.to_thread(migrate, url, revision)
    return url


async def test_each_voice_gets_the_model_its_provider_had_in_settings(database_url: str) -> None:
    url = await database_at(database_url, "voice_models", "0006")
    stored = {
        "elevenlabs": {"url": "wss://api.elevenlabs.io", "model": "eleven_turbo_v2_5"},
        "sarvam_tts": {"model": "bulbul:v3"},
    }
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE app_settings SET version = 3, values = CAST(:values AS jsonb)"),
            {"values": json.dumps(stored)},
        )
        for provider, voice_id in (("elevenlabs", "el1"), ("sarvam", "anushka"), ("azure", "sara")):
            await add_voice(connection, provider, voice_id)

    await asyncio.to_thread(migrate, url, "head")

    async with engine.connect() as connection:
        voices, personas, versions = await voice_models(connection)
        values, version = (
            await connection.execute(text("SELECT values, version FROM app_settings"))
        ).one()
    await engine.dispose()
    expected = {"elevenlabs": "eleven_flash_v2_5", "sarvam": "bulbul:v3", "azure": None}
    assert voices == personas == versions == expected
    assert (values, version) == (stored, 3)


async def test_nimble_voices_become_plivo_voices_of_koyal(database_url: str) -> None:
    """Nimble's own address, Auth ID and Auth token go: Koyal speaks with the Plivo account's
    Auth ID and Auth token, which were never checked at that address."""
    url = await database_at(database_url, "plivo_voices", "0010")
    secrets = ("nimble_auth_id", "nimble_auth_token", "plivo_auth_id", "plivo_auth_token")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE app_settings SET values = CAST(:values AS jsonb),"
                " secrets = CAST(:secrets AS jsonb)"
            ),
            {
                "values": json.dumps({"nimble": {"base_url": "https://gateway.example"}, **PHONE}),
                "secrets": json.dumps(dict.fromkeys(secrets, "sealed")),
            },
        )
        for provider, voice_id in (("nimble", "t4"), ("azure", "sara")):
            await add_voice(connection, provider, voice_id)

    await asyncio.to_thread(migrate, url, "head")

    async with engine.connect() as connection:
        voices, personas, versions = await voice_models(connection)
        values, stored = (
            await connection.execute(text("SELECT values, secrets FROM app_settings"))
        ).one()
    await engine.dispose()
    assert voices == personas == versions == {"plivo": "koyal-v1", "azure": None}
    assert values == PHONE
    assert set(stored) == {"plivo_auth_id", "plivo_auth_token"}


async def add_voice(connection: AsyncConnection, provider: str, voice_id: str) -> None:
    """A voice, a persona that speaks with it, and the persona's version, without a model."""
    await connection.execute(
        text(
            "INSERT INTO voices (id, provider, provider_voice_id, name, languages,"
            " listed_languages, builtin) VALUES (gen_random_uuid(), CAST(:provider AS"
            " voice_provider), :id, :id, '{en}', '{}', false)"
        ),
        {"provider": provider, "id": voice_id},
    )
    persona_id = await connection.scalar(
        text(
            "INSERT INTO personas (id, name, prompt, language, voice_provider, voice_id,"
            " voice_speed, surroundings, answering, current_version) VALUES"
            " (gen_random_uuid(), :id, 'p', 'en', CAST(:provider AS voice_provider), :id,"
            " 1.0, '{}', '{}', 1) RETURNING id"
        ),
        {"provider": provider, "id": voice_id},
    )
    voice = {"provider": provider, "id": voice_id, "speed": 1.0}
    await connection.execute(
        text(
            "INSERT INTO persona_versions (id, persona_id, version, config) VALUES"
            " (gen_random_uuid(), :persona, 1, CAST(:config AS jsonb))"
        ),
        {"persona": persona_id, "config": json.dumps({"voice": voice})},
    )


async def voice_models(connection: AsyncConnection) -> list[dict[str, str | None]]:
    """The model of each provider's voices, personas and persona versions."""
    return [
        await models_by_provider(connection, query)
        for query in (
            "SELECT provider::text, model FROM voices",
            "SELECT voice_provider::text, voice_model FROM personas",
            "SELECT config -> 'voice' ->> 'provider', voice_model FROM persona_versions",
        )
    ]


async def test_an_upgrade_from_before_the_speech_providers_in_one_step_maps_old_models(
    database_url: str,
) -> None:
    url = await database_at(database_url, "voice_models_old", "0005")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE app_settings SET values = CAST(:values AS jsonb)"),
            {"values": json.dumps({"elevenlabs": {"model": "eleven_v3"}})},
        )
        await connection.execute(
            text(
                "INSERT INTO voices (id, provider, provider_voice_id, name, languages,"
                " listed_languages, builtin) VALUES (gen_random_uuid(), 'elevenlabs', 'el1',"
                " 'el1', '{en}', '{}', false)"
            )
        )

    await asyncio.to_thread(migrate, url, "head")

    async with engine.connect() as connection:
        voices = await models_by_provider(connection, "SELECT provider::text, model FROM voices")
    await engine.dispose()
    assert voices == {"elevenlabs": "eleven_flash_v2_5"}
