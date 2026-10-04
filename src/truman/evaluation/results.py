"""What evaluations found, read for the API. A metric value exists only once its evaluation
is done."""

import uuid
from collections.abc import Iterable
from typing import NamedTuple

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from truman.db.models import Conversation, Evaluation, MetricValue
from truman.domain.evaluations import EvaluationState, Metric, MetricKey
from truman.domain.latency import Latency


class Evaluated(NamedTuple):
    state: EvaluationState
    latency: Latency | None
    """The response times, once the evaluation measured them."""


async def evaluated(
    session: AsyncSession, conversation_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Evaluated]:
    """The evaluation state and the response times of each conversation that has an
    evaluation."""
    rows = await session.execute(
        select(Evaluation.conversation_id, Evaluation.state, MetricValue.value)
        .outerjoin(
            MetricValue,
            and_(
                MetricValue.evaluation_id == Evaluation.id,
                MetricValue.metric_key == MetricKey.RESPONSE_TIME,
            ),
        )
        .where(Evaluation.conversation_id.in_(set(conversation_ids)))
    )
    return {
        row.conversation_id: Evaluated(
            row.state, None if row.value is None else Latency.model_validate(row.value)
        )
        for row in rows
    }


async def metrics(
    session: AsyncSession, conversation_id: uuid.UUID
) -> tuple[Evaluation | None, dict[str, Metric]]:
    """The conversation's evaluation, and its metrics by key once it is done."""
    evaluation = await session.scalar(
        select(Evaluation).where(Evaluation.conversation_id == conversation_id)
    )
    if evaluation is None:
        return None, {}
    rows = await session.scalars(
        select(MetricValue).where(MetricValue.evaluation_id == evaluation.id)
    )
    return evaluation, {row.metric_key: Metric(value=row.value, flags=row.flags) for row in rows}


def response_p90() -> ColumnElement[int]:
    """A conversation's p90 response time, for sorting a list of conversations."""
    return (
        select(MetricValue.value["p90_ms"].as_integer())
        .where(
            Evaluation.conversation_id == Conversation.id,
            MetricValue.evaluation_id == Evaluation.id,
            MetricValue.metric_key == MetricKey.RESPONSE_TIME,
        )
        .scalar_subquery()
    )
