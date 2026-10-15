"""The phone account in the settings: reading its numbers again, choosing which are test
numbers, and the application that receives their calls. A number is a test number when it is
linked to the receiving application; Plivo holds that link, so every Yaksh install on the
account sees the same owners."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.db.models import PhoneCheck, PhoneNumber, StoredSettings
from yaksh.domain.errors import ConflictError, NotFoundError, ProviderCallError, UnavailableError
from yaksh.domain.numbers import (
    CX_AGENT_PREFIX,
    AccountNumber,
    PhoneAccountApi,
    PlivoApplication,
    receiving_urls,
)
from yaksh.simulation.numbers import store_numbers

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


CHECK_TRIES = 3


async def fence(session: AsyncSession, *, lock: bool = False) -> tuple[int, int]:
    """What a check must find unchanged to store what it read: the count of Yaksh's changes to
    numbers, and the settings version, which grows when the account changes."""
    query = select(PhoneCheck.generation).where(PhoneCheck.id == 1)
    generation = await session.scalar(query.with_for_update() if lock else query)
    version = await session.scalar(select(StoredSettings.version).where(StoredSettings.id == 1))
    return generation or 0, version or 0


async def check_numbers(session: AsyncSession, api: PhoneAccountApi) -> str | None:
    """Read the account's numbers again and store them with their applications; returns why
    that failed. When Plivo cannot be reached, or lists no numbers, the stored numbers stand.
    A check that a change to a number, or to the settings, overtook reads again, so it never
    stores what Plivo said before the change."""
    error: str | None = None
    for _ in range(CHECK_TRIES):
        before = await fence(session)
        await session.commit()
        try:
            numbers = await api.list_numbers()
        except ProviderCallError as failure:
            log.warning("keeping the stored numbers: %s", failure)
            error = failure.reason or "Plivo could not be reached"
            break
        if not numbers:
            log.warning("keeping the stored numbers: the account listed no numbers")
            error = "the Plivo account lists no numbers"
            break
        names = await application_names(api, numbers)
        generation, version = await fence(session, lock=True)
        if version != before[1]:
            # The account may have changed: what this client read is not the account's now.
            await session.rollback()
            log.info("the settings changed during the check; the next check reads the numbers")
            return None
        if generation != before[0]:
            await session.rollback()
            continue
        await store_numbers(session, numbers, names)
        log.info("checked %d numbers of the Plivo account", len(numbers))
        break
    else:
        await session.rollback()
        log.warning("the numbers kept changing during the check; the next check reads them")
        return None
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
    """The number's row, locked after the check row, the order a check takes them in too."""
    await session.execute(select(PhoneCheck.id).where(PhoneCheck.id == 1).with_for_update())
    row = await session.scalar(
        select(PhoneNumber).where(PhoneNumber.number == number).with_for_update()
    )
    if row is None:
        raise NotFoundError(f"the Plivo account has no number {number}")
    return row


async def changed(session: AsyncSession, row: PhoneNumber, app_id: str | None) -> None:
    """Store the number's application and commit, counting the change against running checks."""
    row.application_id = app_id
    row.application_name = None
    await session.execute(
        update(PhoneCheck).where(PhoneCheck.id == 1).values(generation=PhoneCheck.generation + 1)
    )
    await session.commit()


async def current_application(api: PhoneAccountApi, number: str) -> str | None:
    try:
        return (await api.get_number(number)).application_id
    except ProviderCallError as error:
        raise unavailable(f"read {number}", error) from error


async def use_number(session: AsyncSession, api: PhoneAccountApi, number: str, app_id: str) -> None:
    """Make a free number a test number: link it to the receiving application in Plivo. A
    number another application receives is never taken: Yaksh asks Plivo again just before
    the change, since another install may have taken the number since the last check. Plivo
    cannot change a number only if it is still free, so two installs that use one number at
    the same moment can still both link it; the later one wins."""
    row = await locked_number(session, number)
    if not row.voice:
        raise ConflictError(f"{number} cannot take calls")
    if row.application_id == app_id:
        await session.commit()
        return
    if row.application_id is not None:
        owner = row.application_name or row.application_id
        raise ConflictError(f"{number} belongs to the application {owner}")
    linked = await current_application(api, number)
    if linked == app_id:
        await changed(session, row, app_id)
        return
    if linked is not None:
        await changed(session, row, linked)
        raise ConflictError(f"{number} belongs to the application {linked}")
    try:
        await api.link_number(number, app_id)
    except ProviderCallError as error:
        raise unavailable(f"link {number}", error) from error
    await changed(session, row, app_id)


async def stop_number(
    session: AsyncSession, api: PhoneAccountApi, number: str, app_id: str
) -> None:
    """Stop using a test number: remove its application in Plivo. Not while a test holds the
    number, nor while it rests after one, so no test loses a call it waits for. The row stays
    locked until Plivo answers, so no test leases the number meanwhile. When Plivo's answer
    does not come, the number leaves the pool anyway, since Plivo may have made the change;
    the next check stores what Plivo has."""
    row = await locked_number(session, number)
    if row.application_id != app_id:
        raise ConflictError(f"{number} is not a test number")
    if row.conversation_id is not None:
        raise ConflictError(f"{number} is in a test")
    now = await session.scalar(select(func.statement_timestamp()))
    if row.available_after is not None and now is not None and row.available_after > now:
        raise ConflictError(f"{number} rests after a test")
    linked = await current_application(api, number)
    if linked != app_id:
        await changed(session, row, linked)
        raise ConflictError(f"{number} is no longer linked to the receiving application")
    try:
        await api.link_number(number, None)
    except ProviderCallError as error:
        await changed(session, row, None)
        raise unavailable(f"unlink {number}", error) from error
    await changed(session, row, None)
