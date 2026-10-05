"""The judges that read the agent's own sources beside the call: instruction adherence against
the agent's pasted instructions, and hallucination against its knowledge-base documents. Each
gives one item; a fail must quote the agent's line and the source word for word. A source
judge's request is large, so it gets one try with the source model's longer timeout, and a
failure is its item's error: it never puts the whole evaluation off."""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from truman.domain.conversations import Role, Turn
from truman.domain.evaluations import DecidedBy, ItemRole, Outcome
from truman.domain.language_models import JsonModel
from truman.evaluation.canonical import contains
from truman.evaluation.criteria import schema
from truman.evaluation.evidence import with_item
from truman.evaluation.judging import Check, ItemResult, JudgeSpec, ask, prompt
from truman.evaluation.quotes import quote_problems

VERDICTS = {"type": "string", "enum": ["pass", "fail", "not_applicable"]}
CALL_QUOTE = {
    "type": "object",
    "properties": {"turn": {"type": "integer"}, "quote": {"type": "string"}},
    "required": ["turn", "quote"],
    "additionalProperties": False,
}
PART = schema(
    {
        "call_quote": {"anyOf": [{"type": "null"}, CALL_QUOTE]},
        "instruction_quote": {"anyOf": [{"type": "null"}, {"type": "string"}]},
        "reasoning": {"type": "string"},
        "verdict": VERDICTS,
    }
)
QUESTIONS = ("objective", "procedure", "boundary")
INSTRUCTIONS = JudgeSpec(
    "instructions", prompt("instructions"), schema({question: PART for question in QUESTIONS})
)
HALLUCINATION = JudgeSpec(
    "hallucination",
    prompt("hallucination"),
    schema(
        {
            "contradictions": {
                "type": "array",
                "items": schema(
                    {
                        "call_quote": CALL_QUOTE,
                        "document": {"type": "string"},
                        "document_quote": {"type": "string"},
                        "reasoning": {"type": "string"},
                    }
                ),
            },
            "reasoning": {"type": "string"},
            "verdict": VERDICTS,
        }
    ),
)


@dataclass(frozen=True)
class Document:
    name: str
    text: str


def too_large(key: str, subject: str) -> ItemResult:
    return ItemResult(
        key=key,
        subject=subject,
        judge=None,
        decided_by=DecidedBy.CODE,
        role=ItemRole.REPORTING,
        outcome=Outcome.ERROR,
        error_reason="sources_too_large",
    )


def agent_quote_problems(quotes: Sequence[dict[str, Any]], turns: Sequence[Turn]) -> list[str]:
    """A source judge quotes the agent's own line, never the caller's."""
    problems = quote_problems(quotes, turns)
    problems += [
        f"Turn {quote['turn']} is the caller's. Quote the agent's line."
        for quote in quotes
        if 1 <= quote["turn"] <= len(turns) and turns[quote["turn"] - 1].role is not Role.AGENT
    ]
    return problems


def readable(config: str) -> list[str]:
    """The texts an instruction can be quoted from: the config as pasted, and when it is JSON,
    such as a flow export, its string values one by one and joined by lines, so a quote of a
    prompt in it matches whatever escapes the export used."""
    try:
        parsed = json.loads(config)
    except ValueError:
        return [config]
    values: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, dict):
            for inner in value.values():
                collect(inner)
        elif isinstance(value, list):
            for inner in value:
                collect(inner)

    collect(parsed)
    return [config, *values, "\n".join(values)]


def instruction_problems(turns: Sequence[Turn], config: str) -> Check:
    texts = readable(config)

    def check(answer: dict[str, Any]) -> tuple[list[str], list[str]]:
        problems = []
        for question in QUESTIONS:
            part = answer[question]
            if part["verdict"] != "fail":
                continue
            if part["call_quote"] is None or part["instruction_quote"] is None:
                problems.append(f"The {question} fail needs both call_quote and instruction_quote.")
                continue
            problems += agent_quote_problems([part["call_quote"]], turns)
            if not any(contains(text, part["instruction_quote"]) for text in texts):
                problems.append(
                    f'The instruction quote "{part["instruction_quote"]}" is not in the '
                    "instructions. Quote them word for word."
                )
        return problems, []

    return check


async def judge_instructions(
    model: JsonModel,
    view: str,
    turns: Sequence[Turn],
    config: str,
    max_chars: int,
    *,
    slots: asyncio.Semaphore,
) -> ItemResult:
    subject = "Follows its instructions"
    user = with_item(view, f"AGENT INSTRUCTIONS\n{config}")
    if len(user) > max_chars:
        return too_large("instructions", subject)
    answered = await ask(
        model,
        INSTRUCTIONS,
        user,
        instruction_problems(turns, config),
        slots=slots,
        retry_later=False,
        patient=False,
    )
    answer = answered.answer
    if answered.error is not None or answer is None:
        outcome = Outcome.ERROR
    else:
        verdicts = {answer[question]["verdict"] for question in QUESTIONS}
        outcome = (
            Outcome.FAIL
            if "fail" in verdicts
            else Outcome.PASS
            if "pass" in verdicts
            else Outcome.NOT_APPLICABLE
        )
    return ItemResult(
        key="instructions",
        subject=subject,
        judge=INSTRUCTIONS.name,
        decided_by=DecidedBy.LLM,
        role=ItemRole.REPORTING,
        outcome=outcome,
        answer=answer,
        error_reason=answered.error,
        re_asks=answered.re_asks,
        attempts=answered.attempts,
    )


def contradiction_problems(turns: Sequence[Turn], documents: Sequence[Document]) -> Check:
    texts = {document.name.lower(): document.text for document in documents}
    names = ", ".join(document.name for document in documents)

    def check(answer: dict[str, Any]) -> tuple[list[str], list[str]]:
        found = answer["contradictions"]
        problems = agent_quote_problems([item["call_quote"] for item in found], turns)
        for item in found:
            text = texts.get(item["document"].lower())
            if text is None:
                problems.append(
                    f'There is no document named "{item["document"]}". The documents are: {names}.'
                )
            elif not contains(text, item["document_quote"]):
                problems.append(
                    f'The quote "{item["document_quote"]}" is not in {item["document"]}. '
                    "Quote the document word for word."
                )
        if answer["verdict"] == "fail" and not found:
            problems.append("A fail needs at least one contradiction.")
        if answer["verdict"] != "fail" and found:
            problems.append("Only a fail has contradictions.")
        return problems, []

    return check


async def judge_hallucination(
    model: JsonModel,
    view: str,
    turns: Sequence[Turn],
    documents: Sequence[Document],
    config: str | None,
    max_chars: int,
    *,
    slots: asyncio.Semaphore,
) -> ItemResult:
    subject = "States no fact its documents contradict"
    sources = "\n\n".join(f"DOCUMENT: {document.name}\n{document.text}" for document in documents)
    if config:
        sources += f"\n\nAGENT INSTRUCTIONS\n{config}"
    user = with_item(view, sources)
    if len(user) > max_chars:
        return too_large("hallucination", subject)
    answered = await ask(
        model,
        HALLUCINATION,
        user,
        contradiction_problems(turns, documents),
        slots=slots,
        retry_later=False,
        patient=False,
    )
    answer = answered.answer
    outcome = (
        Outcome.ERROR
        if answered.error is not None or answer is None
        else Outcome(answer["verdict"])
    )
    return ItemResult(
        key="hallucination",
        subject=subject,
        judge=HALLUCINATION.name,
        decided_by=DecidedBy.LLM,
        role=ItemRole.REPORTING,
        outcome=outcome,
        answer=answer,
        error_reason=answered.error,
        re_asks=answered.re_asks,
        attempts=answered.attempts,
    )
