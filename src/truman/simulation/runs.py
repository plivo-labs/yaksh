import statistics
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Row, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from truman.config import Settings
from truman.db.models import Conversation, Run
from truman.domain.conversations import ACTIVE_STATUSES, EndReason, OutcomeGroup, outcome_group
from truman.domain.errors import ConflictError, NotFoundError, ValidationError
from truman.domain.runs import RunCreate, RunStatus, run_status
from truman.simulation.agents import get_agent
from truman.simulation.conversations import retried, snapshot

REQUEST_KEY_INDEX = "uq_runs_request_key"


@dataclass(frozen=True)
class Claims:
    """What the callers said when they hung up: claims, not verdicts."""

    reached: int
    not_reached: int


@dataclass(frozen=True)
class Progress:
    """What a run's conversations say about it, read in one statement each time the run is
    read. The counts, end reasons, claims and talk time take only the latest attempt of each
    repeat of each scenario."""

    status: RunStatus
    cancelled_at: datetime | None
    counts: dict[OutcomeGroup, int]
    end_reasons: dict[EndReason, int]
    retried: int
    """How many of the run's conversations are retries."""
    caller_claims: Claims
    median_talk_ms: int | None
    started_at: datetime | None
    ended_at: datetime | None


def check_limits(settings: Settings, command: RunCreate) -> None:
    if command.repeats > settings.max_run_repeats:
        raise ValidationError(f"repeats: at most {settings.max_run_repeats}")
    if command.retries > settings.max_run_retries:
        raise ValidationError(f"retries: at most {settings.max_run_retries}")
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
    taken = await snapshot(session, settings, agent, command.scenario_ids)
    run = Run(
        agent_id=agent.id,
        agent_version_id=taken.agent_version_id,
        name=command.name,
        repeats=command.repeats,
        max_duration_s=command.max_duration_s or settings.default_max_duration_s,
        max_parallel=command.max_parallel,
        start_interval_s=command.start_interval_s,
        retries=command.retries,
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
    session.add_all(
        taken.conversation(pins, run.max_duration_s, run_id=run.id, repeat=repeat)
        for repeat in range(1, command.repeats + 1)
        for pins in taken.pins
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


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise NotFoundError("run not found")
    return run


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


async def progress(session: AsyncSession, runs: Sequence[Run]) -> dict[uuid.UUID, Progress]:
    latest = ~retried()
    claim = Conversation.transcript["caller_claim"]["success"].as_boolean()
    rows = await session.execute(
        select(
            Conversation.run_id,
            Run.cancelled_at,
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
        .group_by(
            Conversation.run_id, Run.cancelled_at, Conversation.status, Conversation.end_reason
        )
    )
    by_run: dict[uuid.UUID, list[Row[Any]]] = defaultdict(list)
    for row in rows:
        by_run[row.run_id].append(row)
    return {run_id: counted(run_rows) for run_id, run_rows in by_run.items()}


def counted(rows: list[Row[Any]]) -> Progress:
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
    cancelled_at = rows[0].cancelled_at
    return Progress(
        status=run_status(cancelled=cancelled_at is not None, active=active, started=bool(started)),
        cancelled_at=cancelled_at,
        counts=counts,
        end_reasons=end_reasons,
        retried=sum(row.retries for row in rows),
        caller_claims=Claims(
            reached=sum(row.reached for row in rows),
            not_reached=sum(row.not_reached for row in rows),
        ),
        median_talk_ms=round(statistics.median(talk_ms)) if talk_ms else None,
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
