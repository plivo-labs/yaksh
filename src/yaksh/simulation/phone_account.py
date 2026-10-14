"""The phone account in the settings: reading its numbers again, choosing which are test
numbers, and the application that receives their calls. A number is a test number when it is
linked to the receiving application; Plivo holds that link, so every Yaksh install on the
account sees the same owners."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.db.models import PhoneCheck, PhoneNumber
from yaksh.domain.errors import ConflictError, NotFoundError, ProviderCallError, UnavailableError
from yaksh.domain.numbers import (
    CX_AGENT_PREFIX,
    AccountNumber,
    PhoneAccountApi,
    PlivoApplication,
    receiving_urls,
)
from yaksh.simulation.numbers import sync_numbers

log = logging.getLogger(__name__)

CHECK_CLAIM_S = 60
"""How long a process holds the check before another may take it, should it stop midway."""
NEW_APPLICATION_NAME = "Yaksh"


def unavailable(doing: str, error: ProviderCallError) -> UnavailableError:
    return UnavailableError(f"Plivo did not {doing}: {error.reason or 'it gave no reason'}")


async def claim_check(session: AsyncSession, interval_s: int) -> bool:
    """Take the next check when the last one is older than interval_s and no process holds it;
    only one process checks at a time."""
    now = func.statement_timestamp()
    claimed = await session.scalar(
        update(PhoneCheck)
        .where(
            PhoneCheck.id == 1,
            or_(
                PhoneCheck.checked_at.is_(None),
                PhoneCheck.checked_at <= now - timedelta(seconds=interval_s),
            ),
            or_(PhoneCheck.claimed_until.is_(None), PhoneCheck.claimed_until <= now),
        )
        .values(claimed_until=now + timedelta(seconds=CHECK_CLAIM_S))
        .returning(PhoneCheck.id)
    )
    await session.commit()
    return claimed is not None


async def application_names(api: PhoneAccountApi, numbers: list[AccountNumber]) -> dict[str, str]:
    """The names of the applications linked to the numbers; a name that cannot be read is
    left out."""
    linked = {entry.application_id for entry in numbers if entry.application_id}
    names: dict[str, str] = {}
    for app_id in sorted(linked):
        try:
            names[app_id] = (await api.get_application(app_id)).name
        except ProviderCallError as error:
            log.warning("could not read the name of application %s: %s", app_id, error)
    return names


async def check_numbers(session: AsyncSession, api: PhoneAccountApi) -> str | None:
    """Read the account's numbers again and store them with their applications; returns why
    that failed. When Plivo cannot be reached, or lists no numbers, the stored numbers stand."""
    error: str | None = None
    try:
        numbers = await api.list_numbers()
    except ProviderCallError as failure:
        log.warning("keeping the stored numbers: %s", failure)
        error = failure.reason or "Plivo could not be reached"
    else:
        if numbers:
            await sync_numbers(session, numbers, await application_names(api, numbers))
            log.info("checked %d numbers of the Plivo account", len(numbers))
        else:
            log.warning("keeping the stored numbers: the account listed no numbers")
            error = "the Plivo account lists no numbers"
    await session.execute(
        update(PhoneCheck)
        .where(PhoneCheck.id == 1)
        .values(checked_at=func.statement_timestamp(), error=error, claimed_until=None)
    )
    await session.commit()
    return error


async def last_check(session: AsyncSession) -> tuple[datetime | None, str | None]:
    """When the numbers were last read, and why that failed if it did."""
    row = await session.get_one(PhoneCheck, 1, populate_existing=True)
    return row.checked_at, row.error


@dataclass(frozen=True)
class Receiving:
    """The receiving application as Plivo has it, and why it does not send calls to this
    install, if it does not."""

    application: PlivoApplication | None
    problems: list[str]


async def receiving_application(
    api: PhoneAccountApi, app_id: str, public_url: str | None
) -> Receiving:
    try:
        application = await api.get_application(app_id)
    except ProviderCallError as error:
        if error.status == 404:
            return Receiving(None, [f"Plivo has no application {app_id}"])
        return Receiving(None, [error.reason or f"Plivo could not read application {app_id}"])
    if public_url is None:
        return Receiving(application, ["set YAKSH_PUBLIC_URL to the address Plivo can reach"])
    return Receiving(application, application.problems(public_url))


async def choosable_applications(api: PhoneAccountApi) -> list[PlivoApplication]:
    """The applications people may choose to receive test calls: every one but those of Plivo
    CX agents."""
    try:
        applications = await api.list_applications()
    except ProviderCallError as error:
        raise unavailable("list the applications", error) from error
    return sorted(
        (app for app in applications if not app.name.startswith(CX_AGENT_PREFIX)),
        key=lambda app: app.name.lower(),
    )


async def make_application(api: PhoneAccountApi, public_url: str) -> str:
    """Make an application that sends calls to this install; returns its id."""
    answer_url, hangup_url = receiving_urls(public_url)
    try:
        return await api.create_application(NEW_APPLICATION_NAME, answer_url, hangup_url)
    except ProviderCallError as error:
        raise unavailable("make the application", error) from error


async def fix_application(api: PhoneAccountApi, app_id: str, public_url: str) -> None:
    """Point the application's answer and hangup URLs at this install."""
    answer_url, hangup_url = receiving_urls(public_url)
    try:
        await api.update_application(app_id, answer_url, hangup_url)
    except ProviderCallError as error:
        raise unavailable("change the application", error) from error


async def locked_number(session: AsyncSession, number: str) -> PhoneNumber:
    row = await session.scalar(
        select(PhoneNumber).where(PhoneNumber.number == number).with_for_update()
    )
    if row is None:
        raise NotFoundError(f"the Plivo account has no number {number}")
    return row


async def use_number(session: AsyncSession, api: PhoneAccountApi, number: str, app_id: str) -> None:
    """Make a free number a test number: link it to the receiving application in Plivo. A
    number another application receives is never taken."""
    row = await locked_number(session, number)
    if not row.voice:
        raise ConflictError(f"{number} cannot take calls")
    if row.application_id == app_id:
        await session.commit()
        return
    if row.application_id is not None:
        owner = row.application_name or row.application_id
        raise ConflictError(f"{number} belongs to the application {owner}")
    try:
        await api.link_number(number, app_id)
    except ProviderCallError as error:
        raise unavailable(f"link {number}", error) from error
    row.application_id = app_id
    row.application_name = None
    await session.commit()


async def stop_number(
    session: AsyncSession, api: PhoneAccountApi, number: str, app_id: str
) -> None:
    """Stop using a test number: remove its application in Plivo. Not while a test holds the
    number, nor while it rests after one, so no test loses a call it waits for. The row stays
    locked until Plivo answers, so no test leases the number meanwhile."""
    row = await locked_number(session, number)
    if row.application_id != app_id:
        raise ConflictError(f"{number} is not a test number")
    if row.conversation_id is not None:
        raise ConflictError(f"{number} is in a test")
    now = await session.scalar(select(func.statement_timestamp()))
    if row.available_after is not None and now is not None and row.available_after > now:
        raise ConflictError(f"{number} rests after a test")
    try:
        await api.link_number(number, None)
    except ProviderCallError as error:
        raise unavailable(f"unlink {number}", error) from error
    row.application_id = None
    row.application_name = None
    await session.commit()
