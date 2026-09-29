import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from truman.config import Settings
from truman.db.models import (
    Agent,
    AgentVersion,
    Conversation,
    Persona,
    PersonaVersion,
    PhoneNumber,
    Scenario,
    ScenarioVersion,
)
from truman.domain.agents import AgentConfig, Direction
from truman.domain.conversations import (
    ACTIVE_STATUSES,
    Admission,
    CallOutcome,
    CallRequest,
    ConversationCreate,
    ConversationStatus,
    EndReason,
    IncomingCall,
    Transcript,
    Validity,
)
from truman.domain.errors import NotFoundError, ValidationError
from truman.domain.numbers import AccountNumber
from truman.domain.personas import PersonaConfig
from truman.domain.scenarios import ScenarioConfig, normalized
from truman.domain.triggers import SEND_TIMEOUT_S, agent_data_names
from truman.simulation.agents import config_of as agents_config_of
from truman.simulation.agents import get_agent
from truman.simulation.languages import LANGUAGES
from truman.simulation.personas import config_of, get_persona
from truman.simulation.prompts import caller_instructions
from truman.simulation.scenarios import config_of as scenario_config_of
from truman.simulation.scenarios import get_scenario

LIVE_STATUSES = frozenset({ConversationStatus.RUNNING, ConversationStatus.ENDING})
LEASE_LOST = "worker lost its lease on the conversation; outcome unknown, not retried"
WORKER_STOPPED = "worker stopped during the call; outcome unknown, not retried"
FAILURE_TEXT = {EndReason.WORKER_STOPPED: WORKER_STOPPED, EndReason.LEASE_LOST: LEASE_LOST}


class PoolExhaustedError(Exception):
    """Every pool number is on a call; the conversation goes back to the queue."""


class UnknownNumbersError(Exception):
    """The allowlist names numbers the Plivo account does not have."""


async def create_conversation(
    session: AsyncSession, settings: Settings, command: ConversationCreate
) -> Conversation:
    if not settings.phone_enabled:
        raise ValidationError(
            "phone calls are off: set PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN and TRUMAN_PUBLIC_URL"
        )
    agent = await get_agent(session, command.agent_id, lock=True)
    if agent.direction is Direction.OUTBOUND and settings.plivo_app_id is None:
        raise ValidationError("outbound tests are off: set TRUMAN_PLIVO_APP_ID")
    version_id = await session.scalar(
        select(AgentVersion.id).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == agent.current_version
        )
    )
    scenario = await get_scenario(session, command.scenario_id, lock=True)
    if scenario.agent_id != agent.id:
        raise ValidationError("the scenario belongs to another agent")
    scenario_version_id = await session.scalar(
        select(ScenarioVersion.id).where(
            ScenarioVersion.scenario_id == scenario.id,
            ScenarioVersion.version == scenario.current_version,
        )
    )
    persona = await get_persona(session, command.persona_id, lock=True)
    persona_version_id = await session.scalar(
        select(PersonaVersion.id).where(
            PersonaVersion.persona_id == persona.id,
            PersonaVersion.version == persona.current_version,
        )
    )
    config = config_of(persona)
    wants = scenario_config_of(scenario)
    if agent.direction is Direction.OUTBOUND:
        await check_outbound_start(session, settings, agents_config_of(agent), wants)
    conversation = Conversation(
        direction=agent.direction,
        agent_id=agent.id,
        agent_version_id=version_id,
        persona_id=persona.id,
        persona_version_id=persona_version_id,
        scenario_id=scenario.id,
        scenario_version_id=scenario_version_id,
        language=config.language,
        instructions=caller_instructions(
            config,
            goal=wants.goal,
            known_facts=wants.known_facts,
            unknown_facts=wants.unknown_facts,
            today=datetime.now(ZoneInfo(settings.timezone)).date(),
            direction=agent.direction,
        ),
        nudge=LANGUAGES[config.language].nudge,
        max_duration_s=command.max_duration_s or settings.default_max_duration_s,
    )
    session.add(conversation)
    await session.commit()
    return conversation


async def check_outbound_start(
    session: AsyncSession, settings: Settings, agent: AgentConfig, scenario: ScenarioConfig
) -> None:
    """Refuse a start that could never get a call: nowhere to receive it, or a trigger that
    needs agent data the scenario does not have."""
    linked = await session.scalar(
        select(PhoneNumber.number)
        .where(PhoneNumber.enabled.is_(True), PhoneNumber.application_id == settings.plivo_app_id)
        .limit(1)
    )
    if linked is None:
        raise ValidationError(
            f"no enabled number is linked to Plivo application {settings.plivo_app_id}"
        )
    assert agent.outbound is not None
    have = {normalized(fact.name) for fact in scenario.agent_data}
    missing = sorted(agent_data_names(agent.outbound.trigger) - have)
    if missing:
        raise ValidationError(f"the scenario has no agent data named {', '.join(missing)}")


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


async def pinned_agents(
    session: AsyncSession, conversations: Sequence[Conversation]
) -> dict[uuid.UUID, tuple[int, str]]:
    """The version number each conversation pinned and the agent's current name, by version id."""
    rows = await session.execute(
        select(AgentVersion.id, AgentVersion.version, Agent.name)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(AgentVersion.id.in_({row.agent_version_id for row in conversations}))
    )
    return {row.id: (row.version, row.name) for row in rows}


async def pinned_scenarios(
    session: AsyncSession, conversations: Sequence[Conversation]
) -> dict[uuid.UUID, tuple[int, str]]:
    """The version number each conversation pinned and the scenario's current name, by version
    id."""
    rows = await session.execute(
        select(ScenarioVersion.id, ScenarioVersion.version, Scenario.name)
        .join(Scenario, Scenario.id == ScenarioVersion.scenario_id)
        .where(ScenarioVersion.id.in_({row.scenario_version_id for row in conversations}))
    )
    return {row.id: (row.version, row.name) for row in rows}


async def pinned_scenario_config(
    session: AsyncSession, conversation: Conversation
) -> ScenarioConfig:
    version = await session.get_one(ScenarioVersion, conversation.scenario_version_id)
    return ScenarioConfig.model_validate(version.config)


async def pinned_personas(
    session: AsyncSession, conversations: Sequence[Conversation]
) -> dict[uuid.UUID, tuple[int, str]]:
    """The version number each conversation pinned and the persona's current name, by version
    id."""
    rows = await session.execute(
        select(PersonaVersion.id, PersonaVersion.version, Persona.name)
        .join(Persona, Persona.id == PersonaVersion.persona_id)
        .where(PersonaVersion.id.in_({row.persona_version_id for row in conversations}))
    )
    return {row.id: (row.version, row.name) for row in rows}


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


def free_numbers(receiving_app_id: str | None = None) -> ColumnElement[bool]:
    """Numbers a conversation may lease: enabled and free; to receive an outbound call, also
    linked to Truman's Plivo application and rested since their last test."""
    free = and_(PhoneNumber.enabled.is_(True), PhoneNumber.conversation_id.is_(None))
    if receiving_app_id is None:
        return free
    return and_(
        free,
        PhoneNumber.application_id == receiving_app_id,
        or_(PhoneNumber.available_after.is_(None), PhoneNumber.available_after <= func.now()),
    )


async def claim_next(
    session: AsyncSession, worker_id: str, lease_s: int, receiving_app_id: str | None
) -> Conversation | None:
    """Claim the oldest queued conversation that can run now: one that needs a number waits
    while none it may use is free. Outbound conversations run only on a worker that receives
    calls for receiving_app_id."""
    inbound = and_(
        Conversation.direction == Direction.INBOUND,
        or_(
            Conversation.caller_number.is_not(None),
            select(PhoneNumber).where(free_numbers()).exists(),
        ),
    )
    runnable = inbound
    if receiving_app_id is not None:
        outbound = and_(
            Conversation.direction == Direction.OUTBOUND,
            select(PhoneNumber).where(free_numbers(receiving_app_id)).exists(),
        )
        runnable = or_(inbound, outbound)
    candidate = (
        select(Conversation.id)
        .where(Conversation.status == ConversationStatus.QUEUED, runnable)
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


async def prepare_call(
    session: AsyncSession,
    settings: Settings,
    conversation: Conversation,
    receiving_app_id: str | None,
) -> CallRequest:
    """Lease the conversation's Truman number when it has none yet (the caller ID of an inbound
    test, or the number an outbound agent must call) and build the call from the pinned
    versions."""
    agent_version = await session.get_one(AgentVersion, conversation.agent_version_id)
    agent = AgentConfig.model_validate(agent_version.config)
    number = conversation.caller_number
    if number is None and agent.outbound is not None:
        assert receiving_app_id is not None
        number = await lease_number(
            session,
            conversation.id,
            receiving_app_id=receiving_app_id,
            accept_calls_for_s=SEND_TIMEOUT_S + agent.outbound.dial_window_s,
        )
    elif number is None:
        number = await lease_number(session, conversation.id)
    if number is None:
        raise PoolExhaustedError("no pool number is free")
    leased = await session.get_one(Conversation, conversation.id, populate_existing=True)
    return await call_request(session, settings, leased, number, agent)


async def call_request(
    session: AsyncSession,
    settings: Settings,
    conversation: Conversation,
    number: str,
    agent: AgentConfig | None = None,
) -> CallRequest:
    if agent is None:
        agent_version = await session.get_one(AgentVersion, conversation.agent_version_id)
        agent = AgentConfig.model_validate(agent_version.config)
    persona_version = await session.get_one(PersonaVersion, conversation.persona_version_id)
    scenario_version = await session.get_one(ScenarioVersion, conversation.scenario_version_id)
    return CallRequest(
        conversation_id=conversation.id,
        agent=agent,
        instructions=conversation.instructions,
        nudge=conversation.nudge,
        caller_language=conversation.language,
        voice=PersonaConfig.model_validate(persona_version.config).voice,
        caller_number=number,
        max_duration_s=conversation.max_duration_s,
        agent_data=ScenarioConfig.model_validate(scenario_version.config).agent_data,
        pickup=LANGUAGES[conversation.language].pickup,
        accept_calls_until=conversation.dial_deadline_at,
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


async def accept_incoming_call(
    session: AsyncSession, worker_id: str, call: IncomingCall
) -> Admission | str:
    """Accept a call on a leased number for the outbound conversation waiting on it, or say
    why not. The conversation row stays locked from check to write, so cancellation, the
    reaper and a second call cannot interleave. Plivo retries its answer webhook, so the
    same CallUUID is accepted again even after the dial window closed."""
    conversation = await session.scalar(
        select(Conversation)
        .join(PhoneNumber, PhoneNumber.conversation_id == Conversation.id)
        .where(PhoneNumber.number == call.to_number)
        .with_for_update(of=Conversation)
    )
    if conversation is None:
        return "no conversation holds this number"
    now = (await session.execute(select(func.clock_timestamp()))).scalar_one()
    if conversation.dial_deadline_at is None:
        return "the number is on an inbound test"
    if not (
        conversation.claimed_by == worker_id
        and conversation.status is ConversationStatus.RUNNING
        and conversation.lease_expires_at is not None
        and conversation.lease_expires_at > now
    ):
        return "the conversation is not running on this worker"
    admission = Admission(
        conversation_id=conversation.id, max_duration_s=conversation.max_duration_s
    )
    if conversation.call_uuid == call.call_uuid:
        return admission
    if conversation.call_uuid is not None:
        return "the conversation already has a call"
    if now >= conversation.dial_deadline_at:
        return "the dial window has closed"
    agent_version = await session.get_one(AgentVersion, conversation.agent_version_id)
    outbound = AgentConfig.model_validate(agent_version.config).outbound
    if outbound and outbound.calling_numbers and call.from_number not in outbound.calling_numbers:
        return f"{call.from_number} is not one of the agent's calling numbers"
    conversation.call_uuid = call.call_uuid
    conversation.agent_caller_id = call.from_number
    await session.commit()
    return admission


async def reap_expired(session: AsyncSession, number_rest_s: int) -> int:
    reaped = await session.scalars(
        update(Conversation)
        .where(
            Conversation.status.in_(LIVE_STATUSES),
            Conversation.lease_expires_at <= func.now(),
        )
        .values(
            status=ConversationStatus.FAILED,
            end_reason=EndReason.LEASE_LOST,
            failure_reason=LEASE_LOST,
            ended_at=func.now(),
            claimed_by=None,
            lease_expires_at=None,
        )
        .returning(Conversation.id)
    )
    ids = list(reaped.all())
    if ids:
        await release_numbers(session, ids, number_rest_s)
    await session.commit()
    return len(ids)


def resolve_status(outcome: CallOutcome) -> ConversationStatus:
    if outcome.end_reason in FAILURE_TEXT:
        return ConversationStatus.FAILED
    if not outcome.connected:
        if outcome.end_reason is EndReason.USER_REQUEST:
            return ConversationStatus.CANCELLED
        return ConversationStatus.FAILED
    if outcome.caller_error is not None:
        return ConversationStatus.INVALID
    return ConversationStatus.COMPLETED


def failure_reason(outcome: CallOutcome) -> str | None:
    return FAILURE_TEXT.get(outcome.end_reason, outcome.caller_error)


async def finalize(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    worker_id: str,
    outcome: CallOutcome,
    transcript: Transcript,
    number_rest_s: int,
) -> bool:
    """Record the terminal state. Returns False when the row was no longer ours to finish."""
    transcript.caller_claim = outcome.caller_claim
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
            talk_ms=outcome.talk_ms,
            transcript=transcript.model_dump(mode="json"),
            recording_path=str(outcome.recording_path) if outcome.recording_path else None,
            call_uuid=outcome.call_uuid,
            claimed_by=None,
            lease_expires_at=None,
        )
        .returning(Conversation.id)
    )
    if recorded is not None:
        await release_numbers(session, [conversation_id], number_rest_s)
    await session.commit()
    return recorded is not None


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
    application_names: dict[str, str] | None = None,
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
                    "application_name": (application_names or {}).get(entry.application_id or ""),
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
        .values(conversation_id=conversation_id, leased_at=func.now())
        .returning(PhoneNumber.number)
    )
    if number is not None:
        deadline = (
            None
            if accept_calls_for_s is None
            else func.now() + timedelta(seconds=accept_calls_for_s)
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
            available_after=func.now() + timedelta(seconds=number_rest_s),
        )
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
