import statistics
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, fields
from typing import Any

from sqlalchemy import ColumnElement, Row, and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from truman.config import Settings
from truman.db.models import Agent, Conversation, Persona, Run, Scenario
from truman.domain.conversations import (
    ACTIVE_STATUSES,
    LIVE_STATUSES,
    ConversationStatus,
    EndReason,
    OutcomeGroup,
    outcome_group,
)
from truman.domain.errors import ConflictError, NotFoundError, ValidationError
from truman.domain.runs import (
    ClaimCounts,
    RunCreate,
    RunProgress,
    run_status,
    waiting_reason,
)
from truman.simulation.agents import get_agent
from truman.simulation.starts import Inputs, snapshot

REQUEST_KEY_INDEX = "uq_runs_request_key"
INPUTS = (
    *(getattr(Conversation, field.name) for field in fields(Inputs)),
    Conversation.max_duration_s,
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


def with_defaults(settings: Settings, command: RunCreate) -> RunCreate:
    """The request with the operator's defaults filled in, so a request that writes them out
    hashes the same as one that leaves them out."""
    return command.model_copy(
        update={
            "max_duration_s": command.max_duration_s or settings.default_max_duration_s,
            "max_retries": (
                min(1, settings.max_run_retries)
                if command.max_retries is None
                else command.max_retries
            ),
        }
    )


def check_limits(settings: Settings, command: RunCreate) -> None:
    if command.repeats > settings.max_run_repeats:
        raise ValidationError(f"repeats: at most {settings.max_run_repeats}")
    if (command.max_retries or 0) > settings.max_run_retries:
        raise ValidationError(f"max_retries: at most {settings.max_run_retries}")
    if (command.max_parallel or 0) > settings.max_run_conversations:
        raise ValidationError(f"max_parallel: at most {settings.max_run_conversations}")
    interval = command.start_interval_s or 0
    if interval > settings.max_run_start_interval_s:
        raise ValidationError(f"start_interval_s: at most {settings.max_run_start_interval_s}")
    count = len(command.scenario_ids) * command.repeats
    if count > settings.max_run_conversations:
        raise ValidationError(
            f"a run starts at most {settings.max_run_conversations} conversations;"
            f" {len(command.scenario_ids)} scenarios and {command.repeats} repeats make {count}"
        )


async def create_run(
    session: AsyncSession, settings: Settings, command: RunCreate, request_key: str | None
) -> Run:
    """Start a conversation for each repeat of each scenario, all of them or none, in the order
    repeat, then scenario. A repeated request with the same idempotency key returns the run it
    started, whatever changed since. The key is looked up first, and again once the agent's
    lock is held, so a request that waited for another one with its key returns that run; a
    request for another agent collides with it on the unique key instead."""
    command = with_defaults(settings, command)
    request_hash = command.request_hash() if request_key is not None else None
    earlier = await earlier_run(session, request_key, request_hash)
    if earlier is not None:
        return earlier
    check_limits(settings, command)
    agent = await get_agent(session, command.agent_id, lock=True)
    earlier = await earlier_run(session, request_key, request_hash)
    if earlier is not None:
        await session.commit()
        return earlier
    inputs = await snapshot(session, settings, agent, command.scenario_ids)
    run = Run(
        agent_id=agent.id,
        agent_version_id=inputs[0].agent_version_id,
        name=command.name,
        repeats=command.repeats,
        max_duration_s=command.max_duration_s,
        max_parallel=command.max_parallel,
        start_interval_s=command.start_interval_s,
        max_retries=command.max_retries,
        request_key=request_key,
        request_hash=request_hash,
    )
    session.add(run)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        if REQUEST_KEY_INDEX not in str(error.orig):
            raise
        earlier = await earlier_run(session, request_key, request_hash)
        assert earlier is not None
        return earlier
    await session.execute(
        insert(Conversation),
        [
            {**asdict(item), "max_duration_s": run.max_duration_s, "run_id": run.id, "repeat": n}
            for n in range(1, command.repeats + 1)
            for item in inputs
        ],
    )
    await session.commit()
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
    transaction under the run's lock, which claims and retries take first too, so neither can
    slip in between. A run with no active conversation stays as it is."""
    run = await get_run(session, run_id, lock=True)
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
    await session.commit()
    await session.refresh(run)
    return run


async def get_run(session: AsyncSession, run_id: uuid.UUID, *, lock: bool = False) -> Run:
    run = await session.get(Run, run_id, with_for_update=lock, populate_existing=lock)
    if run is None:
        raise NotFoundError("run not found")
    return run


async def locked_run(session: AsyncSession, conversation_id: uuid.UUID) -> Run | None:
    """The conversation's run, locked, or None for a single test call."""
    return await session.scalar(
        select(Run)
        .join(Conversation, Conversation.run_id == Run.id)
        .where(Conversation.id == conversation_id)
        .with_for_update(of=Run)
        .execution_options(populate_existing=True)
    )


def latest_attempt() -> ColumnElement[bool]:
    """No later attempt replaced the conversation."""
    retry = aliased(Conversation)
    return ~select(retry.id).where(retry.retry_of == Conversation.id).exists()


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
        .on_conflict_do_nothing(index_elements=["run_id", "repeat", "scenario_id", "attempt"])
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
    session: AsyncSession, *, offset: int, limit: int, agent_id: uuid.UUID | None = None
) -> tuple[list[Run], int]:
    query = select(Run)
    if agent_id is not None:
        query = query.where(Run.agent_id == agent_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(Run.created_at.desc(), Run.id.desc()).offset(offset).limit(limit)
    )
    return list(rows), total or 0


async def progress(session: AsyncSession, runs: Sequence[Run]) -> dict[uuid.UUID, RunProgress]:
    latest = latest_attempt()
    claim = Conversation.caller_claim["success"].as_boolean()
    rows = await session.execute(
        select(
            Run.id.label("run_id"),
            Run.cancelled_at,
            run_full().label("full"),
            run_waiting().label("waiting"),
            Conversation.status,
            Conversation.end_reason,
            func.count().filter(latest).label("latest"),
            func.count().filter(Conversation.attempt > 1).label("retries"),
            func.count().filter(latest, claim.is_(True)).label("reached"),
            func.count().filter(latest, claim.is_(False)).label("not_reached"),
            func.array_agg(Conversation.talk_ms)
            .filter(latest, Conversation.talk_ms.is_not(None))
            .label("talk_ms"),
            func.min(Conversation.started_at).label("started_at"),
            func.max(Conversation.ended_at).label("ended_at"),
        )
        .join(Run, Run.id == Conversation.run_id)
        .where(Run.id.in_([run.id for run in runs]))
        .group_by(Run.id, Conversation.status, Conversation.end_reason)
    )
    by_run: dict[uuid.UUID, list[Row[Any]]] = defaultdict(list)
    for row in rows:
        by_run[row.run_id].append(row)
    return {run_id: counted(run_rows) for run_id, run_rows in by_run.items()}


def counted(rows: list[Row[Any]]) -> RunProgress:
    """One run's progress from its rows grouped by status and end reason."""
    counts = dict.fromkeys(OutcomeGroup, 0)
    end_reasons: dict[EndReason, int] = {}
    talk_ms: list[int] = []
    for row in rows:
        counts[outcome_group(row.status, row.end_reason)] += row.latest
        if row.end_reason is not None and row.latest:
            end_reasons[row.end_reason] = end_reasons.get(row.end_reason, 0) + row.latest
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
        retries=sum(row.retries for row in rows),
        caller_claims=ClaimCounts(
            reached=sum(row.reached for row in rows),
            not_reached=sum(row.not_reached for row in rows),
        ),
        median_talk_ms=round(statistics.median(talk_ms)) if talk_ms else None,
        waiting_reason=waiting_reason(
            queued=counts[OutcomeGroup.WAITING] > 0, full=run.full, waiting=run.waiting
        ),
        started_at=min(started, default=None),
        ended_at=None if active else max(ended, default=None),
    )


async def scenario_ids(session: AsyncSession, run: Run) -> list[uuid.UUID]:
    """The run's scenarios in the order the conversations of each repeat start."""
    rows = await session.scalars(
        select(Conversation.scenario_id)
        .where(Conversation.run_id == run.id, Conversation.repeat == 1, Conversation.attempt == 1)
        .order_by(Conversation.created_at, Conversation.id)
    )
    return list(rows)
