import pytest

from yaksha.config import Settings
from yaksha.worker.evaluator import judge_model


def test_an_empty_variable_counts_as_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YAKSHA_PUBLIC_URL", "")
    settings = Settings(
        _env_file=None,
        api_token="token",
        database_url="postgresql+asyncpg://yaksha@localhost/yaksha",
        plivo_auth_id="MAXXXX",
        plivo_auth_token="token",
    )

    assert settings.public_url is None
    assert not settings.phone_enabled


@pytest.mark.parametrize(("value", "judged"), [("off", False), ("OFF", False), ("", True)])
def test_off_turns_the_judges_off_and_an_empty_model_keeps_the_default(
    monkeypatch: pytest.MonkeyPatch, value: str, judged: bool
) -> None:
    monkeypatch.setenv("JUDGE_LLM_MODEL", value)
    settings = Settings(
        _env_file=None,
        api_token="token",
        database_url="postgresql+asyncpg://yaksha@localhost/yaksha",
        openai_api_key="key",
    )

    assert (judge_model(settings) is not None) is judged
