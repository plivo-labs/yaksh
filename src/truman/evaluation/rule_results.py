"""An agent's rules over its judged calls: the calls whose evaluation gave a verdict. Only a call
that completed and that no one stopped gets rule items, and a call evaluated with no judge model
gets phrase-rule items but no verdict, so it is left out, as on the run page.

A call counts for a rule only when the agent version it pinned judged that rule as the current
version does. A change to what a rule checks starts its results again; a change to its role does
not. The judge model reads an LLM rule's name, so a new name starts an LLM rule's results again,
and not a phrase rule's."""

import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import and_, any_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.ext.asyncio import AsyncSession

from truman.db.models import AgentVersion, Conversation, Evaluation, EvaluationItem, Scenario
from truman.domain.evaluations import Outcome, RuleFailure, RuleResults
from truman.domain.rules import AgentRule
from truman.evaluation.run_verdicts import outcome_name
from truman.evaluation.verdicts import RULE

FAILURES = 5
UNJUDGED = {"llm": {"role"}, "phrase": {"name", "role"}}
"""By rule kind, the fields that do not change how a call is judged."""
STORED_RULES = TypeAdapter(list[AgentRule])


def judged_as(rule: AgentRule) -> dict[str, Any]:
    return rule.model_dump(exclude=UNJUDGED[rule.kind])


async def rule_results(
    session: AsyncSession, agent_id: uuid.UUID, rules: Sequence[AgentRule]
) -> list[RuleResults]:
    """Each of the agent's current `rules`, in their order."""
    current = {f"{RULE}{rule.key}": judged_as(rule) for rule in rules}
    versions: dict[str, list[uuid.UUID]] = defaultdict(list)
    if current:
        for version_id, stored in await session.execute(
            select(AgentVersion.id, AgentVersion.config["rules"]).where(
                AgentVersion.agent_id == agent_id
            )
        ):
            # Parsed, not compared as stored, so that a field added later with a default matches.
            for rule in STORED_RULES.validate_python(stored or []):
                key = f"{RULE}{rule.key}"
                if current.get(key) == judged_as(rule):
                    versions[key].append(version_id)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    failures: dict[str, list[RuleFailure]] = defaultdict(list)
    if versions:
        judged = (
            select(EvaluationItem.item_key)
            .join(Evaluation, Evaluation.id == EvaluationItem.evaluation_id)
            .join(Conversation, Conversation.id == Evaluation.conversation_id)
            .where(
                Conversation.agent_id == agent_id,
                or_(
                    *(
                        and_(
                            EvaluationItem.item_key == key,
                            Conversation.agent_version_id
                            == any_(literal(ids, ARRAY(UUID(as_uuid=True)))),
                        )
                        for key, ids in versions.items()
                    )
                ),
                Evaluation.effective_scenario_verdict.is_not(None),
            )
        )
        for row in await session.execute(
            judged.add_columns(
                EvaluationItem.effective_outcome,
                EvaluationItem.effective_unsure_kind,
                func.count().label("calls"),
            ).group_by(
                EvaluationItem.item_key,
                EvaluationItem.effective_outcome,
                EvaluationItem.effective_unsure_kind,
            )
        ):
            counts[row.item_key][outcome_name(row)] += row.calls
        latest = (
            judged.add_columns(
                Conversation.id.label("conversation_id"),
                Conversation.ended_at,
                Scenario.name.label("scenario_name"),
                func.row_number()
                .over(
                    partition_by=EvaluationItem.item_key,
                    order_by=Conversation.ended_at.desc().nulls_last(),
                )
                .label("rank"),
            )
            .join(Scenario, Scenario.id == Conversation.scenario_id)
            .where(EvaluationItem.effective_outcome == Outcome.FAIL)
            .subquery()
        )
        for row in await session.execute(
            select(latest).where(latest.c.rank <= FAILURES).order_by(latest.c.rank)
        ):
            failures[row.item_key].append(
                RuleFailure(
                    conversation_id=row.conversation_id,
                    scenario_name=row.scenario_name,
                    ended_at=row.ended_at,
                )
            )
    return [
        RuleResults(
            key=rule.key,
            counts=dict(counts[f"{RULE}{rule.key}"]),
            failures=failures[f"{RULE}{rule.key}"],
        )
        for rule in rules
    ]
