"""A run's verdict numbers, read from its judged calls: the completed calls that no one
stopped, among the run's counted conversations, whose evaluation gave a verdict or failed."""

import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from yaksha.db.models import (
    Conversation,
    Evaluation,
    EvaluationItem,
    JudgeVersion,
    Persona,
    Scenario,
)
from yaksha.domain.conversations import ConversationStatus, EndReason
from yaksha.domain.evaluations import (
    CallerFidelity,
    CallVerdict,
    CriterionCounts,
    EvaluationState,
    JudgeVersionUsed,
    Outcome,
    RuleCounts,
    RunVerdicts,
    ScenarioVerdicts,
    UnsureKind,
)
from yaksha.evaluation import numbers
from yaksha.evaluation.verdicts import CRITERION, RULE

DECIDED = (CRITERION, RULE)
"""The keys of the items a verdict counts: the criteria and the agent rules."""
FINISHED = frozenset({EvaluationState.DONE, EvaluationState.FAILED})


async def run_verdicts(
    session: AsyncSession,
    conversation_ids: Sequence[uuid.UUID],
    scenario_order: Sequence[uuid.UUID],
    seed: int,
) -> RunVerdicts:
    rows = (
        await session.execute(
            select(
                Conversation.id.label("conversation_id"),
                Conversation.scenario_id,
                Conversation.persona_id,
                Conversation.repeat,
                Scenario.name,
                Scenario.category,
                Persona.name.label("persona"),
                Evaluation.id.label("evaluation_id"),
                Evaluation.state,
                Evaluation.effective_scenario_verdict.label("verdict"),
            )
            .join(Scenario, Scenario.id == Conversation.scenario_id)
            .join(Persona, Persona.id == Conversation.persona_id)
            .outerjoin(Evaluation, Evaluation.conversation_id == Conversation.id)
            .where(
                Conversation.id.in_(set(conversation_ids)),
                Conversation.status == ConversationStatus.COMPLETED,
                Conversation.end_reason.is_distinct_from(EndReason.USER_REQUEST),
            )
            .order_by(Conversation.repeat, Conversation.created_at)
        )
    ).all()
    finished = [row for row in rows if row.state in FINISHED]
    judged = [
        row for row in finished if row.state is EvaluationState.FAILED or row.verdict is not None
    ]
    items = (
        await session.execute(
            select(
                EvaluationItem.evaluation_id,
                EvaluationItem.item_key,
                EvaluationItem.subject,
                EvaluationItem.role,
                EvaluationItem.decided_by,
                EvaluationItem.machine_outcome,
                EvaluationItem.effective_outcome,
                EvaluationItem.effective_unsure_kind,
                EvaluationItem.judge_version_id,
                EvaluationItem.jev_version_id,
                EvaluationItem.answer["blame_risk"].astext.label("blame_risk"),
            ).where(EvaluationItem.evaluation_id.in_([row.evaluation_id for row in judged]))
        )
    ).all()
    position = {scenario: index for index, scenario in enumerate(scenario_order)}
    grouped: dict[uuid.UUID, list[Row[Any]]] = defaultdict(list)
    for row in sorted(judged, key=lambda row: position.get(row.scenario_id, len(position))):
        grouped[row.scenario_id].append(row)
    scenarios, results = [], []
    for calls in grouped.values():
        result = numbers.ScenarioResults([call.verdict for call in calls])
        scenarios.append(
            ScenarioVerdicts(
                scenario_id=calls[0].scenario_id,
                name=calls[0].name,
                category=calls[0].category,
                calls=[
                    CallVerdict(
                        conversation_id=call.conversation_id,
                        repeat=call.repeat,
                        persona_id=call.persona_id,
                        persona=call.persona,
                        verdict=call.verdict,
                    )
                    for call in calls
                ],
                passes=result.passes,
                scored=result.scored,
            )
        )
        results.append(result)
    worst_best = numbers.worst_and_best(results)
    interval = numbers.suite_interval(results, seed)
    # Repeats compare only when the same persona called: each scenario and persona pair is one
    # group for pass^2 and for the scenarios that both passed and failed.
    pairs: dict[tuple[uuid.UUID, uuid.UUID], list[Row[Any]]] = defaultdict(list)
    for calls in grouped.values():
        for call in calls:
            pairs[(call.scenario_id, call.persona_id)].append(call)
    pair_results = [
        numbers.ScenarioResults([call.verdict for call in calls]) for calls in pairs.values()
    ]
    pass_hat, pass_hat_scenarios = numbers.pass_hat_k(pair_results, 2)
    decided = [item for item in items if item.item_key.startswith(DECIDED)]
    return RunVerdicts(
        pending=len(rows) - len(finished),
        not_judged=len(finished) - len(judged),
        pass_rate=numbers.pass_rate(results),
        coverage=numbers.coverage(results),
        worst=worst_best[0] if worst_best else None,
        best=worst_best[1] if worst_best else None,
        interval_low=interval[0] if interval else None,
        interval_high=interval[1] if interval else None,
        pass_hat_2=pass_hat,
        pass_hat_2_scenarios=pass_hat_scenarios,
        scenarios=scenarios,
        inconsistent=list(
            dict.fromkeys(list(pairs)[index][0] for index in numbers.inconsistent(pair_results))
        ),
        criteria=criterion_counts(list(grouped), judged, items),
        rules=rule_counts(items),
        decided_by=dict(
            Counter(
                item.decided_by for item in decided if item.machine_outcome is not Outcome.ERROR
            )
        ),
        errors=sum(item.machine_outcome is Outcome.ERROR for item in decided),
        callers=caller_fidelity(judged, items),
        judge_versions=await versions_used(session, items),
    )


def outcome_name(item: Row[Any]) -> str:
    if (
        item.effective_outcome is Outcome.UNSURE
        and item.effective_unsure_kind is UnsureKind.HIDDEN_ACTION
    ):
        return "not_testable"
    return item.effective_outcome.value


def criterion_counts(
    order: Sequence[uuid.UUID], rows: Sequence[Row[Any]], items: Sequence[Row[Any]]
) -> list[CriterionCounts]:
    """Each criterion of each scenario, by its number in the pinned scenario version, in the
    scenarios' order."""
    scenario_of = {row.evaluation_id: row.scenario_id for row in rows}
    position = {scenario: index for index, scenario in enumerate(order)}
    counts: dict[tuple[uuid.UUID, int], Counter[str]] = defaultdict(Counter)
    texts: dict[tuple[uuid.UUID, int], str] = {}
    for item in items:
        if not item.item_key.startswith(CRITERION):
            continue
        key = (scenario_of[item.evaluation_id], int(item.item_key.removeprefix(CRITERION)))
        counts[key][outcome_name(item)] += 1
        texts[key] = item.subject
    found = []
    for (scenario_id, number), counted in sorted(
        counts.items(), key=lambda entry: (position[entry[0][0]], entry[0][1])
    ):
        decided = counted["pass"] + counted["fail"]
        found.append(
            CriterionCounts(
                scenario_id=scenario_id,
                number=number,
                text=texts[scenario_id, number],
                counts=dict(counted),
                rate=counted["pass"] / decided if decided else None,
            )
        )
    return found


def rule_counts(items: Sequence[Row[Any]]) -> list[RuleCounts]:
    """Each agent rule the judged calls ran, by name."""
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    named: dict[str, Row[Any]] = {}
    for item in items:
        if item.item_key.startswith(RULE):
            counts[item.item_key][outcome_name(item)] += 1
            named[item.item_key] = item
    found = [
        RuleCounts(
            key=key.removeprefix(RULE),
            name=named[key].subject,
            role=named[key].role,
            counts=dict(counted),
        )
        for key, counted in counts.items()
    ]
    return sorted(found, key=lambda rule: rule.name.casefold())


def caller_fidelity(rows: Sequence[Row[Any]], items: Sequence[Row[Any]]) -> list[CallerFidelity]:
    persona_of = {row.evaluation_id: row.persona for row in rows}
    found: dict[str, Counter[str]] = defaultdict(Counter)
    for item in items:
        if (
            item.item_key != "caller_check"
            or item.machine_outcome is Outcome.ERROR
            or item.blame_risk is None
        ):
            continue
        counted = found[persona_of[item.evaluation_id]]
        counted["calls"] += 1
        counted[item.blame_risk] += 1
    return [
        CallerFidelity(
            persona=persona,
            calls=counted["calls"],
            likely=counted["likely"],
            possible=counted["possible"],
        )
        for persona, counted in sorted(found.items())
    ]


async def versions_used(session: AsyncSession, items: Sequence[Row[Any]]) -> list[JudgeVersionUsed]:
    """The judge versions the run's items name, with how many items each judged; one run can
    mix versions, since a judge's version follows the evaluator that judged each call."""
    counts = Counter(
        version
        for item in items
        for version in (item.judge_version_id, item.jev_version_id)
        if version is not None
    )
    if not counts:
        return []
    versions = await session.scalars(
        select(JudgeVersion)
        .where(JudgeVersion.id.in_(counts))
        .order_by(JudgeVersion.judge, JudgeVersion.model)
    )
    return [
        JudgeVersionUsed(
            judge=v.judge, model=v.model, version=v.content_sha256[:12], items=counts[v.id]
        )
        for v in versions
    ]
