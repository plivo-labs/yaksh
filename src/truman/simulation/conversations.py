import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from truman.config import Settings
from truman.db.models import AgentVersion, Conversation
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
from truman.simulation.agents import get_agent

LIVE_STATUSES = frozenset({ConversationStatus.RUNNING, ConversationStatus.ENDING})
LEASE_LOST = "worker lease expired; outcome unknown, not retried"
WORKER_STOPPED = "worker stopped during the call; outcome unknown, not retried"


async def create_conversation(
    session: AsyncSession, settings: Settings, command: ConversationCreate
) -> Conversation:
    agent = await get_agent(session, command.agent_id, lock=True)
    if agent.direction is not Direction.INBOUND or agent.transport is not Transport.PLIVO_WEBSOCKET:
        raise ValidationError("not supported yet: only inbound agents over plivo_websocket")
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
        caller_number=command.caller_number or settings.default_caller_number,
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


async def version_number(session: AsyncSession, conversation: Conversation) -> int:
    number = await session.scalar(
        select(AgentVersion.version).where(AgentVersion.id == conversation.agent_version_id)
    )
    return number or 0


def transcript_of(conversation: Conversation) -> Transcript:
    if conversation.transcript is None:
        return Transcript()
    return Transcript.model_validate(conversation.transcript)


async def end_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    cancelled = await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id, Conversation.status == ConversationStatus.QUEUED)
        .values(
            status=ConversationStatus.CANCELLED,
            end_reason=EndReason.USER_REQUEST,
            ended_at=func.now(),
        )
        .returning(Conversation.id)
    )
    await session.commit()
    if cancelled.scalar_one_or_none() is None:
        await session.execute(
            update(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.status == ConversationStatus.RUNNING,
            )
            .values(status=ConversationStatus.ENDING)
        )
        await session.commit()
    return await get_conversation(session, conversation_id)


async def claim_next(session: AsyncSession, worker_id: str, lease_s: int) -> Conversation | None:
    candidate = (
        select(Conversation.id)
        .where(Conversation.status == ConversationStatus.QUEUED)
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
    return CallRequest(
        conversation_id=conversation.id,
        agent=AgentConfig.model_validate(version.config),
        persona_prompt=conversation.persona_prompt,
        caller_number=conversation.caller_number,
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
            Conversation.lease_expires_at < func.now(),
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
    count = len(reaped.all())
    await session.commit()
    return count


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
            claimed_by=None,
            lease_expires_at=None,
        )
        .returning(Conversation.id)
    )
    await session.commit()
    return recorded is not None


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
