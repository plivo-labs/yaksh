"""What finished evaluations found, read for the API."""

import uuid
from collections.abc import Iterable

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from truman.db.models import Conversation, Evaluation, MetricValue
from truman.domain.evaluations import EvaluationState, MetricKey
from truman.domain.latency import Latency


def done_metric(key: MetricKey) -> tuple[ColumnElement[bool], ...]:
    """The conditions that pick a metric of a finished evaluation."""
    return (
        MetricValue.evaluation_id == Evaluation.id,
        Evaluation.state == EvaluationState.DONE,
        MetricValue.metric_key == key,
    )


async def latencies(
    session: AsyncSession, conversation_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Latency]:
    """The response times of each conversation that its evaluation measured."""
    rows = await session.execute(
        select(Evaluation.conversation_id, MetricValue.value).where(
            Evaluation.conversation_id.in_(set(conversation_ids)),
            *done_metric(MetricKey.RESPONSE_TIME),
        )
    )
    return {row.conversation_id: Latency.model_validate(row.value) for row in rows}


def response_p90() -> ColumnElement[int]:
    """A conversation's p90 response time, for sorting a list of conversations."""
    return (
        select(MetricValue.value["p90_ms"].as_integer())
        .where(Evaluation.conversation_id == Conversation.id, *done_metric(MetricKey.RESPONSE_TIME))
        .scalar_subquery()
    )
