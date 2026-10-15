"""The pool of Plivo numbers Yaksh calls from and receives calls on: syncing it with the
account, and leasing and resting its numbers."""

import uuid
from datetime import timedelta

from sqlalchemy import ColumnElement, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.config import Settings
from yaksh.db.models import Conversation, PhoneNumber
from yaksh.domain.numbers import AccountNumber
from yaksh.domain.settings import AppSettings
from yaksh.simulation.workers import application_problem, receiving_problem
from yaksh.timings import TIMINGS


def phone_problem(settings: Settings, app: AppSettings) -> str | None:
    """Why phone calls are off, or None when they are on."""
    if app.plivo_credentials is None:
        return "add the Plivo Auth ID and Auth token in Settings"
    if app.missing_caller_keys:
        return f"add the {', '.join(app.missing_caller_keys)} key in Settings"
    if settings.public_url is None:
        return "set YAKSH_PUBLIC_URL to the address Plivo can reach"
    return None


def free_numbers(app_id: str, *, rested: bool = False) -> ColumnElement[bool]:
    """Test numbers a conversation may lease: linked to the receiving application app_id and
    held by no conversation; to receive an outbound call, also rested since their last test."""
    free = and_(
        PhoneNumber.application_id == app_id,
        PhoneNumber.voice.is_(True),
        PhoneNumber.conversation_id.is_(None),
    )
    if not rested:
        return free
    return and_(
        free,
        or_(
            PhoneNumber.available_after.is_(None),
            PhoneNumber.available_after <= func.statement_timestamp(),
        ),
    )


async def account_numbers(session: AsyncSession) -> list[PhoneNumber]:
    """Every number of the account as the last check found it."""
    rows = await session.scalars(select(PhoneNumber).order_by(PhoneNumber.number))
    return list(rows)


async def sync_numbers(
    session: AsyncSession, numbers: list[AccountNumber], application_names: dict[str, str]
) -> None:
    await store_numbers(session, numbers, application_names)
    await session.commit()


async def store_numbers(
    session: AsyncSession, numbers: list[AccountNumber], application_names: dict[str, str]
) -> None:
    """Make the stored numbers match the Plivo account, without committing: each number's
    application, name and region as Plivo lists them; numbers gone from the account are
    dropped once free. A lease is never touched, so a number that leaves the receiving
    application, or the account, keeps its test until the test ends; one gone from the account
    leaves the pool at once."""
    listed = {entry.number for entry in numbers}
    if numbers:
        rows = insert(PhoneNumber).values(
            [
                {
                    "number": entry.number,
                    "alias": entry.alias,
                    "region": entry.region,
                    "voice": entry.voice,
                    "application_id": entry.application_id,
                    "application_name": application_names.get(entry.application_id or ""),
                }
                for entry in numbers
            ]
        )
        await session.execute(
            rows.on_conflict_do_update(
                index_elements=[PhoneNumber.number],
                set_={
                    "alias": rows.excluded.alias,
                    "region": rows.excluded.region,
                    "voice": rows.excluded.voice,
                    "application_id": rows.excluded.application_id,
                    "application_name": rows.excluded.application_name,
                },
            )
        )
    gone = PhoneNumber.number.notin_(listed)
    await session.execute(
        update(PhoneNumber).where(gone).values(application_id=None, application_name=None)
    )
    await session.execute(delete(PhoneNumber).where(gone, PhoneNumber.conversation_id.is_(None)))


async def lease_number(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    app_id: str,
    *,
    accept_calls_for_s: int | None = None,
) -> str | None:
    """Lease the least recently used test number the conversation may use, or None when all
    are taken. An outbound lease, the one with accept_calls_for_s, needs a rested number and
    opens the window for the agent's call to arrive."""
    candidate = (
        select(PhoneNumber.number)
        .where(free_numbers(app_id, rested=accept_calls_for_s is not None))
        .order_by(PhoneNumber.leased_at.nulls_first(), PhoneNumber.number)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    number = await session.scalar(
        update(PhoneNumber)
        .where(PhoneNumber.number == candidate)
        .values(conversation_id=conversation_id, leased_at=func.statement_timestamp())
        .returning(PhoneNumber.number)
    )
    if number is not None:
        deadline = (
            None
            if accept_calls_for_s is None
            else func.statement_timestamp() + timedelta(seconds=accept_calls_for_s)
        )
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(caller_number=number, dial_deadline_at=deadline)
        )
    await session.commit()
    return number


async def release_numbers(
    session: AsyncSession, conversation_ids: list[uuid.UUID], number_rest_s: int
) -> None:
    """Free the numbers. A number rests before a new test may receive calls on it, so a late
    call from the finished test does not reach the next one."""
    await session.execute(
        update(PhoneNumber)
        .where(PhoneNumber.conversation_id.in_(conversation_ids))
        .values(
            conversation_id=None,
            available_after=func.statement_timestamp() + timedelta(seconds=number_rest_s),
        )
    )


async def outbound_problem(
    session: AsyncSession, settings: Settings, app: AppSettings
) -> str | None:
    """Why an outbound test could not get its call now, or None when it could."""
    problem = phone_problem(settings, app)
    if problem is not None:
        return problem
    app_id = app.phone.application_id
    if app_id is None:
        return NO_APPLICATION
    problem = await receiving_problem(session, app_id, TIMINGS.worker_lease_s)
    if problem is not None:
        return problem
    return await no_numbers_problem(session, app_id)


NO_APPLICATION = "choose the receiving application in Settings"


async def no_numbers_problem(session: AsyncSession, app_id: str) -> str | None:
    """Why no test can get a number: the receiving application has none."""
    linked = await session.scalar(
        select(PhoneNumber.number)
        .where(PhoneNumber.application_id == app_id, PhoneNumber.voice.is_(True))
        .limit(1)
    )
    if linked is None:
        return "choose test numbers on the Numbers page"
    return None


async def inbound_problem(
    session: AsyncSession, settings: Settings, app: AppSettings
) -> str | None:
    """Why an inbound test could not get a number to call from, or None when it could."""
    problem = phone_problem(settings, app)
    if problem is not None:
        return problem
    app_id = app.phone.application_id
    if app_id is None:
        return NO_APPLICATION
    problem = await no_numbers_problem(session, app_id)
    if problem is not None:
        return problem
    return await application_problem(session, app_id, TIMINGS.worker_lease_s)
