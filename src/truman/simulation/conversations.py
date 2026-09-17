import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from truman.config import Settings
from truman.db.models import Agent, AgentVersion, Conversation, PhoneNumber
from truman.domain.agents import AgentConfig, Direction, Transport
from truman.domain.conversations import (
    ACTIVE_STATUSES,
    CallOutcome,
    CallRequest,
    ConversationCreate,
    ConversationStatus,
    EndReason,
    Transcript,
    Validity,
)
from truman.domain.errors import NotFoundError, ValidationError
from truman.domain.numbers import AccountNumber
from truman.simulation.agents import get_agent

LIVE_STATUSES = frozenset({ConversationStatus.RUNNING, ConversationStatus.ENDING})
LEASE_LOST = "worker lease expired; outcome unknown, not retried"
WORKER_STOPPED = "worker stopped during the call; outcome unknown, not retried"


class PoolExhaustedError(Exception):
    """Every pool number is on a call; the conversation goes back to the queue."""


class UnknownNumbersError(Exception):
    """The allowlist names numbers the Plivo account does not have."""


async def create_conversation(
    session: AsyncSession, settings: Settings, command: ConversationCreate
) -> Conversation:
    agent = await get_agent(session, command.agent_id, lock=True)
    if agent.direction is not Direction.INBOUND:
        raise ValidationError("not supported yet: only inbound agents")
    if agent.transport is Transport.PHONE:
        if command.caller_number is not None:
            raise ValidationError("caller_number is leased from the number pool for phone agents")
        caller_number = None
    else:
        caller_number = command.caller_number or settings.default_caller_number
    version_id = await session.scalar(
        select(AgentVersion.id).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == agent.current_version
        )
    )
    conversation = Conversation(
        id=uuid.uuid4(),
        agent_id=agent.id,
        agent_version_id=version_id,
        persona_prompt=command.persona_prompt,
        caller_number=caller_number,
        max_duration_s=command.max_duration_s or settings.default_max_duration_s,
    )
    session.add(conversation)
    await session.commit()
    return conversation


async def get_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise NotFoundError("conversation not found")
    return conversation


async def list_conversations(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    agent_id: uuid.UUID | None = None,
    status: ConversationStatus | None = None,
) -> tuple[list[Conversation], int]:
    query = select(Conversation)
    if agent_id is not None:
        query = query.where(Conversation.agent_id == agent_id)
    if status is not None:
        query = query.where(Conversation.status == status)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(Conversation.created_at.desc(), Conversation.id).offset(offset).limit(limit)
    )
    return list(rows), total or 0


async def pinned_agent(session: AsyncSession, conversation: Conversation) -> tuple[int, str]:
    """The version number and agent name a conversation was started against."""
    row = (
        await session.execute(
            select(AgentVersion.version, Agent.name)
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .where(AgentVersion.id == conversation.agent_version_id)
        )
    ).one()
    return row.version, row.name


def transcript_of(conversation: Conversation) -> Transcript:
    if conversation.transcript is None:
        return Transcript()
    return Transcript.model_validate(conversation.transcript)


async def end_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    """Cancel a queued conversation or ask the worker to end a running one; the row is locked so
    a concurrent claim or requeue cannot slip between the read and the write."""
    conversation = await session.get(Conversation, conversation_id, with_for_update=True)
    if conversation is None:
        raise NotFoundError("conversation not found")
    if conversation.status is ConversationStatus.QUEUED:
        conversation.status = ConversationStatus.CANCELLED
        conversation.end_reason = EndReason.USER_REQUEST
        conversation.ended_at = func.now()
    elif conversation.status is ConversationStatus.RUNNING:
        conversation.status = ConversationStatus.ENDING
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def claim_next(session: AsyncSession, worker_id: str, lease_s: int) -> Conversation | None:
    """Claim the oldest queued conversation that can run now.

    A conversation without a caller number takes one from the pool, so it waits while none is free.
    """
    free_number = (
        select(PhoneNumber.number)
        .where(PhoneNumber.enabled.is_(True), PhoneNumber.conversation_id.is_(None))
        .exists()
    )
    candidate = (
        select(Conversation.id)
        .where(
            Conversation.status == ConversationStatus.QUEUED,
            or_(Conversation.caller_number.is_not(None), free_number),
        )
        .order_by(Conversation.created_at, Conversation.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    rows = await session.scalars(
        update(Conversation)
        .where(Conversation.id == candidate)
        .values(
            status=ConversationStatus.RUNNING,
            started_at=func.now(),
            claimed_by=worker_id,
            lease_expires_at=func.now() + timedelta(seconds=lease_s),
        )
        .returning(Conversation)
    )
    conversation = rows.one_or_none()
    await session.commit()
    return conversation


async def call_request(
    session: AsyncSession, settings: Settings, conversation: Conversation
) -> CallRequest:
    version = await session.get_one(AgentVersion, conversation.agent_version_id)
    agent = AgentConfig.model_validate(version.config)
    number = conversation.caller_number
    if number is None:
        number = await lease_number(session, conversation.id)
    if number is None:
        raise PoolExhaustedError("no pool number is free")
    return CallRequest(
        conversation_id=conversation.id,
        agent=agent,
        persona_prompt=conversation.persona_prompt,
        caller_number=number,
        max_duration_s=conversation.max_duration_s,
        output_dir=settings.data_dir / str(conversation.id),
    )


async def renew_lease(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    worker_id: str,
    lease_s: int,
    progress: Transcript | None,
) -> ConversationStatus | None:
    values: dict[str, object] = {
        "lease_expires_at": func.now() + timedelta(seconds=lease_s),
    }
    if progress is not None:
        values["transcript"] = progress.model_dump(mode="json")
    status = await session.scalar(
        update(Conversation)
        .where(owned_by(conversation_id, worker_id))
        .values(**values)
        .returning(Conversation.status)
    )
    await session.commit()
    return status


async def requeue(session: AsyncSession, conversation_id: uuid.UUID, worker_id: str) -> bool:
    """Hand a claimed conversation back to the queue. False when it is no longer ours to return."""
    returned = await session.scalar(
        update(Conversation)
        .where(
            owned_by(conversation_id, worker_id), Conversation.status == ConversationStatus.RUNNING
        )
        .values(
            status=ConversationStatus.QUEUED,
            started_at=None,
            claimed_by=None,
            lease_expires_at=None,
        )
        .returning(Conversation.id)
    )
    await session.commit()
    return returned is not None


def owned_by(conversation_id: uuid.UUID, worker_id: str) -> ColumnElement[bool]:
    return and_(
        Conversation.id == conversation_id,
        Conversation.claimed_by == worker_id,
        Conversation.status.in_(LIVE_STATUSES),
        Conversation.lease_expires_at > func.now(),
    )


async def reap_expired(session: AsyncSession) -> int:
    reaped = await session.scalars(
        update(Conversation)
        .where(
            Conversation.status.in_(LIVE_STATUSES),
            Conversation.lease_expires_at <= func.now(),
        )
        .values(
            status=ConversationStatus.FAILED,
            end_reason=EndReason.PROCESS_RESTART,
            failure_reason=LEASE_LOST,
            ended_at=func.now(),
            claimed_by=None,
            lease_expires_at=None,
        )
        .returning(Conversation.id)
    )
    ids = list(reaped.all())
    if ids:
        await release_numbers(session, ids)
    await session.commit()
    return len(ids)


def resolve_status(outcome: CallOutcome) -> ConversationStatus:
    if outcome.end_reason is EndReason.PROCESS_RESTART:
        return ConversationStatus.FAILED
    if not outcome.connected:
        if outcome.end_reason is EndReason.USER_REQUEST:
            return ConversationStatus.CANCELLED
        return ConversationStatus.FAILED
    if outcome.caller_error is not None:
        return ConversationStatus.INVALID
    return ConversationStatus.COMPLETED


def failure_reason(outcome: CallOutcome) -> str | None:
    if outcome.end_reason is EndReason.PROCESS_RESTART:
        return WORKER_STOPPED
    return outcome.caller_error


async def finalize(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    worker_id: str,
    outcome: CallOutcome,
    transcript: Transcript,
    duration_ms: int,
) -> bool:
    """Record the terminal state. Returns False when the row was no longer ours to finish."""
    if outcome.connected:
        transcript.validity = Validity(
            ok=outcome.caller_error is None,
            reasons=[outcome.caller_error] if outcome.caller_error else [],
        )
    recorded = await session.scalar(
        update(Conversation)
        .where(owned_by(conversation_id, worker_id))
        .values(
            status=resolve_status(outcome),
            end_reason=outcome.end_reason,
            failure_reason=failure_reason(outcome),
            ended_at=func.now(),
            duration_ms=duration_ms,
            transcript=transcript.model_dump(mode="json"),
            recording_path=str(outcome.recording_path) if outcome.recording_path else None,
            call_uuid=outcome.call_uuid,
            claimed_by=None,
            lease_expires_at=None,
        )
        .returning(Conversation.id)
    )
    if recorded is not None:
        await release_numbers(session, [conversation_id])
    await session.commit()
    return recorded is not None


async def sync_numbers(
    session: AsyncSession, numbers: list[AccountNumber], allowlist: list[str]
) -> list[str]:
    """Make the pool match the Plivo account: every voice number is enabled, or only the
    allowlisted ones when there is an allowlist; numbers gone from the account are dropped once
    free. Returns the enabled numbers."""
    listed = {entry.number for entry in numbers}
    missing = [number for number in allowlist if number not in listed]
    if missing:
        raise UnknownNumbersError(f"the Plivo account does not have {', '.join(missing)}")
    if numbers:
        rows = insert(PhoneNumber).values(
            [
                {
                    "number": entry.number,
                    "alias": entry.alias,
                    "region": entry.region,
                    "enabled": entry.number in allowlist if allowlist else entry.voice,
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
                },
            )
        )
    await session.execute(
        delete(PhoneNumber).where(
            PhoneNumber.number.notin_(listed), PhoneNumber.conversation_id.is_(None)
        )
    )
    await session.commit()
    return [
        entry.number
        for entry in numbers
        if (entry.number in allowlist if allowlist else entry.voice)
    ]


async def lease_number(session: AsyncSession, conversation_id: uuid.UUID) -> str | None:
    """Lease the least recently used free number to the conversation, or None when all are taken."""
    candidate = (
        select(PhoneNumber.number)
        .where(PhoneNumber.enabled.is_(True), PhoneNumber.conversation_id.is_(None))
        .order_by(PhoneNumber.leased_at.nulls_first(), PhoneNumber.number)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    number = await session.scalar(
        update(PhoneNumber)
        .where(PhoneNumber.number == candidate)
        .values(conversation_id=conversation_id, leased_at=func.now())
        .returning(PhoneNumber.number)
    )
    if number is not None:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(caller_number=number)
        )
    await session.commit()
    return number


async def release_numbers(session: AsyncSession, conversation_ids: list[uuid.UUID]) -> None:
    await session.execute(
        update(PhoneNumber)
        .where(PhoneNumber.conversation_id.in_(conversation_ids))
        .values(conversation_id=None)
    )


async def stream_events(
    sessionmaker: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID, *, interval_s: float
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield (event, data) pairs as the transcript grows, ending after the final status."""
    seen_turns = seen_events = 0
    last_status: ConversationStatus | None = None
    while True:
        async with sessionmaker() as session:
            conversation = await get_conversation(session, conversation_id)
        transcript = transcript_of(conversation)
        for turn in transcript.turns[seen_turns:]:
            yield "turn", turn.model_dump(mode="json")
        for event in transcript.wire_events[seen_events:]:
            yield "wire_event", event.model_dump(mode="json")
        seen_turns, seen_events = len(transcript.turns), len(transcript.wire_events)
        if conversation.status is not last_status:
            last_status = conversation.status
            yield "status", {"status": conversation.status}
        if conversation.status not in ACTIVE_STATUSES:
            return
        await asyncio.sleep(interval_s)
