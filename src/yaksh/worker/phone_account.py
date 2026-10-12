"""The Plivo account in the settings: the number pool synced from it, and the Application that
sends outbound agents' calls to this worker. Both are read again when the credentials change."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yaksh.config import Settings
from yaksh.domain.numbers import AccountNumber
from yaksh.domain.settings import AppSettings
from yaksh.integrations.plivo import PlivoApi, PlivoError
from yaksh.simulation.numbers import UnknownNumbersError, enabled_numbers, sync_numbers

log = logging.getLogger(__name__)


async def application_names(
    api: PlivoApi, numbers: list[AccountNumber], allowlist: list[str]
) -> dict[str, str]:
    """The names of the Applications linked to the numbers Yaksh may use, for the Numbers
    page; a name that cannot be read is left out."""
    enabled = set(enabled_numbers(numbers, allowlist))
    linked = {n.application_id for n in numbers if n.number in enabled and n.application_id}
    names: dict[str, str] = {}
    for app_id in sorted(linked):
        try:
            names[app_id] = (await api.get_application(app_id)).name
        except PlivoError as error:
            log.warning("could not read the name of application %s: %s", app_id, error)
    return names


def outbound_off(problem: str) -> tuple[None, str]:
    log.error("outbound tests are off: %s", problem)
    return None, problem


async def check_receiving(api: PlivoApi, settings: Settings) -> tuple[str | None, str | None]:
    """The Plivo application whose calls this worker receives, so it runs outbound
    conversations; or, when outbound tests are set up, why it does not."""
    if settings.plivo_app_id is None or settings.public_url is None:
        return None, None
    try:
        application = await api.get_application(settings.plivo_app_id)
    except PlivoError as error:
        return outbound_off(str(error))
    problems = application.problems(settings.public_url)
    if problems:
        return outbound_off("; ".join(problems))
    log.info("outbound tests: application %s sends calls here", application.name)
    return application.app_id, None


async def sync_pool(
    sessionmaker: async_sessionmaker[AsyncSession], api: PlivoApi, allowlist: list[str]
) -> None:
    """Refresh the number pool from the account; when Plivo cannot be reached, the last synced
    pool stands."""
    try:
        numbers = await api.list_numbers()
    except PlivoError as error:
        log.warning("keeping the last synced number pool: %s", error)
        return
    if not numbers:
        log.warning("keeping the last synced number pool: the account listed no numbers")
        return
    names = await application_names(api, numbers, allowlist)
    async with sessionmaker() as session:
        enabled = await sync_numbers(session, numbers, allowlist, names)
    log.info(
        "number pool: %d of %d account numbers enabled: %s",
        len(enabled),
        len(numbers),
        ", ".join(enabled[:10]) + (", ..." if len(enabled) > 10 else ""),
    )


class PhoneAccount:
    """What this worker knows of the Plivo account; refresh() reads it again when the
    credentials in the settings differ from the ones it last read."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._credentials: tuple[str, str] | None = None
        self._read = False
        self.receiving_app_id: str | None = None
        """The Plivo application that sends outbound agents' calls to this worker; without it
        the worker runs only inbound conversations."""
        self.outbound_problem: str | None = None
        """Why the worker runs no outbound conversations, when they are set up."""

    async def refresh(self, app: AppSettings) -> None:
        """The credentials count as read only once the pool and the Application are read, so
        a refresh that a stop or an error cuts short runs again at the next poll."""
        credentials = app.plivo_credentials
        if self._read and credentials == self._credentials:
            return
        receiving_app_id, problem = None, None
        if credentials is not None:
            api = PlivoApi(*credentials)
            try:
                await sync_pool(self._sessionmaker, api, self._settings.plivo_numbers)
            except UnknownNumbersError as error:
                log.error("YAKSH_PLIVO_NUMBERS: %s; keeping the last synced number pool", error)
                problem = f"YAKSH_PLIVO_NUMBERS: {error}"
            else:
                receiving_app_id, problem = await check_receiving(api, self._settings)
        self.receiving_app_id, self.outbound_problem = receiving_app_id, problem
        self._credentials = credentials
        self._read = True
