import asyncio
import sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from truman.db.base import Base

UPGRADE = "import sys; from truman.db.migrate import upgrade_to_head; upgrade_to_head(sys.argv[1])"


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
