"""The numbers a suite gives each of its runs a result from. Unlike the run page, they count
the calls that did not complete and the calls that a user stopped, as not scored: a run must
not pass because most of its calls never got a verdict."""

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.db.models import Conversation, Evaluation
from yaksh.domain.answering import plays_scenario
from yaksh.domain.conversations import ACTIVE_STATUSES, judges_score
from yaksh.domain.evaluations import EvaluationState, GateNumbers, Verdict
from yaksh.evaluation import numbers
from yaksh.evaluation.run_verdicts import persona_picked_up

FINISHED = frozenset({EvaluationState.DONE, EvaluationState.FAILED})


async def gate_numbers(
    session: AsyncSession, conversations: Mapping[uuid.UUID, Sequence[uuid.UUID]]
) -> dict[uuid.UUID, GateNumbers]:
    """The numbers of each run from its counted conversations, cancelled and stopped ones
    included. A call that has not ended is not counted: its run is still running."""
    run_of = {conversation: run for run, ids in conversations.items() for conversation in ids}
    rows = await session.execute(
        select(
            Conversation.id,
            Conversation.scenario_id,
            Conversation.status,
            Conversation.end_reason,
            Conversation.answered_by,
            persona_picked_up().label("picked_up"),
            Evaluation.state,
            Evaluation.effective_scenario_verdict.label("verdict"),
            Evaluation.effective_conversation_verdict.label("with_rules"),
        )
        .outerjoin(Evaluation, Evaluation.conversation_id == Conversation.id)
        .where(Conversation.id.in_(run_of.keys()))
    )
    pending: dict[uuid.UUID, int] = defaultdict(int)
    played: dict[uuid.UUID, dict[uuid.UUID, list[Verdict | None]]] = defaultdict(
        lambda: defaultdict(list)
    )
    unplayed: dict[uuid.UUID, list[Verdict | None]] = defaultdict(list)
    for row in rows:
        run = run_of[row.id]
        if row.status in ACTIVE_STATUSES:
            continue
        scored = judges_score(row.status, row.end_reason)
        if scored and row.state not in FINISHED:
            pending[run] += 1
            continue
        done = scored and row.state is EvaluationState.DONE
        if plays_scenario(row.answered_by, picked_up=bool(row.picked_up)):
            played[run][row.scenario_id].append(row.verdict if done else None)
        else:
            unplayed[run].append(row.with_rules if done else None)
    return {
        run: numbers_of(pending[run], list(played[run].values()), unplayed[run])
        for run in conversations
    }


def numbers_of(
    pending: int, played: Sequence[Sequence[Verdict | None]], unplayed: Sequence[Verdict | None]
) -> GateNumbers:
    results = [numbers.ScenarioResults(verdicts) for verdicts in played]
    verdicts = [verdict for scenario in played for verdict in scenario]
    passed = verdicts.count(Verdict.PASS)
    failed = verdicts.count(Verdict.FAIL)
    unplayed_passed = unplayed.count(Verdict.PASS)
    unplayed_failed = unplayed.count(Verdict.FAIL)
    worst_best = numbers.worst_and_best(results)
    return GateNumbers(
        pending=pending,
        passed=passed,
        failed=failed,
        not_scored=len(verdicts) - passed - failed,
        pass_rate=numbers.pass_rate(results),
        coverage=numbers.coverage(results),
        worst=worst_best[0] if worst_best else None,
        best=worst_best[1] if worst_best else None,
        unplayed_passed=unplayed_passed,
        unplayed_failed=unplayed_failed,
        unplayed_not_scored=len(unplayed) - unplayed_passed - unplayed_failed,
    )
