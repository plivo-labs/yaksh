import asyncio
import json
import sys

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from yaksh.db.base import Base
from yaksh.db.migrate import MIGRATIONS_DIR
from yaksh.db.models import Conversation
from yaksh.db.session import create_sessionmaker
from yaksh.domain.conversations import CallerSettings
from yaksh.domain.voices import VoiceProvider, VoiceSettings
from yaksh.evaluation.call import parsed

UPGRADE = "import sys; from yaksh.db.migrate import upgrade_to_head; upgrade_to_head(sys.argv[1])"
PHONE = {"phone": {"timezone": "Asia/Kolkata"}}
NIMBLE_CALLER = {
    "llm_model": "gpt-6-luna",
    "reasoning_effort": None,
    "voice": {"provider": "nimble", "id": "t4", "speed": 0.9},
}


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


async def test_nimble_voices_become_plivo_voices(database_url: str) -> None:
    """Nimble's own address, Auth ID and Auth token go: a Plivo voice speaks at Plivo's API with
    the Plivo account's Auth ID and Auth token. A call's stored voice reads as a Plivo voice."""
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
        await connection.execute(
            text(CONVERSATIONS), {"voice": "t4", "nimble": json.dumps(NIMBLE_CALLER)}
        )

    await asyncio.to_thread(migrate, url, "head")

    async with engine.connect() as connection:
        voices, personas, versions = await voice_models(connection)
        values, stored = (
            await connection.execute(text("SELECT values, secrets FROM app_settings"))
        ).one()
    async with create_sessionmaker(engine)() as session:
        calls = await session.scalars(select(Conversation).order_by(Conversation.repeat))
        callers = [parsed(CallerSettings, call.caller_settings) for call in calls]
    await engine.dispose()
    assert voices == personas == versions == {"plivo": "koyal-v1", "azure": None}
    assert values == PHONE
    assert set(stored) == {"plivo_auth_id", "plivo_auth_token"}
    voice = VoiceSettings(provider=VoiceProvider.PLIVO, id="t4", speed=0.9)
    assert callers == [
        CallerSettings(llm_model="gpt-6-luna", reasoning_effort=None, voice=voice),
        None,
    ]


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


CONVERSATIONS = """
WITH persona AS (
  SELECT persona_id, id FROM persona_versions WHERE config -> 'voice' ->> 'id' = :voice
), agent AS (
  INSERT INTO agents (name, source, direction, agent_number, agent_speaks_first, languages,
    brief, current_version)
  VALUES ('Agent', 'manual', 'inbound', '+15550100000', true, '{en-US}', '', 1) RETURNING id
), version AS (
  INSERT INTO agent_versions (agent_id, version, config) SELECT id, 1, '{}' FROM agent
  RETURNING id, agent_id
), run AS (
  INSERT INTO runs (agent_id, agent_version_id, transport, repeats, max_duration_s, max_turns,
    max_retries) SELECT agent_id, id, 'phone', 2, 60, 20, 0 FROM version
  RETURNING id, agent_id, agent_version_id
), scenario AS (
  INSERT INTO scenarios (agent_id, persona_id, name, config, current_version)
  SELECT agent.id, persona.persona_id, 'Scenario', '{}', 1 FROM agent, persona RETURNING id
), scenario_version AS (
  INSERT INTO scenario_versions (scenario_id, version, config) SELECT id, 1, '{}' FROM scenario
  RETURNING id, scenario_id
)
INSERT INTO conversations (agent_id, agent_version_id, run_id, repeat, attempt, persona_id,
  persona_version_id, scenario_id, scenario_version_id, data_set_id, data_set_name, channel,
  direction, transport, language, instructions, nudge, today, time_zone, max_duration_s,
  max_turns, surroundings, sound_plan, status, caller_settings)
SELECT run.agent_id, run.agent_version_id, run.id, caller.repeat, 1, persona.persona_id,
  persona.id, scenario_version.scenario_id, scenario_version.id, gen_random_uuid(), 'Default',
  'voice', 'inbound', 'phone', 'en', '', '', '2026-11-25', 'UTC', 60, 20, '{}', '{}',
  'completed', caller.settings
FROM run, persona, scenario_version,
  (VALUES (1, CAST(:nimble AS jsonb)), (2, NULL)) AS caller (repeat, settings)
"""
"""A run of two calls with the persona of a voice: one with a Nimble voice in its caller
settings, as 0.13 saved it, and one with none."""


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
