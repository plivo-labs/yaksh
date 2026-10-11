from collections.abc import Callable

import pydantic
import pytest
from sqlalchemy import text

from yaksha.config import Settings
from yaksha.db.session import create_engine, notify_connection

REQUIRED = {
    "api_token": "token",
    "database_url": "postgresql+asyncpg://yaksha@localhost/yaksha",
    "encryption_key": "k" * 32,
    "s3_endpoint": "http://storage.test",
    "s3_access_key": "access",
    "s3_secret_key": "secret",
}


def test_an_empty_variable_counts_as_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YAKSHA_PUBLIC_URL", "")
    settings = Settings(_env_file=None, **REQUIRED)

    assert settings.public_url is None


def test_yaksha_refuses_to_start_with_an_empty_api_token() -> None:
    with pytest.raises(pydantic.ValidationError, match="api_token"):
        Settings(_env_file=None, **{**REQUIRED, "api_token": ""})


@pytest.mark.parametrize("key", [None, "k" * 31])
def test_yaksha_refuses_to_start_without_a_long_enough_encryption_key(key: str | None) -> None:
    values = {**REQUIRED, "encryption_key": key} if key else REQUIRED.copy()
    if key is None:
        del values["encryption_key"]

    with pytest.raises(pydantic.ValidationError, match="encryption_key"):
        Settings(_env_file=None, **values)


def test_port_comes_from_the_platform_port_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setenv("YAKSHA_PORT", "9200")
    assert Settings(_env_file=None, **REQUIRED).port is None

    monkeypatch.setenv("PORT", "9100")
    assert Settings(_env_file=None, **REQUIRED).port == 9100


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
async def test_yaksha_connects_with_the_url_a_host_gives(
    scheme: str, database_url: str, settings_factory: Callable[..., Settings]
) -> None:
    host_url = f"{scheme}://{database_url.split('://', 1)[1]}?sslmode=disable"
    url = str(settings_factory(database_url=host_url).database_url)

    engine = create_engine(url)
    async with engine.connect() as connection:
        assert await connection.scalar(text("SELECT 1")) == 1
    await engine.dispose()
    async with notify_connection(url) as connection:
        assert await connection.fetchval("SELECT 1") == 1


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("postgresql+psycopg://yaksha@localhost/yaksha", "URL scheme should be"),
        (
            "postgresql://yaksha@localhost/yaksha?sslmode=require&channel_binding=require",
            "asyncpg does not take: channel_binding",
        ),
        ("postgresql://yaksha@localhost/yaksha?sslmode=require&ssl=disable", "not both"),
    ],
    ids=["another driver", "an option asyncpg does not take", "sslmode and ssl"],
)
def test_yaksha_refuses_a_database_url_it_cannot_connect_with(url: str, reason: str) -> None:
    with pytest.raises(pydantic.ValidationError, match=reason):
        Settings(_env_file=None, **{**REQUIRED, "database_url": url})
