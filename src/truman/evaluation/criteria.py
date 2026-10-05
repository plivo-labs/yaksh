"""The criterion judge and the LLM agent rule judge: one model call per item, its reasoning
before its verdict, and quotes that code checks."""

import asyncio
from collections.abc import Sequence
from typing import Any

from truman.domain.conversations import Turn
from truman.domain.evaluations import DecidedBy, ItemRole, Outcome, UnsureKind
from truman.domain.language_models import JsonModel
from truman.domain.rules import LlmRule
from truman.evaluation.evidence import with_item
from truman.evaluation.judging import Answered, Check, ItemResult, JudgeSpec, ask, prompt
from truman.evaluation.quotes import absence_problems, quote_problems
from truman.evaluation.verdicts import RULE

NULLABLE_TURNS = {
    "anyOf": [
        {"type": "null"},
        {
            "type": "object",
            "properties": {"first": {"type": "integer"}, "last": {"type": "integer"}},
            "required": ["first", "last"],
            "additionalProperties": False,
        },
    ]
}
ANSWER_PROPERTIES: dict[str, Any] = {
    "evidence": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"turn": {"type": "integer"}, "quote": {"type": "string"}},
            "required": ["turn", "quote"],
            "additionalProperties": False,
        },
    },
    "absence": {"type": "boolean"},
    "absence_turns": NULLABLE_TURNS,
    "reasoning": {"type": "string"},
    "verdict": {"type": "string", "enum": ["pass", "fail", "not_applicable", "unsure"]},
    "kind": {
        "anyOf": [{"type": "null"}, {"type": "string", "enum": [kind.value for kind in UnsureKind]}]
    },
}


def schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


CRITERION = JudgeSpec("criterion", prompt("criterion"), schema(ANSWER_PROPERTIES))
AGENT_RULE = JudgeSpec(
    "agent_rule", prompt("agent_rule"), schema({"applies": {"type": "boolean"}} | ANSWER_PROPERTIES)
)


def answer_problems(turns: Sequence[Turn]) -> Check:
    def check(answer: dict[str, Any]) -> tuple[list[str], list[str]]:
        hard = quote_problems(answer["evidence"], turns)
        if answer["verdict"] == "unsure" and answer["kind"] is None:
            hard.append("An unsure verdict needs a kind.")
        if answer["verdict"] == "fail" and not answer["evidence"] and not answer["absence"]:
            hard.append("A fail needs quotes, or an absence claim with absence_turns.")
        absent_hard, soft = absence_problems(answer, len(turns))
        return hard + absent_hard, soft

    return check


def item(answered: Answered, key: str, subject: str, judge: str, role: ItemRole) -> ItemResult:
    """The item an answer gives. An agent rule that does not apply is not applicable, whatever
    verdict came with it."""
    answer = answered.answer
    if answered.error is not None or answer is None:
        outcome, kind = Outcome.ERROR, None
    elif not answer.get("applies", True):
        outcome, kind = Outcome.NOT_APPLICABLE, None
    else:
        outcome = Outcome(answer["verdict"])
        kind = UnsureKind(answer["kind"]) if outcome is Outcome.UNSURE else None
    return ItemResult(
        key=key,
        subject=subject,
        judge=judge,
        decided_by=DecidedBy.LLM,
        role=role,
        outcome=outcome,
        unsure_kind=kind,
        answer=answer,
        error_reason=answered.error,
        re_asks=answered.re_asks,
        attempts=answered.attempts,
    )


async def judge_criterion(
    model: JsonModel,
    view: str,
    turns: Sequence[Turn],
    number: int,
    criterion: str,
    *,
    slots: asyncio.Semaphore,
    retry_later: bool,
) -> ItemResult:
    answered = await ask(
        model,
        CRITERION,
        with_item(view, f"Criterion: {criterion}"),
        answer_problems(turns),
        slots=slots,
        retry_later=retry_later,
    )
    return item(answered, f"criterion-{number}", criterion, CRITERION.name, ItemRole.DECIDING)


def rule_text(rule: LlmRule) -> str:
    lines = [
        f"Agent rule: {rule.name}",
        f"Applies when: {rule.applies_when}",
        f"Passes when: {rule.pass_when}",
        f"Fails when: {rule.fail_when}",
    ]
    if rule.not_a_failure:
        lines.append(f"Not a failure: {rule.not_a_failure}")
    return "\n".join(lines)


async def judge_rule(
    model: JsonModel,
    view: str,
    turns: Sequence[Turn],
    rule: LlmRule,
    *,
    slots: asyncio.Semaphore,
    retry_later: bool,
) -> ItemResult:
    answered = await ask(
        model,
        AGENT_RULE,
        with_item(view, rule_text(rule)),
        answer_problems(turns),
        slots=slots,
        retry_later=retry_later,
    )
    return item(answered, f"{RULE}{rule.key}", rule.name, AGENT_RULE.name, rule.role)
