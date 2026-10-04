"""The evaluation queue: one evaluation per saved conversation, claimed by one evaluator at a
time under a lease, written back only by the evaluator that holds the latest claim."""

import uuid
from collections.abc import Mapping, Sequence
from datetime import timedelta

from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from truman.db.models import Evaluation, MetricValue
from truman.domain.evaluations import EvaluationState, Metric, MetricKey

MAX_ATTEMPTS = 10
"""An evaluation that fails this many times ends failed: it would fail every time."""
CODE_VERSION = "1"
"""The version of the code metrics; it changes when a metric's definition does."""


async def enqueue(session: AsyncSession, conversation_ids: Sequence[uuid.UUID]) -> None:
    """Queue the conversations' evaluations in the caller's transaction; a conversation that
    has one already keeps it."""
    if not conversation_ids:
        return
    await session.execute(
        insert(Evaluation)
        .values(
            [{"conversation_id": id, "state": EvaluationState.QUEUED} for id in conversation_ids]
        )
        .on_conflict_do_nothing(index_elements=["conversation_id"])
    )


async def claim(session: AsyncSession, evaluator_id: str, lease_s: int) -> Evaluation | None:
    """Claim the oldest evaluation that is due: queued and past its back-off, or running under
    a lease that expired, as when its evaluator stopped. An evaluation whose evaluator stopped
    during its last attempt ends failed instead: it can stop every evaluator that claims it."""
    now = func.statement_timestamp()
    abandoned = and_(Evaluation.state == EvaluationState.RUNNING, Evaluation.lease_expires_at < now)
    await session.execute(
        update(Evaluation)
        .where(abandoned, Evaluation.attempts >= MAX_ATTEMPTS)
        .values(
            state=EvaluationState.FAILED,
            failure="the evaluator stopped during its last attempt",
            claimed_by=None,
            lease_expires_at=None,
            ended_at=now,
        )
    )
    due = (
        select(Evaluation.id)
        .where(
            or_(
                and_(
                    Evaluation.state == EvaluationState.QUEUED,
                    or_(Evaluation.not_before.is_(None), Evaluation.not_before <= now),
                ),
                and_(abandoned, Evaluation.attempts < MAX_ATTEMPTS),
            )
        )
        .order_by(Evaluation.created_at, Evaluation.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    claimed = (
        await session.scalars(
            update(Evaluation)
            .where(Evaluation.id == due)
            .values(
                state=EvaluationState.RUNNING,
                claimed_by=evaluator_id,
                claim_seq=Evaluation.claim_seq + 1,
                attempts=Evaluation.attempts + 1,
                lease_expires_at=now + timedelta(seconds=lease_s),
                started_at=func.coalesce(Evaluation.started_at, now),
            )
            .returning(Evaluation)
        )
    ).one_or_none()
    await session.commit()
    return claimed


def held(evaluation_id: uuid.UUID, claim_seq: int) -> ColumnElement[bool]:
    return and_(
        Evaluation.id == evaluation_id,
        Evaluation.claim_seq == claim_seq,
        Evaluation.state == EvaluationState.RUNNING,
    )


async def renew(
    session: AsyncSession, evaluation_id: uuid.UUID, claim_seq: int, lease_s: int
) -> bool:
    """Extend the lease; False when another evaluator has claimed it since."""
    renewed = await session.scalar(
        update(Evaluation)
        .where(held(evaluation_id, claim_seq))
        .values(lease_expires_at=func.statement_timestamp() + timedelta(seconds=lease_s))
        .returning(Evaluation.id)
    )
    await session.commit()
    return renewed is not None


async def finish(
    session: AsyncSession,
    evaluation_id: uuid.UUID,
    claim_seq: int,
    metrics: Mapping[MetricKey, Metric],
) -> bool:
    """Store the metrics and end the evaluation, in one transaction; False, with nothing
    written, when another evaluator holds a later claim."""
    ended = await session.scalar(
        update(Evaluation)
        .where(held(evaluation_id, claim_seq))
        .values(
            state=EvaluationState.DONE,
            code_version=CODE_VERSION,
            ended_at=func.statement_timestamp(),
            failure=None,
        )
        .returning(Evaluation.id)
    )
    if ended is None:
        await session.rollback()
        return False
    if metrics:
        await session.execute(
            insert(MetricValue),
            [
                {"evaluation_id": evaluation_id, "metric_key": key, **metric.model_dump()}
                for key, metric in metrics.items()
            ],
        )
    await session.commit()
    return True


async def fail(
    session: AsyncSession, evaluation_id: uuid.UUID, claim_seq: int, attempts: int, failure: str
) -> None:
    """Record a failed attempt: try again after a back-off that doubles with each attempt, or,
    after MAX_ATTEMPTS, end the evaluation failed."""
    last = attempts >= MAX_ATTEMPTS
    now = func.statement_timestamp()
    await session.execute(
        update(Evaluation)
        .where(held(evaluation_id, claim_seq))
        .values(
            failure=failure,
            claimed_by=None,
            lease_expires_at=None,
            state=EvaluationState.FAILED if last else EvaluationState.QUEUED,
            not_before=None if last else now + timedelta(seconds=min(2**attempts, 300)),
            ended_at=now if last else None,
        )
    )
    await session.commit()
