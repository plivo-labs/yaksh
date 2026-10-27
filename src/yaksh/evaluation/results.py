"""What evaluations found, read for the API. A metric value exists only once its evaluation
is done."""

import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, NamedTuple

from sqlalchemy import ColumnElement, and_, case, column, distinct, func, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.db.models import Conversation, Evaluation, EvaluationItem, MetricValue, Scenario
from yaksh.domain.conversations import OutcomeGroup, WireEventKind, outcome_group
from yaksh.domain.evaluations import (
    CategoryNumbers,
    EvaluationState,
    Metric,
    MetricKey,
    RunMetrics,
    RunNumbers,
    Share,
    SurroundingsNumbers,
)
from yaksh.domain.latency import Latency, pooled
from yaksh.domain.scenarios import Category
from yaksh.domain.surroundings import Surroundings
from yaksh.evaluation.run_verdicts import run_verdicts


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


async def evaluation(
    session: AsyncSession, conversation_id: uuid.UUID
) -> tuple[Evaluation | None, dict[str, Metric], list[EvaluationItem]]:
    """The conversation's evaluation, and once it is done, its metrics by key and its items in
    the order they were stored."""
    found = await session.scalar(
        select(Evaluation).where(Evaluation.conversation_id == conversation_id)
    )
    if found is None:
        return None, {}, []
    rows = await session.scalars(select(MetricValue).where(MetricValue.evaluation_id == found.id))
    items = await session.scalars(
        select(EvaluationItem)
        .where(EvaluationItem.evaluation_id == found.id)
        .order_by(EvaluationItem.created_at, EvaluationItem.id)
    )
    metrics = {row.metric_key: Metric(value=row.value, flags=row.flags) for row in rows}
    return found, metrics, list(items)


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


@dataclass(frozen=True)
class CallFacts:
    """What run numbers need of one conversation."""

    group: OutcomeGroup
    connected: bool
    category: Category
    surroundings: Surroundings
    state: EvaluationState | None
    flags: frozenset[str]
    turn_taking: dict[str, Any] | None
    latency: Latency | None


SUMMED = (MetricKey.TURN_TAKING, MetricKey.RESPONSE_TIME)
"""The metrics whose values run numbers read; of the others, only the flags."""


async def run_metrics(
    session: AsyncSession,
    conversation_ids: Sequence[uuid.UUID],
    scenario_order: Sequence[uuid.UUID],
    seed: int,
) -> RunMetrics:
    """The run numbers over these conversations, overall, by scenario category and by
    surroundings, and the verdict numbers of the judged ones, by scenario in the run's
    order. seed, the run's, fixes the verdicts' interval."""
    ids = set(conversation_ids)
    values = await session.execute(
        select(
            Evaluation.conversation_id,
            MetricValue.metric_key,
            MetricValue.flags,
            case((MetricValue.metric_key.in_(SUMMED), MetricValue.value)).label("value"),
        )
        .join(MetricValue, MetricValue.evaluation_id == Evaluation.id)
        .where(Evaluation.conversation_id.in_(ids))
    )
    flags: dict[uuid.UUID, set[str]] = defaultdict(set)
    summed: dict[tuple[uuid.UUID, str], dict[str, Any]] = {}
    for conversation_id, key, raised, value in values:
        flags[conversation_id].update(raised)
        if value is not None:
            summed[conversation_id, key] = value
    rows = await session.execute(
        select(
            Conversation.id,
            Conversation.status,
            Conversation.end_reason,
            Conversation.transcript["wire_events"]
            .contains([{"kind": WireEventKind.CONNECTED}])
            .label("connected"),
            Conversation.surroundings,
            Scenario.category,
            Evaluation.state,
        )
        .join(Scenario, Scenario.id == Conversation.scenario_id)
        .outerjoin(Evaluation, Evaluation.conversation_id == Conversation.id)
        .where(Conversation.id.in_(ids))
    )
    calls = []
    for row in rows:
        latency = summed.get((row.id, MetricKey.RESPONSE_TIME))
        calls.append(
            CallFacts(
                group=outcome_group(row.status, row.end_reason),
                connected=bool(row.connected),
                category=row.category,
                surroundings=Surroundings.model_validate(row.surroundings),
                state=row.state,
                flags=frozenset(flags[row.id]),
                turn_taking=summed.get((row.id, MetricKey.TURN_TAKING)),
                latency=None if latency is None else Latency.model_validate(latency),
            )
        )
    return RunMetrics(
        overall=numbers(calls),
        by_category=[
            CategoryNumbers(category=category, numbers=numbers(group))
            for category, group in grouped(calls, lambda call: call.category, list(Category).index)
        ],
        by_surroundings=[
            SurroundingsNumbers(surroundings=surroundings, numbers=numbers(group))
            for surroundings, group in grouped(
                calls, lambda call: call.surroundings, surroundings_order
            )
        ],
        verdicts=await run_verdicts(session, conversation_ids, scenario_order, seed),
    )


def grouped[K](
    calls: Sequence[CallFacts], key: Callable[[CallFacts], K], order: Callable[[K], Any]
) -> list[tuple[K, list[CallFacts]]]:
    groups: dict[K, list[CallFacts]] = defaultdict(list)
    for call in calls:
        groups[key(call)].append(call)
    return sorted(groups.items(), key=lambda item: order(item[0]))


def surroundings_order(surroundings: Surroundings) -> tuple[bool, str]:
    """A quiet room first, then the rest in a fixed order."""
    return surroundings != Surroundings(), surroundings.model_dump_json()


def numbers(calls: Sequence[CallFacts]) -> RunNumbers:
    """The run numbers of these calls. A share counts calls, as one call's replies are not
    independent of each other."""
    ended = [call for call in calls if call.group not in UNENDED]
    connected = sum(call.connected for call in ended)
    not_connected = sum(call.group is OutcomeGroup.DID_NOT_CONNECT for call in ended)
    taking = [(call.turn_taking, call.flags) for call in calls if call.turn_taking is not None]
    response = pooled([call.latency for call in calls if call.latency is not None])
    raised: dict[str, int] = defaultdict(int)
    for call in calls:
        for flag in call.flags:
            raised[flag] += 1

    def calls_with(found: Callable[[dict[str, Any], frozenset[str]], bool]) -> Share:
        return Share.of(sum(found(value, flags) for value, flags in taking), len(taking))

    return RunNumbers(
        conversations=len(calls),
        evaluated=sum(call.state is EvaluationState.DONE for call in calls),
        pending=sum(call.state in PENDING for call in calls),
        failed=sum(call.state is EvaluationState.FAILED for call in calls),
        connected=Share.of(connected, connected + not_connected),
        errors_before_connect=sum(
            call.group is OutcomeGroup.ERROR and not call.connected for call in ended
        ),
        response_p50_ms=response.p50_ms,
        response_p90_ms=response.p90_ms,
        unanswered=calls_with(lambda value, _: value["unanswered"] > 0),
        talked_over=calls_with(lambda value, _: value["talked_over"] > 0),
        long_wait=calls_with(lambda _, flags: "long_wait" in flags),
        dead_air=calls_with(lambda _, flags: "dead_air" in flags),
        flags=dict(sorted(raised.items())),
    )


UNENDED = frozenset({OutcomeGroup.WAITING, OutcomeGroup.IN_PROGRESS})
PENDING = frozenset({None, EvaluationState.QUEUED, EvaluationState.RUNNING})


REPLY_TIME_WINDOW = timedelta(days=7)


class ModelReplyTime(NamedTuple):
    """The caller's reply time with one model and effort: nearest-rank percentiles over the
    measured replies of the calls that ran with it."""

    model: str
    reasoning_effort: str | None
    calls: int
    replies: int
    p50_ms: int
    p90_ms: int
    llm_p50_ms: int
    """The LLM inference part, a reply without one counted as 0, as on a conversation page."""


async def reply_time_by_model(session: AsyncSession) -> list[ModelReplyTime]:
    """The caller's reply time by caller model and effort, over the phone calls that ran in the
    last REPLY_TIME_WINDOW, most replies first. A call counts by when it ran, not by when its
    run was made."""
    reply = (
        func.jsonb_array_elements(Conversation.caller_reply_times)
        .table_valued(column("value", JSONB), joins_implicitly=True)
        .alias("reply")
    )
    total = reply.c.value["total_ms"].as_integer()
    llm = func.coalesce(reply.c.value[("steps", "llm_inference")].as_integer(), 0)
    model = Conversation.caller_settings["llm_model"].as_string()
    effort = Conversation.caller_settings["reasoning_effort"].as_string()
    rows = await session.execute(
        select(
            model,
            effort,
            func.count(distinct(Conversation.id)),
            func.count(),
            func.percentile_disc(0.5).within_group(total),
            func.percentile_disc(0.9).within_group(total),
            func.percentile_disc(0.5).within_group(llm),
        )
        .select_from(Conversation)
        .join(reply, true())
        .where(
            Conversation.started_at >= func.now() - REPLY_TIME_WINDOW,
            Conversation.caller_reply_times.is_not(None),
            model.is_not(None),
        )
        .group_by(model, effort)
        .order_by(func.count().desc(), model, effort)
    )
    return [ModelReplyTime(*row) for row in rows]
