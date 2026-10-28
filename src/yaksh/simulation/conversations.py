import asyncio
import uuid
from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import ColumnElement, Row, String, and_, cast, false, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import defer

from yaksh.db.models import (
    Agent,
    AgentVersion,
    Conversation,
    Persona,
    PersonaVersion,
    PhoneNumber,
    RefusedCall,
    Run,
    Scenario,
    ScenarioVersion,
)
from yaksh.domain.agents import AgentConfig, Direction, Transport
from yaksh.domain.answering import AnsweredBy, Answering
from yaksh.domain.conversations import (
    ACTIVE_STATUSES,
    LIVE_STATUSES,
    Admission,
    CallerSettings,
    CallOutcome,
    CallRequest,
    ConversationStatus,
    EndReason,
    IncomingCall,
    OutcomeGroup,
    StoredAudio,
    Transcript,
    Validity,
    outcome_group,
)
from yaksh.domain.errors import NotFoundError
from yaksh.domain.files import FileStore
from yaksh.domain.personas import PersonaConfig
from yaksh.domain.scenarios import PlayedScenario, ScenarioConfig
from yaksh.domain.settings import AppSettings
from yaksh.domain.surroundings import SoundPlan
from yaksh.domain.triggers import SEND_TIMEOUT_S
from yaksh.evaluation import evaluations, results
from yaksh.simulation.answering import answering_plan
from yaksh.simulation.files import OpenedFile, open_file
from yaksh.simulation.languages import LANGUAGES
from yaksh.simulation.numbers import free_numbers, lease_number, release_numbers
from yaksh.simulation.personas import version_config
from yaksh.simulation.runs import (
    ENDED,
    get_run,
    latest_attempt,
    locked_run,
    retry,
    run_full,
    run_waiting,
)
from yaksh.simulation.surroundings import with_full_paths

LEASE_LOST = "worker lost its lease on the conversation; outcome unknown"
WORKER_STOPPED = "worker stopped during the call; outcome unknown"
FAILURE_TEXT = {EndReason.WORKER_STOPPED: WORKER_STOPPED, EndReason.LEASE_LOST: LEASE_LOST}


class PoolExhaustedError(Exception):
    """Every pool number is on a call; the conversation goes back to the queue."""


SORT_KEYS = {
    "created_at": Conversation.created_at,
    "talk_ms": Conversation.talk_ms,
    "response_p90_ms": results.response_p90(),
}
"""Values a conversation list sorts on; `-` before a key sorts descending. Calls with no talk
time or no response times sort last either way."""


async def get_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise NotFoundError("conversation not found")
    return conversation


async def open_recording(
    session: AsyncSession, store: FileStore, conversation_id: uuid.UUID
) -> OpenedFile:
    conversation = await get_conversation(session, conversation_id)
    if conversation.recording_key is None:
        raise NotFoundError("no recording yet")
    return await open_file(store, conversation.recording_key)


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
    groups: Sequence[OutcomeGroup] = (),
    latest_attempts: bool = False,
    answered_by: AnsweredBy | None = None,
    search: str | None = None,
    sort: str = "-created_at",
) -> tuple[list[Conversation], int]:
    """groups keeps the conversations in any of them; empty keeps all."""
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
    if groups:
        query = query.where(or_(*(in_group(group) for group in groups)))
    if latest_attempts:
        query = query.where(latest_attempt())
    if answered_by is not None:
        query = query.where(Conversation.answered_by == answered_by)
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
) -> dict[uuid.UUID, tuple[int, str, int]]:
    """The version number of each scenario version, the scenario's current name and how many
    data sets the version holds, by version id."""
    rows = await session.execute(
        select(
            ScenarioVersion.id,
            ScenarioVersion.version,
            Scenario.name,
            func.jsonb_array_length(ScenarioVersion.config["data_sets"]).label("data_sets"),
        )
        .join(Scenario, Scenario.id == ScenarioVersion.scenario_id)
        .where(ScenarioVersion.id.in_(set(version_ids)))
    )
    return {row.id: (row.version, row.name, row.data_sets) for row in rows}


async def played_scenario(session: AsyncSession, conversation: Conversation) -> PlayedScenario:
    """The pinned scenario version as the conversation's data set plays it."""
    version = await session.get_one(ScenarioVersion, conversation.scenario_version_id)
    return ScenarioConfig.model_validate(version.config).played(conversation.data_set_id)


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


async def persona_answering(session: AsyncSession, conversation: Conversation) -> Answering:
    """The voicemail and call screener of the pinned persona version."""
    version = await session.get_one(PersonaVersion, conversation.persona_version_id)
    return PersonaConfig.model_validate(version.config).answering


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


def runnable_now(
    pool_app_id: str | None, receiving_app_id: str | None, transports: frozenset[Transport]
) -> ColumnElement[bool]:
    """A queued conversation of one of `transports` that can start now: a text one always can;
    a phone one that needs a number waits while no test number of pool_app_id is free, and
    outbound phone conversations run only on a worker that receives calls for
    receiving_app_id."""
    text = Conversation.transport == Transport.TEXT
    has_number = Conversation.caller_number.is_not(None)
    inbound = and_(
        Conversation.transport == Transport.PHONE,
        Conversation.direction == Direction.INBOUND,
        has_number
        if pool_app_id is None
        else or_(has_number, select(PhoneNumber).where(free_numbers(pool_app_id)).exists()),
    )
    phone = inbound
    if receiving_app_id is not None:
        outbound = and_(
            Conversation.transport == Transport.PHONE,
            Conversation.direction == Direction.OUTBOUND,
            select(PhoneNumber).where(free_numbers(receiving_app_id, rested=True)).exists(),
        )
        phone = or_(inbound, outbound)
    allowed = {Transport.TEXT: text, Transport.PHONE: phone}
    return or_(false(), *(allowed[transport] for transport in transports))


def claim_values(worker_id: str, lease_s: float) -> dict[str, Any]:
    return {
        "status": ConversationStatus.RUNNING,
        "started_at": func.statement_timestamp(),
        "claimed_by": worker_id,
        "lease_expires_at": func.statement_timestamp() + timedelta(seconds=lease_s),
    }


async def claim_next(
    session: AsyncSession,
    worker_id: str,
    lease_s: float,
    pool_app_id: str | None,
    receiving_app_id: str | None,
    transports: frozenset[Transport],
) -> Conversation | None:
    """Claim the oldest queued conversation of one of `transports` that can run now, in the
    order the runs were created. The claim holds the run's lock, so no two workers pass a run's
    max parallel or its start interval. The candidate is picked without a lock; when the claim
    finds it taken, or its run no longer ready, the next candidate is tried."""
    ready = and_(
        Conversation.status == ConversationStatus.QUEUED,
        runnable_now(pool_app_id, receiving_app_id, transports),
        ~run_full(),
        ~run_waiting(),
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
    app: AppSettings,
    conversation: Conversation,
    pool_app_id: str | None,
    receiving_app_id: str | None,
) -> CallRequest:
    """Lease the conversation's Yaksh number when it has none yet (the caller ID of an inbound
    test, or the number an outbound agent must call) and build the call from the pinned
    versions. A text agent needs no number."""
    agent_version = await session.get_one(AgentVersion, conversation.agent_version_id)
    agent = AgentConfig.model_validate(agent_version.config)
    if conversation.transport is Transport.TEXT:
        return await call_request(session, app, conversation, None, agent)
    number = conversation.caller_number
    if number is None and agent.outbound is not None:
        assert receiving_app_id is not None
        number = await lease_number(
            session,
            conversation.id,
            receiving_app_id,
            accept_calls_for_s=SEND_TIMEOUT_S + agent.outbound.dial_window_s,
        )
    elif number is None and pool_app_id is not None:
        number = await lease_number(session, conversation.id, pool_app_id)
    if number is None:
        raise PoolExhaustedError("no pool number is free")
    leased = await session.get_one(Conversation, conversation.id, populate_existing=True)
    return await call_request(session, app, leased, number, agent)


async def call_request(
    session: AsyncSession,
    app: AppSettings,
    conversation: Conversation,
    number: str | None,
    agent: AgentConfig,
) -> CallRequest:
    persona_version = await session.get_one(PersonaVersion, conversation.persona_version_id)
    persona = await version_config(session, persona_version)
    scenario = await played_scenario(session, conversation)
    return CallRequest(
        conversation_id=conversation.id,
        agent=agent,
        transport=conversation.transport,
        instructions=conversation.instructions,
        first_words=scenario.first_words or LANGUAGES[conversation.language].first_words,
        nudge=conversation.nudge,
        caller_language=conversation.language,
        voice=persona.voice,
        sound_plan=with_full_paths(SoundPlan.model_validate(conversation.sound_plan)),
        caller_number=number,
        max_duration_s=conversation.max_duration_s,
        max_turns=conversation.max_turns,
        goodbye=LANGUAGES[conversation.language].goodbye,
        agent_data=scenario.agent_data,
        accept_calls_until=conversation.dial_deadline_at,
        app_settings=app,
        caller=scenario.caller or app.caller,
        scenario_model=scenario.caller is not None,
        answered_by=conversation.answered_by,
        answering=answering_plan(conversation.answered_by, persona.answering),
    )


async def renew_lease(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    worker_id: str,
    lease_s: float,
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
        return await refuse(session, call, "no conversation holds this number")
    now = (await session.execute(select(func.clock_timestamp()))).scalar_one()
    if conversation.dial_deadline_at is None:
        return await refuse(session, call, "the number is on an inbound test", conversation.id)
    if not (
        conversation.claimed_by == worker_id
        and conversation.status is ConversationStatus.RUNNING
        and conversation.lease_expires_at is not None
        and conversation.lease_expires_at > now
    ):
        return await refuse(
            session, call, "the conversation is not running on this worker", conversation.id
        )
    admission = Admission(
        conversation_id=conversation.id, max_duration_s=conversation.max_duration_s
    )
    if conversation.call_uuid == call.call_uuid:
        return admission
    if conversation.call_uuid is not None:
        return await refuse(session, call, "the conversation already has a call", conversation.id)
    if now >= conversation.dial_deadline_at:
        return await refuse(session, call, "the dial window has closed", conversation.id)
    agent_version = await session.get_one(AgentVersion, conversation.agent_version_id)
    outbound = AgentConfig.model_validate(agent_version.config).outbound
    if outbound and outbound.calling_numbers and call.from_number not in outbound.calling_numbers:
        reason = f"{call.from_number} is not one of the agent's calling numbers"
        return await refuse(session, call, reason, conversation.id)
    conversation.call_uuid = call.call_uuid
    conversation.agent_caller_id = call.from_number
    await session.commit()
    return admission


async def refuse(
    session: AsyncSession,
    call: IncomingCall,
    reason: str,
    conversation_id: uuid.UUID | None = None,
) -> str:
    """Record that Yaksh turned the call away, once per call, since Plivo retries its answer
    webhook, and give the reason. The record is committed before the refusal is answered."""
    await session.execute(
        insert(RefusedCall)
        .values(
            call_uuid=call.call_uuid,
            to_number=call.to_number,
            from_number=call.from_number,
            reason=reason,
            conversation_id=conversation_id,
        )
        .on_conflict_do_nothing(index_elements=["call_uuid"])
    )
    await session.commit()
    return reason


def expired() -> ColumnElement[bool]:
    return and_(
        Conversation.status.in_(LIVE_STATUSES),
        Conversation.lease_expires_at <= func.statement_timestamp(),
    )


async def reap_expired(session: AsyncSession, number_rest_s: int) -> int:
    """Fail the live conversations whose worker lost its lease: each run's in its own
    transaction, under the run's lock, with its retries."""
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
    reaped = 0
    for run_id in run_ids:
        run = await get_run(session, run_id, lock=True)
        ended = await end_expired(session, run_id, number_rest_s)
        await retry(session, run, ended)
        await session.commit()
        reaped += len(ended)
    return reaped


async def end_expired(
    session: AsyncSession, run_id: uuid.UUID, number_rest_s: int
) -> list[Row[Any]]:
    ended = list(
        await session.execute(
            update(Conversation)
            .where(expired(), Conversation.run_id == run_id)
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
        await evaluations.enqueue(session, [row.id for row in ended])
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


def dump(value: BaseModel | None) -> dict[str, Any] | None:
    return None if value is None else value.model_dump(mode="json")


def stored_caller_settings(settings: CallerSettings | None) -> dict[str, Any] | None:
    """The voice's model is kept as `tts_model`, never in the voice: an older process refuses
    a voice with a field that it does not know."""
    if settings is None:
        return None
    return settings.model_dump(mode="json", exclude={"voice": {"model"}})


def failure_reason(outcome: CallOutcome) -> str | None:
    return FAILURE_TEXT.get(outcome.end_reason, outcome.caller_error)


async def finalize(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    worker_id: str,
    outcome: CallOutcome,
    transcript: Transcript,
    audio: StoredAudio,
    number_rest_s: int,
) -> bool:
    """Record the terminal state; a conversation in the error group is queued again, up to its
    run's retries. A call that was not cancelled is queued for evaluation in the same
    transaction, so it is evaluated exactly when it is saved. Returns False when the row was no
    longer ours to finish."""
    transcript.stream_opened_ms = outcome.stream_opened_ms
    transcript.loop_lag = outcome.loop_lag
    transcript.recording_start_ms = outcome.recording_start_ms
    transcript.agent_media = outcome.agent_media
    transcript.caller_replies = outcome.caller_replies
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
                caller_settings=stored_caller_settings(outcome.caller_settings),
                caller_usage=dump(outcome.caller_usage),
                caller_reply_times=None
                if outcome.caller_reply_times is None
                else [reply.model_dump(mode="json") for reply in outcome.caller_reply_times],
                line_facts=dump(outcome.line_facts),
                recording_key=audio.recording_key,
                caller_voice_key=audio.caller_voice_key,
                call_uuid=outcome.call_uuid,
                agent_caller_id=Conversation.agent_caller_id if outcome.call_uuid else None,
                trigger_response=outcome.trigger_response,
                clock_started_at=outcome.clock_started_at,
                claimed_by=None,
                lease_expires_at=None,
            )
            .returning(*ENDED)
        )
    ).one_or_none()
    if ended is not None:
        await release_numbers(session, [conversation_id], number_rest_s)
        await retry(session, run, [ended])
        if ended.status is not ConversationStatus.CANCELLED:
            await evaluations.enqueue(session, [conversation_id])
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
