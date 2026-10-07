import pydantic
import pytest

from yaksha.config import Settings

REQUIRED = {
    "api_token": "token",
    "database_url": "postgresql+asyncpg://yaksha@localhost/yaksha",
    "encryption_key": "k" * 32,
}


def test_an_empty_variable_counts_as_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YAKSHA_PUBLIC_URL", "")
    settings = Settings(_env_file=None, **REQUIRED)

    assert settings.public_url is None


@pytest.mark.parametrize("key", [None, "k" * 31])
def test_yaksha_refuses_to_start_without_a_long_enough_encryption_key(key: str | None) -> None:
    values = {**REQUIRED, "encryption_key": key} if key else REQUIRED.copy()
    if key is None:
        del values["encryption_key"]

    with pytest.raises(pydantic.ValidationError, match="encryption_key"):
        Settings(_env_file=None, **values)
