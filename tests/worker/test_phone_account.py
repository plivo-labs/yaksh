import pytest
from pydantic import SecretStr

from tests.conftest import APP_SETTINGS
from yaksha.config import Settings
from yaksha.db.session import create_engine, create_sessionmaker
from yaksha.domain.settings import AppSettings
from yaksha.integrations.plivo import PlivoApi
from yaksha.worker import phone_account
from yaksha.worker.phone_account import PhoneAccount


async def test_a_refresh_cut_short_runs_again_and_a_new_account_is_read_again(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[str] = []

    async def sync_pool(_sessionmaker: object, api: PlivoApi, _allowlist: list[str]) -> None:
        synced.append(api.auth_id)
        if len(synced) == 1:
            raise ConnectionError("the database went away")

    async def check_receiving(api: PlivoApi, _settings: Settings) -> tuple[str, None]:
        return f"app-of-{api.auth_id}", None

    monkeypatch.setattr(phone_account, "sync_pool", sync_pool)
    monkeypatch.setattr(phone_account, "check_receiving", check_receiving)
    engine = create_engine(offline_settings.database_url.encoded_string())
    account = PhoneAccount(create_sessionmaker(engine), offline_settings)
    moved = APP_SETTINGS.model_copy(
        update={
            "secrets": APP_SETTINGS.secrets.model_copy(update={"plivo_auth_id": SecretStr("MANEW")})
        }
    )

    with pytest.raises(ConnectionError):
        await account.refresh(APP_SETTINGS)
    await account.refresh(APP_SETTINGS)
    await account.refresh(APP_SETTINGS)
    read = account.receiving_app_id
    await account.refresh(moved)
    await account.refresh(AppSettings())

    assert synced == ["MAXXXX", "MAXXXX", "MANEW"]
    assert read == "app-of-MAXXXX"
    assert account.receiving_app_id is None
