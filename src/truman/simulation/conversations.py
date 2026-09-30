import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, String, and_, cast, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

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
from truman.domain.conversations import (
    ACTIVE_STATUSES,
    LIVE_STATUSES,
    Admission,
    CallerClaim,
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
from truman.domain.errors import NotFoundError, ValidationError
from truman.domain.languages import Language
from truman.domain.numbers import AccountNumber
from truman.domain.personas import PersonaConfig
from truman.domain.scenarios import ScenarioConfig, normalized
from truman.domain.triggers import SEND_TIMEOUT_S, agent_data_names
from truman.simulation.agents import config_of as agents_config_of
from truman.simulation.agents import get_agent
from truman.simulation.languages import LANGUAGES
from truman.simulation.personas import config_of
from truman.simulation.prompts import caller_instructions
from truman.simulation.scenarios import config_of as scenario_config_of
from truman.simulation.workers import receiving_problem

LEASE_LOST = "worker lost its lease on the conversation; outcome unknown, not retried"
WORKER_STOPPED = "worker stopped during the call; outcome unknown, not retried"
FAILURE_TEXT = {EndReason.WORKER_STOPPED: WORKER_STOPPED, EndReason.LEASE_LOST: LEASE_LOST}
PHONE_SETTINGS = "set PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN and TRUMAN_PUBLIC_URL"


class PoolExhaustedError(Exception):
    """Every pool number is on a call; the conversation goes back to the queue."""


class UnknownNumbersError(Exception):
    """The allowlist names numbers the Plivo account does not have."""


@dataclass(frozen=True)
class Pins:
    """What the conversations of one scenario pin, read once for all of them."""

    scenario_id: uuid.UUID
    scenario_version_id: uuid.UUID
    persona_id: uuid.UUID
    persona_version_id: uuid.UUID
    language: Language
    instructions: str
    nudge: str


@dataclass(frozen=True)
class Snapshot:
    """What new conversations of one agent pin: the agent version, and the pins of each
    scenario in the order asked."""

    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    direction: Direction
    pins: list[Pins]

    def conversation(
        self,
        pins: Pins,
        max_duration_s: int,
        *,
        run_id: uuid.UUID | None = None,
        repeat: int | None = None,
    ) -> Conversation:
        return Conversation(
            direction=self.direction,
            agent_id=self.agent_id,
            agent_version_id=self.agent_version_id,
            persona_id=pins.persona_id,
            persona_version_id=pins.persona_version_id,
            scenario_id=pins.scenario_id,
            scenario_version_id=pins.scenario_version_id,
            language=pins.language,
            instructions=pins.instructions,
            nudge=pins.nudge,
            max_duration_s=max_duration_s,
            run_id=run_id,
            repeat=repeat,
        )


async def create_conversation(
    session: AsyncSession, settings: Settings, command: ConversationCreate
) -> Conversation:
    agent = await get_agent(session, command.agent_id, lock=True)
    taken = await snapshot(session, settings, agent, [command.scenario_id], command.persona_id)
    conversation = taken.conversation(
        taken.pins[0], command.max_duration_s or settings.default_max_duration_s
    )
    session.add(conversation)
    await session.commit()
    return conversation


async def snapshot(
    session: AsyncSession,
    settings: Settings,
    agent: Agent,
    scenario_ids: Sequence[uuid.UUID],
    persona_id: uuid.UUID | None = None,
) -> Snapshot:
    """Check that conversations of the agent's scenarios can start now, and read what they pin,
    once for all of them: the current agent, scenario and persona versions, and today. Each
    scenario runs with its own persona, or with persona_id when one is given. The caller locks
    the agent first. The scenarios, then the personas are share-locked here, each set in id
    order: edits and deletes wait until the conversations are saved, while transactions that
    only reference these rows, such as duplicating an agent, do not conflict. A refusal about a
    scenario names it."""
    if not settings.phone_enabled:
        raise ValidationError(f"phone calls are off: {PHONE_SETTINGS}")
    if agent.direction is Direction.OUTBOUND:
        problem = await outbound_problem(session, settings)
        if problem is not None:
            raise ValidationError(f"outbound tests are off: {problem}")
    scenarios = await scenarios_to_start(session, agent, scenario_ids)
    chosen = [persona_id if persona_id is not None else s.persona_id for s in scenarios]
    personas = await personas_to_start(session, chosen)
    agent_version_id = (
        await session.execute(
            select(AgentVersion.id).where(
                AgentVersion.agent_id == agent.id, AgentVersion.version == agent.current_version
            )
        )
    ).scalar_one()
    scenario_versions = dict(
        (
            await session.execute(
                select(ScenarioVersion.scenario_id, ScenarioVersion.id)
                .join(Scenario, Scenario.id == ScenarioVersion.scenario_id)
                .where(
                    Scenario.id.in_(scenario_ids),
                    ScenarioVersion.version == Scenario.current_version,
                )
            )
        )
        .tuples()
        .all()
    )
    persona_versions = dict(
        (
            await session.execute(
                select(PersonaVersion.persona_id, PersonaVersion.id)
                .join(Persona, Persona.id == PersonaVersion.persona_id)
                .where(
                    Persona.id.in_(personas.keys()),
                    PersonaVersion.version == Persona.current_version,
                )
            )
        )
        .tuples()
        .all()
    )
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    outbound = agents_config_of(agent) if agent.direction is Direction.OUTBOUND else None
    pins = []
    for scenario, persona_id_of_scenario in zip(scenarios, chosen, strict=True):
        persona = personas[persona_id_of_scenario]
        config = config_of(persona)
        wants = scenario_config_of(scenario)
        if outbound is not None:
            check_agent_data(outbound, wants, scenario.name)
        pins.append(
            Pins(
                scenario_id=scenario.id,
                scenario_version_id=scenario_versions[scenario.id],
                persona_id=persona.id,
                persona_version_id=persona_versions[persona.id],
                language=config.language,
                instructions=caller_instructions(
                    config,
                    goal=wants.goal,
                    known_facts=wants.known_facts,
                    unknown_facts=wants.unknown_facts,
                    today=today,
                    direction=agent.direction,
                ),
                nudge=LANGUAGES[config.language].nudge,
            )
        )
    return Snapshot(agent.id, agent_version_id, agent.direction, pins)


async def scenarios_to_start(
    session: AsyncSession, agent: Agent, scenario_ids: Sequence[uuid.UUID]
) -> list[Scenario]:
    """The agent's live scenarios in the order asked, share-locked in id order."""
    rows = await session.scalars(
        select(Scenario)
        .where(Scenario.id.in_(scenario_ids))
        .order_by(Scenario.id)
        .with_for_update(read=True)
    )
    found = {row.id: row for row in rows}
    for scenario_id in scenario_ids:
        scenario = found.get(scenario_id)
        if scenario is None or scenario.deleted_at is not None:
            raise NotFoundError(f"scenario {scenario_id} not found")
        if scenario.agent_id != agent.id:
            raise ValidationError(f'the scenario "{scenario.name}" belongs to another agent')
    return [found[scenario_id] for scenario_id in scenario_ids]


async def personas_to_start(
    session: AsyncSession, persona_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Persona]:
    """The live personas by id, share-locked in id order."""
    rows = await session.scalars(
        select(Persona)
        .where(Persona.id.in_(persona_ids))
        .order_by(Persona.id)
        .with_for_update(read=True)
    )
    found = {row.id: row for row in rows if row.deleted_at is None}
    for persona_id in persona_ids:
        if persona_id not in found:
            raise NotFoundError(f"persona {persona_id} not found")
    return found


async def outbound_problem(session: AsyncSession, settings: Settings) -> str | None:
    """Why an outbound test could not get its call now, or None when it could."""
    if not settings.phone_enabled:
        return PHONE_SETTINGS
    app_id = settings.plivo_app_id
    if app_id is None:
        return "set TRUMAN_PLIVO_APP_ID"
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


def check_agent_data(agent: AgentConfig, scenario: ScenarioConfig, name: str | None = None) -> None:
    """Refuse a scenario that lacks agent data the trigger needs; the refusal names the
    scenario when its name is given."""
    assert agent.outbound is not None
    have = {normalized(fact.name) for fact in scenario.agent_data}
    missing = sorted(agent_data_names(agent.outbound.trigger) - have)
    if missing:
        subject = "the scenario" if name is None else f'the scenario "{name}"'
        raise ValidationError(f"{subject} has no agent data named {', '.join(missing)}")


SORT_KEYS = {"created_at": Conversation.created_at, "talk_ms": Conversation.talk_ms}
"""Columns a conversation list sorts on; `-` before a key sorts descending. Calls that never
connected have no talk time and sort last either way."""


async def get_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise NotFoundError("conversation not found")
    return conversation


def retried() -> ColumnElement[bool]:
    """A later attempt replaced the conversation."""
    retry = aliased(Conversation)
    return select(retry.id).where(retry.retry_of == Conversation.id).exists()


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
    was_retried: bool | None = None,
    search: str | None = None,
    sort: str = "-created_at",
) -> tuple[list[Conversation], int]:
    query = select(Conversation)
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
    if was_retried is not None:
        query = query.where(retried() if was_retried else ~retried())
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    key = SORT_KEYS[sort.removeprefix("-")]
    order = key.desc() if sort.startswith("-") else key.asc()
    rows = await session.scalars(
        query.order_by(order.nulls_last(), Conversation.id).offset(offset).limit(limit)
    )
    return list(rows), total or 0


async def pinned_agents(
    session: AsyncSession, pinning: Sequence[Conversation | Run]
) -> dict[uuid.UUID, tuple[int, str]]:
    """The version number each conversation or run pinned and the agent's current name, by
    version id."""
    rows = await session.execute(
        select(AgentVersion.id, AgentVersion.version, Agent.name)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(AgentVersion.id.in_({row.agent_version_id for row in pinning}))
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


def caller_claim_of(conversation: Conversation) -> CallerClaim | None:
    """The claim alone, without reading the whole transcript."""
    claim = (conversation.transcript or {}).get("caller_claim")
    return None if claim is None else CallerClaim.model_validate(claim)


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


def run_full() -> ColumnElement[bool]:
    """The run has as many calls on the line as its max parallel."""
    live = aliased(Conversation)
    on_line = (
        select(func.count())
        .where(live.run_id == Run.id, live.status.in_(LIVE_STATUSES))
        .scalar_subquery()
    )
    return and_(Run.max_parallel.is_not(None), on_line >= Run.max_parallel)


def run_waiting() -> ColumnElement[bool]:
    """A call of the run started less than its delay between calls ago."""
    recent = aliased(Conversation)
    delay = func.make_interval(0, 0, 0, 0, 0, 0, Run.start_interval_s)
    return and_(
        Run.start_interval_s.is_not(None),
        select(recent.id)
        .where(recent.run_id == Run.id, recent.started_at > func.statement_timestamp() - delay)
        .exists(),
    )


def claim_values(worker_id: str, lease_s: int) -> dict[str, Any]:
    """The statement's time, not the transaction's: a claim that waited for its run's lock
    starts the run's delay when it claims."""
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
    """Claim under the run's lock, taken before any conversation row as on every path that
    locks both, so no two workers pass a run's max parallel or its delay between calls. The
    candidate is picked without a lock; when the claim finds it taken, or its run no longer
    ready, the next candidate is tried."""
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
        await session.execute(select(Run.id).where(Run.id == candidate.run_id).with_for_update())
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


def expired() -> ColumnElement[bool]:
    return and_(
        Conversation.status.in_(LIVE_STATUSES),
        Conversation.lease_expires_at <= func.statement_timestamp(),
    )


async def reap_expired(session: AsyncSession, number_rest_s: int) -> int:
    """Fail the live conversations whose worker lost its lease: single test calls in one
    transaction, then each run's in its own, under the run's lock taken first, as on every path
    that locks a run and its conversations."""
    reaped = len(await end_expired(session, Conversation.run_id.is_(None), number_rest_s))
    await session.commit()
    run_ids = list(
        await session.scalars(
            select(Conversation.run_id)
            .where(expired(), Conversation.run_id.is_not(None))
            .distinct()
            .order_by(Conversation.run_id)
        )
    )
    await session.commit()
    for run_id in run_ids:
        await session.execute(select(Run.id).where(Run.id == run_id).with_for_update())
        reaped += len(await end_expired(session, Conversation.run_id == run_id, number_rest_s))
        await session.commit()
    return reaped


async def end_expired(
    session: AsyncSession, which: ColumnElement[bool], number_rest_s: int
) -> list[uuid.UUID]:
    ended = list(
        await session.scalars(
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
            .returning(Conversation.id)
        )
    )
    if ended:
        await release_numbers(session, ended, number_rest_s)
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
            agent_caller_id=Conversation.agent_caller_id if outcome.call_uuid else None,
            claimed_by=None,
            lease_expires_at=None,
        )
        .returning(Conversation.id)
    )
    if recorded is not None:
        await release_numbers(session, [conversation_id], number_rest_s)
    await session.commit()
    return recorded is not None


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
    call from the finished test does not reach the next one. The rest runs from this statement,
    not from the start of a transaction that may have waited for a run's lock."""
    await session.execute(
        update(PhoneNumber)
        .where(PhoneNumber.conversation_id.in_(conversation_ids))
        .values(
            conversation_id=None,
            available_after=func.statement_timestamp() + timedelta(seconds=number_rest_s),
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
