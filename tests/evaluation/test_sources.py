import asyncio
import json
from typing import Any

from tests.conftest import Scripted
from yaksh.domain.conversations import Role, Turn
from yaksh.domain.evaluations import Outcome
from yaksh.domain.language_models import ModelCallError
from yaksh.evaluation.sources import Document, judge_hallucination, judge_instructions

TURNS = [
    Turn(role=Role.AGENT, text="Thanks for calling Maple Dental.", started_at_ms=0, ended_at_ms=1),
    Turn(
        role=Role.CALLER, text="How much is a new patient cleaning?", started_at_ms=2, ended_at_ms=3
    ),
    Turn(role=Role.AGENT, text="It is eighty dollars.", started_at_ms=4, ended_at_ms=5),
    Turn(
        role=Role.AGENT,
        text="Great, you're booked for Tuesday at two thirty.",
        started_at_ms=6,
        ended_at_ms=7,
    ),
]
CONFIG = """You are Ava, the front desk agent for Maple Dental.
3. Read the date and time back and ask the caller to confirm before you book.
5. Do not offer discounts."""
PRICES = Document(name="prices.md", text="New patient cleaning: $95\nX-rays: $40")


def part(
    verdict: str, call: dict[str, Any] | None = None, line: str | None = None
) -> dict[str, Any]:
    return {"call_quote": call, "instruction_quote": line, "reasoning": "...", "verdict": verdict}


def adherence(procedure: dict[str, Any]) -> dict[str, Any]:
    return {"objective": part("pass"), "procedure": procedure, "boundary": part("pass")}


async def instructions(model: Scripted, config: str = CONFIG, max_chars: int = 100_000) -> Any:
    return await judge_instructions(
        model, "VIEW", TURNS, config, max_chars, slots=asyncio.Semaphore(1)
    )


async def test_a_broken_instruction_fails_with_both_quotes_checked() -> None:
    booked = {"turn": 4, "quote": "you're booked for Tuesday at two thirty"}
    wrong_line = adherence(part("fail", booked, "3. Confirm every booking twice."))
    right_line = adherence(
        part("fail", booked, "Read the date and time back and ask the caller to confirm")
    )
    model = Scripted(wrong_line, right_line)

    found = await instructions(model)

    assert (found.key, found.outcome, found.re_asks) == ("instructions", Outcome.FAIL, 1)
    assert "is not in the instructions" in model.requests[1]
    assert (await instructions(Scripted(adherence(part("pass"))))).outcome is Outcome.PASS


async def test_an_instruction_in_a_json_export_is_found_as_the_prompt_reads() -> None:
    export = json.dumps(
        {"nodes": [{"prompt": "Don\u2019t give medical advice.\nOffer a call back."}]}
    )
    medical = {"turn": 3, "quote": "It is eighty dollars."}
    found = await instructions(
        Scripted(
            adherence(part("fail", medical, "Don\u2019t give medical advice.\nOffer a call back."))
        ),
        config=export,
    )

    assert (found.outcome, found.re_asks) == (Outcome.FAIL, 0)


async def test_a_source_judge_quotes_the_agent_never_the_caller() -> None:
    caller_line = {"turn": 2, "quote": "How much is a new patient cleaning?"}
    model = Scripted(
        adherence(part("fail", caller_line, "Do not offer discounts.")),
        adherence(part("pass")),
    )

    found = await instructions(model)

    assert (found.outcome, found.re_asks) == (Outcome.PASS, 1)
    assert "Turn 2 is the caller's" in model.requests[1]


async def test_a_source_judge_that_times_out_is_its_items_error_at_once() -> None:
    busy = ModelCallError("timed out", temporary=True)

    found = await instructions(Scripted(busy))

    assert (found.outcome, found.error_reason, len(found.attempts)) == (
        Outcome.ERROR,
        "judge_unavailable",
        1,
    )


async def test_sources_too_large_for_one_request_are_an_error_with_no_model_call() -> None:
    model = Scripted()

    found = await instructions(model, max_chars=100)

    assert (found.outcome, found.error_reason, model.requests) == (
        Outcome.ERROR,
        "sources_too_large",
        [],
    )


def contradiction(document: str, quote: str) -> dict[str, Any]:
    return {
        "call_quote": {"turn": 3, "quote": "eighty dollars"},
        "document": document,
        "document_quote": quote,
        "reasoning": "The agent said $80; the price list says $95.",
    }


async def test_a_contradiction_needs_the_document_line_word_for_word() -> None:
    misquoted = {
        "contradictions": [contradiction("hours.md", "Cleaning costs $95")],
        "reasoning": "...",
        "verdict": "fail",
    }
    quoted = {
        "contradictions": [contradiction("Prices.MD", "New patient cleaning: $95")],
        "reasoning": "...",
        "verdict": "fail",
    }
    model = Scripted(misquoted, quoted)

    found = await judge_hallucination(
        model, "VIEW", TURNS, [PRICES], None, 100_000, slots=asyncio.Semaphore(1)
    )

    assert (found.key, found.outcome, found.re_asks) == ("hallucination", Outcome.FAIL, 1)
    assert 'no document named "hours.md". The documents are: prices.md' in model.requests[1]
    assert "DOCUMENT: prices.md" in model.requests[0]


async def test_a_pass_with_contradictions_is_asked_again() -> None:
    confused = {
        "contradictions": [contradiction("prices.md", "New patient cleaning: $95")],
        "reasoning": "...",
        "verdict": "pass",
    }
    covered = {
        "contradictions": [],
        "reasoning": "Nothing contradicts.",
        "verdict": "not_applicable",
    }

    found = await judge_hallucination(
        Scripted(confused, covered),
        "VIEW",
        TURNS,
        [PRICES],
        CONFIG,
        100_000,
        slots=asyncio.Semaphore(1),
    )

    assert (found.outcome, found.re_asks) == (Outcome.NOT_APPLICABLE, 1)
