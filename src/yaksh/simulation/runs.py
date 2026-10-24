import asyncio
import statistics
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Row, and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from yaksh.config import Settings
from yaksh.db.models import (
    Agent,
    Conversation,
    Persona,
    Run,
    Scenario,
    ScenarioVersion,
    SuiteRun,
)
from yaksh.domain.agents import Transport
from yaksh.domain.answering import AnsweredBy
from yaksh.domain.conversations import (
    ACTIVE_STATUSES,
    LIVE_STATUSES,
    ConversationStatus,
    EndReason,
    OutcomeGroup,
    outcome_group,
)
from yaksh.domain.errors import ConflictError, NotFoundError, ValidationError
from yaksh.domain.languages import Language
from yaksh.domain.runs import (
    RunCreate,
    RunNames,
    RunProgress,
    RunScenario,
    RunStatus,
    run_status,
    waiting_reason,
)
from yaksh.domain.scenarios import ScenarioConfig
from yaksh.domain.settings import AppSettings, CallerModel, Limits
from yaksh.domain.surroundings import SoundPlan, Surroundings
from yaksh.simulation.agents import get_agent
from yaksh.simulation.starts import Inputs, snapshot
from yaksh.simulation.surroundings import sound_plan

REQUEST_KEY_INDEX = "uq_runs_request_key"
INPUTS = (
    *(getattr(Conversation, field.name) for field in fields(Inputs)),
    Conversation.max_duration_s,
    Conversation.max_turns,
    Conversation.sound_plan,
    Conversation.run_id,
    Conversation.repeat,
)
"""The columns a retry copies from the attempt it replaces."""
ENDED = (
    Conversation.id,
    Conversation.status,
    Conversation.end_reason,
    Conversation.attempt,
    Conversation.agent_id,
    Conversation.scenario_id,
    Conversation.persona_id,
)
"""What the retry step reads from a conversation that just ended."""


def with_defaults(limits: Limits, command: RunCreate) -> RunCreate:
    """The request with the operator's defaults in place of the fields it leaves out."""
    return command.model_copy(
        update={
            "max_duration_s": command.max_duration_s or limits.default_max_duration_s,
            "max_turns": command.max_turns or limits.default_max_turns,
            "max_retries": (
                limits.default_max_retries if command.max_retries is None else command.max_retries
            ),
        }
    )


def check_limits(limits: Limits, command: RunCreate) -> None:
    if command.repeats > limits.max_run_repeats:
        raise ValidationError(f"repeats: at most {limits.max_run_repeats}")
    if (command.max_retries or 0) > limits.max_run_retries:
        raise ValidationError(f"max_retries: at most {limits.max_run_retries}")
    if (command.max_parallel or 0) > limits.max_run_conversations:
        raise ValidationError(f"max_parallel: at most {limits.max_run_conversations}")
    interval = command.start_interval_s or 0
    if interval > limits.max_run_start_interval_s:
        raise ValidationError(f"start_interval_s: at most {limits.max_run_start_interval_s}")


CallerCheck = Callable[[CallerModel], Awaitable[str | None]]
"""Asks the LLM provider to serve a caller model; returns why it refused, or None."""
CALLER_CHECKS_AT_ONCE = 4


@dataclass(frozen=True)
class RefusedCaller:
    """A caller model that the provider refused, and the pinned scenario versions that choose
    it, with their scenarios' names."""

    chosen_by: dict[uuid.UUID, str]
    reason: str

    def message(self, versions: Iterable[uuid.UUID] | None = None) -> str:
        """Names the scenarios among these versions, or all of them."""
        wanted = set(self.chosen_by if versions is None else versions)
        names = [name for version, name in self.chosen_by.items() if version in wanted]
        quoted = ", ".join(f'"{name}"' for name in names)
        return f"{quoted}: the LLM provider refused its caller model: {self.reason}"


async def unserved_callers(
    session: AsyncSession, check: CallerCheck, inputs: Sequence[Inputs]
) -> list[RefusedCaller]:
    """Asks the provider once for each caller model that a pinned scenario version chooses."""
    chosen: dict[CallerModel, dict[uuid.UUID, str]] = defaultdict(dict)
    rows = await session.execute(
        select(ScenarioVersion.id, Scenario.name, ScenarioVersion.config)
        .join(Scenario, Scenario.id == ScenarioVersion.scenario_id)
        .where(ScenarioVersion.id.in_({item.scenario_version_id for item in inputs}))
        .order_by(Scenario.name)
    )
    for version_id, name, config in rows.tuples():
        caller = ScenarioConfig.model_validate(config).caller
        if caller is not None:
            chosen[caller][version_id] = name
    slots = asyncio.Semaphore(CALLER_CHECKS_AT_ONCE)

    async def bounded(caller: CallerModel) -> str | None:
        async with slots:
            return await check(caller)

    reasons = await asyncio.gather(*(bounded(caller) for caller in chosen))
    return [
        RefusedCaller(chosen_by, reason)
        for chosen_by, reason in zip(chosen.values(), reasons, strict=True)
        if reason is not None
    ]


async def refuse_unserved_callers(
    session: AsyncSession, check: CallerCheck, inputs: Sequence[Inputs]
) -> None:
    """Refuses the run when the provider refuses a caller model that a pinned scenario version
    chooses, naming those scenarios."""
    refused = await unserved_callers(session, check, inputs)
    if refused:
        raise ValidationError("; ".join(caller.message() for caller in refused))


@dataclass(frozen=True)
class PreparedRun:
    """A run that passed its checks, with the request's defaults filled in and what each of its
    conversations pins; nothing is saved yet."""

    command: RunCreate
    inputs: list[Inputs]

    @property
    def count(self) -> int:
        return len(self.inputs) * self.command.repeats


async def prepare_run(
    session: AsyncSession, settings: Settings, app: AppSettings, agent: Agent, command: RunCreate
) -> PreparedRun:
    """The checks of a run and the snapshot of its conversations. The caller holds the agent's
    lock."""
    command = with_defaults(app.limits, command)
    check_limits(app.limits, command)
    inputs = await snapshot(session, settings, app, agent, command.scenarios, command.transport)
    prepared = PreparedRun(command, inputs)
    if prepared.count > app.limits.max_run_conversations:
        raise ValidationError(
            f"a run starts at most {app.limits.max_run_conversations} conversations;"
            f" {len(inputs)} different calls and {command.repeats} repeats make {prepared.count}"
        )
    return prepared


async def create_run(
    session: AsyncSession,
    settings: Settings,
    app: AppSettings,
    command: RunCreate,
    request_key: str | None,
    check_caller: CallerCheck | None = None,
) -> Run:
    """Start a conversation for each repeat of each scenario, persona, data set and answer, all
    of them or none, in the order repeat, then scenario, then persona, then data set, then answer.
    A call that a machine answers plays no surroundings: a recording has none behind it. A repeated
    request with the same idempotency key returns the run it started, whatever changed since.
    The key is looked up first, and again once the agent's lock is held, so a request that
    waited for another one with its key returns that run; a request for another agent collides
    with it on the unique key instead."""
    request_hash = command.request_hash() if request_key is not None else None
    earlier = await earlier_run(session, request_key, request_hash)
    if earlier is not None:
        return earlier
    agent = await get_agent(session, command.agent_id, lock=True)
    earlier = await earlier_run(session, request_key, request_hash)
    if earlier is not None:
        await session.commit()
        return earlier
    prepared = await prepare_run(session, settings, app, agent, command)
    if check_caller is not None:
        await refuse_unserved_callers(session, check_caller, prepared.inputs)
    try:
        run = await add_run(session, prepared, request_key=request_key, request_hash=request_hash)
    except IntegrityError as error:
        await session.rollback()
        if REQUEST_KEY_INDEX not in str(error.orig):
            raise
        earlier = await earlier_run(session, request_key, request_hash)
        assert earlier is not None
        return earlier
    await session.commit()
    return run


async def add_run(
    session: AsyncSession,
    prepared: PreparedRun,
    *,
    request_key: str | None = None,
    request_hash: str | None = None,
    suite_run_id: uuid.UUID | None = None,
    suite_position: int | None = None,
) -> Run:
    """Insert a prepared run and its conversations, without a commit."""
    command, inputs = prepared.command, prepared.inputs
    run = Run(
        agent_id=command.agent_id,
        agent_version_id=inputs[0].agent_version_id,
        transport=inputs[0].transport,
        name=command.name,
        repeats=command.repeats,
        max_duration_s=command.max_duration_s,
        max_turns=command.max_turns,
        max_parallel=command.max_parallel,
        start_interval_s=command.start_interval_s,
        max_retries=command.max_retries,
        request_key=request_key,
        request_hash=request_hash,
        suite_run_id=suite_run_id,
        suite_position=suite_position,
    )
    session.add(run)
    await session.flush()
    await session.execute(
        insert(Conversation),
        [
            {
                **asdict(item),
                "max_duration_s": run.max_duration_s,
                "max_turns": run.max_turns,
                "sound_plan": (
                    sound_plan(
                        Surroundings.model_validate(item.surroundings),
                        item.language,
                        key=f"{item.scenario_version_id}/{item.persona_version_id}/{n}",
                        duration_s=run.max_duration_s,
                    )
                    if item.answered_by is AnsweredBy.CALLER
                    else SoundPlan()
                ).model_dump(mode="json"),
                "run_id": run.id,
                "repeat": n,
            }
            for n in range(1, command.repeats + 1)
            for item in inputs
        ],
    )
    return run


async def earlier_run(
    session: AsyncSession, request_key: str | None, request_hash: str | None
) -> Run | None:
    """The run an earlier request with this idempotency key started, if any."""
    if request_key is None:
        return None
    run = await session.scalar(select(Run).where(Run.request_key == request_key))
    if run is not None and run.request_hash != request_hash:
        raise ConflictError("the Idempotency-Key was already used for another request")
    return run


async def cancel_run(session: AsyncSession, run_id: uuid.UUID) -> Run:
    """Cancel the run's queued conversations and ask the workers to end its live calls, in one
    transaction under the run's lock. A run with no active conversation stays as it is."""
    run = await get_run(session, run_id, lock=True)
    await cancel_conversations(session, run)
    await session.commit()
    await session.refresh(run)
    return run


async def cancel_conversations(session: AsyncSession, run: Run) -> bool:
    """The steps of `cancel_run`, without a commit; True when the run had an active
    conversation. The caller holds the run's lock."""
    of_run = Conversation.run_id == run.id
    active = await session.scalar(
        select(Conversation.id).where(of_run, Conversation.status.in_(ACTIVE_STATUSES)).limit(1)
    )
    if active is not None:
        if run.cancelled_at is None:
            run.cancelled_at = func.statement_timestamp()
        # Live calls first: a worker hands a running conversation back to the queue without
        # the run's lock, and the second update then cancels it.
        await session.execute(
            update(Conversation)
            .where(of_run, Conversation.status == ConversationStatus.RUNNING)
            .values(status=ConversationStatus.ENDING)
        )
        await session.execute(
            update(Conversation)
            .where(of_run, Conversation.status == ConversationStatus.QUEUED)
            .values(
                status=ConversationStatus.CANCELLED,
                end_reason=EndReason.USER_REQUEST,
                ended_at=func.statement_timestamp(),
            )
        )
    return active is not None


async def get_run(session: AsyncSession, run_id: uuid.UUID, *, lock: bool = False) -> Run:
    run = await session.get(Run, run_id, with_for_update=lock, populate_existing=lock)
    if run is None:
        raise NotFoundError("run not found")
    return run


async def locked_run(session: AsyncSession, conversation_id: uuid.UUID) -> Run:
    """The conversation's run, locked."""
    return (
        await session.scalars(
            select(Run)
            .join(Conversation, Conversation.run_id == Run.id)
            .where(Conversation.id == conversation_id)
            .with_for_update(of=Run)
            .execution_options(populate_existing=True)
        )
    ).one()


def latest_attempt() -> ColumnElement[bool]:
    """No later attempt replaced the conversation."""
    retry = aliased(Conversation)
    return ~select(retry.id).where(retry.retry_of == Conversation.id).exists()


def has_status(status: RunStatus) -> ColumnElement[bool]:
    """The runs that show this status: the rule of `run_status` over the same facts that
    `counted` reads, a latest attempt still active and any attempt started."""
    active = (
        select(Conversation.id)
        .where(
            Conversation.run_id == Run.id,
            latest_attempt(),
            Conversation.status.in_(ACTIVE_STATUSES),
        )
        .exists()
    )
    started = (
        select(Conversation.id)
        .where(Conversation.run_id == Run.id, Conversation.started_at.is_not(None))
        .exists()
    )
    cancelled = Run.cancelled_at.is_not(None)
    match status:
        case RunStatus.QUEUED:
            return and_(~cancelled, active, ~started)
        case RunStatus.RUNNING:
            return and_(~cancelled, active, started)
        case RunStatus.CANCELLING:
            return and_(cancelled, active)
        case RunStatus.DONE:
            return and_(~cancelled, ~active)
        case RunStatus.CANCELLED:
            return and_(cancelled, ~active)


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


async def retry(session: AsyncSession, run: Run, ended: Sequence[Row[Any]]) -> None:
    """Queue the next attempt of each just-ended conversation of the run that is in the error
    group, up to the run's max_retries, and none once the run is cancelled. The caller holds the
    run's lock. An attempt that is already there is left alone, so this step never fails the
    transaction that ended the conversations."""
    due = [
        row
        for row in ended
        if run.cancelled_at is None
        and row.attempt <= run.max_retries
        and outcome_group(row.status, row.end_reason) is OutcomeGroup.ERROR
    ]
    if not due:
        return
    await key_share_references(session, due)
    copies = (
        select(*INPUTS, (Conversation.attempt + 1).label("attempt"), Conversation.id)
        .where(Conversation.id.in_([row.id for row in due]))
        .order_by(Conversation.id)
    )
    await session.execute(
        insert(Conversation)
        .from_select([*(column.key for column in INPUTS), "attempt", "retry_of"], copies)
        .on_conflict_do_nothing(
            index_elements=[
                "run_id",
                "repeat",
                "scenario_id",
                "persona_id",
                "data_set_id",
                "answered_by",
                "attempt",
            ]
        )
    )


async def key_share_references(session: AsyncSession, rows: Sequence[Row[Any]]) -> None:
    """Key-share the agents, scenarios and personas that retries reference, in that order and
    each set in id order, before the insert's foreign key checks take the same locks in an
    order of their own."""
    for model, ids in (
        (Agent, {row.agent_id for row in rows}),
        (Scenario, {row.scenario_id for row in rows}),
        (Persona, {row.persona_id for row in rows}),
    ):
        await session.execute(
            select(model.id)
            .where(model.id.in_(ids))
            .order_by(model.id)
            .with_for_update(read=True, key_share=True)
        )


async def list_runs(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    agent_id: uuid.UUID | None = None,
    transport: Transport | None = None,
    status: RunStatus | None = None,
    created_from: datetime | None = None,
    created_before: datetime | None = None,
    suite_id: uuid.UUID | None = None,
) -> tuple[list[Run], int]:
    query = select(Run)
    if agent_id is not None:
        query = query.where(Run.agent_id == agent_id)
    if suite_id is not None:
        query = query.where(
            Run.suite_run_id.in_(select(SuiteRun.id).where(SuiteRun.suite_id == suite_id))
        )
    if transport is not None:
        query = query.where(Run.transport == transport)
    if status is not None:
        query = query.where(has_status(status))
    if created_from is not None:
        query = query.where(Run.created_at >= created_from)
    if created_before is not None:
        query = query.where(Run.created_at < created_before)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(Run.created_at.desc(), Run.id.desc()).offset(offset).limit(limit)
    )
    return list(rows), total or 0


async def progress(session: AsyncSession, runs: Sequence[Run]) -> dict[uuid.UUID, RunProgress]:
    latest = latest_attempt()
    rows = await session.execute(
        select(
            Run.id.label("run_id"),
            Run.cancelled_at,
            run_full().label("full"),
            run_waiting().label("waiting"),
            Conversation.status,
            Conversation.end_reason,
            Conversation.answered_by,
            func.count().filter(latest).label("latest"),
            func.count().filter(Conversation.attempt > 1).label("retries"),
            func.array_agg(Conversation.talk_ms)
            .filter(latest, Conversation.talk_ms.is_not(None))
            .label("talk_ms"),
            func.min(Conversation.started_at).label("started_at"),
            func.max(Conversation.ended_at).label("ended_at"),
        )
        .join(Run, Run.id == Conversation.run_id)
        .where(Run.id.in_([run.id for run in runs]))
        .group_by(Run.id, Conversation.status, Conversation.end_reason, Conversation.answered_by)
    )
    by_run: dict[uuid.UUID, list[Row[Any]]] = defaultdict(list)
    for row in rows:
        by_run[row.run_id].append(row)
    return {run_id: counted(run_rows) for run_id, run_rows in by_run.items()}


async def caller_languages(
    session: AsyncSession, run_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[Language]]:
    """The languages each run's callers speak, in the languages' order."""
    rows = await session.execute(
        select(Conversation.run_id, Conversation.language)
        .where(Conversation.run_id.in_(run_ids))
        .distinct()
    )
    found: dict[uuid.UUID, set[Language]] = defaultdict(set)
    for run_id, language in rows.tuples():
        found[run_id].add(language)
    return {
        run_id: [language for language in Language if language in spoken]
        for run_id, spoken in found.items()
    }


def counted(rows: list[Row[Any]]) -> RunProgress:
    """One run's progress from its rows grouped by status, end reason and answer."""
    counts = dict.fromkeys(OutcomeGroup, 0)
    end_reasons: dict[EndReason, int] = {}
    answered_by: dict[AnsweredBy, int] = {}
    talk_ms: list[int] = []
    for row in rows:
        counts[outcome_group(row.status, row.end_reason)] += row.latest
        if row.end_reason is not None and row.latest:
            end_reasons[row.end_reason] = end_reasons.get(row.end_reason, 0) + row.latest
        if row.latest:
            answered_by[row.answered_by] = answered_by.get(row.answered_by, 0) + row.latest
        talk_ms += row.talk_ms or []
    active = any(row.latest and row.status in ACTIVE_STATUSES for row in rows)
    started = [row.started_at for row in rows if row.started_at is not None]
    ended = [row.ended_at for row in rows if row.ended_at is not None]
    run = rows[0]
    cancelled_at = run.cancelled_at
    return RunProgress(
        status=run_status(cancelled=cancelled_at is not None, active=active, started=bool(started)),
        cancelled_at=cancelled_at,
        counts=counts,
        end_reasons=end_reasons,
        answered_by=answered_by,
        retries=sum(row.retries for row in rows),
        median_talk_ms=round(statistics.median(talk_ms)) if talk_ms else None,
        waiting_reason=waiting_reason(
            queued=counts[OutcomeGroup.WAITING] > 0, full=run.full, waiting=run.waiting
        ),
        started_at=min(started, default=None),
        ended_at=None if active else max(ended, default=None),
    )


async def counted_conversations(
    session: AsyncSession, run_ids: Sequence[uuid.UUID], *, stopped: bool = False
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """The conversations of each run that its numbers count: the latest attempt of each
    repeat, unless it was cancelled or a user ended it. With `stopped`, those count too: a
    suite counts them as not scored."""
    query = select(Conversation.run_id, Conversation.id).where(
        Conversation.run_id.in_(run_ids), latest_attempt()
    )
    if not stopped:
        query = query.where(
            Conversation.status != ConversationStatus.CANCELLED,
            Conversation.end_reason.is_distinct_from(EndReason.USER_REQUEST),
        )
    rows = await session.execute(query)
    found: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for run_id, conversation_id in rows:
        found[run_id].append(conversation_id)
    return found


async def run_scenarios(session: AsyncSession, run: Run) -> list[RunScenario]:
    """The run's scenarios with the personas that call them, the data sets they play and who
    answers, in the order the conversations of each repeat start."""
    rows = await session.execute(
        select(
            Conversation.scenario_id,
            Conversation.persona_id,
            Conversation.data_set_id,
            Conversation.answered_by,
        )
        .where(Conversation.run_id == run.id, Conversation.repeat == 1, Conversation.attempt == 1)
        .order_by(Conversation.created_at, Conversation.id)
    )
    personas: dict[uuid.UUID, dict[uuid.UUID, None]] = {}
    data_sets: dict[uuid.UUID, dict[uuid.UUID, None]] = {}
    answers: dict[uuid.UUID, dict[AnsweredBy, None]] = {}
    for scenario_id, persona_id, data_set_id, answered_by in rows.tuples():
        personas.setdefault(scenario_id, {})[persona_id] = None
        data_sets.setdefault(scenario_id, {})[data_set_id] = None
        answers.setdefault(scenario_id, {})[answered_by] = None
    return [
        RunScenario(
            scenario_id=s,
            persona_ids=list(p),
            data_set_ids=list(data_sets[s]),
            answered_by=list(answers[s]),
        )
        for s, p in personas.items()
    ]


async def run_names(session: AsyncSession, run: Run) -> RunNames:
    rows = await session.execute(
        select(
            Conversation.scenario_id,
            Scenario.name,
            Conversation.persona_id,
            Persona.name,
            Conversation.data_set_id,
            Conversation.data_set_name,
        )
        .join(Scenario, Scenario.id == Conversation.scenario_id)
        .join(Persona, Persona.id == Conversation.persona_id)
        .where(Conversation.run_id == run.id, Conversation.repeat == 1, Conversation.attempt == 1)
        .distinct()
    )
    names = RunNames(scenarios={}, personas={}, data_sets={})
    for scenario, scenario_name, persona, persona_name, data_set, data_set_name in rows.tuples():
        names.scenarios[scenario] = scenario_name
        names.personas[persona] = persona_name
        names.data_sets.setdefault(scenario, {})[data_set] = data_set_name
    return names
