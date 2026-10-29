from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from yaksh.domain.agent_records import AgentRecord
from yaksh.domain.canonical import canonical, contains
from yaksh.domain.conversations import Provenance, Role, Turn
from yaksh.domain.evaluations import DecidedBy, ItemRole, Outcome
from yaksh.domain.language_models import JsonModel
from yaksh.evaluation.criteria import schema
from yaksh.evaluation.evidence import with_item
from yaksh.evaluation.judging import Answered, Check, ItemResult, JudgeSpec, ask, prompt
from yaksh.evaluation.limit import Slots
from yaksh.evaluation.quotes import quote_problems

SAVED_DATA_KEY = "saved_data"
HEARD_KEY = "heard"
TURN_QUOTE = schema({"turn": {"type": "integer"}, "quote": {"type": "string"}})
SAVED_DATA = JudgeSpec(
    "saved_data",
    prompt("saved_data"),
    schema(
        {
            "values": {
                "type": "array",
                "items": schema(
                    {
                        "name": {"type": "string"},
                        "result": {
                            "type": "string",
                            "enum": ["matches", "contradicts", "not_checkable"],
                        },
                        "evidence": {"type": "array", "items": TURN_QUOTE},
                        "reasoning": {"type": "string"},
                    }
                ),
            },
            "reasoning": {"type": "string"},
        }
    ),
)
HEARD = JudgeSpec(
    "heard",
    prompt("heard"),
    schema(
        {
            "values": {
                "type": "array",
                "items": schema(
                    {
                        "value": {"type": "string"},
                        "said": TURN_QUOTE,
                        "heard": {
                            "anyOf": [
                                {"type": "null"},
                                schema({"line": {"type": "integer"}, "quote": {"type": "string"}}),
                            ]
                        },
                        "result": {"type": "string", "enum": ["same", "different", "missing"]},
                        "reasoning": {"type": "string"},
                    }
                ),
            },
            "reasoning": {"type": "string"},
        }
    ),
)


UNPLAYED = (Provenance.CUT, Provenance.UNCONFIRMED)


def heard_lines(record: AgentRecord) -> list[str]:
    return [turn.text for turn in record.turns if turn.role is Role.CALLER]


async def judge_saved_data(
    model: JsonModel,
    view: str,
    turns: Sequence[Turn],
    record: AgentRecord,
    *,
    slots: Slots,
    retry_later: bool,
) -> ItemResult:
    listed = "\n".join(f"- {value.name} = {value.value or '(empty)'}" for value in record.saved)
    answered = await ask(
        model,
        SAVED_DATA,
        with_item(view, f"Saved values to check:\n{listed}"),
        saved_data_problems(turns, [value.name for value in record.saved]),
        slots=slots,
        retry_later=retry_later,
    )
    return item(
        answered, SAVED_DATA_KEY, "Data the agent saved", ItemRole.DECIDING, saved_data_outcome
    )


async def judge_heard(
    model: JsonModel,
    view: str,
    turns: Sequence[Turn],
    record: AgentRecord,
    *,
    slots: Slots,
    retry_later: bool,
) -> ItemResult:
    lines = heard_lines(record)
    numbered = "\n".join(f"[H{number}] {line}" for number, line in enumerate(lines, 1))
    numbered = numbered or "(no line: the agent's speech-to-text heard nothing)"
    answered = await ask(
        model,
        HEARD,
        with_item(view, f"What the agent's speech-to-text heard from the caller:\n{numbered}"),
        heard_problems(turns, lines),
        slots=slots,
        retry_later=retry_later,
    )
    return item(answered, HEARD_KEY, "What the agent heard", ItemRole.REPORTING, heard_outcome)


def saved_data_problems(turns: Sequence[Turn], names: Sequence[str]) -> Check:
    """A contradicts result needs a quote from a turn that played: the agent may not have
    heard a turn that did not, so that turn alone cannot fail the agent."""

    def check(answer: dict[str, Any]) -> tuple[list[str], list[str]]:
        values = answer["values"]
        listed = Counter(value["name"] for value in values)
        hard = [f"List the saved value {name} once." for name in names if listed[name] != 1]
        hard += [f"{name} is not a saved value." for name in listed if name not in names]
        for value in values:
            hard += quote_problems(value["evidence"], turns)
            played = [
                quote
                for quote in value["evidence"]
                if 1 <= quote["turn"] <= len(turns)
                and turns[quote["turn"] - 1].provenance not in UNPLAYED
            ]
            if value["result"] == "contradicts" and not played:
                hard.append(
                    f"{value['name']} contradicts the call: quote the words of a played turn "
                    "that show the right value. If only turns that did not play show it, the "
                    "value is not_checkable."
                )
        return hard, []

    return check


def heard_problems(turns: Sequence[Turn], lines: Sequence[str]) -> Check:
    def check(answer: dict[str, Any]) -> tuple[list[str], list[str]]:
        hard: list[str] = []
        for value in answer["values"]:
            said, heard, name = value["said"], value["heard"], value["value"]
            turn = said["turn"]
            if not 1 <= turn <= len(turns) or turns[turn - 1].role is not Role.CALLER:
                hard.append(f"{name}: turn {turn} is not a caller turn of this call.")
            elif turns[turn - 1].dtmf:
                hard.append(f"{name}: turn {turn} was pressed on the keypad, not spoken.")
            elif not contains(turns[turn - 1].text, said["quote"]):
                hard.append(f'{name}: "{said["quote"]}" is not in turn {turn}.')
            if (heard is None) != (value["result"] == "missing"):
                hard.append(f"{name}: heard is null exactly when the result is missing.")
            elif heard is not None:
                line = heard["line"]
                if not 1 <= line <= len(lines):
                    hard.append(f"{name}: H{line} is not a heard line; there are {len(lines)}.")
                elif not canonical(heard["quote"]) or not contains(lines[line - 1], heard["quote"]):
                    hard.append(f'{name}: "{heard["quote"]}" is not in H{line}.')
        return hard, []

    return check


def saved_data_outcome(answer: dict[str, Any]) -> Outcome:
    results = {value["result"] for value in answer["values"]}
    if "contradicts" in results:
        return Outcome.FAIL
    return Outcome.PASS if "matches" in results else Outcome.NOT_APPLICABLE


def heard_outcome(answer: dict[str, Any]) -> Outcome:
    results = {value["result"] for value in answer["values"]}
    if results & {"different", "missing"}:
        return Outcome.FAIL
    return Outcome.PASS if "same" in results else Outcome.NOT_APPLICABLE


def item(
    answered: Answered,
    key: str,
    subject: str,
    role: ItemRole,
    outcome_of: Callable[[dict[str, Any]], Outcome],
) -> ItemResult:
    answer = answered.answer
    failed = answered.error is not None or answer is None
    return ItemResult(
        key=key,
        subject=subject,
        judge=key,
        decided_by=DecidedBy.LLM,
        role=role,
        outcome=Outcome.ERROR if failed or answer is None else outcome_of(answer),
        answer=answer,
        error_reason=answered.error,
        re_asks=answered.re_asks,
        attempts=answered.attempts,
    )
