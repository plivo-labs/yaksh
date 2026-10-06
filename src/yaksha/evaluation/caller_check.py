"""The caller check: where Yaksha's own simulated caller broke a test, so that the agent is
never blamed for it. Code finds some facts first; one model call finds the rest and the
effect on each criterion."""

import asyncio
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from yaksha.domain.conversations import EndReason, Role, Transcript, WireEventKind
from yaksha.domain.evaluations import DecidedBy, ItemRole, Outcome, UnsureKind
from yaksha.domain.language_models import JsonModel
from yaksha.domain.languages import Language
from yaksha.evaluation.criteria import schema
from yaksha.evaluation.judging import Check, ItemResult, JudgeSpec, ask, prompt

OWNERS = ("caller", "scenario", "test_settings")
BLAME = ("none", "possible", "likely")
CALLER_CHECK = JudgeSpec(
    "caller_check",
    prompt("caller_check"),
    schema(
        {
            "findings": {
                "type": "array",
                "items": schema({"turn": {"type": "integer"}, "finding": {"type": "string"}}),
            },
            "impact": {
                "type": "array",
                "items": schema(
                    {
                        "criterion": {"type": "integer"},
                        "owner": {"type": "string", "enum": list(OWNERS)},
                        "effect": {"type": "string"},
                    }
                ),
            },
            "blame_risk": {"type": "string", "enum": list(BLAME)},
        }
    ),
)
LIMITS = frozenset({EndReason.TURN_LIMIT, EndReason.DURATION_LIMIT})
CLOSING = re.compile(
    r"\b(bye|goodbye|take care|have a (nice|great|good|wonderful) (day|evening)"
    r"|thank(s| you) for calling)\b",
    re.IGNORECASE,
)
WAITING = re.compile(
    r"\b(let me check|one moment|just a moment|please hold|hold on|give me a (second|moment))\b",
    re.IGNORECASE,
)
WAIT_HANGUP_MS = 10_000


def facts(transcript: Transcript, end_reason: EndReason | None, language: Language) -> list[str]:
    """What code can tell about the caller's part in how the call ended. The closing and wait
    phrases are English, so a call in another language gets neither fact."""
    found = []
    turns = transcript.turns
    agent = [turn for turn in turns if turn.role is Role.AGENT] if language is Language.EN else []
    ended_by_caller = end_reason is EndReason.CALLER_HANGUP
    if ended_by_caller and agent and not CLOSING.search(agent[-1].text):
        found.append("The caller hung up, and the agent's last turn has no closing words.")
    if turns and turns[-1].role is Role.CALLER:
        found.append(f"The last turn, {len(turns)}, is the caller's.")
    ended = next(
        (event.at_ms for event in transcript.wire_events if event.kind is WireEventKind.END_CALL),
        None,
    )
    if (
        ended_by_caller
        and ended is not None
        and agent
        and WAITING.search(agent[-1].text)
        and ended - agent[-1].ended_at_ms <= WAIT_HANGUP_MS
    ):
        found.append(
            "The caller hung up within 10 s of the agent saying it would check or asking it "
            "to wait."
        )
    if end_reason in LIMITS:
        limit = "turn limit" if end_reason is EndReason.TURN_LIMIT else "time limit"
        found.append(f"The test's {limit} ended the call.")
    return found


def problems(transcript: Transcript, criteria: int) -> Check:
    turns = len(transcript.turns)

    def check(answer: dict[str, Any]) -> tuple[list[str], list[str]]:
        found = [
            f"Finding turn {item['turn']} is not a turn of this call (1 to {turns})."
            for item in answer["findings"]
            if not 1 <= item["turn"] <= turns
        ]
        found += [
            f"Criterion {item['criterion']} does not exist (1 to {criteria})."
            for item in answer["impact"]
            if not 1 <= item["criterion"] <= criteria
        ]
        return found, []

    return check


async def check_caller(
    model: JsonModel,
    view: str,
    transcript: Transcript,
    persona: str | None,
    criteria: Sequence[str],
    end_reason: EndReason | None,
    language: Language,
    *,
    slots: asyncio.Semaphore,
    retry_later: bool,
) -> ItemResult:
    """`persona` is how the caller talks; the caller's goal and facts come from the view."""
    numbered = "\n".join(f"{number}. {text}" for number, text in enumerate(criteria, 1))
    found = "\n".join(f"- {fact}" for fact in facts(transcript, end_reason, language)) or "- none"
    user = (
        f"CALLER PERSONA\n{persona or 'none'}\n\nCRITERIA\n{numbered}\n\n"
        f"FACTS CODE FOUND\n{found}\n\n{view}"
    )
    answered = await ask(
        model,
        CALLER_CHECK,
        user,
        problems(transcript, len(criteria)),
        slots=slots,
        retry_later=retry_later,
    )
    answer = answered.answer
    if answered.error is not None or answer is None:
        outcome = Outcome.ERROR
    else:
        outcome = Outcome.FAIL if answer["blame_risk"] == "likely" else Outcome.PASS
    return ItemResult(
        key="caller_check",
        subject="Yaksha's caller kept to its test",
        judge=CALLER_CHECK.name,
        decided_by=DecidedBy.LLM,
        role=ItemRole.REPORTING,
        outcome=outcome,
        answer=answer,
        error_reason=answered.error,
        re_asks=answered.re_asks,
        attempts=answered.attempts,
    )


BLOCKABLE = frozenset({Outcome.FAIL, Outcome.ERROR, Outcome.UNSURE})


def blockable(item: ItemResult) -> bool:
    """A result that could count against the agent or leave it unscored: a pass, and an unsure
    that needs a hidden action, which counts as not applicable, never need blocking."""
    return item.outcome in BLOCKABLE and item.unsure_kind is not UnsureKind.HIDDEN_ACTION


def applied(
    criteria: Sequence[ItemResult], check: ItemResult, end_reason: EndReason | None
) -> list[ItemResult]:
    """The criteria after the caller check. An unmet criterion the caller likely changed is
    blocked: not scored, never the agent's failure. On a call the test's turn or time limit
    ended, an unmet criterion the limit cut off is blocked too, whatever the blame; and when
    the check itself failed on such a call, every unmet criterion is, since an unmet criterion
    there counts only when the check is clean for it. A possible effect keeps the verdict and
    marks it. The judge's own answer stays on the item."""
    limited = end_reason in LIMITS
    if check.outcome is Outcome.ERROR or check.answer is None:
        if not limited:
            return list(criteria)
        effect = {"owner": "test_settings", "effect": "The caller check failed.", "blame": None}
        return [
            replace(item, outcome=Outcome.BLOCKED, unsure_kind=None, caller_effect=effect)
            if blockable(item)
            else item
            for item in criteria
        ]
    blame = check.answer["blame_risk"]
    impacts: dict[int, list[dict[str, Any]]] = {}
    for impact in check.answer["impact"]:
        impacts.setdefault(impact["criterion"], []).append(impact)
    found = []
    for number, item in enumerate(criteria, 1):
        cut = [i for i in impacts.get(number, []) if limited and i["owner"] == "test_settings"]
        named = impacts.get(number, [])
        blocks = blockable(item) and bool(cut or (named and blame == "likely"))
        shown = (cut or named)[:1]
        if not shown or (blame == "none" and not cut):
            found.append(item)
            continue
        effect = {"owner": shown[0]["owner"], "effect": shown[0]["effect"], "blame": blame}
        found.append(
            replace(item, outcome=Outcome.BLOCKED, unsure_kind=None, caller_effect=effect)
            if blocks
            else replace(item, caller_effect=effect)
        )
    return found
