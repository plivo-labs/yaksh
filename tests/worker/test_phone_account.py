import pytest
from pydantic import SecretStr

from tests.conftest import APP_SETTINGS, POOL_APP_ID, POOL_APPLICATION, Db, FakePlivoAccount
from yaksh.config import Settings
from yaksh.domain.numbers import AccountNumber
from yaksh.domain.settings import AppSettings
from yaksh.simulation import phone_account as account_checks
from yaksh.worker.phone_account import PhoneAccount


class CountingAccount(FakePlivoAccount):
    """A fake Plivo account that counts its listings and fails the first one as when the
    database connection drops midway."""

    def __init__(self, fail_first: bool) -> None:
        super().__init__()
        self.fail_first = fail_first
        self.listings = 0

    async def list_numbers(self) -> list[AccountNumber]:
        self.listings += 1
        if self.fail_first and self.listings == 1:
            raise ConnectionError("the database went away")
        return await super().list_numbers()


async def test_a_refresh_cut_short_runs_again_and_new_credentials_are_read_again(
    settings: Settings, db: Db
) -> None:
    accounts: dict[str, CountingAccount] = {}

    def api_for(auth_id: str, _token: str) -> CountingAccount:
        return accounts.setdefault(auth_id, CountingAccount(fail_first=not accounts))

    account = PhoneAccount(db, settings, api_for)
    moved = APP_SETTINGS.model_copy(
        update={
            "secrets": APP_SETTINGS.secrets.model_copy(update={"plivo_auth_id": SecretStr("MANEW")})
        }
    )

    with pytest.raises(ConnectionError):
        await account.refresh(APP_SETTINGS)
    await account.refresh(APP_SETTINGS)
    await account.refresh(APP_SETTINGS)
    read = (account.pool_app_id, account.receiving_app_id)
    await account.refresh(moved)
    await account.refresh(AppSettings())

    assert accounts["MAXXXX"].listings == 2
    assert "MANEW" in accounts
    assert read == (POOL_APP_ID, POOL_APP_ID)
    assert (account.pool_app_id, account.receiving_app_id) == (None, None)


async def test_outbound_waits_until_the_receiving_application_sends_calls_here(
    settings: Settings, db: Db
) -> None:
    elsewhere = POOL_APPLICATION.model_copy(update={"answer_url": "https://old.example/incoming"})
    plivo = FakePlivoAccount(applications=[elsewhere])
    account = PhoneAccount(db, settings, lambda _id, _token: plivo)

    await account.refresh(APP_SETTINGS)
    before = (account.pool_app_id, account.receiving_app_id, account.outbound_problem)
    await plivo.update_application(
        POOL_APP_ID, "http://yaksh.test/incoming", "http://yaksh.test/incoming/hangup"
    )
    await account.refresh(APP_SETTINGS)
    unchanged = account.receiving_app_id
    async with db() as session:
        await account_checks.check_numbers(session, plivo)
    await account.refresh(APP_SETTINGS)

    assert before == (
        POOL_APP_ID,
        None,
        "Plivo application Yaksh-Test has answer URL 'https://old.example/incoming'; "
        "set it to 'http://yaksh.test/incoming'",
    )
    assert unchanged is None, "the application is read again only after a check"
    assert account.receiving_app_id == POOL_APP_ID and account.outbound_problem is None
