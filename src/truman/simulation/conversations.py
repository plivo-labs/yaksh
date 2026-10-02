import asyncio
import uuid
from collections.abc import AsyncIterator, Iterable
from dataclasses import asdict
from datetime import timedelta
from typing import Any

from sqlalchemy import ColumnElement, Row, String, and_, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import defer

from truman.config import Settings
from truman.db.models import (
    Agent,
    AgentVersion,
    Conversation,
    Persona,
    PersonaVersion,
    PhoneNumber,
    Run,
    Scenario,
    ScenarioVersion,
)
from truman.domain.agents import AgentConfig, Direction
from truman.domain.background_noise import BackgroundNoise
from truman.domain.conversations import (
    ACTIVE_STATUSES,
    LIVE_STATUSES,
    Admission,
    CallOutcome,
    CallRequest,
    ConversationCreate,
    ConversationStatus,
    EndReason,
    IncomingCall,
    OutcomeGroup,
    Transcript,
    Validity,
    outcome_group,
)
from truman.domain.errors import NotFoundError
from truman.domain.personas import PersonaConfig
from truman.domain.scenarios import ScenarioConfig
from truman.domain.triggers import SEND_TIMEOUT_S
from truman.simulation.agents import get_agent
from truman.simulation.background_noise import noise_mix
from truman.simulation.languages import LANGUAGES
from truman.simulation.numbers import free_numbers, lease_number, release_numbers
from truman.simulation.runs import (
    ENDED,
    get_run,
    latest_attempt,
    locked_run,
    retry,
    run_full,
    run_waiting,
)
from truman.simulation.starts import snapshot

LEASE_LOST = "worker lost its lease on the conversation; outcome unknown"
WORKER_STOPPED = "worker stopped during the call; outcome unknown"
FAILURE_TEXT = {EndReason.WORKER_STOPPED: WORKER_STOPPED, EndReason.LEASE_LOST: LEASE_LOST}
PHONE_SETTINGS = "set PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN and TRUMAN_PUBLIC_URL"


class PoolExhaustedError(Exception):
    """Every pool number is on a call; the conversation goes back to the queue."""


async def create_conversation(
    session: AsyncSession, settings: Settings, command: ConversationCreate
) -> Conversation:
    agent = await get_agent(session, command.agent_id, lock=True)
    (inputs,) = await snapshot(
        session,
        settings,
        agent,
        [command.scenario_id],
        command.persona_id,
        command.background_noise,
    )
    conversation = Conversation(
        **asdict(inputs),
        max_duration_s=command.max_duration_s or settings.default_max_duration_s,
        max_turns=command.max_turns or settings.default_max_turns,
    )
    session.add(conversation)
    await session.commit()
    return conversation


SORT_KEYS = {"created_at": Conversation.created_at, "talk_ms": Conversation.talk_ms}
"""Columns a conversation list sorts on; `-` before a key sorts descending. Calls that never
connected have no talk time and sort last either way."""


async def get_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise NotFoundError("conversation not found")
    return conversation


def in_group(group: OutcomeGroup) -> ColumnElement[bool]:
    """The conversations outcome_group puts in the group: for each status, the end reasons
    that land there, so the filter cannot drift from the domain rule."""
    clauses = []
    for status in ConversationStatus:
        reasons = [
            reason for reason in (None, *EndReason) if outcome_group(status, reason) is group
        ]
        if len(reasons) == len(EndReason) + 1:
            clauses.append(Conversation.status == status)
        elif reasons:
            named = [reason for reason in reasons if reason is not None]
            matches = [Conversation.end_reason.in_(named)] if named else []
            if None in reasons:
                matches.append(Conversation.end_reason.is_(None))
            clauses.append(and_(Conversation.status == status, or_(*matches)))
    return or_(*clauses)


async def list_conversations(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    agent_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    status: ConversationStatus | None = None,
    group: OutcomeGroup | None = None,
    latest_attempts: bool = False,
    search: str | None = None,
    sort: str = "-created_at",
) -> tuple[list[Conversation], int]:
    query = select(Conversation).options(
        defer(Conversation.transcript), defer(Conversation.instructions)
    )
    if search:
        text = search.strip()
        query = (
            query.join(Agent, Agent.id == Conversation.agent_id)
            .join(Scenario, Scenario.id == Conversation.scenario_id)
            .join(Persona, Persona.id == Conversation.persona_id)
            .where(
                or_(
                    Agent.name.icontains(text, autoescape=True),
                    Scenario.name.icontains(text, autoescape=True),
                    Persona.name.icontains(text, autoescape=True),
                    cast(Conversation.id, String).icontains(text, autoescape=True),
                )
            )
        )
    if agent_id is not None:
        query = query.where(Conversation.agent_id == agent_id)
    if run_id is not None:
        query = query.where(Conversation.run_id == run_id)
    if status is not None:
        query = query.where(Conversation.status == status)
    if group is not None:
        query = query.where(in_group(group))
    if latest_attempts:
        query = query.where(latest_attempt())
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    key = SORT_KEYS[sort.removeprefix("-")]
    order = key.desc() if sort.startswith("-") else key.asc()
    rows = await session.scalars(
        query.order_by(order.nulls_last(), Conversation.id).offset(offset).limit(limit)
    )
    return list(rows), total or 0


async def pinned_agents(
    session: AsyncSession, version_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, str]]:
    """The version number of each agent version and the agent's current name, by version id."""
    rows = await session.execute(
        select(AgentVersion.id, AgentVersion.version, Agent.name)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(AgentVersion.id.in_(set(version_ids)))
    )
    return {row.id: (row.version, row.name) for row in rows}


async def pinned_scenarios(
    session: AsyncSession, version_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, str]]:
    """The version number of each scenario version and the scenario's current name, by
    version id."""
    rows = await session.execute(
        select(ScenarioVersion.id, ScenarioVersion.version, Scenario.name)
        .join(Scenario, Scenario.id == ScenarioVersion.scenario_id)
        .where(ScenarioVersion.id.in_(set(version_ids)))
    )
    return {row.id: (row.version, row.name) for row in rows}


async def pinned_scenario_config(
    session: AsyncSession, conversation: Conversation
) -> ScenarioConfig:
    version = await session.get_one(ScenarioVersion, conversation.scenario_version_id)
    return ScenarioConfig.model_validate(version.config)


async def pinned_personas(
    session: AsyncSession, version_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, str]]:
    """The version number of each persona version and the persona's current name, by version
    id."""
    rows = await session.execute(
        select(PersonaVersion.id, PersonaVersion.version, Persona.name)
        .join(Persona, Persona.id == PersonaVersion.persona_id)
        .where(PersonaVersion.id.in_(set(version_ids)))
    )
    return {row.id: (row.version, row.name) for row in rows}


def transcript_of(conversation: Conversation) -> Transcript:
    if conversation.transcript is None:
        return Transcript()
    return Transcript.model_validate(conversation.transcript)


async def retried_as(session: AsyncSession, conversation: Conversation) -> uuid.UUID | None:
    return await session.scalar(
        select(Conversation.id).where(Conversation.retry_of == conversation.id)
    )


async def end_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    """Cancel a queued conversation or ask the worker to end a running one; the row is locked so
    a concurrent claim or requeue cannot slip between the read and the write."""
    conversation = await session.get(Conversation, conversation_id, with_for_update=True)
    if conversation is None:
        raise NotFoundError("conversation not found")
    if conversation.status is ConversationStatus.QUEUED:
        conversation.status = ConversationStatus.CANCELLED
        conversation.end_reason = EndReason.USER_REQUEST
        conversation.ended_at = func.statement_timestamp()
    elif conversation.status is ConversationStatus.RUNNING:
        conversation.status = ConversationStatus.ENDING
    await session.commit()
    await session.refresh(conversation)
    return conversation


def runnable_now(receiving_app_id: str | None) -> ColumnElement[bool]:
    """A queued conversation that can start now: one that needs a number waits while none it
    may use is free, and outbound conversations run only on a worker that receives calls for
    receiving_app_id."""
    inbound = and_(
        Conversation.direction == Direction.INBOUND,
        or_(
            Conversation.caller_number.is_not(None),
            select(PhoneNumber).where(free_numbers()).exists(),
        ),
    )
    if receiving_app_id is None:
        return inbound
    outbound = and_(
        Conversation.direction == Direction.OUTBOUND,
        select(PhoneNumber).where(free_numbers(receiving_app_id)).exists(),
    )
    return or_(inbound, outbound)


def claim_values(worker_id: str, lease_s: int) -> dict[str, Any]:
    return {
        "status": ConversationStatus.RUNNING,
        "started_at": func.statement_timestamp(),
        "claimed_by": worker_id,
        "lease_expires_at": func.statement_timestamp() + timedelta(seconds=lease_s),
    }


async def claim_next(
    session: AsyncSession, worker_id: str, lease_s: int, receiving_app_id: str | None
) -> Conversation | None:
    """Claim the oldest queued conversation that can run now: single test calls first, then
    run conversations in the order their runs were created."""
    runnable = runnable_now(receiving_app_id)
    candidate = (
        select(Conversation.id)
        .where(
            Conversation.status == ConversationStatus.QUEUED,
            Conversation.run_id.is_(None),
            runnable,
        )
        .order_by(Conversation.created_at, Conversation.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    single = (
        await session.scalars(
            update(Conversation)
            .where(Conversation.id == candidate)
            .values(claim_values(worker_id, lease_s))
            .returning(Conversation)
        )
    ).one_or_none()
    if single is not None:
        await session.commit()
        return single
    return await claim_from_runs(session, worker_id, lease_s, runnable)


async def claim_from_runs(
    session: AsyncSession, worker_id: str, lease_s: int, runnable: ColumnElement[bool]
) -> Conversation | None:
    """Claim under the run's lock, so no two workers pass a run's max parallel or its start
    interval. The candidate is picked without a lock; when the claim finds it taken, or its
    run no longer ready, the next candidate is tried."""
    ready = and_(
        Conversation.status == ConversationStatus.QUEUED, runnable, ~run_full(), ~run_waiting()
    )
    while True:
        candidate = (
            await session.execute(
                select(Conversation.id, Conversation.run_id)
                .join(Run, Run.id == Conversation.run_id)
                .where(ready)
                .order_by(Run.created_at, Run.id, Conversation.created_at, Conversation.id)
                .limit(1)
            )
        ).one_or_none()
        if candidate is None:
            await session.commit()
            return None
        await get_run(session, candidate.run_id, lock=True)
        claimed = (
            await session.scalars(
                update(Conversation)
                .where(Conversation.id == candidate.id, Run.id == Conversation.run_id, ready)
                .values(claim_values(worker_id, lease_s))
                .returning(Conversation)
            )
        ).one_or_none()
        await session.commit()
        if claimed is not None:
            return claimed


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
    agent: AgentConfig,
) -> CallRequest:
    persona_version = await session.get_one(PersonaVersion, conversation.persona_version_id)
    scenario_version = await session.get_one(ScenarioVersion, conversation.scenario_version_id)
    return CallRequest(
        conversation_id=conversation.id,
        agent=agent,
        instructions=conversation.instructions,
        nudge=conversation.nudge,
        caller_language=conversation.language,
        voice=PersonaConfig.model_validate(persona_version.config).voice,
        background_noise=noise_mix(
            BackgroundNoise(
                sound=conversation.background_noise_sound,
                level=conversation.background_noise_level,
            )
        ),
        caller_number=number,
        max_duration_s=conversation.max_duration_s,
        max_turns=conversation.max_turns,
        goodbye=LANGUAGES[conversation.language].goodbye,
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
        "lease_expires_at": func.statement_timestamp() + timedelta(seconds=lease_s),
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
        Conversation.lease_expires_at > func.statement_timestamp(),
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


def expired() -> ColumnElement[bool]:
    return and_(
        Conversation.status.in_(LIVE_STATUSES),
        Conversation.lease_expires_at <= func.statement_timestamp(),
    )


async def reap_expired(session: AsyncSession, number_rest_s: int) -> int:
    """Fail the live conversations whose worker lost its lease: single test calls in one
    transaction, then each run's in its own, under the run's lock, with its retries."""
    reaped = len(await end_expired(session, Conversation.run_id.is_(None), number_rest_s))
    await session.commit()
    run_ids = list(
        await session.scalars(
            select(Run.id)
            .join(Conversation, Conversation.run_id == Run.id)
            .where(expired())
            .distinct()
            .order_by(Run.id)
        )
    )
    await session.commit()
    for run_id in run_ids:
        run = await get_run(session, run_id, lock=True)
        ended = await end_expired(session, Conversation.run_id == run_id, number_rest_s)
        await retry(session, run, ended)
        await session.commit()
        reaped += len(ended)
    return reaped


async def end_expired(
    session: AsyncSession, which: ColumnElement[bool], number_rest_s: int
) -> list[Row[Any]]:
    ended = list(
        await session.execute(
            update(Conversation)
            .where(expired(), which)
            .values(
                status=ConversationStatus.FAILED,
                end_reason=EndReason.LEASE_LOST,
                failure_reason=LEASE_LOST,
                ended_at=func.statement_timestamp(),
                claimed_by=None,
                lease_expires_at=None,
            )
            .returning(*ENDED)
        )
    )
    if ended:
        await release_numbers(session, [row.id for row in ended], number_rest_s)
    return ended


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
    """Record the terminal state; a run conversation in the error group is queued again, up to
    its run's retries. Returns False when the row was no longer ours to finish."""
    if outcome.connected:
        transcript.validity = Validity(
            ok=outcome.caller_error is None,
            reasons=[outcome.caller_error] if outcome.caller_error else [],
        )
    run = await locked_run(session, conversation_id)
    ended = (
        await session.execute(
            update(Conversation)
            .where(owned_by(conversation_id, worker_id))
            .values(
                status=resolve_status(outcome),
                end_reason=outcome.end_reason,
                failure_reason=failure_reason(outcome),
                ended_at=func.statement_timestamp(),
                talk_ms=outcome.talk_ms,
                transcript=transcript.model_dump(mode="json"),
                caller_reason=outcome.caller_reason,
                recording_path=str(outcome.recording_path) if outcome.recording_path else None,
                call_uuid=outcome.call_uuid,
                agent_caller_id=Conversation.agent_caller_id if outcome.call_uuid else None,
                claimed_by=None,
                lease_expires_at=None,
            )
            .returning(*ENDED)
        )
    ).one_or_none()
    if ended is not None:
        await release_numbers(session, [conversation_id], number_rest_s)
        if run is not None:
            await retry(session, run, [ended])
    await session.commit()
    return ended is not None


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
