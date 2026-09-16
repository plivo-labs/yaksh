from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from truman.api import create_app
from truman.config import Settings
from truman.db.migrate import upgrade_to_head

TOKEN = "test-token"
OFFLINE_DATABASE_URL = "postgresql+asyncpg://truman:truman@localhost:5432/truman"


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "api_token": TOKEN,
        "database_url": OFFLINE_DATABASE_URL,
        "data_dir": tmp_path / "data",
        "frontend_dist": tmp_path / "missing",
    }
    return Settings.model_validate({**values, **overrides})


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        upgrade_to_head(url)
        yield url


@pytest.fixture
def settings_factory(tmp_path: Path) -> Callable[..., Settings]:
    return lambda **overrides: make_settings(tmp_path, **overrides)


@pytest.fixture
def offline_settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return make_settings(tmp_path, database_url=database_url)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        yield client
    await app.state.engine.dispose()
    engine = create_async_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE conversations, agent_versions, agents"))
    await engine.dispose()
