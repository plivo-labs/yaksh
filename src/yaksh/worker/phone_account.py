"""What a worker knows of the phone account in the settings: the receiving application, which
decides the test numbers, and whether it sends outbound agents' calls to this worker. The
worker reads the account's numbers again every check interval, and the application again when
the settings change or any process has read the numbers since."""

import logging
import math
import time
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yaksh.config import Settings
from yaksh.domain.numbers import PhoneAccountApi
from yaksh.domain.settings import AppSettings
from yaksh.integrations.plivo import PlivoApi
from yaksh.simulation.phone_account import (
    check_numbers,
    claim_check,
    last_check,
    receiving_application,
)

log = logging.getLogger(__name__)

CLAIM_EVERY_S = 10.0
"""How often a worker asks whether the check is due; the check interval is minutes."""


class PhoneAccount:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        api_for: Callable[[str, str], PhoneAccountApi] = PlivoApi,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._api_for = api_for
        self._read: tuple[tuple[str, str] | None, str | None] | None = None
        """The credentials and application the state below was read for."""
        self._seen_check: datetime | None = None
        self._claim_tried_at = -math.inf
        self.pool_app_id: str | None = None
        """The receiving application in the settings: its numbers are the test numbers."""
        self.receiving_app_id: str | None = None
        """The receiving application when it sends outbound agents' calls to this worker;
        without it the worker runs only inbound conversations."""
        self.outbound_problem: str | None = None
        """Why the worker runs no outbound conversations, when a receiving application is
        chosen."""

    async def refresh(self, app: AppSettings) -> None:
        """Read the numbers again when the check is due, and the application again when the
        settings changed or any process read the numbers since the last refresh. State changes
        only once the reads succeed, so a refresh that a stop cuts short runs again."""
        credentials = app.plivo_credentials
        app_id = app.phone.application_id
        if credentials is None:
            self.pool_app_id = self.receiving_app_id = self.outbound_problem = None
            self._read = (None, app_id)
            return
        api = self._api_for(*credentials)
        changed = self._read != (credentials, app_id)
        async with self._sessionmaker() as session:
            if changed or await self._due(session, app.phone.check_interval_s):
                await check_numbers(session, api)
            checked_at, _ = await last_check(session)
        if not changed and checked_at == self._seen_check:
            return
        receiving_app_id, problem = None, None
        if app_id is not None:
            receiving = await receiving_application(api, app_id, self._settings.public_url)
            if receiving.problems:
                problem = "; ".join(receiving.problems)
                log.error("outbound tests are off: %s", problem)
            else:
                receiving_app_id = app_id
                assert receiving.application is not None
                log.info(
                    "outbound tests: application %s sends calls here", receiving.application.name
                )
        self.pool_app_id = app_id
        self.receiving_app_id, self.outbound_problem = receiving_app_id, problem
        self._read = (credentials, app_id)
        self._seen_check = checked_at

    async def _due(self, session: AsyncSession, interval_s: int) -> bool:
        if time.monotonic() - self._claim_tried_at < CLAIM_EVERY_S:
            return False
        self._claim_tried_at = time.monotonic()
        return await claim_check(session, interval_s)
