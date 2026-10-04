import pytest

from truman.config import Settings


def test_an_empty_variable_counts_as_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUMAN_PUBLIC_URL", "")
    settings = Settings(
        _env_file=None,
        api_token="token",
        database_url="postgresql+asyncpg://truman@localhost/truman",
        plivo_auth_id="MAXXXX",
        plivo_auth_token="token",
    )

    assert settings.public_url is None
    assert not settings.phone_enabled
