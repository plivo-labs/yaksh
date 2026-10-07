"""The pool of Plivo numbers Yaksha calls from and receives calls on: syncing it with the
account, and leasing and resting its numbers."""

import uuid
from datetime import timedelta

from sqlalchemy import ColumnElement, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from yaksha.config import Settings
from yaksha.db.models import Conversation, PhoneNumber
from yaksha.domain.numbers import AccountNumber
from yaksha.domain.settings import AppSettings
from yaksha.simulation.workers import receiving_problem


def phone_problem(settings: Settings, app: AppSettings) -> str | None:
    """Why phone calls are off, or None when they are on."""
    if app.plivo_credentials is None:
        return "add the Plivo Auth ID and Auth token in Settings"
    if app.missing_caller_keys:
        return f"add the {', '.join(app.missing_caller_keys)} key in Settings"
    if settings.public_url is None:
        return "set YAKSHA_PUBLIC_URL to the address Plivo can reach"
    return None


class UnknownNumbersError(Exception):
    """The allowlist names numbers the Plivo account does not have."""


def free_numbers(receiving_app_id: str | None = None) -> ColumnElement[bool]:
    """Numbers a conversation may lease: enabled and free; to receive an outbound call, also
    linked to Yaksha's Plivo application and rested since their last test."""
    free = and_(PhoneNumber.enabled.is_(True), PhoneNumber.conversation_id.is_(None))
    if receiving_app_id is None:
        return free
    return and_(
        free,
        PhoneNumber.application_id == receiving_app_id,
        or_(
            PhoneNumber.available_after.is_(None),
            PhoneNumber.available_after <= func.statement_timestamp(),
        ),
    )


async def enabled_pool(session: AsyncSession) -> list[PhoneNumber]:
    rows = await session.scalars(
        select(PhoneNumber).where(PhoneNumber.enabled.is_(True)).order_by(PhoneNumber.number)
    )
    return list(rows)


def enabled_numbers(numbers: list[AccountNumber], allowlist: list[str]) -> list[str]:
    """The allowlisted numbers, or every voice number when there is no allowlist."""
    return [
        entry.number
        for entry in numbers
        if (entry.number in allowlist if allowlist else entry.voice)
    ]


async def sync_numbers(
    session: AsyncSession,
    numbers: list[AccountNumber],
    allowlist: list[str],
    application_names: dict[str, str],
) -> list[str]:
    """Make the pool match the Plivo account: every voice number is enabled, or only the
    allowlisted ones when there is an allowlist; numbers gone from the account are dropped once
    free. Returns the enabled numbers."""
    listed = {entry.number for entry in numbers}
    missing = [number for number in allowlist if number not in listed]
    if missing:
        raise UnknownNumbersError(f"the Plivo account does not have {', '.join(missing)}")
    enabled = enabled_numbers(numbers, allowlist)
    if numbers:
        rows = insert(PhoneNumber).values(
            [
                {
                    "number": entry.number,
                    "alias": entry.alias,
                    "region": entry.region,
                    "enabled": entry.number in enabled,
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
                    "enabled": rows.excluded.enabled,
                    "application_id": rows.excluded.application_id,
                    "application_name": rows.excluded.application_name,
                },
            )
        )
    await session.execute(
        delete(PhoneNumber).where(
            PhoneNumber.number.notin_(listed), PhoneNumber.conversation_id.is_(None)
        )
    )
    await session.commit()
    return enabled


async def lease_number(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    receiving_app_id: str | None = None,
    accept_calls_for_s: int | None = None,
) -> str | None:
    """Lease the least recently used number the conversation may use, or None when all are
    taken. An outbound lease opens the window for the agent's call to arrive."""
    candidate = (
        select(PhoneNumber.number)
        .where(free_numbers(receiving_app_id))
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
    app_id = settings.plivo_app_id
    if app_id is None:
        return "set YAKSHA_PLIVO_APP_ID"
    problem = await receiving_problem(session, app_id, settings.worker_lease_s)
    if problem is not None:
        return problem
    linked = await session.scalar(
        select(PhoneNumber.number)
        .where(PhoneNumber.enabled.is_(True), PhoneNumber.application_id == app_id)
        .limit(1)
    )
    if linked is None:
        return f"no enabled number is linked to Plivo application {app_id}"
    return None
